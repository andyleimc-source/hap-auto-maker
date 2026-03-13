# 工作流私有接口文档（待补 HAR / 抓包）

更新时间：2026-03-13  
用途：记录工作流创建、发布、启停相关私有接口，供 `scripts/hap/create_workflows_from_plan.py` 落地真实请求。  
当前状态：仅完成字段约定与适配器占位，尚未联调真实工作流 HAR。

## 1. 当前脚本约定
- 创建脚本已经支持：
  - 读取 `workflow_plan_v1`
  - 生成 `saveFlow / publish / enable` 三段请求草稿
  - dry-run 落盘
  - JSONL 日志
- 非 dry-run 模式要求提供私有接口配置文件：
  - `/Users/andy/Desktop/hap_auto/data/api_docs/workflow/private_workflow_api.json`

## 2. 建议补充内容
- 创建/保存工作流接口
  - URL
  - Method
  - Referer
  - 必要 Header
  - 请求体结构
  - 成功响应中的 `processId` / `versionId`
- 发布接口
  - URL
  - Method
  - 请求体最小字段
- 启用 / 停用接口
  - URL
  - Method
  - 状态字段
- 失败响应样本
  - 登录失效
  - 参数缺失
  - 节点配置错误

## 3. 建议 JSON 配置格式
后续补完后，请新增 `private_workflow_api.json`，结构建议如下：

```json
{
  "schemaVersion": "workflow_private_api_v1",
  "enabled": true,
  "saveFlowUrl": "https://...",
  "publishUrl": "https://...",
  "enableUrl": "https://..."
}
```

说明：
- `enabled=true` 时，`create_workflows_from_plan.py` 才会真正发起非 dry-run 请求。
- 未提供该 JSON 时，脚本会明确报错并提示先补抓包资料。
