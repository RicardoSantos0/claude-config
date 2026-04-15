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

### Remove compatibility wrappers

Removed the thin compatibility wrapper modules from `mas/core/` after migrating callers to `mas/core/engine/*`.
Backups were created in `mas/core/wrappers_backup/` and removed after the full test suite passed.

Removed files:
- `mas/core/access_control.py`
- `mas/core/audit_logger.py`
- `mas/core/capability_registry.py`
- `mas/core/checkpoint_writer.py`
- `mas/core/consultation_engine.py`
- `mas/core/context_compressor.py`
- `mas/core/graph_memory.py`
- `mas/core/handoff_helpers.py`
- `mas/core/intake_checker.py`
- `mas/core/log_helpers.py`
- `mas/core/message_bus.py`
- `mas/core/metrics_engine.py`
- `mas/core/prompt_assembler.py`
- `mas/core/shared_state_manager.py`
- `mas/core/skill_bridge.py`
- `mas/core/spawn_policy.py`
- `mas/core/task_board.py`
- `mas/core/training_engine.py`

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

---

## [2026-04-14] proj-20260414-001-true-mas-integration

Post-audit action: transformed the MAS from a governance scaffold into a real multi-agent
system with live LLM calls, wired infrastructure, and a lite operating mode.

### Real LLM Agent Calls

- `mas/core/engine/agent_runner.py` — Anthropic SDK wrapper: gated on `ANTHROPIC_API_KEY`,
  dry-run when absent. Default model `claude-haiku-4-5-20251001`. Logs `agent_call` events
  to SQLite on every invocation.

### SQLite as Primary Event Store

- `mas/core/db.py` — central access layer: `append_event`, `query_events`,
  `query_project_history`, `query_agent_context`, `format_events_for_prompt`
- `mas/core/engine/handoff_engine.py` — every `create`/`accept`/`reject` writes a row
  to `agent_events`; `skill_bridge.SkillBridge().audit_handoff()` called on every create
- `mas/core/engine/prompt_assembler.py` — `_sqlite_context()` injects last 5 events
  into every agent prompt as `injected_recent_events`

### Lite Mode

- `mas/core/cli.py` — `mas init --mode=lite <slug>` creates a 3-phase project
  (`intake → execution → closed`); `[lite]` shown in `mas status`
- `mas/core/engine/spawn_policy.py` — `LITE_MODE_NO_SPAWN` violation blocks spawning
  in lite projects; `shared_state.yaml` gets `workflow.mode: lite`

### Tests

37 new tests (full suite: 976, exit 0):

- `mas/tests/unit/test_db.py`
- `mas/tests/unit/test_agent_runner.py`
- `mas/tests/unit/test_lite_mode.py`
- `mas/tests/integration/test_sqlite_handoff_logging.py`
- `mas/tests/governance/test_unanimous_risk.py`

### Dev Environment

- `mas/CLAUDE.md` — documented venv activation (`C:\..\.venv\Scripts\activate`);
  added `mas init --mode=lite` to quick reference; documented `pytest` bare commands

### Trainer Proposals (backlog — not applied)

- `prop-true-mas-001`: Fix field ownership in `access_control.py` — `inquirer_agent`
  and `master_orchestrator` produce violations on fields they legitimately write
- `prop-true-mas-002`: Wire `token_usage` from live Anthropic responses back into
  `communication.tokens_by_agent`

---

## [2026-04-15] proj-20260415-001-db-semantic-and-acl-fix

Eliminated 28 recurring governance violations per project; replaced `semantic_stub.json`
with live FTS5-backed semantic search; added token tracking.

### Access Control Fix (recurring violation root cause)

Updated `mas/core/engine/access_control.py` — four violation patterns eliminated:

| Field | Before | After |
|---|---|---|
| `artifacts.deliverables` / `documents` / `change_log` | `scribe_agent` only | + `master_orchestrator` |
| `decisions.decision_log` | `scribe_agent` only | + `master_orchestrator` |
| `workflow.completed_phases` | `master_orchestrator` only | + `system` sentinel |
| `project_definition.project_goal` / `problem_statement` / `scope` / `constraints` / `success_criteria` / `acceptance_criteria` | `product_manager_agent` only | + `inquirer_agent` |

Result: 0 violations in `proj-20260415-001-db-semantic-and-acl-fix` (was 28).

### FTS5 Semantic Search (replaces semantic_stub.json)

- `mas/core/utils/log_helpers.py` — `init_db()` now creates `agent_events_fts` FTS5
  virtual table and `AFTER INSERT` trigger; existing 619 rows backfilled
- `mas/core/db.py` — added `semantic_search(query, project_id, limit)` (BM25-ranked FTS5)
  and `query_token_usage(project_id)` (sums `agent_call` token rows)
- `mas/core/engine/prompt_assembler.py` — `_sqlite_context()` now runs
  `semantic_search(phase, project_id)` first; falls back to `query_project_history`
  when < 2 semantic hits. Phase context passed from `assemble()`.
- `mas/data/semantic_stub.json` — updated to `"backend": "sqlite_fts5"` (no longer a stub)

### Token Tracking

- `mas/core/engine/agent_runner.py` — `_log_event()` now records `tokens_prompt`,
  `tokens_completion`, `tokens_total` in the JSON-RPC payload (was a flat `tokens` key);
  dry-run calls also log a zero-token row for observability

### Tests

37 new tests (full suite: 1013, exit 0):

- `mas/tests/unit/test_access_control_fix.py` (20 tests)
- `mas/tests/unit/test_semantic_search.py` (11 tests)
- `mas/tests/unit/test_token_tracking.py` (6 tests)
- Updated `mas/tests/unit/test_agent_runner.py` — `test_dry_run_does_not_log_to_db`
  replaced with `test_dry_run_logs_zero_token_row` to match new behavior

### Trainer Proposals (backlog — not applied)

- `prop-acl-001`: Add `mas db rebuild-fts` CLI command to backfill FTS5 index for
  large existing databases without writing Python directly
- `prop-acl-002`: Track real-vs-dry-run call ratio in `communication` shared state
  (wire compliance analogue for agent_runner calls)
