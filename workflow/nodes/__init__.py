"""
工作流节点注册中心。

用法:
    from workflow.nodes import NODE_REGISTRY, build_save_body

    # 查看所有节点
    for name, spec in NODE_REGISTRY.items():
        print(f"{name}: typeId={spec['typeId']} verified={spec['verified']}")

    # 构建 saveNode body
    body = build_save_body("notify", process_id, node_id, worksheet_id, "通知", extra)
"""

from __future__ import annotations

from . import record_ops, notify, timer, approval, human, flow_control, compute, developer, ai

# (module, NODES dict, build function) 列表
_MODULES = [
    (record_ops, record_ops.NODES, record_ops.build),
    (notify,     notify.NODES,     notify.build),
    (timer,      timer.NODES,      timer.build),
    (approval,   approval.NODES,   approval.build),
    (human,      human.NODES,      human.build),
    (flow_control, flow_control.NODES, flow_control.build),
    (compute,    compute.NODES,    compute.build),
    (developer,  developer.NODES,  developer.build),
    (ai,         ai.NODES,         ai.build),
]

# NODE_REGISTRY: {node_type_name: {typeId, actionId, appType, name, verified, doc, build_fn, module}}
NODE_REGISTRY: dict[str, dict] = {}

for mod, nodes_dict, build_fn in _MODULES:
    for node_type, spec in nodes_dict.items():
        NODE_REGISTRY[node_type] = {
            **spec,
            "build_fn": build_fn,
            "module": mod.__name__,
        }

# 兼容旧 NODE_CONFIGS 格式: {node_type: {typeId, actionId, appType, name, ...}}
NODE_CONFIGS: dict[str, dict] = {
    k: {key: v[key] for key in ("typeId", "actionId", "appType", "name", "needs_worksheet", "needs_relation")
         if key in v}
    for k, v in NODE_REGISTRY.items()
}


def build_save_body(node_type: str, process_id: str, node_id: str,
                    worksheet_id: str, name: str, extra: dict) -> dict | None:
    """构建 saveNode 请求体。返回 None 表示该节点不需要 saveNode。"""
    if node_type not in NODE_REGISTRY:
        raise ValueError(f"未知节点类型: {node_type}。支持: {list(NODE_REGISTRY.keys())}")
    entry = NODE_REGISTRY[node_type]
    return entry["build_fn"](node_type, process_id, node_id, worksheet_id, name, extra)
