"""
Integration Test — Master Orchestrator + Scribe: Project Initialization
Tests that the Python infrastructure supports the full initialization cycle:
Master initializes state → Master creates handoff to Scribe →
Scribe accepts → Scribe creates project folder → Scribe returns handoff.
"""
import pytest
from pathlib import Path
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine


@pytest.fixture
def projects_root(tmp_path):
    return tmp_path / "projects_root"


@pytest.fixture
def project_id():
    return "proj-20260409-001"


@pytest.fixture
def sm(projects_root, project_id):
    manager = SharedStateManager(project_id, projects_root=projects_root)
    manager.initialize(request_id="req-20260409-001")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


def simulate_scribe_init(sm: SharedStateManager, handoff: dict,
                         engine: HandoffEngine, project_dir: Path) -> dict:
    """
    Simulate the Scribe's project initialization response.
    In production the Scribe agent (Claude Code) does this;
    here we test the infrastructure it relies on.
    """
    pid = sm.project_id

    # 1. Create project subdirectories
    for subdir in [
        "intake", "planning", "execution",
        "decisions", "capability/gap_certificates",
        "capability/spawn_requests", "capability/spawn_results",
        "evaluation/agent_evaluations",
        "improvement/improvement_proposals", "improvement/approved_updates",
        "consultation", "working_state",
    ]:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    # 2. Write original brief
    brief_content = handoff["payload"]["payload"].get("original_brief", "Test brief")
    (project_dir / "intake" / "original_brief.md").write_text(
        str(brief_content), encoding="utf-8"
    )

    # 3. Register artifact in shared state
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    sm.append("scribe_agent", "artifacts", "documents", {
        "artifact_id": "art-001",
        "name": "Project Folder",
        "type": "specification",
        "path": f"projects/{pid}/",
        "created_by": "scribe_agent",
        "created_at": now,
        "version": 1,
        "status": "approved",
    })

    # 4. Accept the handoff from Master
    engine.accept(sm, handoff["payload"]["handoff_id"])

    # 5. Create return handoff to Master
    return_handoff = engine.create(
        sm,
        from_agent="scribe_agent",
        to_agent="master_orchestrator",
        phase="intake",
        task_description="Confirm project folder initialization",
        payload={
            "summary": f"Project folder created at projects/{pid}/",
            "artifacts_produced": ["art-001"],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["artifacts.documents"],
        },
    )
    return return_handoff


class TestMasterScribeInitialization:

    def test_master_can_initialize_project(self, sm, project_id):
        """Master can initialize a project and produce valid initial state."""
        state = sm.load()
        assert state["core_identity"]["project_id"] == project_id
        assert state["core_identity"]["current_phase"] == "intake"
        assert state["core_identity"]["status"] == "active"

    def test_master_creates_handoff_to_scribe(self, sm, engine):
        """Master can create a formal handoff to the Scribe."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize project folder",
            payload={
                "summary": "New project started. Initialize project folder.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": ["Use standard folder structure"],
                "shared_state_fields_modified": [],
                "original_brief": "Build a test system",
            },
        )
        assert handoff["handoff_id"].startswith("ho-")
        assert handoff["from_agent"] == "master_orchestrator"
        assert handoff["to_agent"] == "scribe_agent"
        assert handoff["acceptance"]["status"] == "pending"

    def test_handoff_recorded_in_shared_state(self, sm, engine):
        """Handoffs must be recorded in workflow.handoff_history."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize",
            payload={
                "summary": "Test",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )
        history = sm.read("workflow.handoff_history")
        assert len(history) == 1
        assert history[0]["handoff_id"] == handoff["handoff_id"]

    def test_full_initialization_cycle(self, sm, engine, projects_root, project_id):
        """
        Full cycle: Master init → handoff to Scribe → Scribe accepts →
        Scribe creates folder → Scribe returns handoff → Master accepts.
        """
        project_dir = projects_root / project_id

        # 1. Master creates handoff to Scribe
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize project folder",
            payload={
                "summary": "Initialize project folder for proj-20260409-001",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "original_brief": "Build a governed delivery system",
            },
        )

        # 2. Scribe processes the handoff
        return_handoff = simulate_scribe_init(sm, {"payload": handoff}, engine, project_dir)

        # 3. Master accepts Scribe's return handoff
        engine.accept(sm, return_handoff["handoff_id"])

        # --- Verify outcomes ---

        # Project folder structure created
        assert (project_dir / "intake").is_dir()
        assert (project_dir / "decisions").is_dir()
        assert (project_dir / "intake" / "original_brief.md").is_file()

        # Artifact registered in shared state
        docs = sm.read("artifacts.documents")
        assert len(docs) >= 1
        assert any(d["artifact_id"] == "art-001" for d in docs)

        # All handoffs in history (accept updates status in-place, not a new entry)
        history = sm.read("workflow.handoff_history")
        assert len(history) == 2  # Master→Scribe, Scribe→Master

        # All handoffs accepted
        pending = engine.get_pending(sm)
        assert len(pending) == 0

    def test_master_can_advance_phase_after_initialization(self, sm, engine):
        """Master can advance from intake to specification after init cycle."""
        result = sm.write("master_orchestrator", "core_identity",
                          "current_phase", "specification")
        assert result.success

        # Snapshot at phase boundary
        snap = sm.snapshot("specification")
        assert snap.exists()

        # Record completed phase
        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "intake",
            "started_at": "2026-04-09T00:00:00Z",
            "completed_at": "2026-04-09T01:00:00Z",
            "outcome": "Project folder initialized by Scribe",
            "artifacts_produced": ["art-001"],
        })

        phases = sm.read("workflow.completed_phases")
        assert len(phases) == 1
        assert phases[0]["phase"] == "intake"

    def test_governance_preserved_through_initialization(self, sm, engine):
        """No governance violations should occur during normal initialization."""
        # Normal initialization cycle should produce zero violations
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize",
            payload={
                "summary": "Test",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )
        engine.accept(sm, handoff["handoff_id"])

        # No violations from normal operations
        for agent in ["master_orchestrator", "scribe_agent"]:
            assert sm.get_violation_count(agent) == 0
