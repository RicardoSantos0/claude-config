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

| Module | CLI entry | Purpose |
|--------|-----------|---------|
| `shared_state_manager.py` | `uv run python mas/core/shared_state_manager.py` | Project state, access control, snapshots |
| `handoff_engine.py` | `uv run python mas/core/handoff_engine.py` | Handoff creation, acceptance, history |
| `intake_checker.py` | `uv run python mas/core/intake_checker.py` | Spec quality scoring (threshold ≥ 0.85) |
| `capability_registry.py` | `uv run python mas/core/capability_registry.py` | Roster, gap certificates, match scoring |
| `task_board.py` | `uv run python mas/core/task_board.py` | Milestones, tasks, dependency chains |
| `metrics_engine.py` | `uv run python mas/core/metrics_engine.py` | Project + agent scoring, eval reports |
| `spawn_policy.py` | `uv run python mas/core/spawn_policy.py` | Spawn validation, agent package builder |
| `training_engine.py` | `uv run python mas/core/training_engine.py` | Proposal generation, backlog management |
| `consultation_engine.py` | `uv run python mas/core/consultation_engine.py` | Consultation lifecycle, synthesis |
| `cli.py` | `uv run mas` | Top-level CLI |

---

## Key File Locations

```
mas/
├── core/               Python engine (14 modules)
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
uv run pytest                          # All 937 tests
uv run pytest -x                       # Stop on first failure
uv run pytest -v mas/tests/unit/       # Verbose unit tests
uv run pytest mas/tests/integration/test_full_lifecycle.py -v  # E2E lifecycle
uv run pytest --cov=mas/core           # With coverage
```
