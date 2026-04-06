# 造数重构设计文档

**日期**：2026-04-06  
**状态**：已批准，待实现  
**分支**：feat/v2.0

---

## 背景与动机

当前造数（Step 9）在 Wave 4 通过 subprocess 调用 `pipeline_mock_data.py` 执行，存在以下问题：

1. **时机晚**：所有工作表全部创建完成后才开始造数，无法利用表创建期间的等待时间
2. **耗时长**：串行 6 步，40+ 张表逐个调 AI，总耗时超过 1000s
3. **数据质量差**：prompt 没有传入行业/业务背景，AI 生成的数据缺乏业务含义
4. **关联为空**：造数阶段不处理关联字段，旧的关联修复流程可靠性差

---

## 目标

- 每张工作表字段创建完立即开始造数（嵌入 Wave 3，类似 Wave 3.5 视图创建的模式）
- 注入行业/业务背景，生成有意义的数据
- Two-Phase 架构：Phase 1 并发造数（不含关联），Phase 2 并发填关联
- 保留 `pipeline_mock_data.py` 作为独立重跑工具不变

---

## recordCount 规则

| 表的关联类型 | 造数条数 | 判断依据 |
|---|---|---|
| 1:N 主表端（subType=2，聚合端） | 3 条 | `outgoing_edge_subtypes` 含 2 |
| 1:N 明细端（subType=1，单选端） | 6 条 | `outgoing_edge_subtypes` 全为 1 且参与 1-N pair |
| 仅 1:1 关系 | 3 条 | pair_types 全为 1-1 |
| 无关联（独立表） | 3 条 | 无 relation pair |

---

## 架构：Wave 3.5b（新增）

### 触发时机

Wave 3（`create_worksheets_from_plan`）成功完成后，立即在 `waves.py` 内联触发，不走 subprocess。

依赖：`worksheet_create_result_path`（包含 `name_to_worksheet_id`）

### Phase 1：并发造数（不含关联字段）

**并发数**：max_workers=3（与 Wave 3.5 视图创建保持一致，受 `gemini_semaphore` 控制）

**每张表的执行流程**：
1. 从 `relationPairs` 计算该表的 recordCount（新规则）
2. 调用 `plan_and_write_mock_data_for_ws()`，传入业务背景
3. AI 生成数据 → `validate_plan()` 校验 → 批量 POST V3 API
4. 收集 `{worksheetId: [rowId, ...]}`

**Prompt 改进**：在现有 `build_prompt_v2` 的基础上，开头加：

```
## 应用背景
应用名称：{app_name}
行业/业务背景：{business_context}

请根据上述背景，为「{worksheet_name}」生成真实有业务含义的数据，
避免使用"示例"、"测试"、"sample"等无意义词汇。
```

`business_context` 来源：`spec["worksheets"]["business_context"]`

**写入接口**：优先使用批量接口 `POST /v3/app/worksheets/{ws_id}/rows/batch`，失败时回退逐条写入。

**Relation 字段处理**：Phase 1 中 Relation 类型字段一律跳过（不传给 AI，也不写入）。

### Phase 2：并发填关联

**不调用 AI**，完全确定性 round-robin 策略。

**处理对象**（复用 `build_candidate_fields(snapshot)` 逻辑）：
- **1:N 明细端**（`handlingMode="1-N-single"`）：填 Relation 字段指向主表的 rowId
- **1:1 从属端**（`handlingMode="1-1"`）：填 Relation 字段指向对侧的 rowId
- **主表、无关联表**：跳过

**round-robin 分配示例**（订单明细6条 → 订单3条）：
```
明细 #1 → 订单 #1
明细 #2 → 订单 #2
明细 #3 → 订单 #3
明细 #4 → 订单 #1  ← 循环
明细 #5 → 订单 #2
明细 #6 → 订单 #3
```

**并发模型**（按 tier 分批，避免依赖冲突）：
- Batch A：tier=3 的从属端（1:N 明细端） → 并发3
- Batch B：tier=2 的从属端（1:1 从属端） → 并发3

