"""
pipeline/context.py

PipelineContext：封装 execute_requirements.py 中 main() 的共享状态。
包括 build_report() 和 save_report() 方法。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

from utils import now_iso, now_ts, write_json


@dataclass
class PipelineContext:
    # ── 执行参数 ──────────────────────────────────────────────
    spec_path: Path
    execution_dry_run: bool
    fail_fast: bool
    verbose: bool
    selected_steps: set

    # ── 共享状态（由各步骤写入） ─────────────────────────────
    app_id: Optional[str] = None
    app_auth_json: Optional[str] = None
    worksheet_plan_json: Optional[str] = None
    sections_plan_json: Optional[str] = None
    sections_create_result_json: Optional[str] = None
    worksheet_create_result_json: Optional[str] = None
    role_pipeline_report_json: Optional[str] = None
    role_plan_json: Optional[str] = None
    role_create_result_json: Optional[str] = None
    worksheet_layout_plan_json: Optional[str] = None
    worksheet_layout_apply_result_json: Optional[str] = None
    view_plan_json: Optional[str] = None
    view_create_result_json: Optional[str] = None
    tableview_filter_plan_json: Optional[str] = None
    tableview_filter_apply_result_json: Optional[str] = None
    mock_data_run_json: Optional[str] = None
    mock_data_inline_result_json: Optional[str] = None   # Wave 3.5b Phase 1 产物
    mock_relation_apply_result_json: Optional[str] = None  # Wave 3.5b Phase 2 产物
    chatbot_pipeline_result_json: Optional[str] = None
    workflow_plan_json: Optional[str] = None
    workflow_execute_result_json: Optional[str] = None
    page_registry_json: Optional[str] = None

    # ── 步骤报告（线程安全） ────────────────────────────────
    steps_report: List[dict] = field(default_factory=list)
    steps_lock: threading.Lock = field(default_factory=threading.Lock)

    # ── 输出目录 ────────────────────────────────────────────
    execution_run_dir: Optional[Path] = None

    def as_artifacts_dict(self) -> Dict[str, Any]:
        return {
            "app_auth_json": self.app_auth_json,
            "worksheet_plan_json": self.worksheet_plan_json,
            "sections_plan_json": self.sections_plan_json,
            "sections_create_result_json": self.sections_create_result_json,
            "worksheet_create_result_json": self.worksheet_create_result_json,
            "role_pipeline_report_json": self.role_pipeline_report_json,
            "role_plan_json": self.role_plan_json,
            "role_create_result_json": self.role_create_result_json,
            "worksheet_layout_plan_json": self.worksheet_layout_plan_json,
            "worksheet_layout_apply_result_json": self.worksheet_layout_apply_result_json,
            "view_plan_json": self.view_plan_json,
            "view_create_result_json": self.view_create_result_json,
            "tableview_filter_plan_json": self.tableview_filter_plan_json,
            "tableview_filter_apply_result_json": self.tableview_filter_apply_result_json,
            "mock_data_run_json": self.mock_data_run_json,
            "mock_data_inline_result_json": self.mock_data_inline_result_json,
            "mock_relation_apply_result_json": self.mock_relation_apply_result_json,
            "chatbot_pipeline_result_json": self.chatbot_pipeline_result_json,
            "workflow_plan_json": self.workflow_plan_json,
            "workflow_execute_result_json": self.workflow_execute_result_json,
            "page_registry_json": self.page_registry_json,
        }

    def as_legacy_dict(self) -> Dict[str, Any]:
        """兼容旧代码：返回 context dict 格式。"""
        d = {"app_id": self.app_id}
        d.update(self.as_artifacts_dict())
        return d

    def has_failure(self) -> bool:
        with self.steps_lock:
            return any(
                x.get("ok") is False and not x.get("non_fatal")
                for x in self.steps_report
            )

    def build_report(self) -> dict:
        ok_count = len([
            s for s in self.steps_report
            if s.get("ok") is True or s.get("skipped") is True
        ])
        fail_count = len([s for s in self.steps_report if s.get("ok") is False])
        return {
            "schema_version": "workflow_requirement_v1_execution_report",
            "created_at": now_iso(),
            "spec_json": str(self.spec_path),
            "dry_run": self.execution_dry_run,
            "fail_fast": self.fail_fast,
            "summary": {
                "total_steps": len(self.steps_report),
                "ok_or_skipped": ok_count,
                "failed": fail_count,
            },
            "artifacts": self.as_artifacts_dict(),
            "context": self.as_legacy_dict(),
            "steps": self.steps_report,
        }

    def save_report(self) -> Path:
        report = self.build_report()
        run_dir = self.execution_run_dir
        if run_dir is None:
            raise RuntimeError("execution_run_dir not set")
        run_dir.mkdir(parents=True, exist_ok=True)
        out = (run_dir / f"execution_run_{now_ts()}.json").resolve()
        write_json(out, report)
        write_json((run_dir / "execution_run_latest.json").resolve(), report)
        return out
