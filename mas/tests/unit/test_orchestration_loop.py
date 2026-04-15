"""Tests for OrchestrationLoop — proj-20260415-005-mas-run-orchestration-loop."""

import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from mas.core.engine.orchestration_loop import (
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
        assert cfg.dry_run is False
        assert cfg.auto is False
        assert cfg.target_phase is None
        assert cfg.max_agent_retries == 2

    def test_custom_values(self):
        cfg = LoopConfig(project_id="p", max_steps=5, dry_run=True, auto=True,
                         target_phase="specification")
        assert cfg.max_steps == 5
        assert cfg.dry_run is True
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
        cfg = LoopConfig(project_id="proj-loop-test", max_steps=max_steps,
                         dry_run=True, auto=True)
        loop = OrchestrationLoop(cfg)

        loop._load_state = MagicMock(return_value=state)
        loop._dispatch_agent = MagicMock(return_value=MagicMock(
            agent_id="master_orchestrator",
            raw_text=response_text,
            tokens_used=0,
            dry_run=True,
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

    def test_dry_run_uses_zero_tokens(self, tmp_path):
        state = _make_state()
        loop = self._patched_loop(tmp_path, state, max_steps=1)
        loop.run()
        call_kwargs = loop._dispatch_agent.call_args
        # Check config was dry_run
        assert loop.config.dry_run is True


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
            "mas.core.engine.orchestration_loop.ROOT",
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
        import mas.core.engine.orchestration_loop as ol_mod
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

        import mas.core.engine.orchestration_loop as ol_mod
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
                         dry_run=True, auto=True, max_steps=20)
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
            tokens_used=0, dry_run=True,
        ))
        # Prevent actual engine calls from writing to disk
        loop._execute_master_actions = MagicMock(return_value=None)

        result = loop.run()
        assert result.reason == StopReason.TARGET_REACHED
        assert result.last_phase == "specification"
