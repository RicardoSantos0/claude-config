# Phase 5 — Performance Evaluator — Claude Code Instructions

## Objective
Implement the Performance Evaluation Agent so the system can measure
project outcomes and agent effectiveness with evidence-based metrics.

## Prerequisites
- Phases 0-4 must be complete
- At least one full project pipeline must be testable

## What to build

### 1. Evaluator Agent
**File:** `agents/evaluator_agent/agent.py`

```python
class EvaluatorAgent:
    def collect_project_data(self, project_id: str) -> dict:
        """Gather all project data for evaluation."""
    
    def evaluate_project(self, project_data: dict) -> dict:
        """Score project against all project metrics."""
    
    def evaluate_agent(self, agent_id: str, 
                       project_id: str) -> dict:
        """Score individual agent performance."""
    
    def detect_patterns(self, evaluations: list) -> dict:
        """Detect systemic patterns across evaluations."""
    
    def produce_evaluation_report(self, project_id: str) -> dict:
        """Generate comprehensive evaluation report."""
    
    def update_agent_performance(self, agent_id: str,
                                  scores: dict) -> bool:
        """Submit performance update to HR for roster."""