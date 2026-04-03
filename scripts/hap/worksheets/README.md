# 工作表字段类型注册中心

## 字段类型清单 (35 种)

### 基础输入
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Text | 2 | 文本 | 第一个自动设为标题 |
| RichText | 41 | 富文本 | 长文编辑器 |
| AutoNumber | 33 | 自动编号 | 自动递增 |

### 数值
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Number | 6 | 数值 | precision=2 |
| Money | 8 | 金额 | precision=2, unit=¥ |
| Formula | 31 | 公式 | 计算表达式 |

### 选择
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| SingleSelect | 9 | 单选 | 需 option_values |
| MultipleSelect | 10 | 多选 | 需 option_values |
| Dropdown | 11 | 下拉框 | 用于看板分组 |
| Checkbox | 36 | 检查框 | 布尔开关 |
| Rating | 28 | 等级 | 1-5 星 |
| Score | 47 | 评分 | 可配最大分值 |

### 日期时间
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Date | 15 | 日期 | 适合甘特/日历 |
| DateTime | 16 | 日期时间 | 适合日历视图 |
| Time | 46 | 时间 | 仅时:分 |

### 联系方式
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Phone | 3 | 电话 | |
| Email | 5 | 邮箱 | |
| Link | 7 | 链接 | URL |

### 人员组织
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Collaborator | 26 | 成员 | required 强制 false |
| MultiCollaborator | 48 | 成员（多选） | |
| Department | 27 | 部门 | |
| OrgRole | 48 | 组织角色 | |

### 关联
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Relation | 29 | 关联记录 | 需 relation_target |
| SubTable | 34 | 子表 | 嵌入式关联 |
| Cascade | 35 | 级联选择 | 省/市/区 |
| OtherTableField | 30 | 他表字段 | 引用关联表值 |
| Rollup | 37 | 汇总 | 求和/计数等 |

### 文件
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Attachment | 14 | 附件 | 图片/文档 |
| Signature | 42 | 签名 | 手写签名 |

### 地理
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| Area | 24 | 地区 | 省/市/区 |
| Location | 40 | 定位 | GPS |

### 高级/布局
| 枚举名 | controlType | 名称 | 备注 |
|--------|-------------|------|------|
| QRCode | 43 | 二维码 | 自动生成 |
| Embed | 45 | 嵌入 | iframe |
| Section | 22 | 分段 | 表单分隔 |
| Remark | 10007 | 备注说明 | 静态文本 |
