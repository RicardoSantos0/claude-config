"""
Handoff Engine
Creates, validates, accepts, and rejects formal agent-to-agent handoffs.
Every handoff is recorded in shared_state.workflow.handoff_history.

Usage as library:
    from core.handoff_engine import HandoffEngine
    from core.shared_state_manager import SharedStateManager
    engine = HandoffEngine()
    sm = SharedStateManager("proj-001")
    handoff = engine.create(sm, from_agent="master_orchestrator",
                            to_agent="scribe_agent", ...)

Usage as CLI:
    uv run python core/handoff_engine.py create --project-id proj-001 --from master_orchestrator --to scribe_agent --phase intake --task "Initialize project folder" --summary "Starting project"
    uv run python core/handoff_engine.py accept --handoff-id ho-proj-001-001 --project-id proj-001
    uv run python core/handoff_engine.py reject --handoff-id ho-proj-001-001 --project-id proj-001 --reason "Missing required fields"
    uv run python core/handoff_engine.py pending --project-id proj-001
    uv run python core/handoff_engine.py show --handoff-id ho-proj-001-001 --project-id proj-001
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).parent.parent

from core.shared_state_manager import SharedStateManager
from core.audit_logger import get_logger
from core.checkpoint_writer import CheckpointWriter


REQUIRED_PAYLOAD_KEYS = [
    "summary",
    "artifacts_produced",
    "decisions_made",
    "open_questions",
    "constraints_for_next",
    "shared_state_fields_modified",
]


class HandoffEngine:
    """
    Manages formal agent-to-agent handoffs.
    All handoffs are logged in shared_state.workflow.handoff_history.
    """

    def __init__(self, audit_logger=None):
        self.logger = audit_logger or get_logger()

    # --- SEQUENCE COUNTER ---

    def _next_sequence(self, state: dict, project_id: str) -> int:
        history = state.get("workflow", {}).get("handoff_history", [])
        return len(history) + 1

    def _make_id(self, project_id: str, sequence: int) -> str:
        return f"ho-{project_id}-{sequence:03d}"

    # --- CREATE ---

    def create(
        self,
        sm: SharedStateManager,
        from_agent: str,
        to_agent: str,
        phase: str,
        task_description: str,
        payload: dict,
        authorized_by: str = "master_orchestrator",
        token_usage: Optional[dict] = None,
    ) -> dict:
        """
        Create a new handoff record and write it to shared state.
        Returns the handoff dict.
        """
        state = sm.load()
        seq = self._next_sequence(state, sm.project_id)
        handoff_id = self._make_id(sm.project_id, seq)
        now = datetime.now(timezone.utc).isoformat()

        handoff = {
            "handoff_id": handoff_id,
            "project_id": sm.project_id,
            "timestamp": now,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "authorized_by": authorized_by,
            "phase": phase,
            "task_description": task_description,
            "payload": {
                **{k: v for k, v in payload.items()
                   if k not in {"summary", "artifacts_produced", "decisions_made",
                                "open_questions", "constraints_for_next",
                                "shared_state_fields_modified"}},
                "summary": payload.get("summary", ""),
                "artifacts_produced": payload.get("artifacts_produced", []),
                "decisions_made": payload.get("decisions_made", []),
                "open_questions": payload.get("open_questions", []),
                "constraints_for_next": payload.get("constraints_for_next", []),
                "shared_state_fields_modified": payload.get("shared_state_fields_modified", []),
            },
            "token_usage": token_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "acceptance": {
                "status": "pending",
                "rejection_reason": None,
                "follow_up_questions": None,
                "accepted_at": None,
            },
        }

        result = sm.system_append("workflow", "handoff_history", handoff)
        if not result:
            raise RuntimeError(f"Failed to record handoff: {result.reason}")

        self.logger.log_handoff(
            "handoff_created",
            handoff_id=handoff_id,
            project_id=sm.project_id,
            from_agent=from_agent,
            to_agent=to_agent,
        )
        return handoff

    # --- VALIDATE ---

    def validate(self, handoff: dict) -> tuple[bool, list[str]]:
        """
        Validate a handoff has all required fields.
        Returns (is_valid, list_of_errors).
        """
        errors = []
        for key in ("handoff_id", "project_id", "from_agent", "to_agent",
                    "authorized_by", "phase", "task_description", "payload"):
            if not handoff.get(key):
                errors.append(f"Missing required field: {key}")

        payload = handoff.get("payload", {})
        for key in REQUIRED_PAYLOAD_KEYS:
            if key not in payload:
                errors.append(f"Missing payload field: {key}")

        return len(errors) == 0, errors

    # --- ACCEPT / REJECT ---

    def _update_handoff_in_state(self, sm: SharedStateManager,
                                  handoff_id: str, updates: dict) -> bool:
        """Find the handoff in history and update its acceptance record."""
        state = sm.load()
        history = state.get("workflow", {}).get("handoff_history", [])
        found = False
        for h in history:
            if h.get("handoff_id") == handoff_id:
                h["acceptance"].update(updates)
                found = True
                break
        if not found:
            return False
        from pathlib import Path
        import yaml as _yaml
        with open(sm.state_path, "w", encoding="utf-8") as f:
            _yaml.dump(state, f, default_flow_style=False,
                       allow_unicode=True, sort_keys=False)
        return True

    def accept(self, sm: SharedStateManager, handoff_id: str,
               follow_up_questions: Optional[list] = None) -> bool:
        """Accept a pending handoff. Returns True on success."""
        now = datetime.now(timezone.utc).isoformat()
        status = "accepted_with_questions" if follow_up_questions else "accepted"
        ok = self._update_handoff_in_state(sm, handoff_id, {
            "status": status,
            "accepted_at": now,
            "follow_up_questions": follow_up_questions,
        })
        if ok:
            self.logger.log_handoff(
                "handoff_accepted",
                handoff_id=handoff_id,
                project_id=sm.project_id,
                from_agent="",
                to_agent="",
                status=status,
            )
            try:
                CheckpointWriter(sm.project_id).write()
            except Exception:
                pass  # checkpoint failure must never block handoff acceptance
        return ok

    def reject(self, sm: SharedStateManager, handoff_id: str,
               reason: str) -> bool:
        """Reject a pending handoff. Returns True on success."""
        ok = self._update_handoff_in_state(sm, handoff_id, {
            "status": "rejected",
            "rejection_reason": reason,
        })
        if ok:
            self.logger.log_handoff(
                "handoff_rejected",
                handoff_id=handoff_id,
                project_id=sm.project_id,
                from_agent="",
                to_agent="",
                reason=reason,
            )
        return ok

    # --- QUERY ---

    def get(self, sm: SharedStateManager, handoff_id: str) -> Optional[dict]:
        """Get a specific handoff by ID."""
        state = sm.load()
        for h in state.get("workflow", {}).get("handoff_history", []):
            if h.get("handoff_id") == handoff_id:
                return h
        return None

    def get_pending(self, sm: SharedStateManager,
                    to_agent: Optional[str] = None) -> list[dict]:
        """Get all pending handoffs, optionally filtered by recipient."""
        state = sm.load()
        history = state.get("workflow", {}).get("handoff_history", [])
        pending = [h for h in history
                   if h.get("acceptance", {}).get("status") == "pending"]
        if to_agent:
            pending = [h for h in pending if h.get("to_agent") == to_agent]
        return pending

    def get_all(self, sm: SharedStateManager) -> list[dict]:
        """Get all handoffs for the project."""
        state = sm.load()
        return state.get("workflow", {}).get("handoff_history", [])


# --- CLI ---

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="handoff_engine", description="Handoff Engine CLI")
    sub = p.add_subparsers(dest="command", required=True)

    # create
    c = sub.add_parser("create", help="Create a new handoff")
    c.add_argument("--project-id", required=True)
    c.add_argument("--from", dest="from_agent", required=True)
    c.add_argument("--to", dest="to_agent", required=True)
    c.add_argument("--phase", required=True)
    c.add_argument("--task", required=True, dest="task_description")
    c.add_argument("--summary", default="")
    c.add_argument("--authorized-by", default="master_orchestrator")
    c.add_argument("--payload-json", help="Full payload as JSON (overrides --summary)")

    # accept
    a = sub.add_parser("accept", help="Accept a handoff")
    a.add_argument("--handoff-id", required=True)
    a.add_argument("--project-id", required=True)
    a.add_argument("--questions-json", help="Follow-up questions as JSON array")

    # reject
    r = sub.add_parser("reject", help="Reject a handoff")
    r.add_argument("--handoff-id", required=True)
    r.add_argument("--project-id", required=True)
    r.add_argument("--reason", required=True)

    # pending
    pe = sub.add_parser("pending", help="List pending handoffs")
    pe.add_argument("--project-id", required=True)
    pe.add_argument("--to-agent", default=None)

    # show
    s = sub.add_parser("show", help="Show a specific handoff")
    s.add_argument("--handoff-id", required=True)
    s.add_argument("--project-id", required=True)

    return p


def main_cli(args=None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(args)
    engine = HandoffEngine()
    sm = SharedStateManager(ns.project_id)

    if ns.command == "create":
        if ns.payload_json:
            payload = json.loads(ns.payload_json)
        else:
            payload = {
                "summary": ns.summary,
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            }
        handoff = engine.create(
            sm,
            from_agent=ns.from_agent,
            to_agent=ns.to_agent,
            phase=ns.phase,
            task_description=ns.task_description,
            payload=payload,
            authorized_by=ns.authorized_by,
        )
        print(f"OK handoff_id={handoff['handoff_id']}")

    elif ns.command == "accept":
        questions = json.loads(ns.questions_json) if ns.questions_json else None
        ok = engine.accept(sm, ns.handoff_id, follow_up_questions=questions)
        print("OK" if ok else "NOT FOUND")

    elif ns.command == "reject":
        ok = engine.reject(sm, ns.handoff_id, ns.reason)
        print("OK" if ok else "NOT FOUND")

    elif ns.command == "pending":
        pending = engine.get_pending(sm, to_agent=ns.to_agent)
        print(yaml.dump(pending, default_flow_style=False, allow_unicode=True))

    elif ns.command == "show":
        h = engine.get(sm, ns.handoff_id)
        if h:
            print(yaml.dump(h, default_flow_style=False, allow_unicode=True))
        else:
            print("NOT FOUND", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
