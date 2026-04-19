"""Tests for OrchestrationLoop — proj-20260415-005-mas-run-orchestration-loop."""

import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.engine.orchestration_loop import (
    OrchestrationLoop, LoopConfig, LoopResult, StopReason,
    _next_phase,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(phase="intake", status="active", mode="standard",
                handoffs=None, completed=None) -> dict:
    return {
        "core_identity": {
            "project_id": "proj-test-loop",
            "current_phase": phase,
            "status": status,
        },
        "workflow": {
            "mode": mode,
            "handoff_history": handoffs or [],
            "completed_phases": completed or [],
            "current_owner": "master_orchestrator",
        },
        "decisions": {"decision_log": []},
        "artifacts": {"documents": [], "change_log": []},
        "consultation": {"consultation_requests": [], "synthesis": []},
        "_meta": {"governance_violations": []},
    }


def _pending_handoff(to_agent: str) -> dict:
    return {
        "handoff_id": "ho-test-001",
        "from_agent": "master_orchestrator",
        "to_agent": to_agent,
        "phase": "intake",
        "task_description": "test task",
        "payload": {},
        "acceptance": {"status": "pending", "accepted_at": None,
                       "follow_up_questions": None, "rejection_reason": None},
    }


def _accepted_handoff(to_agent: str) -> dict:
    h = _pending_handoff(to_agent)
    h["acceptance"]["status"] = "accepted"
    return h


def _wire_response(**kwargs) -> str:
    wire = {"_v": "1.0", **kwargs}
    return f"Agent reasoning.\n\n```json\n{json.dumps(wire)}\n```"


# ---------------------------------------------------------------------------
# LoopConfig
# ---------------------------------------------------------------------------

class TestLoopConfig:

    def test_defaults(self):
        cfg = LoopConfig(project_id="proj-test")
        assert cfg.max_steps == 50
        assert cfg.auto is False
        assert cfg.target_phase is None
        assert cfg.max_agent_retries == 2

    def test_custom_values(self):
        cfg = LoopConfig(project_id="p", max_steps=5, auto=True,
                         target_phase="specification")
        assert cfg.max_steps == 5
        assert cfg.target_phase == "specification"


# ---------------------------------------------------------------------------
# Phase progression
# ---------------------------------------------------------------------------

class TestNextPhase:

    def test_intake_to_specification(self):
        assert _next_phase("intake") == "specification"

    def test_specification_to_planning(self):
        assert _next_phase("specification") == "planning"

    def test_planning_to_capability_discovery(self):
        assert _next_phase("planning") == "capability_discovery"

    def test_improvement_to_closed(self):
        assert _next_phase("improvement") == "closed"

    def test_unknown_phase_returns_closed(self):
        assert _next_phase("nonexistent") == "closed"

    def test_lite_intake_to_execution(self):
        assert _next_phase("intake", mode="lite") == "execution"


# ---------------------------------------------------------------------------
# _determine_next_agent
# ---------------------------------------------------------------------------

class TestDetermineNextAgent:

    def _loop(self):
        return OrchestrationLoop(LoopConfig(project_id="proj-test"))

    def test_no_history_returns_master(self):
        loop = self._loop()
        state = _make_state(handoffs=[])
        assert loop._determine_next_agent(state) == "master_orchestrator"

    def test_pending_handoff_returns_to_agent(self):
        loop = self._loop()
        state = _make_state(handoffs=[_pending_handoff("inquirer_agent")])
        assert loop._determine_next_agent(state) == "inquirer_agent"

    def test_accepted_handoff_returns_master(self):
        loop = self._loop()
        state = _make_state(handoffs=[_accepted_handoff("inquirer_agent")])
        assert loop._determine_next_agent(state) == "master_orchestrator"

    def test_last_handoff_determines_agent(self):
        """When there are multiple handoffs, only the last one matters."""
        loop = self._loop()
        state = _make_state(handoffs=[
            _accepted_handoff("inquirer_agent"),
            _pending_handoff("scribe_agent"),
        ])
        assert loop._determine_next_agent(state) == "scribe_agent"


# ---------------------------------------------------------------------------
# _build_extra_context
# ---------------------------------------------------------------------------

class TestBuildExtraContext:

    def test_empty_when_no_pending(self):
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        assert loop._build_extra_context() is None

    def test_grounded_context_injected_and_cleared(self):
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        loop._pending_grounded_context = "some knowledge answer"
        ctx = loop._build_extra_context()
        assert ctx is not None
        assert ctx["injected_grounded_context"] == "some knowledge answer"
        # Consumed — next call returns None
        assert loop._build_extra_context() is None

    def test_consultation_synthesis_injected_and_cleared(self):
        from dataclasses import dataclass

        @dataclass
        class FakeSynthesis:
            decision_reached: str = "proceed"
            rationale: str = "ok"

        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        loop._pending_consultation_synthesis = FakeSynthesis()
        ctx = loop._build_extra_context()
        assert ctx is not None
        assert "injected_consultation_synthesis" in ctx
        assert loop._build_extra_context() is None


# ---------------------------------------------------------------------------
# Loop control — max_steps and project closed
# ---------------------------------------------------------------------------

class TestLoopControl:

    def _patched_loop(self, tmp_path, state, response_text="", max_steps=3):
        """Helper: loop with mocked state load and agent dispatch."""
        cfg = LoopConfig(project_id="proj-loop-test", max_steps=max_steps, auto=True)
        loop = OrchestrationLoop(cfg)

        loop._load_state = MagicMock(return_value=state)
        loop._dispatch_agent = MagicMock(return_value=MagicMock(
            agent_id="master_orchestrator",
            raw_text=response_text,
            tokens_used=0,
        ))
        return loop

    def test_project_already_closed_stops_immediately(self, tmp_path):
        state = _make_state(status="closed")
        loop = self._patched_loop(tmp_path, state)
        result = loop.run()
        assert result.reason == StopReason.PROJECT_CLOSED
        assert result.stopped_at_step == 0

    def test_max_steps_stops_loop(self, tmp_path):
        state = _make_state()
        # Response with "wait" so loop doesn't advance phase
        resp = _wire_response(s="wait")
        loop = self._patched_loop(tmp_path, state, response_text=resp, max_steps=3)
        result = loop.run()
        assert result.reason == StopReason.MAX_STEPS
        assert result.stopped_at_step == 3

    def test_subagent_escalation_stops_loop(self, tmp_path):
        state = _make_state(handoffs=[_pending_handoff("inquirer_agent")])
        resp = _wire_response(
            s="human_required",
            next_action="escalate",
            rsn="Dry-run smoke test requires manual execution.",
        )
        loop = self._patched_loop(tmp_path, state, response_text=resp, max_steps=3)
        result = loop.run()
        assert result.reason == StopReason.HUMAN_ESCALATION


# ---------------------------------------------------------------------------
# Human checkpoint
# ---------------------------------------------------------------------------

class TestHumanCheckpoint:

    def test_auto_skips_input(self):
        cfg = LoopConfig(project_id="p", auto=True)
        loop = OrchestrationLoop(cfg)
        state = _make_state(phase="specification",
                            completed=["intake"])
        result = loop._human_checkpoint("specification", state)
        assert result is None  # None means continue

    def test_quit_response_stops_loop(self, monkeypatch):
        cfg = LoopConfig(project_id="p", auto=False)
        loop = OrchestrationLoop(cfg)
        state = _make_state(phase="specification")
        monkeypatch.setattr("builtins.input", lambda _: "q")
        result = loop._human_checkpoint("specification", state)
        assert result is not None
        assert result.reason == StopReason.PHASE_CHECKPOINT

    def test_enter_response_continues(self, monkeypatch):
        cfg = LoopConfig(project_id="p", auto=False)
        loop = OrchestrationLoop(cfg)
        state = _make_state(phase="specification")
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = loop._human_checkpoint("specification", state)
        assert result is None


# ---------------------------------------------------------------------------
# NotebookLM handler
# ---------------------------------------------------------------------------

class TestNotebookLMHandler:

    def test_missing_question_returns_empty(self):
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        result = loop._handle_knowledge_request({})
        assert result == ""

    def test_script_not_found_returns_unavailable(self, tmp_path, monkeypatch):
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        monkeypatch.setattr(
            "core.engine.orchestration_loop.ROOT",
            tmp_path,  # no skills/ folder here
        )
        result = loop._handle_knowledge_request({"question": "What is X?"})
        assert "notebooklm_unavailable" in result

    def test_successful_call_returns_stdout(self, monkeypatch):
        import subprocess as _sp

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "  The answer is 42.  "

        monkeypatch.setattr("subprocess.run", lambda *a, **kw: mock_result)

        # Make script appear to exist
        import core.engine.orchestration_loop as ol_mod
        fake_script = MagicMock()
        fake_script.exists.return_value = True
        fake_root = MagicMock()
        fake_root.__truediv__ = lambda self, other: fake_script

        original_root = ol_mod.ROOT
        ol_mod.ROOT = fake_root
        try:
            loop = OrchestrationLoop(LoopConfig(project_id="p"))
            result = loop._handle_knowledge_request({"question": "What is X?"})
            assert result == "The answer is 42."
        finally:
            ol_mod.ROOT = original_root

    def test_timeout_returns_timeout_message(self, monkeypatch):
        import subprocess as _sp

        def _raise_timeout(*a, **kw):
            raise _sp.TimeoutExpired(cmd="mock", timeout=120)

        monkeypatch.setattr("subprocess.run", _raise_timeout)

        import core.engine.orchestration_loop as ol_mod
        fake_script = MagicMock()
        fake_script.exists.return_value = True
        fake_root = MagicMock()
        fake_root.__truediv__ = lambda self, other: fake_script
        original_root = ol_mod.ROOT
        ol_mod.ROOT = fake_root
        try:
            loop = OrchestrationLoop(LoopConfig(project_id="p"))
            result = loop._handle_knowledge_request({"question": "slow question"})
            assert "timeout" in result
        finally:
            ol_mod.ROOT = original_root


# ---------------------------------------------------------------------------
# Target phase stop
# ---------------------------------------------------------------------------

class TestTargetPhase:

    def test_stops_when_target_phase_reached(self, tmp_path):
        """
        Phase boundary is detected when _load_state() returns different phases
        within the same iteration: 'intake' at the top, 'specification' at the bottom.
        """
        cfg = LoopConfig(project_id="p", target_phase="specification",
                         auto=True, max_steps=20)
        loop = OrchestrationLoop(cfg)

        call_count = [0]
        def _load():
            call_count[0] += 1
            # Odd calls (start of iteration): intake; even calls (end of iteration): specification
            phase = "intake" if call_count[0] % 2 == 1 else "specification"
            return _make_state(phase=phase)

        loop._load_state = _load
        loop._dispatch_agent = MagicMock(return_value=MagicMock(
            agent_id="master_orchestrator",
            raw_text=_wire_response(s="task:complete"),
            tokens_used=0,
        ))
        # Prevent actual engine calls from writing to disk
        loop._execute_master_actions = MagicMock(return_value=None)

        result = loop.run()
        assert result.reason == StopReason.TARGET_REACHED
        assert result.last_phase == "specification"


# ---------------------------------------------------------------------------
# Decision quality fields (proj-007)
# ---------------------------------------------------------------------------

class TestDecisionQualityFields:
    """Decision records must carry rationale/alternatives_considered/related_to."""

    def _wire_with_dec(self, dec_list: list) -> str:
        import json
        wire = {"_v": "1.0", "s": "task:complete", "dec": dec_list}
        return f"reasoning\n\n```json\n{json.dumps(wire)}\n```"

    def test_master_decision_includes_rationale(self, tmp_path):
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.audit_logger import AuditLogger

        pid = "proj-loop-dec-001"
        al = AuditLogger(log_path=tmp_path / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=tmp_path, audit_logger=al)
        sm.initialize(request_id="req-dec-001")

        from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
        cfg = LoopConfig(project_id=pid, max_steps=2, auto=True)
        loop = OrchestrationLoop(cfg)

        dec = [{"id": "d-q-001", "v": "use postgres", "rat": "proven reliability",
                "alt": ["sqlite", "mysql"], "rel": "d-prereq-001"}]

        def _load():
            return sm.load()

        loop._load_state = _load

        from core.engine.response_parser import ResponseParser
        parsed = ResponseParser().parse(self._wire_with_dec(dec))

        # Patch _execute_master_actions to call only decision recording
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for d in parsed.decisions:
            if isinstance(d, dict) and d.get("id"):
                sm.append("master_orchestrator", "decisions", "decision_log", {
                    "decision_id":             d.get("id"),
                    "value":                   d.get("v", ""),
                    "rationale":               d.get("rat", ""),
                    "alternatives_considered": d.get("alt", []),
                    "related_to":              d.get("rel", ""),
                    "recorded_at":             now,
                    "source":                  "orchestration_loop",
                })

        state = sm.load()
        log = state["decisions"]["decision_log"]
        assert len(log) == 1
        entry = log[0]
        assert entry["rationale"] == "proven reliability"
        assert entry["alternatives_considered"] == ["sqlite", "mysql"]
        assert entry["related_to"] == "d-prereq-001"

    def test_decision_without_optional_fields_still_recorded(self):
        """Decisions without rat/alt/rel must still be recorded (fields default to empty)."""
        import json
        from core.engine.response_parser import ResponseParser
        wire = {"_v": "1.0", "s": "task:complete", "dec": [{"id": "d-bare", "v": "bare value"}]}
        text = f"reasoning\n\n```json\n{json.dumps(wire)}\n```"
        parsed = ResponseParser().parse(text)
        dec = parsed.decisions[0]
        assert dec.get("rat", "") == ""
        assert dec.get("alt", []) == []
        assert dec.get("rel", "") == ""


# ---------------------------------------------------------------------------
# Phase document writing (proj-007)
# ---------------------------------------------------------------------------

class TestPhaseDocumentWriting:
    """_write_phase_document must create YAML stubs on phase advance."""

    def _make_state_with_spec(self, phase: str) -> dict:
        return {
            "core_identity": {"current_phase": phase, "status": "active"},
            "project_definition": {
                "clarified_specification": "Build a thing",
                "project_goal": "Deliver value",
                "problem_statement": "Current system is slow",
                "success_criteria": ["criterion 1"],
                "acceptance_criteria": ["AC1"],
                "original_brief": "Original brief",
                "scope": {},
                "constraints": [],
                "expected_outputs": [],
            },
            "execution": {"milestones": [], "tasks": [], "execution_plan_path": None},
            "workflow": {"mode": "standard", "handoff_history": [], "completed_phases": []},
        }

    def test_intake_doc_created(self, tmp_path):
        from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        state = self._make_state_with_spec("intake")
        loop._write_phase_document("intake", state, tmp_path)
        dest = tmp_path / "intake" / "clarified_spec.yaml"
        assert dest.exists()
        import yaml
        content = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert content["clarified_specification"] == "Build a thing"

    def test_planning_doc_created(self, tmp_path):
        from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        state = self._make_state_with_spec("planning")
        loop._write_phase_document("planning", state, tmp_path)
        dest = tmp_path / "planning" / "product_plan.yaml"
        assert dest.exists()

    def test_execution_doc_created(self, tmp_path):
        from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        state = self._make_state_with_spec("execution")
        loop._write_phase_document("execution", state, tmp_path)
        dest = tmp_path / "execution" / "execution_plan.yaml"
        assert dest.exists()

    def test_unknown_phase_no_doc(self, tmp_path):
        from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        state = self._make_state_with_spec("review")
        loop._write_phase_document("review", state, tmp_path)
        # No files created for unrecognised phases
        assert not list(tmp_path.rglob("*.yaml"))

    def test_idempotent_does_not_overwrite(self, tmp_path):
        """Existing docs must not be overwritten."""
        from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
        loop = OrchestrationLoop(LoopConfig(project_id="p"))
        state = self._make_state_with_spec("intake")
        dest = tmp_path / "intake" / "clarified_spec.yaml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("original: content\n", encoding="utf-8")
        loop._write_phase_document("intake", state, tmp_path)
        assert dest.read_text(encoding="utf-8") == "original: content\n"


class TestDeprecatedGraphReplay:

    def test_closure_skips_graph_replay(self, monkeypatch):
        loop = OrchestrationLoop(LoopConfig(project_id="p", auto=True))
        state = _make_state(phase="improvement")

        class _SM:
            project_dir = Path(".")

            def snapshot(self, phase):
                return None

            def write(self, *args, **kwargs):
                return None

            def system_append(self, *args, **kwargs):
                return None

            def append(self, *args, **kwargs):
                return None

        monkeypatch.setattr("core.engine.shared_state_manager.SharedStateManager", lambda *_a, **_k: _SM())
        monkeypatch.setattr(loop, "_write_phase_document", lambda *a, **k: None)

        parsed = loop._parse_response(_wire_response(s="task:complete"))
        with patch("builtins.print") as mock_print:
            loop._execute_master_actions(parsed, state)

        printed = "\n".join(" ".join(map(str, call.args)) for call in mock_print.call_args_list)
        assert "graph memory is deprecated" in printed
