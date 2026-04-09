# Phase 4 — Project Manager + Execution — Claude Code Instructions

## Objective
Implement the Project Manager Agent and a basic execution coordination
layer so the system can plan work, track tasks, and manage delivery.

## Prerequisites
- Phases 0-3 must be complete
- Product Manager must be producing product plans
- HR must be answering capability queries

## What to build

### 1. Project Manager Agent
**File:** `agents/project_manager_agent/agent.py`

```python
class ProjectManagerAgent:
    def receive_product_plan(self, handoff: Handoff) -> bool:
        """Accept approved product plan from Master."""
    
    def decompose_into_tasks(self, product_plan: dict) -> list:
        """Break scope into discrete tasks."""
    
    def map_dependencies(self, tasks: list) -> dict:
        """Map task dependencies."""
    
    def define_milestones(self, tasks: list) -> list:
        """Group tasks into milestones."""
    
    def identify_resource_needs(self, tasks: list) -> list:
        """Identify capabilities needed per task."""
    
    def create_resource_requests(self, needs: list) -> list:
        """Create resource requests for HR."""
    
    def produce_execution_plan(self) -> dict:
        """Compile the full execution plan."""
    
    def update_task_status(self, task_id: str, 
                           status: str, notes: str) -> bool:
        """Update task tracking in shared state."""
    
    def check_blockers(self) -> list:
        """Identify blocked tasks."""
    
    def produce_progress_report(self) -> dict:
        """Generate progress report for current milestone."""