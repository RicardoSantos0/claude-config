"""
Generic execution-plan seeder.

Usage:
    python mas/tools/seed_plan.py <path/to/specs/plan.yaml>

Reads a project-neutral plan spec and registers milestones + tasks through
the TaskBoard engine, then advances the workflow phase.

Spec field names are human-friendly; this loader maps them to engine names:
  exit_criteria  -> completion_criteria  (milestone)
  owner          -> assigned_to          (task)
  depends_on     -> dependencies         (task)

# --- FUTURE INTENT (Option B) ---
# This script is a manual shim. The correct long-term solution is to have
# project_manager_agent produce these artifacts autonomously from a project
# brief via the orchestration loop, making this file unnecessary. Once the
# intake → planning → capability_discovery loop is fully wired end-to-end,
# delete this tool and let the agent own the planning phase output.
# --------------------------------
"""
import sys
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.engine.task_board import TaskBoard
from core.engine.shared_state_manager import SharedStateManager


def load_spec(spec_path: Path) -> dict:
    with spec_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def seed(spec_path: Path) -> None:
    spec = load_spec(spec_path)

    pid = spec["project_id"]
    next_phase = spec["next_phase"]
    plan_path = spec["execution_plan_path"]
    milestones = spec["milestones"]

    board = TaskBoard(pid)
    sm = SharedStateManager(pid)

    n_tasks = 0
    for ms in milestones:
        board.create_milestone({
            "milestone_id": ms["milestone_id"],
            "name": ms["name"],
            "completion_criteria": ms["exit_criteria"],  # spec: exit_criteria
            "description": f"Sprint {ms.get('sprint', '?')}",
        })

        for task in ms.get("tasks", []):
            board.create_task({
                "task_id": task["task_id"],
                "description": f"{task['name']}: {task['description']}",
                "milestone": ms["milestone_id"],
                "assigned_to": task.get("owner"),           # spec: owner
                "dependencies": task.get("depends_on", []), # spec: depends_on
                "notes": task.get("parallel_group", ""),
            })
            n_tasks += 1

    sm.write("project_manager_agent", "execution", "execution_plan_path", plan_path)
    sm.snapshot("planning")
    sm.write("master_orchestrator", "core_identity", "current_phase", next_phase)
    sm.system_append("workflow", "completed_phases", "planning")

    print(f"[seed_plan] {pid}: {len(milestones)} milestones, {n_tasks} tasks -> {next_phase}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed execution plan from a YAML spec.")
    parser.add_argument("spec", type=Path, help="Path to plan.yaml spec file")
    args = parser.parse_args()

    if not args.spec.exists():
        print(f"ERROR: spec not found: {args.spec}", file=sys.stderr)
        sys.exit(1)

    seed(args.spec)


if __name__ == "__main__":
    main()
