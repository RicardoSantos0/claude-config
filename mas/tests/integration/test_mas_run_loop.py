"""
Integration Tests — OrchestrationLoop (mas run)

Runs the full loop against a real project directory with AgentRunner mocked
to return controlled wire-protocol responses.  Verifies that:
  - phase advances are written to shared state
  - phase snapshots are created
  - handoffs are created and accepted
  - sub-agent dec/art are written to shared state
  - StopReason values are correct
  - loop halts cleanly on project_closed
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.engine.orchestration_loop import (
    OrchestrationLoop,
    LoopConfig,
    LoopResult,
    StopReason,
    _next_phase,
)
from core.engine.shared_state_manager import SharedStateManager
from core.engine.audit_logger import AuditLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wire(s: str, **kwargs) -> str:
    wire = {"_v": "1.0", "s": s, **kwargs}
    return f"Agent reasoning.\n\n```json\n{json.dumps(wire)}\n```"


def _make_project(tmp_path: Path, project_id: str) -> Path:
    """Create a minimal project directory with shared_state.yaml."""
    proj_dir = tmp_path / project_id
    proj_dir.mkdir(parents=True)

    al = AuditLogger(log_path=proj_dir / "audit.log")
    sm = SharedStateManager(
        project_id,
        projects_root=tmp_path,
        audit_logger=al,
    )
    sm.initialize(request_id="req-test-001")
    # Initialise with minimal state the loop expects
    sm.write("master_orchestrator", "project_definition", "original_brief", "Test project")
    sm.write("master_orchestrator", "project_definition", "risk_classification", "low")
    return proj_dir


def _patched_loop(
    project_id: str,
    tmp_path: Path,
    responses: list[str],
    *,
    max_steps: int = 10,
    auto: bool = True,
    target_phase: str | None = None,
) -> OrchestrationLoop:
    """Return a loop whose _dispatch_agent cycles through `responses`."""
    cfg = LoopConfig(
        project_id=project_id,
        max_steps=max_steps,
        dry_run=True,
        auto=auto,
        target_phase=target_phase,
    )
    loop = OrchestrationLoop(cfg)

    # Override the projects root so state files are in tmp_path
    _orig_load = loop._load_state

    def _load():
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.audit_logger import AuditLogger
        al = AuditLogger(log_path=tmp_path / project_id / "audit.log")
        sm = SharedStateManager(project_id, projects_root=tmp_path, audit_logger=al)
        return sm.load()

    loop._load_state = _load

    # Cycle through the provided responses
    call_iter = iter(responses + [_wire("wait")] * 100)

    def _dispatch(agent_id, state):
        from core.engine.orchestration_loop import _AgentResponse
        text = next(call_iter)
        return _AgentResponse(
            agent_id=agent_id,
            raw_text=text,
            tokens_used=0,
            dry_run=True,
        )

    loop._dispatch_agent = _dispatch

    # Route all state writes through the tmp_path SM
    def _make_sm():
        al = AuditLogger(log_path=tmp_path / project_id / "audit.log")
        return SharedStateManager(project_id, projects_root=tmp_path, audit_logger=al)

    # Patch _execute_master_actions to use tmp_path SM
    _orig_ema = loop._execute_master_actions

    def _ema(parsed, state):
        from core.engine.shared_state_manager import SharedStateManager as SM
        from core.engine.handoff_engine import HandoffEngine
        from core.engine.orchestration_loop import _next_phase
        from datetime import datetime, timezone
        sm = _make_sm()
        he = HandoffEngine()
        phase = state.get("core_identity", {}).get("current_phase", "intake")
        now = datetime.now(timezone.utc).isoformat()

        for dec in parsed.decisions:
            if isinstance(dec, dict) and dec.get("id"):
                try:
                    sm.append("master_orchestrator", "decisions", "decision_log", {
                        "decision_id":             dec.get("id"),
                        "value":                   dec.get("v", ""),
                        "rationale":               dec.get("rat", ""),
                        "alternatives_considered": dec.get("alt", []),
                        "related_to":              dec.get("rel", ""),
                        "recorded_at":             now,
                        "source":                  "orchestration_loop",
                    })
                except Exception:
                    pass

        for art in parsed.artifacts:
            try:
                sm.append("master_orchestrator", "artifacts", "documents", art)
            except Exception:
                pass

        if parsed.next_action == "advance_phase":
            new_phase = _next_phase(phase, state.get("workflow", {}).get("mode", "standard"))
            sm.snapshot(phase)
            sm.write("master_orchestrator", "core_identity", "current_phase", new_phase)
            sm.system_append("workflow", "completed_phases", phase)
            loop._write_phase_document(phase, state, tmp_path / project_id)

        if parsed.next_action == "delegate" and parsed.next_agent:
            payload = {
                "_v": "1.0", "s": "task:delegated",
                "summary": parsed.reasoning[:200] if parsed.reasoning else "",
                "artifacts_produced": [], "decisions_made": [],
                "open_questions": [], "constraints_for_next": [],
                "shared_state_fields_modified": [],
            }
            try:
                he.create(sm,
                          from_agent="master_orchestrator",
                          to_agent=parsed.next_agent,
                          phase=phase,
                          task_description=parsed.reasoning or f"Execute {phase}",
                          payload=payload)
            except Exception:
                pass

        if parsed.next_action == "escalate":
            from core.engine.orchestration_loop import _EscalationRequired
            raise _EscalationRequired(parsed.reasoning or "escalation")

        return None

    loop._execute_master_actions = _ema

    return loop


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoopAdvancesPhase:

    def test_advance_phase_writes_state(self, tmp_path):
        pid = "proj-loop-int-001"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete"),   # master signals phase complete
        ], max_steps=2)

        result = loop.run()

        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        state = sm.load()

        assert "intake" in state["workflow"]["completed_phases"]
        assert state["core_identity"]["current_phase"] == "specification"

    def test_snapshot_created_on_advance(self, tmp_path):
        pid = "proj-loop-int-002"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete"),
        ], max_steps=2)
        loop.run()

        # snapshot saves a file like intake_snapshot.yaml or intake/snapshot.yaml
        snap_files = list((tmp_path / pid).rglob("*intake*snapshot*"))
        snap_files += list((tmp_path / pid).rglob("*snapshot*intake*"))
        assert snap_files, "No intake snapshot file created"

    def test_phase_boundary_detected(self, tmp_path):
        pid = "proj-loop-int-003"
        _make_project(tmp_path, pid)

        loop = _patched_loop(
            pid, tmp_path,
            [_wire("task:complete")],
            max_steps=5,
            target_phase="specification",
        )
        result = loop.run()
        assert result.reason == StopReason.TARGET_REACHED
        assert result.last_phase == "specification"


class TestLoopDecisions:

    def test_decisions_written_to_state(self, tmp_path):
        pid = "proj-loop-int-004"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete",
                  dec=[{"id": "d-int-001", "v": "use sqlite"}]),
        ], max_steps=2)
        loop.run()

        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        state = sm.load()
        ids = [d.get("decision_id") for d in state["decisions"]["decision_log"]]
        assert "d-int-001" in ids

    def test_artifacts_written_to_state(self, tmp_path):
        pid = "proj-loop-int-005"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete", art=["mas/core/engine/new_module.py"]),
        ], max_steps=2)
        loop.run()

        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        state = sm.load()
        assert "mas/core/engine/new_module.py" in state["artifacts"]["documents"]


class TestLoopHandoffs:

    def test_delegate_creates_handoff(self, tmp_path):
        pid = "proj-loop-int-006"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete",
                  next_action="delegate",
                  next_agent="inquirer_agent",
                  rsn="Delegating intake to inquirer"),
        ], max_steps=3)
        loop.run()

        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        state = sm.load()
        history = state["workflow"]["handoff_history"]
        assert any(h.get("to_agent") == "inquirer_agent" or
                   (isinstance(h, dict) and "to_agent" in str(h))
                   for h in history)


class TestLoopStopConditions:

    def test_stops_on_project_closed(self, tmp_path):
        pid = "proj-loop-int-007"
        _make_project(tmp_path, pid)

        # Pre-close the project
        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        sm.write("master_orchestrator", "core_identity", "status", "closed")

        loop = _patched_loop(pid, tmp_path, [], max_steps=10)
        result = loop.run()
        assert result.reason == StopReason.PROJECT_CLOSED
        assert result.stopped_at_step == 0

    def test_max_steps_respected(self, tmp_path):
        pid = "proj-loop-int-008"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path,
                             [_wire("wait")] * 20,
                             max_steps=3)
        result = loop.run()
        assert result.reason == StopReason.MAX_STEPS
        assert result.stopped_at_step == 3

    def test_escalation_stops_loop(self, tmp_path):
        pid = "proj-loop-int-009"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("escalate", rsn="Critical risk detected"),
        ], max_steps=5)
        result = loop.run()
        assert result.reason == StopReason.HUMAN_ESCALATION


class TestPhaseDocumentsAndGraphReplay:
    """Phase docs written on advance; EpisodeWriter called at closure (proj-007)."""

    def test_intake_doc_written_on_advance(self, tmp_path):
        pid = "proj-loop-int-010"
        _make_project(tmp_path, pid)

        # Set clarified_specification so the doc has content
        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        sm.write("master_orchestrator", "project_definition", "clarified_specification",
                 "Build a test project")

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete"),   # master signals phase complete → advance
        ], max_steps=2)
        loop.run()

        # intake/clarified_spec.yaml should now exist
        doc = tmp_path / pid / "intake" / "clarified_spec.yaml"
        assert doc.exists(), "intake/clarified_spec.yaml not created on phase advance"
        import yaml as _yaml
        content = _yaml.safe_load(doc.read_text(encoding="utf-8"))
        assert content.get("clarified_specification") == "Build a test project"

    def test_decisions_include_rationale_fields(self, tmp_path):
        pid = "proj-loop-int-011"
        _make_project(tmp_path, pid)

        loop = _patched_loop(pid, tmp_path, [
            _wire("task:complete",
                  dec=[{"id": "d-rat-001", "v": "use sqlite",
                        "rat": "lightweight", "alt": ["postgres"], "rel": "d-000"}]),
        ], max_steps=2)
        loop.run()

        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        state = sm.load()
        log = state["decisions"]["decision_log"]
        entry = next((d for d in log if d.get("decision_id") == "d-rat-001"), None)
        assert entry is not None
        assert entry.get("rationale") == "lightweight"
        assert entry.get("alternatives_considered") == ["postgres"]
        assert entry.get("related_to") == "d-000"
