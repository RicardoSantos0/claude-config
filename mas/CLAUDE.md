# Multi-Agent System (MAS)

A governed agent network for project delivery. Coordinates 14 specialized agents through
a formal handoff protocol, shared state with access control, and a full evaluation +
improvement loop.

All commands must be run from the **repo root** (the directory containing `pyproject.toml`).

**Recommended: activate the venv once per session, then use bare commands.**

```powershell
# Windows — activate venv (run once per shell session):
C:\Users\ricar\Documents\claude-config\.venv\Scripts\activate

# After activation, all bare commands work:
mas init session-scheduler
mas init --mode=lite quick-task
mas status proj-20260414-001-true-mas-integration
pytest mas/tests/
```

`uv run` also works but rebuilds the wheel each time, which is slower and fails
if Windows App Store Python is active. Prefer the activated venv.

---

## Live Run Quickstart

To run agents with a real Anthropic API key (live mode — agents make actual LLM calls):

```powershell
# 1. Set your API key (Windows — PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Or add to .env at repo root (key name must be ANTHROPIC_API_KEY):
#   ANTHROPIC_API_KEY=sk-ant-...

# 2. Activate venv (if not already active)
C:\Users\ricar\Documents\claude-config\.venv\Scripts\activate

# 3. Start a project — agents will make live calls
mas init my-project

# 4. Check token usage after a run
mas tokens proj-YYYYMMDD-NNN-my-project

# 5. Rebuild FTS index after a batch of events
mas db rebuild-fts

# 6. Migrate graph relationships to SQLite (run once after setup)
mas db migrate-graph
```

> **Note:** Without `ANTHROPIC_API_KEY`, all `agent_runner` calls are dry-run.
> The engine still works — state is populated by the human acting as orchestrator —
> but evaluation metrics will score `not_applicable` for metrics that require real
> agent output (goal_achievement, AC pass rate, scope adherence, decision quality).

---

## Quick Reference

```bash
# Project lifecycle
mas init    <slug-or-id>               # Initialize new project
mas init    --mode=lite <slug>         # Lite mode: 3 phases, no consultation
mas status  <project-id>              # Current phase [lite], owner, pending handoffs
mas state   <project-id>              # Full shared state dump
mas pending <project-id>              # Unresolved handoffs
mas snapshot <project-id>             # Snapshot state at current phase
mas roster                            # All registered agents

# Tests
pytest mas/tests/                     # Full suite
pytest mas/tests/unit/                # Unit tests only
pytest mas/tests/integration/         # Integration tests only
pytest mas/tests/integration/test_full_lifecycle.py  # End-to-end lifecycle test
```

---

## Project Naming Convention

Project IDs follow the format: `proj-{YYYYMMDD}-{NNN}-{slug}`

- **Date**: UTC date of creation (auto-generated)
- **Sequence**: 3-digit, zero-padded, auto-incremented per day
- **Slug**: human-readable identifier (lowercase, hyphens, max 40 chars)

Examples:
- `mas init session-scheduler` → `proj-20260410-001-session-scheduler`
- `mas init proj-20260410-001-my-project` → accepted as-is

Folder name matches project ID: `mas/projects/proj-20260410-001-session-scheduler/`

---

## Project Lifecycle

```
intake → specification → planning → capability_discovery → execution
       → review → evaluation → improvement → closed
```

Each phase transition requires:
1. Exit criteria met (verified by Master)
2. Shared state snapshot (`uv run mas snapshot <id>`)
3. Phase recorded in `workflow.completed_phases`

---

## Agent Network

### Invoking the Network
Always start by invoking `master_orchestrator`. It reads the project brief, initializes
state, and coordinates the rest of the network.

```
User → master_orchestrator
         ├── scribe_agent          (project memory, folder init)
         ├── inquirer_agent        (intake, clarification Q&A)
         ├── product_manager_agent (requirements, product plan)
         ├── hr_agent              (capability discovery, gap certs)
         ├── project_manager_agent (milestones, tasks, execution)
         ├── evaluator_agent       (metrics, evaluation report)
         ├── trainer_agent         (improvement proposals — L0 advisory)
         ├── spawner_agent         (draft agent packages — T2 supervised)
         └── consultant_panel
               ├── risk_advisor
               ├── quality_advisor
               ├── devils_advocate
               ├── domain_expert
               └── efficiency_advisor
```

### Consultation Triggers
**All 5 consultants** (`spawn`, `scope_change`):
These are mandatory types — the full panel is always convened.

**Core-three consultants** (`governance`, `escalation`, `architecture`):
Scoped panel: `risk_advisor`, `quality_advisor`, `efficiency_advisor`.

If **all responding** consultants return `high` risk → `human_escalation_required = true` (hard stop).

---

## Core Modules

Modules in `mas/core/` (top-level, always use these paths):

