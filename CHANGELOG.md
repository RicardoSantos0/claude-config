# Changelog

All notable changes to this repository are documented here.

---

## [2026-04-19] SQL-first migration, autonomous resume flow, live-only execution

### Changes

**Live-only runtime (dry-run removed):**
- **`mas/core/engine/agent_runner.py`** now enforces live execution; dry-run calls return a non-retryable error instead of simulated output.
- **`mas/core/cli.py`** removed `mas run --dry-run`; `mas run` now fails fast if `ANTHROPIC_API_KEY` is not available.
- **`mas/core/cli.py`** removed `mas db migrate-graph --dry-run`; graph migration now always executes as an idempotent write.
- **`mas/core/engine/orchestration_loop.py`** no longer dispatches dry-run calls and now treats non-retryable execution failures as immediate stops.

**SQL + PostgreSQL/ChromaDB transition path:**
- Added **`mas/core/runtime_config.py`** for backend/control-plane selection.
- Added adapters:
  - **`mas/core/adapters/postgres_store.py`**
  - **`mas/core/adapters/sqlite_shared_state.py`**
  - **`mas/core/adapters/__init__.py`**
- **`mas/core/utils/log_helpers.py`** and **`mas/core/db.py`** now route event/query operations by configured backend and expose shared-state SQL helpers.
- New CLI command: **`mas db migrate-postgres`** in **`mas/core/cli.py`** for SQLite→PostgreSQL migration.
- **`mas/core/engine/shared_state_manager.py`** now upserts shared state into SQL while preserving YAML project files.

**Graph memory deprecation + policy alignment:**
- **`mas/data/semantic_stub.json`** removed.
- **`mas/core/engine/graph_memory.py`** now uses SQLite graph tables only (YAML graph persistence/fallback removed).
- **`mas/core/engine/prompt_assembler.py`** now prefers ChromaDB context (when enabled), then SQL graph context.
- **`mas/core/engine/metrics_engine.py`** marks `global_graph_contribution` as `not_applicable` (deprecated metric).
- **`mas/policies/evaluation_policy.yaml`** and **`mas/policies/governance_policy.yaml`** updated to deprecate graph-contribution closure gating.

**Autonomous resume flow (local MAS):**
- **`mas/core/engine/checkpoint_writer.py`** and **`mas/foundation/checkpoint_format.md`** now point resume instructions to local `/resume-mas` + `mas status` / `mas pending` verification.
- Added config surface in **`mas/system_config.yaml`** + **`.env.example`** for:
  - database provider/target/postgres URL
  - vector provider/enabled/persist path
- **`pyproject.toml`** adds optional dependency groups:
  - `postgres` (`psycopg[binary]`)
  - `vector` (`chromadb`)

**Cleanup + test realignment:**
- Deleted **`mas/tests/unit/test_dry_live_accounting.py`**.
- Added **`mas/tests/unit/test_runtime_config.py`**.
- Added **`mas/tests/conftest.py`** to quarantine deprecated graph-memory test modules.
- Updated unit tests across runner/loop/metrics/token/checkpoint paths to align with live-only + SQL-first behavior.
- **`mas/core/engine/audit_logger.py`** now rotates oversized `audit.log` to `audit.log.bak`.

---

## [2026-04-16] proj-007 trainer proposals — Decision quality, phase docs, graph closure, ACL

### Changes (implementing proj-007 evaluation proposals)

**`mas/core/engine/access_control.py`** — `master_orchestrator` added as co-owner for all `project_definition` fields (`original_brief`, `brief_summary`, `clarified_specification`, `project_goal`, `problem_statement`, `scope`, `constraints`, `success_criteria`, `acceptance_criteria`, `expected_outputs`). Eliminates governance violations in offline/dry-run projects and makes `goal_achievement` / `acceptance_criteria_pass_rate` scoreable when master sets these fields.

