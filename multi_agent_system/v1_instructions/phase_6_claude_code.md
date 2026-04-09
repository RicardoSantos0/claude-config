# Phase 6 — Spawner (Draft-Only Mode) — Claude Code Instructions

## Objective
Implement the Spawning Agent in draft-only mode. It can design agent
packages but NEVER auto-deploy them.

## Prerequisites
- Phases 0-5 must be complete
- HR must be producing Capability Gap Certificates
- Evaluator must be functional (for verification)

## What to build

### 1. Spawner Agent
**File:** `agents/spawner_agent/agent.py`

```python
class SpawnerAgent:
    def receive_spawn_request(self, request: dict) -> bool:
        """Validate spawn request has approved gap certificate."""
    
    def evaluate_spawn_worthiness(self, request: dict) -> dict:
        """Decide: do_not_spawn, spawn_draft_only, spawn_and_verify."""
    
    def design_agent_package(self, request: dict) -> dict:
        """Create complete agent package."""
    
    def generate_agent_definition(self, request: dict) -> dict:
        """Generate agent definition YAML."""
    
    def generate_system_prompt(self, definition: dict) -> str:
        """Generate system prompt for new agent."""
    
    def generate_tool_contract(self, request: dict) -> dict:
        """Define tool access for new agent."""
    
    def generate_verification_plan(self, package: dict) -> dict:
        """Define how to test the new agent."""
    
    def submit_for_verification(self, package: dict) -> str:
        """Submit package to evaluator for testing."""