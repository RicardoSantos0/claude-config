# claude-config

Global Claude Code configuration repository synced across machines. Provides custom VS Code agents, slash commands, skill packages, and a **governed Multi-Agent System (MAS)** that coordinates 14 specialized AI agents through formal protocols for end-to-end project delivery.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Directory Structure](#directory-structure)
- [Multi-Agent System (MAS)](#multi-agent-system-mas)
  - [Agent Network](#agent-network)
  - [Project Lifecycle](#project-lifecycle)
  - [Core Modules](#core-modules)
  - [Governance](#governance)
  - [Shared State](#shared-state)
  - [Consultation System](#consultation-system)
  - [Communication Optimization](#communication-optimization)
  - [LLM Configuration](#llm-configuration)
- [Skills](#skills)
- [Commands](#commands)
- [CLI Reference](#cli-reference)
- [Testing](#testing)
- [Human Escalation Triggers](#human-escalation-triggers)
- [Adding New Agents or Skills](#adding-new-agents-or-skills)

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Claude Code (VS Code extension)

### Setup (per machine)

```powershell
# Windows (PowerShell as Administrator)
.\setup.ps1

# macOS / Linux
./setup.sh
```

This creates symlinks so `agents/`, `commands/`, and `skills/` are globally available in Claude Code:

| Local Path | Symlink Target |
|------------|----------------|
| `agents/` | `~/.claude/agents/` |
| `commands/` | `~/.claude/commands/` |
| `skills/` | `~/.claude/skills/` |

### Run a MAS project

Activate the venv once per session (recommended — faster than `uv run`):

```powershell
# Windows
C:\Users\ricar\Documents\claude-config\.venv\Scripts\activate
```

Then use bare commands:

```bash
mas init session-scheduler          # Standard project (9 phases)
mas init --mode=lite quick-fix      # Lite project (3 phases, no consultation)
mas doctor                          # Runtime diagnostics
mas status <project-id>             # Check project phase
mas resume <project-id>             # Resume guidance from checkpoint + state
mas roster                          # List all agents
pytest mas/tests/                   # Run test suite
```

`uv run mas ...` also works from repo root but is slower.

---

## Directory Structure

```
claude-config/
├── CLAUDE.md              # Agent instructions (loaded by Claude Code)
├── README.md              # This file
├── pyproject.toml         # Python package config (MAS)
├── setup.ps1              # Windows symlink setup (run as Admin)
├── setup.sh               # macOS/Linux symlink setup
│
├── agents/                # Custom Claude Code agents (20 MAS agents + utilities)
│   ├── master_orchestrator.md
│   ├── scribe_agent.md
│   ├── hr_agent.md
│   ├── inquirer_agent.md
│   ├── product_manager_agent.md
│   ├── project_manager_agent.md
│   ├── evaluator_agent.md
│   ├── trainer_agent.md
│   ├── spawner_agent.md
│   ├── librarian_agent.md
│   ├── risk_advisor.md
│   ├── quality_advisor.md
│   ├── devils_advocate.md
│   ├── domain_expert.md
│   ├── efficiency_advisor.md
│   ├── session_scheduler.md
│   ├── canonical_engineer.md
│   ├── analysis_engineer.md
│   ├── integration_engineer.md
│   ├── reliability_engineer.md
│   └── _utilities.md
│
├── commands/              # Custom slash commands
│   └── resume-mas.md      # Resume a paused MAS project
│
├── standards/             # Engineering standards (agent frontmatter, wire protocol, security, …)
│   ├── README.md
│   ├── agent-frontmatter.md
│   ├── commit-style.md
│   ├── documentation-format.md
│   ├── mas-governance.md
│   ├── mas-project-lifecycle.md
│   ├── python-standards.md
│   ├── security-and-permissions.md
│   ├── sql-conventions.md
│   └── wire-protocol.md
│
├── skills/                # Skill packages
│   ├── frontend-design/
│   ├── mas-clarify/       # MAS workflow: surface blocking questions
│   ├── mas-document/      # MAS workflow: update checkpoints and logs
│   ├── mas-examine/       # MAS workflow: analyze without modifying
│   ├── mas-handoff/       # MAS workflow: produce human-readable handoff
│   ├── mas-logwork/       # MAS workflow: track session work
│   ├── mas-plan/          # MAS workflow: produce or update execution plan
│   ├── mas-postmortem/    # MAS workflow: analyze failures and produce proposals
│   ├── mas-review/        # MAS workflow: review project state and next action
│   ├── notebooklm/
│   ├── research-extract/
│   ├── research-sync/
│   └── skill-builder/
│
└── mas/                   # Multi-Agent System engine
    ├── CLAUDE.md
    ├── system_config.yaml
    ├── core/              # Python engine
    │   ├── cli.py         # CLI entry point
    │   ├── db.py          # SQL access layer (SQLite fallback, PostgreSQL optional)
    │   └── engine/        # 20 engine modules
    ├── data/              # Runtime databases and local runtime state
    │   └── episodic.db    # Local SQLite fallback store
    ├── domains/           # Domain context files (auto-injected into domain_expert)
    ├── foundation/        # Protocol & schema specs
    ├── policies/          # 6 governance YAML files
    ├── projects/          # Project workspaces (gitignored)
    ├── roster/            # Agent registry + training_backlog.yaml
    ├── templates/         # Handoff, spawn, eval report templates
    └── tests/             # Test suite
```

---

## Multi-Agent System (MAS)

Version **0.2.0**. A governed multi-agent delivery system that coordinates 20 specialized AI agents through formal handoff protocols, access-controlled shared state, and policy enforcement.

**Key dependencies**: `anthropic>=0.49.0`, `pyyaml>=6.0`, `python-dotenv>=1.0`, `click>=8.1`, `rich>=13.0`, `networkx>=3.0`

### Agent Network

20 agents organized across 4 trust tiers:

```
┌─────────────────────────────────────────────────────────────────┐
│  T0 CORE (highest trust)                                        │
│  ┌──────────────────────┐  ┌────────────┐  ┌──────────┐        │
│  │ master_orchestrator  │  │   scribe   │  │    hr    │        │
│  │ (Opus · coordination │  │ (docs,     │  │ (roster, │        │
│  │  governance, phases) │  │  audit)    │  │  gaps)   │        │
│  └──────────────────────┘  └────────────┘  └──────────┘        │
├─────────────────────────────────────────────────────────────────┤
│  T1 ESTABLISHED (independent specialists)                       │
│  ┌───────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐  │
│  │ inquirer  │ │  product_   │ │  project_   │ │ evaluator │  │
│  │ (intake,  │ │  manager    │ │  manager    │ │ (metrics, │  │
│  │  Q&A)     │ │ (MoSCoW,   │ │ (tasks,     │ │  scoring) │  │
│  │           │ │  scope)     │ │  milestones)│ │           │  │
│  └───────────┘ └─────────────┘ └─────────────┘ └───────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  T1 CONSULTANT PANEL (advisory · invoked for high-impact)       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐ │
│  │   risk   │ │ quality  │ │ devil's  │ │ domain │ │ effic. │ │
│  │ advisor  │ │ advisor  │ │ advocate │ │ expert │ │advisor │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ └────────┘ │
├─────────────────────────────────────────────────────────────────┤
│  T1 DELIVERY ENGINEERS (file/code delivery)                     │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐       │
│  │ canonical │ │ analysis  │ │integration│ │reliability│       │
│  │ engineer  │ │ engineer  │ │ engineer  │ │ engineer  │       │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘       │
│  ┌───────────┐  ┌──────────┐                                    │
│  │ session   │  │librarian │                                     │
│  │ scheduler │  │ (db ops) │                                     │
│  └───────────┘  └──────────┘                                    │
├─────────────────────────────────────────────────────────────────┤
│  T2 SUPERVISED (require Master oversight)                       │
│  ┌───────────┐  ┌───────────┐                                   │
│  │  trainer  │  │  spawner  │                                   │
│  │ (L0 advise│  │ (agent    │                                   │
│  │  only)    │  │  design)  │                                   │
│  └───────────┘  └───────────┘                                   │
├─────────────────────────────────────────────────────────────────┤
│  T3 PROVISIONAL (sandbox · spawned agents, none currently)      │
└─────────────────────────────────────────────────────────────────┘
```

| Tier | Agent | Role |
|------|-------|------|
| **T0** | `master_orchestrator` | Overall coordination, governance, delegation, phase management, spawn approval |
| **T0** | `scribe_agent` | Documentation, record-keeping, decision logging, artifact tracking, audit trail |
| **T0** | `hr_agent` | Capability discovery, DeploymentPlan production, roster management, gap certification, agent registration |
| **T1** | `inquirer_agent` | Intake, requirements elicitation, clarification Q&A |
| **T1** | `product_manager_agent` | Product planning, MoSCoW prioritization, acceptance criteria, scope definition |
| **T1** | `project_manager_agent` | Execution planning, task decomposition, milestone tracking, dependency mapping |
| **T1** | `evaluator_agent` | Performance evaluation, metric scoring, pattern detection |
| **T1 Consultant** | `risk_advisor` | Risk analysis, failure mode analysis, mitigation planning, blast radius |
| **T1 Consultant** | `quality_advisor` | Quality review, completeness check, testability assessment |
| **T1 Consultant** | `devils_advocate` | Assumption challenging, alternative perspectives, blind spot detection |
| **T1 Consultant** | `domain_expert` | Domain knowledge, best practices, prior art (auto-injects from `mas/domains/`) |
| **T1 Consultant** | `efficiency_advisor` | Overengineering detection, cost estimation, simplification |
| **T1** | `trainer_agent` | Improvement proposals, pattern detection (L0 advisory only) |
| **T1** | `session_scheduler` | Scheduled session-resume, project lock management, cron-triggered checkpoint continuation |
| **T1** | `canonical_engineer` | Pydantic v2 model design, schema registry, provenance field patterns |
| **T1** | `analysis_engineer` | DataFrame flattening (Polars), CLI analysis reports, review QA reports |
| **T1** | `integration_engineer` | Read-only external connectors, dry-run diff engine, API-key-gated sync |
| **T1** | `reliability_engineer` | Test suite (≥80% coverage), golden fixtures, CI lint guards, quality gates |
| **T2** | `librarian_agent` | Database operations: FTS5 maintenance, graph migration, vacuum on episodic.db |
| **T2** | `spawner_agent` | Agent design, capability packaging, draft generation |

### Project Lifecycle

**Standard mode** (9 phases):

```mermaid
flowchart LR
    A[intake] --> B[specification]
    B --> C[planning]
    C --> D[capability_discovery]
    D --> E[execution]
    E --> F[review]
    F --> G[evaluation]
    G --> H[improvement]
    H --> I[closed]
```

**Lite mode** (`mas init --mode=lite <slug>`, 3 phases):

```
intake → execution → closed
```

Lite mode skips specification, planning, capability discovery, consultation, and review.
`mas status` shows `[lite]` next to the phase. Spawn is blocked in lite projects.

Each standard phase transition requires:
1. Exit criteria verification by Master
2. Shared state snapshot
3. Phase recording in state

**Project IDs** follow the format: `proj-{YYYYMMDD}-{NNN}-{slug}` (e.g., `proj-20260410-001-session-scheduler`). Each project gets a standardized folder structure created by Scribe.

### Core Modules

**`mas/core/`** — top-level (always importable as `core.*`):

| Module | Purpose |
|--------|---------|
| `cli.py` | CLI entry point (`mas init`, `mas status`, `mas init --mode=lite`, …) |
| `db.py` | Central SQL layer: `append_event`, `semantic_search`, `query_token_usage`, shared-state SQL helpers |
| `wire_protocol.py` | Compact wire format for handoff payloads |
| `config.py` | System configuration loader (reads `mas/system_config.yaml`) |

**`mas/data/`** — runtime databases and sync scripts:

| Module | Purpose |
|--------|---------|
| `episodic.db` | SQLite: agent events, FTS5 index, agents table (queryable projection of registry) |
| `roster_sync.py` | Sync `registry_canonical.yaml` → `episodic.db` agents table (idempotent upsert) |

**`mas/core/engine/`** — engine subpackage (import as `core.engine.*`):

| Module | Purpose |
|--------|---------|
| `shared_state_manager.py` | Project state, access control, snapshots |
| `handoff_engine.py` | Handoff creation, acceptance, SQL event logging |
| `access_control.py` | Field-level write permissions (updated 0.2.0 — broader write rights) |
| `prompt_assembler.py` | State projection + FTS5-aware prompt injection |
| `agent_runner.py` | Anthropic SDK wrapper; gated on `ANTHROPIC_API_KEY`; logs tokens |
| `consultation_engine.py` | Consultation lifecycle, synthesis, compact format |
| `intake_checker.py` | Spec quality scoring (threshold ≥ 0.85) |
| `capability_registry.py` | Roster, gap certificates, match scoring |
| `task_board.py` | Milestones, tasks, dependency chains |
| `metrics_engine.py` | Project + agent scoring, evaluation reports |
| `spawn_policy.py` | Spawn validation; `LITE_MODE_NO_SPAWN` for lite projects |
| `training_engine.py` | Proposal generation, backlog management |
| `skill_bridge.py` | Agent-to-skill gateway with authorization matrix |
| `graph_memory.py` | Legacy graph helper still present for migration/compatibility work |
| `audit_logger.py` | Structured YAML event logging |
| `checkpoint_writer.py` | Human-readable project checkpoints |
| `context_compressor.py` | Progressive state compression for token budgets |
| `message_bus.py` | Inter-agent messaging |

### Governance

Six YAML policy files in `mas/policies/` enforce all system rules:

| Policy | Key Rules |
|--------|-----------|
| **governance_policy.yaml** | Reuse before create · document before forget · improve only through evidence · violations blocked pre-execution · 3 violations → human escalation |
| **handoff_protocol.yaml** | Structured handoff records (identity, parties, context, payload, acceptance status) |
| **trust_tier_policy.yaml** | 4 tiers (T0–T3) with promotion requirements: evaluator verification + zero violations + human approval |
| **spawn_policy.yaml** | Gap cert + Master approval + consultant review · max 3/project · max 1/phase · no recursive spawning |
| **evaluation_policy.yaml** | Metrics: goal achievement, acceptance pass rate, handoff acceptance, doc completeness, boundary violations · Probation <60, Exemplary >90 |
| **training_policy.yaml** | L0 advisory → L1 supervised → L2 autonomous · proposals need ≥1 evaluation report |

#### Trust Tier Promotions

- **T3 → T1**: Evaluator verification + zero governance violations + human approval
- **Trainer L0 → L1**: 3 successful projects + human review + zero violations
- **Trainer L1 → L2**: 5 successful L1 cycles + human approval

### Shared State

Each project has a single source of truth (`shared_state.yaml`) with access-controlled sections:

| Section | Contents |
|---------|----------|
| `core_identity` | project_id, phase, status (immutable after creation) |
| `project_definition` | brief, spec, goal, scope, constraints, success/acceptance criteria, risk classification |
| `workflow` | active agents, completed phases, handoff history, resource requests |
| `decisions` | decision log, assumptions, open questions, approvals, policy flags |
| `capability` | available skills, gap certificates, spawn requests |
| `artifacts` | documents, deliverables, change log |
| `evaluation` | performance metrics, quality findings, improvement proposals |
| `communication` | token tracking, wire compliance counters |
| `consultation` | consultation requests and responses |
| `execution` | tasks and milestones |

All fields have `set_by` (owner), `mutability` rules, and type definitions. **No agent may write to fields it doesn't own.**

### Consultation System

The 5-member consultant panel: `risk_advisor`, `quality_advisor`, `devils_advocate`, `domain_expert`, `efficiency_advisor`.

**Master decides the panel composition** — the engine adds no defaults. Master specifies which consultants to invoke via `consultation_trigger.consultants` in its wire response. Typical selections:

| Decision type | Consultants |
|---------------|-------------|
| Architecture / technical | `domain_expert`, `risk_advisor`, `quality_advisor` |
| Scope / governance | `risk_advisor`, `devils_advocate`, `efficiency_advisor` |
| Critical / high-stakes | All five |

**Hard stop**: If all invoked consultants return "high" risk → human escalation required. Master cannot override unanimous high-risk without human approval.

### Communication Optimization

- **Compact wire format**: `HandoffEngine.compact()`/`expand()`, `ConsultationEngine.compact_request()`/`expand_request()`
- **Token counter**: Heuristic and tiktoken backends
- **Wire protocol validation** for payload compliance
- **Skill bridge** with per-agent access control matrix
- **SQL-backed context lookups** with SQLite as the local fallback and PostgreSQL/ChromaDB available when configured
- **Communication efficiency metrics** in evaluation (half-weight): token efficiency, payload density, context injection efficiency, consultation overhead, wire compliance

### Memory and Episodic DB

**Three-tier memory:**

| Type | Scope | Lifetime | Store |
|------|-------|----------|-------|
| Working state | Task/phase | Ephemeral | `shared_state.yaml` (archived at phase end) |
| Episodic (events) | Per project | Durable | SQL backend (`mas/data/episodic.db` locally, PostgreSQL when configured) |
| Roster | System-wide | Durable | `mas/roster/` YAML files |

The runtime uses a SQL event store:

- Every handoff create/accept/reject writes a row
- Every live `agent_runner` call writes a row
- SQLite uses FTS5 locally; PostgreSQL uses a simple SQL text match until a richer search backend is configured
- `core.db.semantic_search(query, project_id)` — SQL-backed event search
- `core.db.query_token_usage(project_id)` — sums `tokens_prompt/completion/total`
- `prompt_assembler` injects the 5 most relevant past events into every agent prompt
  (uses semantic search with current phase as query; falls back to recent-5 if < 2 hits)

### LLM Configuration

| Agent | Model | Max Tokens | Temperature |
|-------|-------|------------|-------------|
| `master_orchestrator` | `claude-opus-4-7` | 4096 | 0.3 |
| `efficiency_advisor` | `claude-haiku-4-5` | 4096 | 0.3 |
| All others | `claude-sonnet-4-6` | 4096 | 0.3 |

Model selection is canonical in `mas/system_config.yaml` (llm block) and per-agent in `mas/roster/registry_canonical.yaml`. Override at runtime via `MAS_MASTER_MODEL` / `MAS_DEFAULT_MODEL` env vars.

### Domain Contexts

Markdown files in `mas/domains/` auto-injected into `domain_expert`:

- `software_engineering.md`
- `data_science.md`
- `content_creation.md`
- `research.md`

---

## Skills

### MAS Workflow Skills

These skills provide ergonomic session workflows over MAS governance state. They wrap MAS concepts without replacing them.

| Skill | Trigger | Description |
|-------|---------|-------------|
| `mas-review` | Start/resume a session | Review MAS project state, pending handoffs, risks, and recommended next action |
| `mas-plan` | Need a phase-aware plan | Produce or update an execution plan from project state and objectives |
| `mas-clarify` | Ambiguity blocks work | Surface and prioritize blocking questions; propose safe assumptions |
| `mas-examine` | Need to analyze before acting | Analyze code, docs, state, policies, or architecture without modifying anything |
| `mas-document` | Completing a phase or session | Update checkpoints, decision logs, artifact indexes, and progress summaries |
| `mas-handoff` | Ending a session or handing off | Produce a human-readable handoff from MAS state (session, PR, agent, incident) |
| `mas-logwork` | Track session work | Record start/stop/pause/resume and feed work context into MAS evaluation |
| `mas-postmortem` | After a failure or violation | Analyze root causes and produce action items and training proposals |

### Other Skills

| Skill | Description |
|-------|-------------|
| `frontend-design` | Frontend design patterns and guidance |
| `notebooklm` | NotebookLM integration (auth, scripts, data) |
| `research-extract` | Research extraction workflows |
| `research-sync` | Research synchronization |
| `skill-builder` | Skill creation toolkit |

---

## Commands

| Command | Description |
|---------|-------------|
| `resume-mas` | Resume a paused MAS project from its checkpoint |

---

## CLI Reference

Activate the venv first (`...\.venv\Scripts\activate`), then:

```bash
mas init <slug>                  # Initialize standard project (9 phases)
mas init --mode=lite <slug>      # Initialize lite project (3 phases, no consultation)
mas doctor                       # Runtime/env diagnostics (DB, vector, templates, API key)
mas status <project-id>          # Current phase [lite], owner, pending handoffs
mas resume <project-id>          # Resume summary + next action
mas pending <project-id>         # Unresolved handoffs
mas snapshot <project-id>        # Snapshot state at current phase
mas roster                       # All registered agents
```

Or via `uv run mas <command>` from repo root (slower).

---

## Testing

```bash
pytest mas/tests/              # Full suite
pytest mas/tests/unit/         # Unit tests
pytest mas/tests/integration/  # Integration tests
pytest mas/tests/governance/   # Access control & immutability
pytest mas/tests/prompts/      # Agent prompt tests
```

- **Total test files:** 50 Python test files (located under `mas/tests/`).

Legacy graph-memory tests remain quarantined while the repo uses the SQL/vector path instead.

---

## Human Escalation Triggers

The system forces human intervention when:

- Risk classification is "critical"
- Unresolvable consultant concern
- Two consecutive spawn denials
- Phase blocked after retry
- Unanimous high-risk from all 5 consultants
- Master needs to override unanimous recommendation
- Trust tier promotion, governance policy change, or trainer promotion

---

## Adding New Agents or Skills

- **Agent**: Create `agents/{name}.md` with frontmatter (`name`, `description`, `tools`)
- **Skill**: Create `skills/{name}/SKILL.md`
- **Command**: Create `commands/{name}.md`

---

## Sharing / Exporting This Repo

**Do not zip the working tree directly.**

The working tree may contain runtime state, local Claude permissions, browser state,
databases, logs, or credentials that must not be shared.

Use the source-only export scripts instead:

```bash
# Bash / macOS / Linux
scripts/export_source.sh
python scripts/check_archive_clean.py claude-config-source.zip

# PowerShell / Windows
.\scripts\export_source.ps1
python scripts/check_archive_clean.py claude-config-source.zip
```

The export scripts use `git archive` which only includes tracked source files and
honours `.gitattributes` export-ignore rules. The scanner will fail with a non-zero
exit code if any blocked path (`.env`, `.venv/`, `mas/projects/`, browser state, etc.)
is present in the archive.
- Push to GitHub — other machines pull to sync