**`mas/core/engine/orchestration_loop.py`**:
- Decision records now include `rationale` (`rat`), `alternatives_considered` (`alt`), `related_to` (`rel`) from wire `dec` objects — raises `decision_quality` from 51 → up to 100 when agents populate these fields
- New `_write_phase_document(phase, state, project_dir)`: writes minimal YAML stubs (`intake/clarified_spec.yaml`, `planning/product_plan.yaml`, `execution/execution_plan.yaml`) on phase advance — makes `documentation_completeness` scoreable
- On transition to `"closed"`: calls `EpisodeWriter.replay_from_state()` automatically — fixes `global_graph_contribution` scoring

**`mas/core/engine/graph_memory.py`** — `EpisodeWriter.replay_from_state()` now handles both string and dict entries in `artifacts.documents` (previous: `AttributeError` on plain path strings)

**`mas/core/cli.py`** — New `mas close <project-id>` command: closes a project, snapshots state, and replays all episodes into the graph

**`agents/master_orchestrator.md`** — Wire protocol section now documents `rat`, `alt`, `rel` fields in `dec` objects with scoring context

### Tests

- `test_access_control_fix.py`: 13 new tests for `master_orchestrator` on all `project_definition` fields
- `test_orchestration_loop.py`: 7 new tests — decision rationale fields, `_write_phase_document` (intake/planning/execution/unknown/idempotent)
- `test_mas_run_loop.py`: 2 new integration tests — phase doc on advance, decision rationale in state

**Suite: 1039 tests passing.**

---

## [2026-04-16] proj-20260415-007-mas-run-fixes-db-consolidation — Loop Fixes + DB Consolidation

### Bug Fixes

**`mas/core/engine/orchestration_loop.py`**:
- Phase snapshot now called (`sm.snapshot(phase)`) before every `advance_phase` action — closes the gap where a phase could be abandoned without a checkpoint
- New `_record_subagent_output(agent_id, parsed)`: after accepting a sub-agent handoff, saves the agent's `dec`/`art` fields to shared state (previously discarded)
- New `_pending_handoff_context(agent_id, state)`: injects the pending handoff `task_description` into sub-agent prompts via `extra_ctx["pending_task"]`
- Richer step output: `[status] -> next_action:agent` replacing bare `tokens=0 dry=True`

**`mas/core/engine/graph_memory.py`** — DB consolidation (stops dual YAML+SQLite maintenance):
- `GraphStore.save()` now upserts to SQLite (primary) and writes YAML as a compatibility copy
- `GraphStore._load()` reads SQLite first, falls back to YAML for legacy projects
- New `_save_to_sqlite(data)` and `_load_from_sqlite()` private methods

**`mas/core/cli.py`** — Updated `migrate-graph` docstring: migration is now a one-time bootstrap; GraphStore writes SQLite on every save going forward

### Tests

**`mas/tests/integration/test_mas_run_loop.py`** (new, 9 tests):
- Full loop lifecycle against a real tmp_path project directory with mocked `_dispatch_agent`
- Covers: phase advance → state write, snapshot creation, target phase stop, decisions/artifacts to state, delegate → handoff creation, `project_closed` early halt, `max_steps` enforcement, escalation stop

**`mas/tests/prompts/test_prompt_assembler.py`** — two tests updated:
- `test_graph_context_injected_when_dense`: accepts either SQLite or YAML context header (SQLite now has real data from project runs)
- `test_graph_context_never_raises`: patches both `db.query_graph_node`/`query_graph_edges` and `GraphMemory.query` to raise; asserts `isinstance(result, str)` (contract: never raises)

**Suite: 1017 tests passing.**

---

## [2026-04-15] proj-20260415-005-mas-run-orchestration-loop — Autonomous Orchestration Loop

### New Modules

**`mas/core/engine/response_parser.py`** — Wire protocol parser:
- Extracts last JSON fence from raw LLM text as the authoritative wire block
- Maps `s` (status) to `next_action`: `task:complete` → `advance_phase`, `escalate` → `escalate`, etc.
- Extracts `dec`, `art`, `rsn`, `consultation_trigger`, `KNOWLEDGE_REQUEST` blocks
- Accumulates parse errors (no_wire_block_found, parse_error, rsn_exceeds_100_words)

