# Phase 8 — Master Consultant Panel — Claude Code Instructions

## Objective
Implement the Consultant Panel as an advisory subsystem that the Master
can invoke for multi-perspective input on significant decisions.

## Important Design Note
Phase 8 can actually be built in parallel with Phases 2-7 since it
only depends on Phase 1 (Master Orchestrator). Consider starting
it alongside Phase 3 or 4.

## Prerequisites
- Phase 1 must be complete (Master Orchestrator must exist)
- Consultation request/response stubs in Master must exist

## What to build

### 1. Consultant Panel Manager
**File:** `agents/consultant_panel/panel_manager.py`

```python
class ConsultantPanelManager:
    def __init__(self):
        self.consultants = {
            "risk_advisor": RiskAdvisor(),
            "quality_advisor": QualityAdvisor(),
            "devils_advocate": DevilsAdvocate(),
            "domain_expert": DomainExpert(),
            "efficiency_advisor": EfficiencyAdvisor(),
        }
    
    def should_consult(self, decision_type: str, 
                       risk_level: str) -> bool:
        """Determine if consultation is mandatory/recommended."""
    
    def create_consultation_request(self, question: str,
        context: dict, decision_type: str) -> dict:
        """Create structured consultation request."""
    
    def distribute_request(self, request: dict,
        consultants: list = None) -> dict:
        """Send request to each consultant independently."""
    
    def collect_responses(self, request_id: str) -> list:
        """Collect all consultant responses."""
    
    def present_to_master(self, responses: list) -> dict:
        """Present all responses to Master for synthesis."""