**写入接口**：`PATCH /v3/app/worksheets/{ws_id}/rows/{row_id}`（`update_row_relation` 已有函数）

---

## 新建文件：`scripts/hap/planners/mock_data_inline.py`

包含以下函数（供 `waves.py` 内联调用）：

### `compute_new_record_count(ws_id, relation_pairs, relation_edges) -> int`

根据新规则计算 recordCount。

### `build_mock_prompt(app_name, business_context, ws_name, ws_schema, record_count) -> str`

基于 `build_prompt_v2` 增强，注入业务背景。Relation 字段从 `writableFields` 中剔除。

### `plan_and_write_mock_data_for_ws(...) -> dict`

单表原子操作：AI 生成 → validate → 批量写入。

**返回值**：
```python
{
    "worksheetId": str,
    "worksheetName": str,
    "rowIds": [str, ...],  # 成功写入的 rowId 列表
    "error": str | None,
}
```

**构造 mini_snapshot 供 `validate_plan` 使用**：
```python
mini_snapshot = {
    "app": {"appId": app_id, "appName": app_name},
    "worksheets": [ws_schema_with_skipped_relations],
    "worksheetTiers": [{"worksheetId": ws_id, "worksheetName": ws_name,
                        "tier": 1, "order": 1, "recordCount": record_count, "reason": "..."}],
}
```

### `apply_relation_phase(app_id, app_key, sign, base_url, relation_pairs, relation_edges, all_row_ids, worksheet_schemas, dry_run) -> dict`

Phase 2 关联处理。返回 `{worksheetId: {"updated": int, "failed": int}}`。

---

## 修改文件清单

| 文件 | 修改内容 |
|---|---|
| `scripts/hap/planners/mock_data_inline.py` | 新建，包含上述4个函数 |
| `scripts/hap/pipeline/waves.py` | 插入 Wave 3.5b（Phase 1+2），修改 `run_step_9` 增加跳过逻辑 |
| `scripts/hap/pipeline/context.py` | 新增 `mock_data_write_result_json`、`mock_relation_apply_result_json` 字段 |

**保持不变**：
- `scripts/hap/pipeline_mock_data.py`（独立重跑工具）
- `scripts/hap/planners/plan_mock_data_gemini.py`（内部函数复用）
- `scripts/hap/mock_data_common.py`（API 函数复用）
- `scripts/hap/planners/plan_mock_relations_gemini.py`（`build_candidate_fields` 复用）

---

## waves.py 修改点

### 插入位置

Wave 3.5（视图创建）结束后、Wave 4 开始前，约 `_abort_if_failed()` 之后。

### Wave 3.5b 伪代码

