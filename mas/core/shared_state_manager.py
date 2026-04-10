"""
Shared State Manager
Single source of truth for any active project.
Enforces access control, mutability, and append-only rules on every write.

Usage as library:
    from core.shared_state_manager import SharedStateManager
    sm = SharedStateManager("proj-20260409-001")
    sm.initialize(request_id="req-001")

Usage as CLI:
    uv run python core/shared_state_manager.py init --project-id proj-001 --request-id req-001
    uv run python core/shared_state_manager.py read --project-id proj-001 --path core_identity.current_phase
    uv run python core/shared_state_manager.py write --project-id proj-001 --section core_identity --field status --value active --agent master_orchestrator
    uv run python core/shared_state_manager.py append --project-id proj-001 --section decisions --field assumptions --value-json '{"assumption_id":"a-001","stated_by":"master_orchestrator","description":"..."}' --agent master_orchestrator
    uv run python core/shared_state_manager.py approve --project-id proj-001 --section project_definition --field original_brief --agent master_orchestrator
    uv run python core/shared_state_manager.py snapshot --project-id proj-001 --phase intake
    uv run python core/shared_state_manager.py show --project-id proj-001
"""

import sys
import json
import shutil
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent

from core.access_control import (
    ACCESS_CONTROL, is_authorized, get_mode, get_mutability,
    requires_append_only, is_immutable, is_immutable_after_approval,
    SYSTEM, ANY_AGENT,
)
from core.audit_logger import AuditLogger, get_logger


@dataclass
class WriteResult:
    success: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.success


# --- INITIAL STATE FACTORY ---

def create_initial_state(project_id: str, request_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "core_identity": {
            "project_id": project_id,
            "request_id": request_id,
            "created_at": now,
            "updated_at": now,
            "current_phase": "intake",
            "status": "active",
        },
        "project_definition": {
            "original_brief": None,
            "clarified_specification": None,
            "project_goal": None,
            "problem_statement": None,
            "scope": {"inclusions": [], "exclusions": []},
            "constraints": [],
            "success_criteria": [],
            "acceptance_criteria": [],
            "risk_classification": None,
            "priority": None,
        },
        "workflow": {
            "active_agents": [],
            "completed_phases": [],
            "pending_assignments": [],
            "current_owner": "master_orchestrator",
            "handoff_history": [],
            "resource_requests": [],
            "resource_allocations": [],
        },
        "decisions": {
            "decision_log": [],
            "assumptions": [],
            "open_questions": [],
            "approvals": [],
            "policy_flags": [],
        },
        "capability": {
            "available_skills_snapshot": [],
            "reuse_candidates": [],
            "capability_gap_certificates": [],
            "spawn_requests": [],
            "spawned_agents": [],
            "verification_results": [],
        },
        "execution": {
            "execution_plan_path": None,
            "milestones": [],
            "tasks": [],
            "resource_requests": [],
            "progress_reports": [],
            "blocker_alerts": [],
            "delivery_risks": [],
        },
        "artifacts": {
            "documents": [],
            "deliverables": [],
            "change_log": [],
        },
        "evaluation": {
            "performance_metrics": [],
            "quality_findings": [],
            "improvement_proposals": [],
            "approved_updates": [],
        },
        "consultation": {
            "consultation_requests": [],
            "consultation_responses": [],
            "synthesis": [],
        },
        "_meta": {
            "version": "1.0.0",
            "approved_fields": [],
            "governance_violations": [],
        },
    }


# --- MAIN CLASS ---

