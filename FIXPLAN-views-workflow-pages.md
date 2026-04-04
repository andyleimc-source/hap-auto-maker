# FIXPLAN — 视图/工作流/统计图五个问题修复计划

测试应用：**室内设计与装修公司管理平台**（app_id: b9aec84d-4bbb-4b53-acfd-a14db6b24db5）
分支：`feat/v2.0`

修复完成后在此应用上直接验证，通过后再跑新行业。

---

## 根因速查

| # | 问题 | 根因 |
|---|------|------|
| 1 | 视图停在配置界面/主视图不对 | **VIEW_REGISTRY 编号与 prompt 编号错位一位**（0=表格但 prompt 写成 1=表格）|
| 2 | 工作表没有列表视图 | 上次修复把 viewType=0 禁掉了，但 0 就是列表/表格视图 |
| 3 | 工作流 time_trigger 崩溃 | AI 输出 `"frequency":"daily"` 字符串，`int("daily")` 崩溃 |
| 4 | 统计图表只有 2 个 Page | `validate_page_plan()` 硬编码 `len(pages) != 2` 强制只能 2 个 |
| 5 | 未命名分组（已强调三次） | 待确认：检查 sections_create_result 是否 UpdateAppSectionName 失败 |

---

## Fix 1 + 2：修正 viewType 编号（最重要）

**VIEW_REGISTRY 实际编号（`scripts/hap/views/view_types.py`）：**
```
0=表格(列表)  1=看板  2=层级  3=画廊  4=日历  5=甘特图  6=详情  7=资源  8=地图
```

**文件：`scripts/hap/planning/view_planner.py`**

### 1a. `build_structure_prompt()` 约 151-158 行 — 修正编号 + 恢复 0 合法

```python
# 修改前（错误）
1) viewType 必须是整数：1(表格), 2(看板), 3(层级), 4(画廊), 5(日历), 6(甘特图)。⚠️ 禁止使用 0
3) 看板(2)：...
4) 甘特图(6)：...
5) 层级(3)：...
6) 日历(5)：...
7) 画廊(4)：...

# 修改后（正确）
1) viewType 必须是整数：0(表格/列表), 1(看板), 2(层级), 3(画廊), 4(日历), 5(甘特图)
   ⚠️ 0 是最基础的列表视图，每个工作表必须至少有 1 个 viewType=0 的列表视图
2) 每个工作表 1-5 个视图，实用不凑数
3) 看板(1)：适合有明确流转阶段的表；必须有多状态单选字段(type=9 或 type=11)
4) 甘特图(5)：适合有时间跨度的项目/计划/合同；需要开始日期+结束日期两个字段
5) 层级(2)：适合有父子关系的表；需要自关联字段(type=29)
6) 日历(4)：适合以日期为核心的表（排班/预约/日程等）；需要日期字段
7) 画廊(3)：适合以图片为主的表（商品/案例/设计稿等）
8) 判断标准：先理解这张表的业务用途，再选最能提升使用体验的视图类型
```

同样修改 `build_enhanced_prompt()` 约 413-423 行（内容相同的规则列表）。

### 1b. `validate_structure_plan()` 约 203-206 行 — 恢复 0 合法

```python
# 修改前（错误，禁止了 0）
if vt_int == 0 or vt_int not in VIEW_REGISTRY:
    raise ValueError(...)

# 修改后（0 是合法的列表视图）
if vt_int not in VIEW_REGISTRY:
    raise ValueError(...)
```

### 1c. `create_views_from_plan.py` 约 315-316 行 — 删除错误 fallback

```python
# 修改前（错误，把合法的 0 改成了 1）
if _vt_int == 0:
    _vt_int = 1  # 0 不合法，fallback 到表格

# 修改后：直接删除这两行，0 是合法的表格视图
```

---

## Fix 3：time_trigger frequency 容错

**文件：`workflow/scripts/execute_workflow_plan.py`**

搜索 `def create_time_trigger`，找到约 877 行：
```python
frequency = int(trigger_plan.get("frequency", 7))
```

替换为：
```python
_freq_map = {"hourly": 60, "daily": 1440, "weekly": 10080, "monthly": 43200}
_freq_raw = trigger_plan.get("frequency", 1440)
if isinstance(_freq_raw, str):
    frequency = _freq_map.get(_freq_raw.lower().strip(), 1440)
else:
    frequency = int(_freq_raw or 1440)
```

**文件：`workflow/scripts/pipeline_workflows.py`**

在 time_trigger 的 prompt 中，明确说明 frequency 必须是整数（分钟数）：
```
- frequency：触发频率，必须是整数（分钟数）。常用值：1440=每天，10080=每周，43200=每月。禁止使用字符串如 "daily"。
```

---

## Fix 4：统计图 Page 数量动态化

**文件：`scripts/hap/plan_pages_gemini.py`**

### 4a. `build_prompt()` 约 261、266 行

```python
# 修改前
规划 3~5 个自定义数据分析页
...
1. 规划恰好 2 个 Page

# 修改后：根据工作表数量动态计算
num_ws = len(worksheets_detail)
if num_ws <= 6:
    target_pages = 2
elif num_ws <= 15:
    target_pages = 3
else:
    target_pages = 4

# prompt 中改为：
f"1. 规划恰好 {target_pages} 个 Page，每个 Page 聚焦不同业务主题"
```

### 4b. `validate_page_plan()` 约 326 行

```python
# 修改前（硬编码 2）
if len(pages) != 2:
    raise ValueError(f"期望恰好 2 个 Page，实际返回 {len(pages)} 个")

# 修改后（允许 2-5 个）
if not (2 <= len(pages) <= 5):
    raise ValueError(f"期望 2-5 个 Page，实际返回 {len(pages)} 个")
```

---

## Fix 5：未命名分组确认

先检查 sections 创建结果：
```bash
python3 -c "
import json, glob
files = sorted(glob.glob('data/outputs/sections_create_results/sections_create_b9aec84d*.json'))
if files:
    d = json.load(open(files[-1]))
    for s in d.get('sections',[]): print(s.get('name'), '->', s.get('appSectionId'))
"
```

如果分组名称正确但应用里出现「未命名分组」，说明 `UpdateAppSectionName` 调用失败。
修复位置：`scripts/hap/create_sections_from_plan.py` 的 `create_section()` 函数，
加强重试检查（目前已有 3 次重试，检查是否有 state != 1 被忽略的情况）。

---

## 验证步骤（在现有应用上）

```bash
# Step 1：重新规划+创建视图
python scripts/hap/pipeline_views.py \
  --app-id b9aec84d-4bbb-4b53-acfd-a14db6b24db5

# Step 2：重新创建统计图表页
python scripts/hap/pipeline_pages.py \
  --app-id b9aec84d-4bbb-4b53-acfd-a14db6b24db5

# Step 3：验证视图结果
python3 -c "
import json, glob
files = sorted(glob.glob('data/outputs/view_create_results/view_create_result_*.json'))
d = json.load(open(files[-1]))
summary = d.get('summary',{})
print('创建成功:', summary.get('createdViewCount'))
print('失败:', summary.get('failedCount'))
"
```

验证标准：
- 每张工作表都有 viewType=0 列表视图
- 看板/日历/甘特等视图能正常打开（不停在配置界面）
- 统计图 Page 数量 ≥ 3（26张表的应用）
- time_trigger 不再报 `int("daily")` 错误