**`mas/core/engine/orchestration_loop.py`** — Autonomous loop engine:
- `LoopConfig`: `project_id`, `max_steps=50`, `dry_run`, `auto`, `target_phase`, `max_agent_retries`
- `StopReason` enum: MAX_STEPS, UNANIMOUS_RISK, HUMAN_ESCALATION, PROJECT_CLOSED, PHASE_CHECKPOINT, TARGET_REACHED, ERROR
- `_determine_next_agent(state)`: reads last handoff; pending → `to_agent`; accepted → `master_orchestrator`
- `_run_consultation(trigger, state)`: delegates to ConsultationEngine, dispatches consultant panel
- `_handle_knowledge_request(kr_block)`: calls `skills/notebooklm/scripts/ask_question.py` via subprocess
- `_human_checkpoint(phase, state)`: pauses at phase boundaries (bypassed with `--auto`)
- `_build_extra_context()`: injects consultation synthesis + grounded NotebookLM answers

### CLI Extension

**`mas/core/cli.py`** — Added `mas run` command:
```
mas run <project-id> [--dry-run] [--auto] [--max-steps N] [--target-phase PHASE]
```

### Agent Documentation

**`agents/master_orchestrator.md`** — Documented wire protocol extension keys:
- `next_action`, `next_agent`, `consultation_trigger` in JSON wire block
- `KNOWLEDGE_REQUEST` pattern for grounded knowledge queries

### Tests

- `mas/tests/unit/test_response_parser.py`: 24 tests covering wire extraction, status mapping, dec/art, KNOWLEDGE_REQUEST, rsn word limit
- `mas/tests/unit/test_orchestration_loop.py`: 24 tests covering LoopConfig, phase progression, agent determination, loop control, human checkpoints, NotebookLM handler, target phase stop

**Suite: 1008 tests passing.**

### Bug Fixes

- `orchestration_loop.py`: Removed invalid `phase=` kwarg from `PromptAssembler.assemble()` call
- `orchestration_loop.py`: Fixed `agents_dir` to resolve to repo-root `agents/` (not `mas/agents/`)

---

## [2026-04-15] Trainer proposal implementation (6 proposals applied)

### Applied training proposals from proj-20260414 and proj-20260415-004

**prop-8d1b86d2 (P2, approved) — `product_manager_agent.md` writes success/acceptance criteria:**
- `agents/product_manager_agent.md`: Added explicit Step 5 with CLI commands to write
  `project_definition.success_criteria` and `project_definition.acceptance_criteria` to shared
  state after producing the product plan. Explains that these fields drive the `goal_achievement`
  and `acceptance_criteria_pass_rate` evaluation metrics.

**prop-0515a6a5 + prop-f3b3a7e9 (P3/P2, approved) — `global_graph_contribution` policy:**
- `mas/policies/evaluation_policy.yaml`: Added `graph_contribution` section documenting that
  `EpisodeWriter.replay_from_state()` + `mas db migrate-graph` are required at project closure.
  Added `dry_run_metrics` section listing which metrics become `not_applicable` in dry-run mode
  and how detection works.

**prop-85472733 (P4) — `goal_achievement` 0.0 on dry-run projects:**
- `mas/core/engine/metrics_engine.py`: Extended `_dry_run_defaults` logic — `goal_achievement`
  now becomes `not_applicable` when score ≤ 50.0 on dry-run (previously only caught score == 50.0,
  missing the 0.0 case when criteria exist but no tasks matched).

**prop-3a881566 (P4) — `documentation_completeness` 0.0 in simulated phases:**
- `mas/core/engine/metrics_engine.py`: `documentation_completeness` now becomes `not_applicable`
  when score ≤ 50.0 on dry-run projects (scribe not invoked in simulation).

**prop-f53c0198 (P4) — `global_graph_contribution` low when EpisodeWriter not run:**
- `mas/core/engine/metrics_engine.py`: `global_graph_contribution` ≤ 25.0 on dry-run projects
  is now `not_applicable` with a note pointing to `mas db migrate-graph`.
- `mas/policies/evaluation_policy.yaml`: Documented threshold and not_applicable promotion rule.

### Also in this session

