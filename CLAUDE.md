# Claude Config — Global Agent & Skill Repository

This repository is the global Claude Code configuration synced across all machines.
It provides custom agents, skills, slash commands, and the Multi-Agent System (MAS).

## Structure

```
agents/          Custom Claude Code agents   → symlinked to ~/.claude/agents/
commands/        Custom slash commands       → symlinked to ~/.claude/commands/
skills/          Skill packages              → symlinked to ~/.claude/skills/
mas/             Multi-Agent System engine   → see mas/CLAUDE.md
pyproject.toml   Python package config (MAS)
setup.ps1        One-time setup — Windows (run as Administrator)
setup.sh         One-time setup — macOS / Linux
```

## First-Time Setup (per machine)

```powershell
# Windows (PowerShell as Administrator)
.\setup.ps1

# macOS / Linux
./setup.sh
```

This creates symlinks so agents, commands, and skills are globally available in Claude Code.

## Running the MAS

All `uv run` commands must be executed from this repo root (where `pyproject.toml` lives).

```bash
uv run mas init    <slug-or-id>      # Start a new project (e.g. 'session-scheduler')
uv run mas status  <project-id>     # Show project status and phase
uv run mas state   <project-id>     # Dump full shared state
uv run mas pending <project-id>     # List unresolved handoffs
uv run mas roster                   # Show all registered agents
uv run pytest mas/tests/            # Run the full test suite
```

### Two execution modes

| Mode | How | When |
|------|-----|------|
| **Claude Code manual orchestration** | Use `uv run mas prompt <project-id> [agent]` plus Claude Code agents / manual wire application | Primary no-API workflow |
| **`mas run` CLI** | `uv run mas run <project-id>` drives the live loop autonomously | Requires `ANTHROPIC_API_KEY` with credits |

Claude Code is the primary workflow for this environment. The Python engine handles state, handoffs, and governance; Claude Code is the manual agent invoker.

To get the assembled prompt for any agent (useful in Claude Code mode):
```bash
uv run mas prompt <project-id>                # next agent auto-detected
uv run mas prompt <project-id> inquirer_agent # specific agent
```

## Agent Network

The MAS has 14 agents across 4 trust tiers:

| Tier | Agents |
|------|--------|
| T0 Core | `master_orchestrator`, `scribe_agent`, `hr_agent` |
| T1 Established | `inquirer_agent`, `product_manager_agent`, `project_manager_agent`, `evaluator_agent`, `trainer_agent` |
| T1 Consultants | `risk_advisor`, `quality_advisor`, `devils_advocate`, `domain_expert`, `efficiency_advisor` |
| T2 Supervised | `spawner_agent` |

Invoke `master_orchestrator` to start a project. It coordinates all other agents.

## Adding New Agents or Skills

- New agent: `agents/{name}.md` with frontmatter `name`, `description`, `tools`
- New skill: `skills/{name}/SKILL.md`
- New command: `commands/{name}.md`
- Push to GitHub — other machines pull to sync

## Key Policies (enforced by the MAS engine)

- Every delegation goes through a formal handoff (`handoff_engine.py`)
- Shared state has access control — agents can only write fields they own
- Spawning new agents requires: gap certificate + master approval + consultant review
- Max 3 spawns per project, 1 per phase, no recursive spawning
- All training proposals are advisory — nothing changes without Master approval

## MAS Workflow Enforcement

**Master Orchestrator is strictly prohibited from bypassing the MAS structure for any project ordered to MAS.**

- The Master Orchestrator must always follow the MAS workflow and protocols for all project phases and delegations.
- It is not authorized to delegate work outside the MAS, including direct delegation to Claude Code or any agent/process not governed by the MAS system.
- Any attempt to override or circumvent the MAS workflow is a governance violation and must be escalated for review.

## Four Engineering Principles

These principles apply to all code changes made in this repository and any project governed by the MAS.

### 1. Think Before Coding
State assumptions explicitly. Present multiple interpretations when ambiguity exists. Push back when a simpler approach exists. Stop and ask when confused — do not silently pick an interpretation and run with it.

### 2. Simplicity First
Minimum code that solves the problem. No features beyond what was asked. No abstractions for single-use code. No "flexibility" that wasn't requested. No error handling for impossible scenarios. If 200 lines could be 50, rewrite it. Test: would a senior engineer say this is overcomplicated? If yes, simplify.

### 3. Surgical Changes
Touch only what you must. Don't improve adjacent code, comments, or formatting. Don't refactor things that aren't broken. Match existing style. When your changes create orphaned imports/variables/functions, remove them. Don't remove pre-existing dead code unless asked. Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution
Define success criteria before starting. Transform imperative tasks into verifiable goals. For multi-step tasks, state a brief plan with explicit verify steps: `[Step] → verify: [check]`. Loop until verified — weak criteria require constant clarification; strong criteria let you work independently.
