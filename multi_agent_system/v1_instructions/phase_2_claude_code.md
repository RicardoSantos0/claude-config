# Phase 2 — Inquirer + Product Manager — Claude Code Instructions

## Objective
Implement the Inquirer Agent and Product Manager Agent so the system
can intake raw project briefs and produce defined product plans.

## Prerequisites
- Phase 0 and Phase 1 must be complete
- Master Orchestrator and Scribe must be functional
- Handoff engine must be working

## What to build

### 1. Inquirer Agent
**File:** `agents/inquirer_agent/agent.py`

```python
class InquirerAgent:
    def receive_brief(self, raw_brief: str) -> dict:
        """Parse and store the raw project brief."""
    
    def analyze_completeness(self, brief: dict) -> dict:
        """Check brief against intake checklist. 
        Returns: {complete: bool, missing: list, ambiguous: list}"""
    
    def generate_questions(self, analysis: dict, round: int) -> list:
        """Generate targeted clarification questions.
        Max 7 questions per round. Max 3 rounds total."""
    
    def process_answers(self, questions: list, answers: list) -> dict:
        """Integrate answers into the specification."""
    
    def produce_specification(self) -> dict:
        """Generate the final clarified specification."""
    
    def create_handoff(self, project_id: str) -> Handoff:
        """Create formal handoff to Master with clarified spec."""