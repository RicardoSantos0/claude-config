"""
Orchestration Loop
Autonomous execution engine for the Governed Multi-Agent Delivery System.

Drives a project through its phases by:
  1. Determining which agent runs next (from shared state)
  2. Assembling a context-aware prompt (PromptAssembler)
  3. Calling the agent via AgentRunner
  4. Parsing the wire-protocol response (ResponseParser)
  5. Executing the response: handoffs, phase advances, decisions, artifacts
  6. Handling consultation (ConsultationEngine + per-consultant agent calls)
  7. Handling NotebookLM KNOWLEDGE_REQUESTs (subprocess to ask_question.py)
  8. Pausing at phase boundaries for human confirmation (unless --auto)

Usage:
    from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig
    config = LoopConfig(project_id="proj-20260415-005-...", auto=True)
    result = OrchestrationLoop(config).run()
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent.parent.parent  # repo root (claude-config/)

# ---------------------------------------------------------------------------
# Config / result types
# ---------------------------------------------------------------------------

@dataclass
class LoopConfig:
    project_id: str
    max_steps: int = 50
    auto: bool = False                # skip human checkpoints
    target_phase: str | None = None   # stop after this phase completes
    max_agent_retries: int = 2        # per-agent consecutive error limit


class StopReason(str, Enum):
    MAX_STEPS        = "max_steps"
    UNANIMOUS_RISK   = "unanimous_risk"
    HUMAN_ESCALATION = "human_escalation"
    PROJECT_CLOSED   = "project_closed"
    PHASE_CHECKPOINT = "phase_checkpoint"
    TARGET_REACHED   = "target_reached"
    ERROR            = "error"


@dataclass
class LoopResult:
    stopped_at_step: int
    reason: StopReason
    last_agent: str
    last_phase: str
    message: str = ""


# ---------------------------------------------------------------------------
# Internal exceptions
# ---------------------------------------------------------------------------

class _EscalationRequired(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Phase progression
# ---------------------------------------------------------------------------

from core.engine.shared_state_manager import STANDARD_PHASES  # noqa: E402

_LITE_PHASES = ("intake", "execution", "closed")

def _next_phase(current: str, mode: str = "standard") -> str:
    phases = _LITE_PHASES if mode == "lite" else STANDARD_PHASES
    try:
        idx = phases.index(current)
        return phases[idx + 1] if idx + 1 < len(phases) else "closed"
    except ValueError:
        return "closed"


# ---------------------------------------------------------------------------
# OrchestrationLoop
# ---------------------------------------------------------------------------

class OrchestrationLoop:
    """
    Runs the MAS project lifecycle autonomously.

    Instantiate with a LoopConfig, call .run(). The loop reads and writes
    shared state on every iteration — resume-safe by design.
    """

    def __init__(self, config: LoopConfig) -> None:
        self.config = config
        self._pending_consultation_synthesis: Any = None
        self._pending_grounded_context: str = ""
        self._agent_error_counts: dict[str, int] = {}
        # Lazy-loaded helpers
        self._runner = None
        self._assembler = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> LoopResult:
        """Main loop. Reads state each iteration. Never raises."""
        step = 0
        last_agent = "master_orchestrator"
        last_phase = "intake"

        try:
            while step < self.config.max_steps:
                state = self._load_state()
                last_phase = state.get("core_identity", {}).get("current_phase", last_phase)
                status = state.get("core_identity", {}).get("status", "active")

                if status == "closed":
                    return LoopResult(step, StopReason.PROJECT_CLOSED, last_agent, last_phase,
                                      "Project is already closed.")

                agent_id = self._determine_next_agent(state)
                last_agent = agent_id

                self._print_step(step + 1, agent_id, last_phase)

                # Dispatch agent
                agent_resp = self._dispatch_agent(agent_id, state)
                parsed = self._parse_response(agent_resp.raw_text)

                # Print result summary
                tok_tag = f" tok={agent_resp.tokens_used}" if agent_resp.tokens_used else ""
                status_tag = f" [{parsed.status}]" if parsed.status else ""
                action_tag = f" -> {parsed.next_action}" if parsed.next_action not in ("", "wait") else ""
                agent_tag = f":{parsed.next_agent}" if parsed.next_agent else ""
                print(f"  tokens={agent_resp.tokens_used}"
                      f"{status_tag}{action_tag}{agent_tag}")

                # Log any parse warnings
                for err in parsed.parse_errors:
                    print(f"  [parse_warn] {err}")

                # Handle KNOWLEDGE_REQUEST before acting (so grounded_context is
                # available for the NEXT step's prompt)
                if parsed.knowledge_request:
                    answer = self._handle_knowledge_request(parsed.knowledge_request)
                    self._pending_grounded_context = answer
                    print(f"  [notebooklm] grounded context injected for next step")

                if agent_id != "master_orchestrator" and parsed.next_action == "escalate":
                    raise _EscalationRequired(
                        parsed.reasoning or f"Agent '{agent_id}' requested escalation."
                    )

                # Execute master or sub-agent actions
                if agent_id == "master_orchestrator":
                    stop = self._execute_master_actions(parsed, state)
                    if stop:
                        return stop
                else:
                    # Sub-agent completed — accept handoff and record its output
                    self._accept_pending_handoff(state, agent_id, parsed)
                    self._record_subagent_output(agent_id, parsed)

                # Phase boundary check
                new_state = self._load_state()
                new_phase = new_state.get("core_identity", {}).get("current_phase", last_phase)
                if new_phase != last_phase:
                    print(f"\n  [phase] {last_phase} → {new_phase}")
                    last_phase = new_phase

                    if self.config.target_phase and last_phase == self.config.target_phase:
                        return LoopResult(step + 1, StopReason.TARGET_REACHED,
                                          last_agent, last_phase,
                                          f"Reached target phase '{last_phase}'.")

                    stop = self._human_checkpoint(last_phase, new_state)
                    if stop:
                        return stop

                step += 1

            return LoopResult(step, StopReason.MAX_STEPS, last_agent, last_phase,
                              f"Reached max_steps={self.config.max_steps}")

        except _EscalationRequired as e:
            return LoopResult(step, StopReason.HUMAN_ESCALATION, last_agent, last_phase,
                              e.message)
        except KeyboardInterrupt:
            return LoopResult(step, StopReason.PHASE_CHECKPOINT, last_agent, last_phase,
                              "Interrupted by user.")
        except Exception as e:
            return LoopResult(step, StopReason.ERROR, last_agent, last_phase, str(e))

    # ------------------------------------------------------------------
    # Agent dispatch
    # ------------------------------------------------------------------

    def _dispatch_agent(self, agent_id: str, state: dict) -> "_AgentResponse":
        from core.engine.agent_runner import AgentRunner
        from core.engine.prompt_assembler import PromptAssembler
        from core.utils.config import get_model_for_agent

        if self._assembler is None:
            self._assembler = PromptAssembler(agents_dir=ROOT / "agents")

        phase = state.get("core_identity", {}).get("current_phase", "intake")
        extra_ctx = self._build_extra_context()

        # Inject pending handoff task description for sub-agents
        if agent_id != "master_orchestrator":
            task_ctx = self._pending_handoff_context(agent_id, state)
            if task_ctx:
                if extra_ctx is None:
                    extra_ctx = {}
                extra_ctx["pending_task"] = task_ctx

        prompt = self._assembler.assemble(agent_id, state,
                                          extra_context=extra_ctx)

        model = get_model_for_agent(agent_id)
        runner = AgentRunner(model=model)

        from core.utils.config import load_config
        max_tokens = load_config().get("llm", {}).get("max_tokens", 4096)

        result = runner.run(
            agent_id=agent_id,
            prompt=prompt,
            project_id=self.config.project_id,
            max_tokens=max_tokens,
        )

        text = result.get("text", "")
        tokens = result.get("tokens_used", 0)

        if result.get("error"):
            if not result.get("retryable", True):
                raise Exception(f"Non-retryable error from '{agent_id}': {result['error']}")
            self._agent_error_counts[agent_id] = self._agent_error_counts.get(agent_id, 0) + 1
            if self._agent_error_counts[agent_id] > self.config.max_agent_retries:
                raise Exception(f"Agent '{agent_id}' failed {self.config.max_agent_retries+1} "
                                f"times: {result['error']}")
            print(f"  [agent_error] {agent_id}: {result['error']} "
                  f"(retry {self._agent_error_counts[agent_id]}/{self.config.max_agent_retries})")
            text = ""
        else:
            self._agent_error_counts.pop(agent_id, None)

        return _AgentResponse(agent_id=agent_id, raw_text=text, tokens_used=tokens)

    def _determine_next_agent(self, state: dict) -> str:
        """
        Returns which agent should run next.
        Pending handoff → that agent. Accepted / no handoffs → master_orchestrator.
        """
        history = state.get("workflow", {}).get("handoff_history", [])
        if not history:
            return "master_orchestrator"

        last = history[-1]
        # Expand compact format if needed
        try:
            from core.engine.handoff_engine import HandoffEngine
            last = HandoffEngine.expand(last)
        except Exception:
            pass

        acc_status = last.get("acceptance", {}).get("status", "pending")
        if acc_status == "pending":
            return last.get("to_agent", "master_orchestrator")
        return "master_orchestrator"

    def _pending_handoff_context(self, agent_id: str, state: dict) -> str:
        """Return the task_description from the pending handoff for this agent."""
        history = state.get("workflow", {}).get("handoff_history", [])
        for ho in reversed(history):
            try:
                from core.engine.handoff_engine import HandoffEngine
                expanded = HandoffEngine.expand(ho)
            except Exception:
                expanded = ho
            if (expanded.get("to_agent") == agent_id and
                    expanded.get("acceptance", {}).get("status") == "pending"):
                task = expanded.get("task_description", "")
                payload_summary = expanded.get("payload", {}).get("summary", "")
                parts = [p for p in (task, payload_summary) if p]
                return "\n".join(parts)
        return ""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw_text: str) -> "ParsedResponse":
        from core.engine.response_parser import ResponseParser
        return ResponseParser().parse(raw_text)

    # ------------------------------------------------------------------
    # Master action execution
    # ------------------------------------------------------------------

    def _execute_master_actions(self, parsed: "ParsedResponse",
                                state: dict) -> LoopResult | None:
        """
        Translates master_orchestrator wire response into concrete engine calls.
        Returns a LoopResult to stop the loop, or None to continue.
        """
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.handoff_engine import HandoffEngine

        sm = SharedStateManager(self.config.project_id)
        he = HandoffEngine()
        phase = state.get("core_identity", {}).get("current_phase", "intake")
        now = datetime.now(timezone.utc).isoformat()

        # 1. Record decisions
        for dec in parsed.decisions:
            if isinstance(dec, dict) and dec.get("id"):
                sm.append("master_orchestrator", "decisions", "decision_log", {
                    "decision_id":             dec.get("id"),
                    "value":                   dec.get("v", ""),
                    "rationale":               dec.get("rat", ""),
                    "alternatives_considered": dec.get("alt", []),
                    "related_to":              dec.get("rel", ""),
                    "recorded_at":             now,
                    "source":                  "orchestration_loop",
                })

        # 2. Record artifacts
        for art in parsed.artifacts:
            sm.append("master_orchestrator", "artifacts", "documents", art)

        # 3. Consultation trigger
        if parsed.consultation_trigger and not self._pending_consultation_synthesis:
            synthesis = self._run_consultation(parsed.consultation_trigger, state)
            if synthesis and getattr(synthesis, "unanimous_high_risk", False):
                return LoopResult(0, StopReason.UNANIMOUS_RISK,
                                  "master_orchestrator", phase,
                                  "Unanimous high risk — human review required.")
            if synthesis and getattr(synthesis, "human_escalation_required", False):
                raise _EscalationRequired("Human escalation required by consultation panel.")
            self._pending_consultation_synthesis = synthesis

        # 4. Escalation
        if parsed.next_action == "escalate":
            raise _EscalationRequired(parsed.reasoning or "Agent requested escalation.")

        # 5. Phase advance
        if parsed.next_action == "advance_phase":
            new_phase = _next_phase(phase, state.get("workflow", {}).get("mode", "standard"))
            sm.snapshot(phase)                         # checkpoint before leaving phase
            sm.write("master_orchestrator", "core_identity", "current_phase", new_phase)
            sm.system_append("workflow", "completed_phases", phase)
            self._write_phase_document(phase, state, sm.project_dir)
            print(f"  [snapshot] {phase} saved")

            # Trigger EpisodeWriter replay when closing project
            if new_phase == "closed":
                print("  [graph] skipped: graph memory is deprecated; prefer SQL-backed retrieval")

        # 6. Delegate to next agent
        if parsed.next_action == "delegate" and parsed.next_agent:
            payload = self._build_handoff_payload(parsed)
            he.create(sm,
                      from_agent="master_orchestrator",
                      to_agent=parsed.next_agent,
                      phase=phase,
                      task_description=parsed.reasoning or f"Execute {phase} tasks",
                      payload=payload)
            print(f"  [handoff] master_orchestrator → {parsed.next_agent}")

        return None

    def _accept_pending_handoff(self, state: dict, agent_id: str,
                                parsed: "ParsedResponse") -> None:
        """Accept the pending handoff the sub-agent was working on."""
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.handoff_engine import HandoffEngine

        sm = SharedStateManager(self.config.project_id)
        he = HandoffEngine()
        history = state.get("workflow", {}).get("handoff_history", [])

        for ho in reversed(history):
            try:
                expanded = HandoffEngine.expand(ho)
            except Exception:
                expanded = ho
            if (expanded.get("to_agent") == agent_id and
                    expanded.get("acceptance", {}).get("status") == "pending"):
                he.accept(sm, expanded["handoff_id"])
                print(f"  [accept] {expanded['handoff_id']}")
                break

    def _record_subagent_output(self, agent_id: str,
                                parsed: "ParsedResponse") -> None:
        """Write sub-agent dec/art from wire response into shared state."""
        from core.engine.shared_state_manager import SharedStateManager

        sm = SharedStateManager(self.config.project_id)
        now = datetime.now(timezone.utc).isoformat()

        for dec in parsed.decisions:
            if isinstance(dec, dict) and dec.get("id"):
                try:
                    sm.append("scribe_agent", "decisions", "decision_log", {
                        "decision_id":             dec.get("id"),
                        "decided_by":              agent_id,
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
                sm.append("scribe_agent", "artifacts", "change_log", {
                    "change_id": f"chg-{agent_id}-{now[:10]}",
                    "phase": "execution",
                    "description": art,
                    "author": agent_id,
                })
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------

    def _run_consultation(self, trigger: dict,
                          state: dict) -> Any:
        """Run full consultation round. Returns ConsultationSynthesis or None."""
        from core.engine.consultation_engine import ConsultationEngine
        from core.engine.agent_runner import AgentRunner
        from core.engine.prompt_assembler import PromptAssembler
        from core.engine.shared_state_manager import SharedStateManager
        from core.utils.config import get_model_for_agent

        sm = SharedStateManager(self.config.project_id)
        engine = ConsultationEngine()
        assembler = PromptAssembler(agents_dir=ROOT / "agents")

        try:
            request = engine.create_request(
                project_id=self.config.project_id,
                question=trigger.get("question", ""),
                context=trigger.get("context", {}),
                decision_type=trigger.get("decision_type", "governance"),
            )
        except Exception as e:
            print(f"  [consult_error] create_request failed: {e}")
            return None

        print(f"  [consult] decision_type={trigger.get('decision_type')} "
              f"consultants={request.consultants_selected}")

        for consultant_id in request.consultants_selected:
            extra = {
                "injected_consultation_question": request.question,
                "injected_consultation_context": yaml.dump(
                    trigger.get("context", {}), default_flow_style=False),
            }
            prompt = assembler.assemble(consultant_id, state, extra_context=extra)
            model = get_model_for_agent(consultant_id)
            runner = AgentRunner(model=model)
            result = runner.run(consultant_id, prompt,
                                project_id=self.config.project_id)

            c_text = result.get("text", "")
            c_parsed = self._parse_consultant_response(c_text)

            # Handle consultant KNOWLEDGE_REQUEST (broker pattern)
            if c_parsed.get("knowledge_request"):
                answer = self._handle_knowledge_request(c_parsed["knowledge_request"])
                c_parsed["key_concerns"] = (
                    c_parsed.get("key_concerns", []) + [f"[grounded] {answer[:200]}"]
                )

            try:
                engine.record_response(
                    request,
                    consultant_id=consultant_id,
                    response_text=c_text,
                    risk_level=c_parsed.get("risk_level", "low"),
                    key_concerns=c_parsed.get("key_concerns", []),
                    recommendation=c_parsed.get("recommendation", "proceed"),
                    reasoning=c_parsed.get("reasoning", ""),
                )
            except Exception as e:
                print(f"  [consult_warn] record_response for {consultant_id}: {e}")

        # Check unanimous risk
        try:
            if engine.check_unanimous_risk(request):
                synthesis = engine.synthesize(
                    request, "escalated", "Unanimous high risk from panel", "")
                synthesis.unanimous_high_risk = True
                return synthesis
        except Exception:
            pass

        # Synthesize
        try:
            synthesis = engine.synthesize(
                request,
                decision_reached=trigger.get("decision_reached", "proceed with caution"),
                rationale=trigger.get("rationale", "Consultant panel reviewed."),
                risks_addressed="synthesized from panel responses",
            )
        except Exception as e:
            print(f"  [consult_warn] synthesize failed: {e}")
            return None

        # Save to shared state
        try:
            sm.append("master_orchestrator", "consultation", "synthesis",
                      dataclasses.asdict(synthesis) if dataclasses.is_dataclass(synthesis)
                      else dict(synthesis))
        except Exception:
            pass

        return synthesis

    def _parse_consultant_response(self, text: str) -> dict:
        """
        Light parser for consultant responses.
        Extracts risk_level, key_concerns, recommendation, reasoning.
        """
        result: dict[str, Any] = {
            "risk_level": "low",
            "key_concerns": [],
            "recommendation": "proceed",
            "reasoning": "",
            "knowledge_request": None,
        }
        if not text:
            return result

        # Try wire block first
        from core.engine.response_parser import ResponseParser
        parsed = ResponseParser().parse(text)
        if parsed.raw_wire:
            w = parsed.raw_wire
            result["risk_level"] = w.get("risk_level", w.get("rl", "low"))
            result["key_concerns"] = w.get("key_concerns", w.get("kc", []))
            result["recommendation"] = w.get("recommendation", w.get("rec", "proceed"))
            result["reasoning"] = parsed.reasoning
            result["knowledge_request"] = parsed.knowledge_request
            return result

        # Heuristic: scan for risk keywords
        lower = text.lower()
        if any(w in lower for w in ("critical", "high risk", "severe", "dangerous")):
            result["risk_level"] = "high"
        elif any(w in lower for w in ("medium risk", "moderate", "concern")):
            result["risk_level"] = "medium"

        result["reasoning"] = text[:500]
        result["knowledge_request"] = parsed.knowledge_request
        return result

    # ------------------------------------------------------------------
    # NotebookLM
    # ------------------------------------------------------------------

    def _handle_knowledge_request(self, kr_block: dict) -> str:
        """Call skills/notebooklm/scripts/ask_question.py and return answer."""
        question = kr_block.get("question", "")
        if not question:
            return ""

        script = ROOT / "skills" / "notebooklm" / "scripts" / "ask_question.py"
        if not script.exists():
            return f"[notebooklm_unavailable] script not found at {script}"

        cmd = [sys.executable, str(script), "--question", question]
        notebook_id = kr_block.get("notebook_id", "")
        if notebook_id:
            cmd += ["--notebook-id", notebook_id]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT / "skills" / "notebooklm"),
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return f"[notebooklm_error] exit={result.returncode}: {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            return "[notebooklm_timeout] query exceeded 120s"
        except Exception as e:
            return f"[notebooklm_exception] {e}"

    # ------------------------------------------------------------------
    # Human checkpoint
    # ------------------------------------------------------------------

    def _human_checkpoint(self, phase: str, state: dict) -> LoopResult | None:
        """
        Print phase summary and optionally wait for human confirmation.
        Returns a LoopResult to stop, or None to continue.
        """
        ci = state.get("core_identity", {})
        wf = state.get("workflow", {})
        completed = wf.get("completed_phases", [])
        handoffs = wf.get("handoff_history", [])
        pending = [h for h in handoffs
                   if h.get("acceptance", {}).get("status") == "pending" or
                      h.get("status") == "pending"]
        violations = state.get("_meta", {}).get("governance_violations", [])

        print(f"\n{'─'*60}")
        print(f"  PHASE CHECKPOINT: {ci.get('current_phase','?').upper()}")
        print(f"  Completed : {', '.join(completed) or 'none'}")
        print(f"  Handoffs  : {len(handoffs)} total, {len(pending)} pending")
        print(f"  Violations: {len(violations)}")
        if pending:
            for h in pending[-2:]:
                print(f"    ↳ pending: {h.get('handoff_id','?')} "
                      f"({h.get('from_agent','?')} → {h.get('to_agent','?')})")
        print(f"{'─'*60}")

        if self.config.auto:
            print("  [auto] continuing without confirmation")
            return None

        try:
            resp = input("  [enter] continue  [q+enter] quit: ").strip().lower()
            if resp in ("q", "quit", "exit"):
                return LoopResult(0, StopReason.PHASE_CHECKPOINT,
                                  "master_orchestrator", phase,
                                  "Stopped at human checkpoint.")
        except (EOFError, KeyboardInterrupt):
            return LoopResult(0, StopReason.PHASE_CHECKPOINT,
                              "master_orchestrator", phase,
                              "Stopped at human checkpoint.")
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write_phase_document(self, phase: str, state: dict,
                              project_dir: Path) -> None:
        """
        Write a minimal phase document to the project directory when leaving
        a phase.  Files are only created if they don't already exist (idempotent).
        Documents are derived from shared state so metrics_engine can score them.
        """
        pd = state.get("project_definition", {})
        ex = state.get("execution", {})

        phase_files: dict[str, tuple[Path, dict]] = {
            "intake": (
                project_dir / "intake" / "clarified_spec.yaml",
                {
                    "phase": "intake",
                    "clarified_specification": pd.get("clarified_specification", ""),
                    "project_goal":            pd.get("project_goal", ""),
                    "problem_statement":       pd.get("problem_statement", ""),
                    "success_criteria":        pd.get("success_criteria", []),
                    "acceptance_criteria":     pd.get("acceptance_criteria", []),
                    "original_brief":          pd.get("original_brief", ""),
                },
            ),
            "planning": (
                project_dir / "planning" / "product_plan.yaml",
                {
                    "phase": "planning",
                    "project_goal":       pd.get("project_goal", ""),
                    "scope":              pd.get("scope", {}),
                    "constraints":        pd.get("constraints", []),
                    "success_criteria":   pd.get("success_criteria", []),
                    "acceptance_criteria":pd.get("acceptance_criteria", []),
                    "expected_outputs":   pd.get("expected_outputs", []),
                },
            ),
            "execution": (
                project_dir / "execution" / "execution_plan.yaml",
                {
                    "phase":      "execution",
                    "milestones": ex.get("milestones", []),
                    "tasks":      ex.get("tasks", []),
                    "plan_path":  ex.get("execution_plan_path", ""),
                },
            ),
        }

        if phase not in phase_files:
            return

        dest_path, content = phase_files[phase]
        if dest_path.exists():
            return  # idempotent — don't overwrite existing docs

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("w", encoding="utf-8") as f:
                yaml.dump(content, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            print(f"  [doc] {dest_path.relative_to(project_dir)} written")
        except Exception as e:
            print(f"  [doc_warn] could not write {phase} doc: {e}")

    def _load_state(self) -> dict:
        from core.engine.shared_state_manager import SharedStateManager
        return SharedStateManager(self.config.project_id).load()

    def _build_extra_context(self) -> dict | None:
        ctx: dict[str, str] = {}
        if self._pending_consultation_synthesis:
            try:
                raw = (dataclasses.asdict(self._pending_consultation_synthesis)
                       if dataclasses.is_dataclass(self._pending_consultation_synthesis)
                       else dict(self._pending_consultation_synthesis))
                ctx["injected_consultation_synthesis"] = yaml.dump(raw, default_flow_style=False)
            except Exception:
                pass
            self._pending_consultation_synthesis = None
        if self._pending_grounded_context:
            ctx["injected_grounded_context"] = self._pending_grounded_context
            self._pending_grounded_context = ""
        return ctx or None

    def _build_handoff_payload(self, parsed: "ParsedResponse") -> dict:
        return {
            "_v": "1.0",
            "s": "task:delegated",
            "summary": parsed.reasoning[:300] if parsed.reasoning else "",
            "artifacts_produced": parsed.artifacts,
            "decisions_made": [d.get("v", "") for d in parsed.decisions if isinstance(d, dict)],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
        }

    def _print_step(self, step: int, agent_id: str, phase: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[step {step:>3}] {ts}  {agent_id:<30} phase={phase}")


# ---------------------------------------------------------------------------
# Internal response container
# ---------------------------------------------------------------------------

@dataclass
class _AgentResponse:
    agent_id: str
    raw_text: str
    tokens_used: int


# Re-export ParsedResponse for callers
from core.engine.response_parser import ParsedResponse  # noqa: F401, E402
