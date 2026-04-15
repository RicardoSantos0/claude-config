"""
Unit Tests — Spawn Policy Engine
Tests all spawn governance rules in isolation.
No live LLM calls. No disk writes beyond tmp_path.
"""
import pytest
import yaml
from pathlib import Path
from core.engine.spawn_policy import (
    SpawnPolicyEngine,
    LimitCheckResult,
    CertificateCheckResult,
    RecursiveSpawnCheckResult,
    WorthinessResult,
    ValidationResult,
    build_agent_package,
    record_spawn,
    _load_history,
    MAX_SPAWNS_PER_PROJECT,
    MAX_SPAWNS_PER_PHASE,
    DENY,
    DRAFT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return SpawnPolicyEngine()


@pytest.fixture
def empty_registry():
    return {"registry": {"agents": []}}


@pytest.fixture
def registry_with_spawned():
    """Registry where 'analytics_agent' was itself spawned."""
    return {
        "registry": {
            "agents": [
                {
                    "agent_id": "analytics_agent",
                    "trust_tier": "T3_provisional",
                    "status": "active",
                    "spawn_origin": "spawner_agent",
                },
                {
                    "agent_id": "hr_agent",
                    "trust_tier": "T1_established",
                    "status": "active",
                    "spawn_origin": None,
                },
            ]
        }
    }


@pytest.fixture
def full_registry():
    """Registry with core agents (no spawn_origin)."""
    agents = [
        {"agent_id": "master_orchestrator", "trust_tier": "T0_core", "status": "active", "spawn_origin": None},
        {"agent_id": "hr_agent", "trust_tier": "T1_established", "status": "active", "spawn_origin": None},
        {"agent_id": "project_manager_agent", "trust_tier": "T1_established", "status": "active", "spawn_origin": None},
    ]
    return {"registry": {"agents": agents}}


@pytest.fixture
def valid_spawn_request():
    return {
        "request_id": "spawn-req-001",
        "project_id": "proj-test-001",
        "gap_certificate_id": "gap-cert-001",
        "requested_by": "hr_agent",
        "master_approval": True,
        "agent_purpose": "Generate weekly sales reports from Salesforce data",
        "required_inputs": ["salesforce_data.json", "report_period"],
        "required_outputs": ["weekly_report.yaml", "summary.md"],
        "allowed_tools": ["read", "search"],
        "scope": "project_scoped",
        "base_template": "analysis_agent",
        "worthiness": {
            "bounded": True,
            "recurring": True,
            "verifiable": True,
            "no_existing_match": True,
        },
    }


@pytest.fixture
def approved_gap_cert():
    return {
        "certificate_id": "gap-cert-001",
        "project_id": "proj-test-001",
        "status": "approved",
        "approval_status": "master_approved",
        "certified_by": "hr_agent",
        "required_capabilities": ["reporting", "salesforce-integration"],
        "best_match_score": 45.0,
    }


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "projects" / "proj-test-001"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# Tests: check_limits
# ---------------------------------------------------------------------------

class TestCheckLimits:

    def test_empty_history_passes(self, engine):
        result = engine.check_limits("execution", {"spawns": []})
        assert result.passed
        assert result.project_spawn_count == 0
        assert result.phase_spawn_count == 0

    def test_within_limits_passes(self, engine):
        history = {"spawns": [
            {"phase": "intake", "agent_id": "agent_a"},
            {"phase": "planning", "agent_id": "agent_b"},
        ]}
        result = engine.check_limits("execution", history)
        assert result.passed
        assert result.project_spawn_count == 2

    def test_project_limit_exceeded(self, engine):
        spawns = [{"phase": f"phase{i}", "agent_id": f"agent_{i}"} for i in range(MAX_SPAWNS_PER_PROJECT)]
        result = engine.check_limits("new_phase", {"spawns": spawns})
        assert not result.passed
        assert not result.within_project_limit
        assert any(v.code == "LIMIT_PROJECT_EXCEEDED" for v in result.violations)

    def test_phase_limit_exceeded(self, engine):
        history = {"spawns": [
            {"phase": "execution", "agent_id": "agent_a"},
        ]}
        result = engine.check_limits("execution", history)
        assert not result.passed
        assert not result.within_phase_limit
        assert any(v.code == "LIMIT_PHASE_EXCEEDED" for v in result.violations)

    def test_different_phases_independent(self, engine):
        history = {"spawns": [
            {"phase": "planning", "agent_id": "agent_a"},
        ]}
        result = engine.check_limits("execution", history)
        assert result.passed
        assert result.phase_spawn_count == 0

    def test_project_limit_is_three(self):
        assert MAX_SPAWNS_PER_PROJECT == 3

    def test_phase_limit_is_one(self):
        assert MAX_SPAWNS_PER_PHASE == 1


# ---------------------------------------------------------------------------
# Tests: check_certificate
# ---------------------------------------------------------------------------

class TestCheckCertificate:

    def test_valid_cert_and_approval_passes(self, engine, valid_spawn_request, approved_gap_cert):
        result = engine.check_certificate(valid_spawn_request, approved_gap_cert)
        assert result.passed
        assert result.certificate_present
        assert result.master_approved

    def test_missing_cert_id_fails(self, engine, approved_gap_cert):
        request = {"gap_certificate_id": "", "master_approval": True}
        result = engine.check_certificate(request, approved_gap_cert)
        assert not result.passed
        assert not result.certificate_present
        assert any(v.code == "CERT_MISSING" for v in result.violations)

    def test_no_gap_cert_object_fails(self, engine, valid_spawn_request):
        result = engine.check_certificate(valid_spawn_request, gap_cert=None)
        assert not result.passed
        assert any(v.code == "CERT_MISSING" for v in result.violations)

    def test_master_approval_false_fails(self, engine, approved_gap_cert):
        request = {
            "gap_certificate_id": "gap-cert-001",
            "master_approval": False,
        }
        result = engine.check_certificate(request, approved_gap_cert)
        assert not result.passed
        assert any(v.code == "CERT_NOT_APPROVED" for v in result.violations)

    def test_cert_status_not_approved_fails(self, engine, valid_spawn_request):
        cert = {"certificate_id": "gap-cert-001", "status": "pending"}
        result = engine.check_certificate(valid_spawn_request, cert)
        assert not result.passed

    def test_cert_id_stored_in_result(self, engine, valid_spawn_request, approved_gap_cert):
        result = engine.check_certificate(valid_spawn_request, approved_gap_cert)
        assert result.certificate_id == "gap-cert-001"


# ---------------------------------------------------------------------------
# Tests: check_recursive_spawn
# ---------------------------------------------------------------------------

class TestCheckRecursiveSpawn:

    def test_core_agent_requesting_passes(self, engine, full_registry):
        result = engine.check_recursive_spawn("hr_agent", full_registry)
        assert result.passed
        assert not result.requester_is_spawned

    def test_spawned_agent_requesting_blocked(self, engine, registry_with_spawned):
        result = engine.check_recursive_spawn("analytics_agent", registry_with_spawned)
        assert not result.passed
        assert result.requester_is_spawned
        assert any(v.code == "RECURSIVE_SPAWN_BLOCKED" for v in result.violations)

    def test_spawner_self_spawn_blocked(self, engine, empty_registry):
        result = engine.check_recursive_spawn("spawner_agent", empty_registry)
        assert not result.passed
        assert any(v.code == "RECURSIVE_SELF_SPAWN" for v in result.violations)

    def test_unknown_agent_treated_as_safe(self, engine, empty_registry):
        result = engine.check_recursive_spawn("unknown_agent_xyz", empty_registry)
        assert result.passed

    def test_non_spawned_agent_no_violations(self, engine, full_registry):
        result = engine.check_recursive_spawn("master_orchestrator", full_registry)
        assert result.passed
        assert len(result.violations) == 0


# ---------------------------------------------------------------------------
# Tests: check_worthiness
# ---------------------------------------------------------------------------

class TestCheckWorthiness:

    def test_all_explicit_flags_passes(self, engine, valid_spawn_request, approved_gap_cert):
        result = engine.check_worthiness(valid_spawn_request, approved_gap_cert)
        assert result.passed
        assert result.bounded
        assert result.recurring
        assert result.verifiable
        assert result.no_existing_match

    def test_missing_recurring_fails(self, engine, approved_gap_cert):
        request = {
            "agent_purpose": "Generate reports",
            "required_inputs": ["data.json"],
            "required_outputs": ["report.yaml"],
            "allowed_tools": ["read"],
            "scope": "project_scoped",
            "worthiness": {
                "bounded": True,
                "recurring": False,  # missing
                "verifiable": True,
                "no_existing_match": True,
            },
        }
        result = engine.check_worthiness(request, approved_gap_cert)
        assert not result.passed
        assert not result.recurring
        assert any(v.code == "WORTHINESS_RECURRING_FAILED" for v in result.violations)

    def test_no_existing_match_inferred_from_approved_cert(self, engine, approved_gap_cert):
        request = {
            "agent_purpose": "Do something",
            "required_inputs": ["input"],
            "required_outputs": ["output"],
            "allowed_tools": ["read"],
            "scope": "project_scoped",
            "worthiness": {
                "bounded": True,
                "recurring": True,
                "verifiable": True,
                "no_existing_match": False,  # not set explicitly
            },
        }
        result = engine.check_worthiness(request, approved_gap_cert)
        assert result.no_existing_match  # inferred from approved cert

    def test_bounded_inferred_from_inputs_outputs(self, engine):
        request = {
            "required_inputs": ["input.json"],
            "required_outputs": ["output.yaml"],
            "allowed_tools": ["read"],
            "scope": "project_scoped",
            "worthiness": {
                "bounded": False,
                "recurring": True,
                "verifiable": True,
                "no_existing_match": True,
            },
        }
        result = engine.check_worthiness(request, gap_cert=None)
        assert result.bounded  # inferred from non-empty inputs+outputs

    def test_no_worthiness_block_all_fail(self, engine):
        request = {}
        result = engine.check_worthiness(request, gap_cert=None)
        assert not result.passed
        assert len(result.violations) == 4


# ---------------------------------------------------------------------------
# Tests: validate (full)
# ---------------------------------------------------------------------------

class TestValidate:

    def test_all_checks_pass_returns_draft(
        self, engine, valid_spawn_request, approved_gap_cert, full_registry, project_dir
    ):
        result = engine.validate(
            valid_spawn_request, full_registry, project_dir,
            gap_cert=approved_gap_cert, phase="execution"
        )
        assert result.decision == DRAFT
        assert result.approved
        assert len(result.all_violations) == 0

    def test_missing_cert_returns_deny(self, engine, full_registry, project_dir):
        request = {
            "request_id": "req-001",
            "gap_certificate_id": "",
            "requested_by": "hr_agent",
            "master_approval": False,
        }
        result = engine.validate(request, full_registry, project_dir, gap_cert=None)
        assert result.decision == DENY
        assert not result.approved

    def test_project_limit_reached_returns_deny(
        self, engine, valid_spawn_request, approved_gap_cert, full_registry, project_dir
    ):
        # Saturate project history
        for i in range(MAX_SPAWNS_PER_PROJECT):
            record_spawn(project_dir, f"req-{i}", f"agent_{i}", f"phase_{i}", DRAFT)

        result = engine.validate(
            valid_spawn_request, full_registry, project_dir,
            gap_cert=approved_gap_cert, phase="new_phase"
        )
        assert result.decision == DENY
        assert any(v.code == "LIMIT_PROJECT_EXCEEDED" for v in result.all_violations)

    def test_phase_limit_reached_returns_deny(
        self, engine, valid_spawn_request, approved_gap_cert, full_registry, project_dir
    ):
        record_spawn(project_dir, "req-001", "agent_a", "execution", DRAFT)

        result = engine.validate(
            valid_spawn_request, full_registry, project_dir,
            gap_cert=approved_gap_cert, phase="execution"
        )
        assert result.decision == DENY
        assert any(v.code == "LIMIT_PHASE_EXCEEDED" for v in result.all_violations)

    def test_recursive_spawn_returns_deny(
        self, engine, valid_spawn_request, approved_gap_cert, registry_with_spawned, project_dir
    ):
        # analytics_agent was itself spawned
        request = dict(valid_spawn_request, requested_by="analytics_agent")
        result = engine.validate(
            request, registry_with_spawned, project_dir,
            gap_cert=approved_gap_cert, phase="execution"
        )
        assert result.decision == DENY
        assert any(v.code == "RECURSIVE_SPAWN_BLOCKED" for v in result.all_violations)

    def test_worthiness_failure_returns_deny(
        self, engine, approved_gap_cert, full_registry, project_dir
    ):
        request = {
            "request_id": "req-001",
            "gap_certificate_id": "gap-cert-001",
            "requested_by": "hr_agent",
            "master_approval": True,
            "agent_purpose": "Do something",
            "required_inputs": ["data"],
            "required_outputs": ["result"],
            "allowed_tools": ["read"],
            "scope": "project_scoped",
            # No worthiness block → all fail
        }
        result = engine.validate(
            request, full_registry, project_dir,
            gap_cert=approved_gap_cert, phase="execution"
        )
        assert result.decision == DENY

    def test_decision_uses_phase_from_request_if_not_passed(
        self, engine, valid_spawn_request, approved_gap_cert, full_registry, project_dir
    ):
        request = dict(valid_spawn_request, phase="planning")
        # No phase kwarg passed — should fall back to request phase
        result = engine.validate(request, full_registry, project_dir, gap_cert=approved_gap_cert)
        assert result.decision == DRAFT


# ---------------------------------------------------------------------------
# Tests: record_spawn + history
# ---------------------------------------------------------------------------

class TestSpawnHistory:

    def test_record_spawn_creates_file(self, project_dir):
        record = record_spawn(project_dir, "req-001", "test_agent", "execution", DRAFT)
        history = _load_history(project_dir)
        assert len(history["spawns"]) == 1
        assert history["spawns"][0]["agent_id"] == "test_agent"

    def test_record_spawn_accumulates(self, project_dir):
        record_spawn(project_dir, "req-001", "agent_a", "execution", DRAFT)
        record_spawn(project_dir, "req-002", "agent_b", "planning", DRAFT)
        history = _load_history(project_dir)
        assert len(history["spawns"]) == 2

    def test_record_spawn_returns_record_with_id(self, project_dir):
        record = record_spawn(project_dir, "req-001", "agent_x", "execution", DRAFT)
        assert "spawn_id" in record
        assert record["spawn_id"].startswith("spawn-")

    def test_load_history_missing_file_returns_empty(self, tmp_path):
        d = tmp_path / "projects" / "proj-xyz"
        d.mkdir(parents=True)
        history = _load_history(d)
        assert history == {"spawns": []}


# ---------------------------------------------------------------------------
# Tests: build_agent_package
# ---------------------------------------------------------------------------

class TestBuildAgentPackage:

    def test_package_dir_created(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        assert pkg_dir.exists()
        assert pkg_dir.is_dir()

    def test_all_package_files_created(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        expected = [
            "manifest.yaml",
            "agent_definition.md",
            "tool_contract.yaml",
            "verification_plan.yaml",
            "behavioral_contract.yaml",
        ]
        for fname in expected:
            assert (pkg_dir / fname).exists(), f"Missing: {fname}"

    def test_manifest_has_draft_status(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        with open(pkg_dir / "manifest.yaml") as f:
            manifest = yaml.safe_load(f)
        assert manifest["status"] == "draft"
        assert manifest["trust_tier"] == "T3_provisional"

    def test_manifest_contains_spawn_request_id(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        with open(pkg_dir / "manifest.yaml") as f:
            manifest = yaml.safe_load(f)
        assert manifest["spawn_request_id"] == "spawn-req-001"
        assert manifest["gap_certificate_id"] == "gap-cert-001"

    def test_tool_contract_includes_forbidden_tools(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        with open(pkg_dir / "tool_contract.yaml") as f:
            tc = yaml.safe_load(f)
        assert "spawn" in tc["forbidden_tools"]
        assert "retire" in tc["forbidden_tools"]

    def test_tool_contract_allowed_tools_match_request(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        with open(pkg_dir / "tool_contract.yaml") as f:
            tc = yaml.safe_load(f)
        assert set(tc["allowed_tools"]) == set(valid_spawn_request["allowed_tools"])

    def test_verification_plan_has_steps(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        with open(pkg_dir / "verification_plan.yaml") as f:
            vp = yaml.safe_load(f)
        assert len(vp["verification_steps"]) >= 3
        assert vp["status"] == "pending"
        assert vp["verifier"] == "evaluator_agent"

    def test_agent_definition_contains_draft_warning(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        content = (pkg_dir / "agent_definition.md").read_text()
        assert "DRAFT" in content
        assert "pending verification" in content.lower() or "draft" in content.lower()

    def test_behavioral_contract_lists_forbidden_actions(self, valid_spawn_request, project_dir):
        pkg_dir = build_agent_package(valid_spawn_request, project_dir)
        with open(pkg_dir / "behavioral_contract.yaml") as f:
            bc = yaml.safe_load(f)
        cannot_do = bc["authority"]["cannot_do"]
        assert any("spawn" in s for s in cannot_do)
        assert any("approve" in s for s in cannot_do)

    def test_agent_id_derived_from_purpose(self, project_dir):
        request = {
            "request_id": "req-test",
            "gap_certificate_id": "cert-test",
            "agent_purpose": "Generate weekly sales reports",
            "required_inputs": ["data"],
            "required_outputs": ["report"],
            "allowed_tools": ["read"],
            "scope": "project_scoped",
            "base_template": "analysis_agent",
        }
        pkg_dir = build_agent_package(request, project_dir)
        # agent_id should be derived from first 4 words of purpose
        assert "generate" in pkg_dir.name or "agent" in pkg_dir.name

    def test_fallback_template_used_when_base_template_null(self, project_dir):
        request = {
            "request_id": "req-test",
            "gap_certificate_id": "cert-test",
            "agent_purpose": "Format output files",
            "required_inputs": ["raw.txt"],
            "required_outputs": ["formatted.yaml"],
            "allowed_tools": ["read"],
            "scope": "project_scoped",
            "base_template": None,
        }
        pkg_dir = build_agent_package(request, project_dir)
        assert pkg_dir.exists()
        with open(pkg_dir / "manifest.yaml") as f:
            manifest = yaml.safe_load(f)
        assert manifest["status"] == "draft"