class SharedStateManager:
    """
    Manages shared state for a single project.
    Enforces access control and governance rules on every write.
    """

    def __init__(self, project_id: str,
                 projects_root: Path | None = None,
                 audit_logger: AuditLogger | None = None):
        self.project_id = project_id
        self.projects_root = projects_root or (ROOT / "projects")
        self.project_dir = self.projects_root / project_id
        self.state_path = self.project_dir / "shared_state.yaml"
        self.logger = audit_logger or get_logger()

    # --- LIFECYCLE ---

    def initialize(self, request_id: str) -> None:
        """Create project directory and initialize shared state. Idempotent."""
        self.project_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            state = create_initial_state(self.project_id, request_id)
            self._save(state)
            self.logger.log(
                "project_initialized",
                project_id=self.project_id,
                request_id=request_id,
            )

    def exists(self) -> bool:
        return self.state_path.exists()

    # --- READ ---

    def load(self) -> dict:
        """Load and return the current shared state from disk."""
        with open(self.state_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def read(self, path: str) -> Any:
        """
        Read a value by dot-notation path (e.g. 'core_identity.current_phase').
        Returns None if path not found.
        """
        state = self.load()
        parts = path.split(".")
        node = state
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    # --- WRITE ---

    def write(self, agent_id: str, section: str, field: str,
              value: Any) -> WriteResult:
        """
        Write a value to section.field with full governance checks.
        Returns WriteResult(success, reason).
        """
        field_path = f"{section}.{field}"
        state = self.load()

        # 1. Check authorization
        if not is_authorized(agent_id, field_path):
            reason = "unauthorized_write"
            self._record_violation(state, agent_id, field_path, reason)
            self.logger.log_violation(agent_id, field_path, self.project_id, reason)
            return WriteResult(False, reason)

        # 2. Check immutability (set-once fields like created_at)
        if is_immutable(field_path):
            current = state.get(section, {}).get(field)
            if current is not None:
                reason = "field_is_immutable"
                self._record_violation(state, agent_id, field_path, reason)
                self.logger.log_violation(agent_id, field_path, self.project_id, reason)
                return WriteResult(False, reason)

        # 3. Check immutable-after-approval
        if is_immutable_after_approval(field_path):
            approved = state.get("_meta", {}).get("approved_fields", [])
            if field_path in approved:
                reason = "field_is_immutable"
                self._record_violation(state, agent_id, field_path, reason)
                self.logger.log_violation(agent_id, field_path, self.project_id, reason)
                return WriteResult(False, reason)

        # 4. Reject writes to append-only fields (must use append())
        if requires_append_only(field_path):
            reason = "field_is_append_only"
            self._record_violation(state, agent_id, field_path, reason)
            self.logger.log_violation(agent_id, field_path, self.project_id, reason)
            return WriteResult(False, reason)

        # 5. Apply write
        if section not in state:
            state[section] = {}
        state[section][field] = value
        state["core_identity"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save(state)
        self.logger.log_write(agent_id, field_path, self.project_id, True)

        # 6. Checkpoint after phase transitions
        if field_path == "core_identity.current_phase":
            try:
                from core.checkpoint_writer import CheckpointWriter
                CheckpointWriter(self.project_id).write()
            except Exception:
                pass  # checkpoint failure must never block state writes

        return WriteResult(True)

    def append(self, agent_id: str, section: str, field: str,
               item: Any) -> WriteResult:
        """
        Append an item to an append-only list field.
        Also works for fields with no mode restriction.
        """
        field_path = f"{section}.{field}"
        state = self.load()

        # 1. Check authorization
        if not is_authorized(agent_id, field_path):
            reason = "unauthorized_write"
            self._record_violation(state, agent_id, field_path, reason)
            self.logger.log_violation(agent_id, field_path, self.project_id, reason)
            return WriteResult(False, reason)

        # 2. The field must currently be (or become) a list
        if section not in state:
            state[section] = {}
        current = state[section].get(field, [])
        if current is None:
            current = []
        if not isinstance(current, list):
            return WriteResult(False, "field_is_not_a_list")

        current.append(item)
        state[section][field] = current
        state["core_identity"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save(state)
        self.logger.log_write(agent_id, field_path, self.project_id, True)
        return WriteResult(True)

    def system_append(self, section: str, field: str, item: Any) -> WriteResult:
        """Internal system append — bypasses agent authorization check for system-owned fields."""
        return self.append(SYSTEM, section, field, item)

    # --- APPROVAL ---

    def approve(self, agent_id: str, section: str, field: str) -> WriteResult:
        """
        Mark a field as approved. After this, immutable_after_approval fields
        cannot be changed.
        Only master_orchestrator can approve fields.
        """
        if agent_id != "master_orchestrator":
            return WriteResult(False, "only_master_can_approve")
        field_path = f"{section}.{field}"
        state = self.load()
        meta = state.setdefault("_meta", {})
        approved = meta.setdefault("approved_fields", [])
        if field_path not in approved:
            approved.append(field_path)
        state["core_identity"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save(state)
        self.logger.log("field_approved", agent_id=agent_id,
                        field_path=field_path, project_id=self.project_id)
        return WriteResult(True)

    # --- SNAPSHOT ---

    def snapshot(self, phase: str) -> Path:
        """Save a copy of current state as a phase snapshot."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        snap_path = self.project_dir / f"shared_state_snapshot_{phase}_{ts}.yaml"
        shutil.copy2(self.state_path, snap_path)
        self.logger.log_phase_transition(self.project_id, "current", phase)
        return snap_path

    # --- GOVERNANCE TRACKING ---

    def _record_violation(self, state: dict, agent_id: str,
                          field_path: str, reason: str) -> None:
        """Record a governance violation inside the state (best-effort, no save here)."""
        violations = state.get("_meta", {}).setdefault("governance_violations", [])
        violations.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "field_path": field_path,
            "reason": reason,
        })
        # Save violation record
        try:
            self._save(state)
        except Exception:
            pass  # Violations are logged to audit even if state save fails

    def get_violation_count(self, agent_id: str) -> int:
        """Count governance violations for a specific agent."""
        state = self.load()
        violations = state.get("_meta", {}).get("governance_violations", [])
        return sum(1 for v in violations if v.get("agent_id") == agent_id)

    # --- INTERNAL ---

    def _save(self, state: dict) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            yaml.dump(state, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)


# --- CLI ---

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shared_state_manager",
        description="Shared State Manager CLI",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # init
    init_p = sub.add_parser("init", help="Initialize a new project state")
    init_p.add_argument("--project-id", required=True)
    init_p.add_argument("--request-id", required=True)

    # read
    read_p = sub.add_parser("read", help="Read a field value")
    read_p.add_argument("--project-id", required=True)
    read_p.add_argument("--path", required=True, help="Dot-notation field path")

    # write
    write_p = sub.add_parser("write", help="Write a field value")
    write_p.add_argument("--project-id", required=True)
    write_p.add_argument("--section", required=True)
    write_p.add_argument("--field", required=True)
    write_p.add_argument("--value", help="String value")
    write_p.add_argument("--value-json", help="JSON value (overrides --value)")
    write_p.add_argument("--agent", required=True)

    # append
    append_p = sub.add_parser("append", help="Append to a list field")
    append_p.add_argument("--project-id", required=True)
    append_p.add_argument("--section", required=True)
    append_p.add_argument("--field", required=True)
    append_p.add_argument("--value-json", required=True, help="JSON item to append")
    append_p.add_argument("--agent", required=True)

    # approve
    approve_p = sub.add_parser("approve", help="Approve a field (makes it immutable)")
    approve_p.add_argument("--project-id", required=True)
    approve_p.add_argument("--section", required=True)
    approve_p.add_argument("--field", required=True)
    approve_p.add_argument("--agent", required=True)

    # snapshot
    snap_p = sub.add_parser("snapshot", help="Snapshot current state at phase")
    snap_p.add_argument("--project-id", required=True)
    snap_p.add_argument("--phase", required=True)

    # show
    show_p = sub.add_parser("show", help="Print current state")
    show_p.add_argument("--project-id", required=True)

    return p


def main_cli(args=None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(args)
    sm = SharedStateManager(ns.project_id)

    if ns.command == "init":
        sm.initialize(ns.request_id)
        print(f"OK project {ns.project_id} initialized")

    elif ns.command == "read":
        val = sm.read(ns.path)
        print(yaml.dump(val, default_flow_style=False, allow_unicode=True))

    elif ns.command == "write":
        value = ns.value
        if ns.value_json:
            value = json.loads(ns.value_json)
        result = sm.write(ns.agent, ns.section, ns.field, value)
        if result.success:
            print("OK")
        else:
            print(f"DENIED: {result.reason}", file=sys.stderr)
            return 1

    elif ns.command == "append":
        item = json.loads(ns.value_json)
        result = sm.append(ns.agent, ns.section, ns.field, item)
        if result.success:
            print("OK")
        else:
            print(f"DENIED: {result.reason}", file=sys.stderr)
            return 1

    elif ns.command == "approve":
        result = sm.approve(ns.agent, ns.section, ns.field)
        if result.success:
            print("OK")
        else:
            print(f"DENIED: {result.reason}", file=sys.stderr)
            return 1

    elif ns.command == "snapshot":
        path = sm.snapshot(ns.phase)
        print(f"OK snapshot saved: {path}")

    elif ns.command == "show":
        state = sm.load()
        print(yaml.dump(state, default_flow_style=False, allow_unicode=True, sort_keys=False))

    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
