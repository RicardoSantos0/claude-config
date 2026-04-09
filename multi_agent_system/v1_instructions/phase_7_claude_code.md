# Phase 7 — Trainer (L0 Advisory) — Claude Code Instructions

## Objective
Implement the Trainer Agent in L0 advisory mode. It can analyze
evaluations and propose improvements but NEVER apply them.

## Prerequisites
- Phases 0-6 must be complete
- Evaluator must be producing evaluation reports

## What to build

### 1. Trainer Agent
**File:** `agents/trainer_agent/agent.py`

```python
class TrainerAgent:
    def __init__(self):
        self.authority_level = "L0_advisory"
    
    def receive_evaluation_reports(self, reports: list) -> bool:
        """Ingest evaluation reports for analysis."""
    
    def analyze_findings(self, reports: list) -> dict:
        """Identify improvement opportunities from findings."""
    
    def create_improvement_proposal(self, finding: dict,
                                     target: dict) -> dict:
        """Create a structured improvement proposal."""
    
    def design_rollback_plan(self, proposal: dict) -> dict:
        """Create rollback plan for a proposal."""
    
    def submit_proposal(self, proposal: dict) -> str:
        """Submit proposal to Master. Returns proposal_id."""
    
    def check_authority(self, action: str) -> bool:
        """Check if action is allowed at current authority level."""
    
    # These are STUBS for future L1/L2:
    def apply_change(self, proposal: dict) -> bool:
        """BLOCKED at L0. Raises AuthorityError."""
        raise AuthorityError("L0 advisory cannot apply changes")