# 多模型接入计划

## 需求确认

- 初始化阶段选择 AI 平台：`Gemini` 或 `DeepSeek`
- 选择后输入对应平台 `API Key`，并持久化保存
- 后续运行自动复用该配置
- `python3 setup.py --show` 支持查看并修改 AI 平台、模型和 Key
- 需求收集、工作表规划、视图规划、筛选规划、造数规划、角色规划、机器人规划、工作流规划、Page 规划、图标匹配等大模型调用，统一走当前选中的平台和模型

## 实施方案

1. 新增统一 AI 配置：`config/credentials/ai_auth.json`
2. 保留对旧 `gemini_auth.json` 的兼容读取
3. 扩展统一 AI 工具层，提供：
   - provider/api_key/model/base_url 统一读取
   - Gemini / DeepSeek 统一客户端
   - 统一生成配置构造方法
4. 修改 `setup.py`
   - 初始化时选择平台并写入 `ai_auth.json`
   - `--show` 模式下支持交互式修改 AI 配置
5. 修改主流程涉及的 AI 脚本
   - 默认模型从统一配置读取
   - 客户端创建改为统一兼容层
   - 去除 Gemini 硬编码默认平台
6. 验证
   - Python 语法检查
   - 关键入口 help/静态运行验证
