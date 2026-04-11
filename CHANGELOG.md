# Changelog

All notable changes to this repository are documented here.

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
