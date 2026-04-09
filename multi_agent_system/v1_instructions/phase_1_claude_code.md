# Phase 1 — Master Orchestrator + Scribe — Claude Code Instructions

## Objective
Implement the Master Orchestrator and Scribe Agent as functional agents
that can initialize a project, create the project folder, populate shared
state, and perform basic handoffs between each other.

## Prerequisites
- Phase 0 foundation must be complete
- All schema files must exist
- All template files must exist
- Directory structure must be in place

## What to build

### 1. Master Orchestrator Agent
**File:** `agents/master_orchestrator/agent.py` (or appropriate language)

Core capabilities to implement:
- Read and parse the shared state schema
- Initialize a new project from a clarified specification
- Generate a project_id
- Create the initial shared state object
- Send initialization directive to Scribe
- Accept handoff confirmation from Scribe
- Maintain phase tracking
- Log all decisions to shared state
- Implement the consultation request interface (stub for now)

Key functions:
```python
def initialize_project(clarified_spec: dict) -> str:
    """Create a new project. Returns project_id."""

def advance_phase(project_id: str, next_phase: str) -> bool:
    """Advance project to next phase if exit criteria are met."""

def delegate_task(project_id: str, agent_id: str, task: dict) -> Handoff:
    """Create a formal handoff to an agent."""

def accept_handoff(project_id: str, handoff: Handoff) -> bool:
    """Accept a completed handoff from an agent."""

def record_decision(project_id: str, decision: dict) -> str:
    """Record a decision in shared state. Returns decision_id."""

def request_consultation(project_id: str, question: str, 
                         context: dict) -> str:
    """Request input from consultant panel. Returns request_id."""
    # STUB: Will be implemented in Phase 8

def check_phase_exit_criteria(project_id: str) -> dict:
    """Check if current phase exit criteria are met."""

def escalate_to_human(project_id: str, reason: str, 
                      context: dict) -> None:
    """Escalate a decision to human."""