- `mas/core/engine/agent_runner.py` + `mas/core/cli.py`: Added `load_dotenv()` so `.env`
  at repo root is auto-loaded; `ANTHROPIC_API_KEY` now available at runtime without manual export.
- `mas/tests/integration/`: Removed 12 dummy-repo integration tests that spun up temporary YAML
  project directories (irrelevant now that the goal is SQLite-backed storage). Kept
  `test_sqlite_handoff_logging.py` (SQL-focused, passes). Suite: 960 tests.
- `mas/core/engine/access_control.py`: Added `SYSTEM` sentinel to `decisions.decision_log`
  write list (required for handoff_engine AC1 auto-population).

**All 6 proposals marked `applied` in `mas/roster/training_backlog.yaml`.**

---

## [2026-04-15] proj-20260415-004-mas-improvements-full — MAS Improvements (9 Deliverables)

### Code Changes

**AC1 — `handoff_engine.accept()` auto-populates `decisions.decision_log` from `dec` payload:**
- `mas/core/engine/handoff_engine.py`: Added post-accept block that extracts `dec` items from
  accepted handoff payload and appends them to `decisions.decision_log` via `system_append`.
- `mas/core/engine/access_control.py`: Added `SYSTEM` to `decisions.decision_log` write list
  so `system_append` is authorized.

**AC2 — `metrics_engine` `not_applicable` mode for dry-run projects:**
- `mas/core/engine/metrics_engine.py`: Added `mode: str = "live"` field to `MetricResult`
  dataclass; added `_is_dry_run_state()`; updated `aggregate_project_score()` to exclude
  `not_applicable` metrics; updated `evaluate_project()` to promote 50-default metrics to
  `not_applicable` on dry-run projects.

**AC3 — `prompt_assembler` cross-project semantic search fallback:**
- `mas/core/engine/prompt_assembler.py`: Updated `_sqlite_context()` — when local semantic
  search returns < 2 results, tries a second `semantic_search(project_id=None)` cross-project
  call before falling back to `query_project_history`.

**AC4 — `db.py` graph query helpers:**
- `mas/core/db.py`: Added `query_graph_node(node_id)` and `query_graph_edges(node_id, limit)`
  querying the `agent_graph` and `agent_graph_edges` SQLite tables.

**AC5 — `prompt_assembler._graph_context()` uses SQLite:**
- `mas/core/engine/prompt_assembler.py`: Refactored `_graph_context()` to query
  `agent_graph`/`agent_graph_edges` tables first via the new `query_graph_node` and
  `query_graph_edges` helpers; falls back to YAML GraphMemory if tables are empty.

**AC6 — `training_engine` proposal deduplication:**
- `mas/core/engine/training_engine.py`: Added `_is_duplicate(description, backlog)` helper;
  added deduplication check in all 3 proposal generation loops; skips proposals whose
  description matches an `applied` or `approved` entry in the training backlog; also skips
  `not_applicable` metrics.

### Documentation Changes

**AC7 — `mas/CLAUDE.md` Live Run Quickstart:**
- Added "## Live Run Quickstart" section with ANTHROPIC_API_KEY setup, venv activation,
  `mas tokens`, `mas db rebuild-fts`, `mas db migrate-graph` commands, and dry-run note.

**AC8 — `master_orchestrator.md` + `scribe_agent.md` phase-close documentation:**
- `agents/master_orchestrator.md`: Added step 5 (invoke scribe_agent at phase transitions),
  step 6 (spawn opportunity review at review phase), step 7 (EpisodeWriter + migrate-graph at
  closure).
- `agents/scribe_agent.md`: Added D8 section detailing exactly what to do at phase-close:
  create phase summary file, append to `artifacts.change_log`, append to `artifacts.documents`,
  return handoff with `s: "scribe:recorded"`.

**AC9 — `librarian_agent.md` maintenance schedule** (carried from proj-002):
- Already present in `agents/librarian_agent.md` as a dedicated maintenance schedule section.

### Tests

