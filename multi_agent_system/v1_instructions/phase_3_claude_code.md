# Phase 3 — HR Agent + Capability Registry — Claude Code Instructions

## Objective
Implement the HR Agent and the capability registry so the system can
discover existing capabilities, evaluate matches, and produce
Capability Gap Certificates.

## Prerequisites
- Phases 0-1 must be complete
- Shared state manager and handoff engine must work

## What to build

### 1. HR Agent
**File:** `agents/hr_agent/agent.py`

```python
class HRAgent:
    def receive_capability_query(self, query: dict) -> dict:
        """Parse capability need from query."""
    
    def search_exact_matches(self, need: dict) -> list:
        """Search roster for exact capability matches."""
    
    def search_partial_matches(self, need: dict) -> list:
        """Search roster for parameterizable matches."""
    
    def score_match(self, need: dict, candidate: dict) -> dict:
        """Score a candidate against need. Returns match_record."""
    
    def evaluate_matches(self, matches: list) -> dict:
        """Determine best action: reuse, parameterize, or gap-certify."""
    
    def produce_capability_gap_certificate(self, need: dict,
        search_evidence: dict) -> dict:
        """Create a formal Capability Gap Certificate."""
    
    def submit_spawn_request(self, certificate: dict,
        project_id: str) -> dict:
        """Forward gap certificate to Master for spawn approval."""
    
    def update_roster(self, entry: dict) -> bool:
        """Add or update a roster entry with versioning."""
    
    def retire_agent(self, agent_id: str, reason: str) -> bool:
        """Mark an agent as retired (never delete)."""