| Module | CLI entry | Purpose |
|--------|-----------|---------|
| `cli.py` | `mas` / `uv run mas` | Top-level CLI entry point |
| `db.py` | — (library) | Central SQLite access layer; `semantic_search()`, `query_token_usage()` |
| `wire_protocol.py` | — (library) | Compact wire format for handoff payloads |
| `config.py` | — (library) | System configuration loader |

Modules in `mas/core/engine/` (engine subpackage — use full path):

| Module | CLI entry | Purpose |
|--------|-----------|---------|
| `shared_state_manager.py` | `python mas/core/engine/shared_state_manager.py` | Project state, access control, snapshots |
| `handoff_engine.py` | `python mas/core/engine/handoff_engine.py` | Handoff creation, acceptance, SQLite logging |
| `intake_checker.py` | `python mas/core/engine/intake_checker.py` | Spec quality scoring (threshold ≥ 0.85) |
| `capability_registry.py` | `python mas/core/engine/capability_registry.py` | Roster, gap certificates, match scoring |
| `task_board.py` | `python mas/core/engine/task_board.py` | Milestones, tasks, dependency chains |
| `metrics_engine.py` | `python mas/core/engine/metrics_engine.py` | Project + agent scoring, eval reports |
| `spawn_policy.py` | `python mas/core/engine/spawn_policy.py` | Spawn validation; `LITE_MODE_NO_SPAWN` check |
| `training_engine.py` | `python mas/core/engine/training_engine.py` | Proposal generation, backlog management |
| `consultation_engine.py` | `python mas/core/engine/consultation_engine.py` | Consultation lifecycle, synthesis |
| `agent_runner.py` | — (library) | Anthropic SDK wrapper; gated on `ANTHROPIC_API_KEY`; logs token usage |
| `prompt_assembler.py` | — (library) | State projection + FTS5-aware prompt building |
| `access_control.py` | — (library) | Field-level write permissions matrix |
| `skill_bridge.py` | — (library) | Agent-to-skill gateway with auth matrix |
| `graph_memory.py` | — (library) | Graph-based relationship memory |
| `audit_logger.py` | — (library) | Structured YAML event logging |
| `checkpoint_writer.py` | — (library) | Human-readable project checkpoints |

> **Note:** Always use the activated venv (`mas/core/engine/`) not `uv run python` (slower; fails with Windows App Store Python).

---

## Key File Locations

```
mas/
├── core/               Python engine
│   ├── cli.py          CLI entry point
│   ├── db.py           SQLite access layer (semantic_search, query_token_usage)
│   ├── wire_protocol.py
│   ├── config.py
│   └── engine/         Engine subpackage (20 modules)
├── data/
│   ├── episodic.db     SQLite WAL — agent_events table + agent_events_fts (FTS5)
│   └── semantic_stub.json  ← now live; backend: sqlite_fts5
├── agents/             → see ../agents/ at repo root (symlinked globally)
├── policies/           Governance rules (YAML)
├── templates/          Handoff, spawn, eval report templates (YAML)
├── domains/            Domain context injected into domain_expert (Markdown)
├── foundation/         Shared state schema, memory types, folder structure
├── roster/
│   ├── registry_index.yaml     Active agent registry
│   ├── version_history.yaml    All roster changes (append-only)
│   ├── training_backlog.yaml   Created at runtime by training_engine
│   └── trust_tiers/            Tier definitions
├── tests/
│   ├── unit/           Per-module unit tests
│   ├── integration/    Per-phase integration tests
│   │   └── test_full_lifecycle.py   ← end-to-end test
│   ├── governance/     Access control and immutability tests
│   └── prompts/        Agent prompt tests
├── projects/           Runtime project data (gitignored)
├── system_config.yaml  Master configuration
└── CLAUDE.md           ← you are here
```

---

## Governance Rules (summary)

| Rule | Detail |
|------|--------|
| Handoff protocol | Every delegation uses `handoff_engine.py` — no informal routing |
| Access control | Each shared state field has an owner; writes from non-owners fail |
| Approval authority | Only `master_orchestrator` can call `sm.approve()` |
| Spawn limits | Max 3/project · max 1/phase · no recursive spawn |
| Spawn prerequisites | Gap cert (master-approved) + consultant review + worthiness check |
| Training authority | L0 — proposals only; Trainer cannot apply changes |
| Trust promotion | Requires human approval — not automated |
| Unanimous risk | 5/5 consultants at `high` → human escalation required (hard stop) |

---

## Adding a New Domain

Drop a Markdown file in `mas/domains/{domain_name}.md`.
The `domain_expert` consultant will inject it automatically when `decision_type` matches.

Current domains: `software_engineering` · `data_science` · `content_creation` · `research` · `learning_analytics`

---

## Running Tests

```bash
pytest mas/tests/                      # All 1013 tests (activate venv first)
pytest mas/tests/ -x                   # Stop on first failure
pytest mas/tests/unit/                 # Unit tests only
pytest mas/tests/integration/test_full_lifecycle.py -v  # E2E lifecycle
pytest mas/tests/ --cov=mas/core       # With coverage

# Or via uv (slower, rebuilds wheel):
uv run pytest mas/tests/
```