- `mas/tests/unit/test_mas_improvements.py` — 31 tests covering all 9 ACs
- `mas/tests/unit/test_semantic_search.py` — updated `test_sqlite_context_falls_back_when_semantic_empty`
  to assert `call_count >= 1` (AC3 now makes 2 calls when local results < 2)

**Full suite: 1083 tests, all passing.**

### Backlog

3 systemic proposals added to `mas/roster/training_backlog.yaml`:
- goal_achievement scoring on dry-run projects needs explicit N/A handling (not just 0.0)
- documentation_completeness should account for simulated scribe writes
- EpisodeWriter + migrate-graph should auto-run on project close in live mode

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

---

## [2026-04-15] proj-20260415-002-db-ops-and-librarian — DB Ops, Token CLI, Librarian Agent

**MAS project** | Standard mode | 9 phases | Score: 54.4/100 | 1052 tests (exit 0)

### Deliverables

**D1 — `mas tokens <project-id>` CLI**
- New `mas tokens` subcommand reads `query_token_usage()` and prints prompt/completion/total
  token counts plus dry/live call breakdown
- `mas status` now includes agent call counts and dry% ratio

**D2 — `mas db rebuild-fts` CLI**
- New `mas db` subgroup with `rebuild-fts` subcommand
- Runs `INSERT INTO agent_events_fts(agent_events_fts) VALUES ('rebuild')` — safe and idempotent

**D3 — Dry/Live Run Accounting**
- `agent_runner._log_event()` now includes `"dry_run": bool` in every `agent_call` payload
- `query_token_usage()` returns `dry_calls` and `live_calls` counts alongside totals
- `mas status` and `mas tokens` surface the dry% ratio

**D4 — Graph SQLite Tables + Migration CLI**
- `init_db()` in `log_helpers.py` now creates `agent_graph` and `agent_graph_edges` tables
- New `mas db migrate-graph [--dry-run]` CLI migrates `global_graph.yaml` nodes/edges
  into SQLite with `INSERT OR IGNORE` (idempotent)

**D5 — `librarian_agent` Spawn**
- Gap certificate `gap-proj-20260415-002-001` issued by hr_agent (db_operations capability)
- All-5-consultant review: 4/5 approve (low risk), 1/5 caution (ACL constraint — addressed)
- `agents/librarian_agent.md` drafted — T2 supervised, db_operations capability
- Registered in `mas/roster/registry_index.yaml` (16 active agents, spawned_total=1)
- ACL entry added in `access_control.py` (`governance.consultation_outcome`)

### Backlog Proposals Applied

- `prop-true-mas-002` → **applied** (tokens CLI + dry/live accounting fully implemented)
- `prop-acl-001` → **applied** (`mas db rebuild-fts` CLI implemented)
- `prop-acl-002` → **applied** (dry_run field in payload, ratio in `mas status`)

### Tests

39 new tests (full suite: 1052, exit 0):

- `mas/tests/unit/test_cli_tokens.py` (7 tests — AC1, AC2)
- `mas/tests/unit/test_cli_db.py` (12 tests — AC3, AC6, AC7)
- `mas/tests/unit/test_dry_live_accounting.py` (5 tests — AC4, AC5)
- `mas/tests/unit/test_librarian_agent_prompt.py` (15 tests — AC8, AC9)
- Updated `mas/tests/unit/test_token_tracking.py` — `test_empty_project_returns_zeros`
  updated to assert new `dry_calls`/`live_calls` keys in return dict

### Trainer Proposals (this project — pending Master decision)

16 proposals generated; 4 auto-reject candidates (systemic engine noise).
12 actionable proposals flagged — all relate to metrics scored <70 due to missing
structured state (no formal task board, no decision log entries, no AC formal records):

- `global_graph_contribution` (15/100) — D4 migrates graph to SQLite; score will improve
  once `mas db migrate-graph` is run against the live DB
- `documentation_completeness` (20/100) — Scribe Agent not fully exercised in simulated
  runs; will improve when live agent calls populate project folders
- `goal_achievement`, `acceptance_criteria_pass_rate`, `scope_adherence`,
  `decision_quality` (all 50/100) — metrics fire at 50 when structured state not present;
  real improvement requires live agent runs with formal spec/AC recording
