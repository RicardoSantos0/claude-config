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
uv run pytest mas/tests/            # Run the full test suite (590 tests)
```

## Agent Network

The MAS has 14 agents in 3 tiers:

| Tier | Agents |
|------|--------|
| T0 Core | `master_orchestrator`, `scribe_agent` |
| T1 Established | `inquirer_agent`, `product_manager_agent`, `hr_agent`, `project_manager_agent`, `evaluator_agent`, `trainer_agent` |
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