```python
# Wave 3.5b: 逐表造数 + 关联填写
if mock_data.get("enabled", True) and worksheet_create_result_path and not execution_dry_run:
    from planners.mock_data_inline import plan_and_write_mock_data_for_ws, apply_relation_phase
    from mock_data_common import build_schema_snapshot, DEFAULT_BASE_URL

    print(f"\n-- Wave 3.5b Phase 1: 逐表造数 --- 总计 {time.time()-pipeline_start:.0f}s")

    # 1. 获取 appKey/sign
    _app_key, _app_sign = ...  # 从 app_auth_json 读取

    # 2. 获取结构快照（含 relationPairs）
    _snapshot = build_schema_snapshot(DEFAULT_BASE_URL, {...})
    _relation_pairs = _snapshot.get("relationPairs", [])
    _relation_edges = _snapshot.get("relationEdges", [])
    _ws_schemas_by_id = {ws["worksheetId"]: ws for ws in _snapshot["worksheets"]}

    # 3. 获取业务背景
    _business_context = str(ws.get("business_context", "")).strip()
    _app_name = str(app.get("name", "")).strip()

    # 4. AI client
    _md_ai_config = load_ai_config(AI_CONFIG_PATH)
    _md_client = get_ai_client(_md_ai_config)
    _md_model = _md_ai_config["model"]

    # 5. Phase 1: 并发造数
    _all_row_ids: dict[str, list[str]] = {}
    _mock_lock = threading.Lock()

    def _do_mock_for_ws(ws_name, ws_id):
        ws_schema = _ws_schemas_by_id.get(ws_id)
        if not ws_schema:
            return
        with gemini_semaphore:
            result = plan_and_write_mock_data_for_ws(
                client=_md_client, model=_md_model,
                app_id=app_id, app_name=_app_name,
                business_context=_business_context,
                app_key=_app_key, sign=_app_sign,
                base_url=DEFAULT_BASE_URL,
                worksheet_id=ws_id, worksheet_name=ws_name,
                ws_schema=ws_schema,
                relation_pairs=_relation_pairs,
                dry_run=execution_dry_run or mock_data.get("dry_run", False),
            )
        with _mock_lock:
            if result.get("rowIds"):
                _all_row_ids[ws_id] = result["rowIds"]

    ws_create_data = load_json(Path(worksheet_create_result_path))
    _name_to_id = ws_create_data.get("name_to_worksheet_id", {})

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_do_mock_for_ws, wn, wi) for wn, wi in _name_to_id.items()]
        for f in futures:
            try:
                f.result()
            except Exception as exc:
                print(f"  ✗ 造数任务异常: {exc}", file=sys.stderr)

    ctx.mock_data_write_result_json = "..."  # 写入汇总结果文件

    # 6. Phase 2: 并发填关联
    if mock_data.get("relation_enabled", True) and _all_row_ids and _relation_pairs:
        print(f"\n-- Wave 3.5b Phase 2: 关联字段填写 --- 总计 {time.time()-pipeline_start:.0f}s")
        _rel_result = apply_relation_phase(
            app_id=app_id, app_key=_app_key, sign=_app_sign,
            base_url=DEFAULT_BASE_URL,
            relation_pairs=_relation_pairs,
            relation_edges=_relation_edges,
            all_row_ids=_all_row_ids,
            worksheet_schemas=list(_ws_schemas_by_id.values()),
            dry_run=execution_dry_run or mock_data.get("dry_run", False),
        )
        ctx.mock_relation_apply_result_json = "..."
```

### `run_step_9` 修改

```python
def run_step_9() -> bool:
    # 如果 Wave 3.5b 已经完成造数，跳过旧流水线
    if ctx.mock_data_write_result_json:
        with steps_lock:
            steps_report.append({
                "step_id": 9, "step_key": "mock_data",
                "title": "执行造数流水线",
                "skipped": True,
                "reason": "already_done_in_wave_3.5b",
                "result": {},
            })
        return True
    # ... 原有逻辑不变
```

---

## spec 新增字段

`mock_data` 节点新增 `relation_enabled`：

```json
"mock_data": {
    "enabled": true,
    "relation_enabled": true,
    "dry_run": false,
    "trigger_workflow": false
}
```

---

## 数据流图

```
worksheet_create_result_path
    └── name_to_worksheet_id: {ws_name: ws_id}

build_schema_snapshot()
    └── relation_pairs, relation_edges, ws_schemas

Wave 3.5b Phase 1（并发3）
    每张表：
        compute_new_record_count() → 3 or 6
        build_mock_prompt() → 注入 app_name + business_context
        AI call → validate_plan() → batch POST V3 API
    → all_row_ids: {ws_id: [rowId, ...]}

Wave 3.5b Phase 2（按tier并发）
    build_candidate_fields() → 从属端列表
    Batch A（tier=3）: round-robin PATCH V3
    Batch B（tier=2）: round-robin PATCH V3
    → relation_apply_result

Wave 4 Step 9：ctx.mock_data_write_result_json 已填 → skipped
```

---

## 验证方案

1. 运行 `python make_app.py --requirements "..."` 跑一个新应用
2. 检查 terminal 输出：应出现 `-- Wave 3.5b Phase 1: 逐表造数` 和 `Phase 2: 关联字段填写`
3. 检查 Step 9：应显示 `skipped: already_done_in_wave_3.5b`
4. 打开应用，检查各表是否有数据，数据内容是否有业务含义
5. 检查关联字段：明细表的 Relation 字段应有值，指向主表记录
6. 检查总耗时：应比原来（1053s）显著减少
