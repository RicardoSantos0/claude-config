# Changelog

All notable changes to this repository are documented here.

---

## [2026-04-14] Post-restructuring migration fixes

### Engine Subpackage Migration

Completed migration of all MAS core modules from `mas/core/*.py` to `mas/core/engine/*.py`
after the `95da5c6` folder restructuring commit left several files truncated or incomplete.

**Files restored / completed:**

- `mas/core/engine/training_engine.py` — restored 396 missing lines:
  `get_by_status`, all `_metric_to_*` helpers, `generate_communication_proposals`,
  module-level helpers `_proposal_to_dict` / `_count_by` / `_save_backlog`, and CLI
- `mas/core/engine/consultation_engine.py` — restored 225 missing lines:
  compact wire format class methods (`compact_request/response`, `expand_request/response`)
  and CLI (`create`, `show`, `check-risk` sub-commands)
- `mas/core/engine/metrics_engine.py` — merged two divergent versions:
  added `score_phase_efficiency`, `score_decision_quality` (new implementations),
  plus all agent-level scoring (`score_task_completion_rate`, `score_handoff_quality`,
  `score_boundary_adherence`), communication metrics (`score_token_efficiency`, etc.),
  and aggregate / evaluate / produce_report / save_report methods
- `mas/core/engine/skill_bridge.py` — fixed `ROOT` path depth (was `parent.parent`,
  now `parent.parent.parent`); fixed `check` CLI to output `AUTHORIZED`/`DENIED`
  with correct exit codes
- `mas/core/engine/graph_memory.py` — fixed `ROOT` path depth
- `mas/core/engine/consultation_engine.py` — fixed `DOMAINS_DIR` path depth

**Config / utils fixes:**

- `mas/core/utils/config.py` — added missing functions re-exported by `core.config`:
  `get_model_for_agent`, `get_api_key`, `get_projects_dir`, `get_governance_mode`, `get_defaults`
- `mas/core/wire_protocol.py` — added `__main__` entry-point so `python -m core.wire_protocol` works
- `mas/core/capability_registry.py` — added `__main__` entry-point

**Test fixes (stale patch targets after restructuring):**

- `mas/tests/integration/test_comms_metrics_flow.py` — updated 3 patch targets from
  `core.training_engine.MetricsEngine` → `core.engine.training_engine.MetricsEngine`
- `mas/tests/unit/test_training_engine_comms.py` — updated 1 patch target (same)
- `mas/tests/unit/test_intake_checker.py` — updated 4 monkeypatch targets from
  `core.intake_checker` → `core.engine.intake_checker`

**Agent utilities:**

- `agents/_utilities.md` — updated all CLI paths from `mas/core/*.py` to
  `mas/core/engine/*.py` (canonical location); added Consultation and Graph Memory sections

**Result:** 937 tests pass (0 failures), up from 583 pre-migration.

---

## [2026-04-11] proj-20260411-001-agent-knowledge-and-flow-opt

### Agent Knowledge Retrieval (NotebookLM integration — 8 agents)

Added `## Knowledge Retrieval (NotebookLM)` section to 8 agents:

- `agents/master_orchestrator.md` — direct invocation + broker pattern for read-only consultants
- `agents/evaluator_agent.md` — direct invocation
- `agents/inquirer_agent.md` — direct invocation
- `agents/risk_advisor.md` — KNOWLEDGE_REQUEST broker protocol
- `agents/quality_advisor.md` — KNOWLEDGE_REQUEST broker protocol
- `agents/devils_advocate.md` — KNOWLEDGE_REQUEST broker protocol
- `agents/domain_expert.md` — KNOWLEDGE_REQUEST broker protocol
- `agents/efficiency_advisor.md` — KNOWLEDGE_REQUEST broker protocol

Consultants (tools: [read] only) issue a `KNOWLEDGE_REQUEST` in their output;
master_orchestrator fetches from NotebookLM and re-injects into follow-up consultation.

### NotebookLM Skill Infrastructure

- `skills/notebooklm/notebooks.yaml` — 6-notebook registry (no hardcoded IDs):
  ai-agents, agentic-ai-systems, database-systems, ml-deep-learning,
  performance-management, zotero-notion-python-integration
- `skills/notebooklm/TEMPLATE.md` — canonical invocation template: notebook
  selection by domain, query formation, KNOWLEDGE_REQUEST protocol, additive-only
  insertion rules for agent markdown files

### MAS Core — Tiered Storage and Context Compression

New files in `mas/core/` (no existing files modified):

- `mas/core/log_helpers.py` — JSON-RPC 2.0 structured log format:
  `make_log_entry()`, `append_event()` (SQLite WAL), `query_by_action_id()`,
  `query_events()` with project/agent/action filters
- `mas/core/db_init.py` — idempotent SQLite initialiser: creates
  `mas/data/episodic.db` (WAL mode, 4 indexes) and `mas/data/semantic_stub.json`
- `mas/core/context_compressor.py` — progressive disclosure compression:
  summary (−95.6%), detail (−10.4%), reanchor (−99.1%), full (passthrough);
  benchmark against 15,675-char real project state
- `mas/core/handoff_helpers.py` — re-anchor YAML handoff builder:
  `build_reanchor_payload()` (tried/worked/failed/do_not_retry),
  `extract_delta()`, `summarise_handoff_history()`, `payload_token_estimate()`

### Data

- `mas/data/episodic.db` — SQLite WAL database, schema:
  `agent_events(id, project_id, agent_id, action_type, timestamp, intent, result_shape, payload)`
- `mas/data/semantic_stub.json` — semantic tier interface contract (stub, no vector DB)

### Tests

44 new tests added (full suite: 634, exit 0):

- `mas/tests/unit/test_log_helpers.py` (20 tests)
- `mas/tests/unit/test_context_compressor.py` (14 tests)
- `mas/tests/unit/test_handoff_helpers.py` (10 tests)

### Policy and Governance

- `mas/policies/evaluation_policy.yaml` — added `spawn_opportunity_review` policy
  (triggers on review phase: flag spawn opportunities identified during execution)
- `mas/core/training_engine.py` — added `"deferred"` to `PROPOSAL_STATUSES`

### Project Documentation

- `mas/projects/proj-20260411-001-agent-knowledge-and-flow-opt/docs/librarian_agent_decision.md`
  — no dedicated librarian agent; broker pattern; rationale and alternatives considered
- `mas/projects/proj-20260411-001-agent-knowledge-and-flow-opt/docs/tiered_storage_design.md`
  — tiered memory architecture: working (session YAML) → episodic (SQLite) → semantic (stub)
- `mas/projects/proj-20260411-001-agent-knowledge-and-flow-opt/docs/token_baseline.md`
  — compression benchmarks and project-over-project trending methodology
- `mas/projects/proj-20260411-001-agent-knowledge-and-flow-opt/docs/acceptance_evidence.md`
  — verification evidence for req-001 through req-007

### Bug Fix (from prior Infarmed project evaluation)

- `agents/inquirer_agent.md` — Step 6 now writes both `clarified_specification`
  and `success_criteria` to shared state (prop-8d1b86d2, previously missing)
