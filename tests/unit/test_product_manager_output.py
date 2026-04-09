"""
Unit Tests — Product Manager Agent Output Validation
Tests that product plan structures are well-formed and meet quality rules.
These tests validate the schema and logic, not the agent's reasoning.
"""
import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone


# --- Product plan schema validator (standalone utility for testing) ---

REQUIRED_PLAN_KEYS = [
    "project_id", "created_at", "created_by", "version", "status",
    "product_goal", "requirements", "constraints_summary", "risks",
    "open_questions", "approval_status",
]

REQUIRED_REQUIREMENTS_KEYS = ["must_have", "should_have", "could_have", "wont_have"]

REQUIREMENT_KEYS = ["id", "description", "source", "acceptance_criteria"]

RISK_KEYS = ["id", "description", "severity", "mitigation"]

VALID_SEVERITIES = {"low", "medium", "high"}

VALID_APPROVAL_STATUSES = {
    "pending_master_review", "approved", "rejected", "revision_requested"
}


def validate_product_plan(plan: dict) -> list[str]:
    """
    Validate a product plan dict against the schema.
    Returns a list of validation errors (empty = valid).
    """
    errors = []

    # Top-level keys
    for key in REQUIRED_PLAN_KEYS:
        if key not in plan:
            errors.append(f"Missing required key: {key}")

    if errors:
        return errors  # Can't proceed without structure

    # requirements section
    req_section = plan.get("requirements", {})
    for key in REQUIRED_REQUIREMENTS_KEYS:
        if key not in req_section:
            errors.append(f"requirements missing key: {key}")

    # must_have requirements must have acceptance criteria
    must_haves = req_section.get("must_have", [])
    for i, req in enumerate(must_haves):
        for key in REQUIREMENT_KEYS:
            if key not in req:
                errors.append(f"must_have[{i}] missing key: {key}")
        if req.get("acceptance_criteria") is not None:
            if not isinstance(req["acceptance_criteria"], list):
                errors.append(f"must_have[{i}].acceptance_criteria must be a list")
            elif len(req["acceptance_criteria"]) == 0:
                errors.append(f"must_have[{i}] must have at least one acceptance criterion")

    # risks
    for i, risk in enumerate(plan.get("risks", [])):
        for key in RISK_KEYS:
            if key not in risk:
                errors.append(f"risks[{i}] missing key: {key}")
        if risk.get("severity") not in VALID_SEVERITIES:
            errors.append(
                f"risks[{i}].severity must be one of {VALID_SEVERITIES}, "
                f"got: {risk.get('severity')}"
            )

    # approval_status
    if plan.get("approval_status") not in VALID_APPROVAL_STATUSES:
        errors.append(
            f"approval_status must be one of {VALID_APPROVAL_STATUSES}, "
            f"got: {plan.get('approval_status')}"
        )

    # created_by
    if plan.get("created_by") != "product_manager_agent":
        errors.append(
            f"created_by must be 'product_manager_agent', got: {plan.get('created_by')}"
        )

    # version must be positive int
    if not isinstance(plan.get("version"), int) or plan.get("version") < 1:
        errors.append("version must be a positive integer")

    return errors


# --- Fixtures ---

@pytest.fixture
def minimal_valid_plan():
    """Smallest valid product plan."""
    return {
        "project_id": "proj-test-001",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "product_manager_agent",
        "version": 1,
        "status": "draft",
        "product_goal": "Build a sales reporting dashboard",
        "requirements": {
            "must_have": [
                {
                    "id": "req-001",
                    "description": "Dashboard displays pipeline metrics",
                    "source": "scope_inclusions",
                    "acceptance_criteria": [
                        "Given a logged-in sales user, when they open the dashboard, "
                        "then pipeline metrics are displayed within 3 seconds"
                    ],
                }
            ],
            "should_have": [],
            "could_have": [],
            "wont_have": [],
        },
        "constraints_summary": ["Must use existing AWS infrastructure"],
        "risks": [
            {
                "id": "risk-001",
                "description": "Salesforce API rate limits may affect data freshness",
                "severity": "medium",
                "mitigation": "Implement caching layer with 15-minute refresh interval",
            }
        ],
        "open_questions": [],
        "approval_status": "pending_master_review",
    }


@pytest.fixture
def plan_with_all_categories(minimal_valid_plan):
    """Plan with all MoSCoW categories populated."""
    plan = dict(minimal_valid_plan)
    plan["requirements"] = {
        "must_have": [
            {
                "id": "req-001",
                "description": "Pipeline metrics dashboard",
                "source": "scope_inclusions",
                "acceptance_criteria": ["Given ... when ... then pipeline visible"],
            }
        ],
        "should_have": [
            {
                "id": "req-002",
                "description": "Export to CSV",
                "source": "recommended by stakeholders",
                "acceptance_criteria": ["Given dashboard, when export clicked, then CSV downloads"],
            }
        ],
        "could_have": [
            {"id": "req-003", "description": "Dark mode", "source": "user feedback", "acceptance_criteria": None}
        ],
        "wont_have": [
            {"id": "req-004", "description": "Mobile app", "source": "scope_exclusions", "acceptance_criteria": None}
        ],
    }
    return plan


# --- Schema validation tests ---

class TestProductPlanSchema:

    def test_minimal_valid_plan_passes_validation(self, minimal_valid_plan):
        errors = validate_product_plan(minimal_valid_plan)
        assert errors == [], f"Unexpected validation errors: {errors}"

    def test_missing_top_level_key_fails(self, minimal_valid_plan):
        del minimal_valid_plan["product_goal"]
        errors = validate_product_plan(minimal_valid_plan)
        assert any("product_goal" in e for e in errors)

    def test_missing_requirements_section_fails(self, minimal_valid_plan):
        del minimal_valid_plan["requirements"]
        errors = validate_product_plan(minimal_valid_plan)
        assert len(errors) > 0

    def test_must_have_without_acceptance_criteria_fails(self, minimal_valid_plan):
        minimal_valid_plan["requirements"]["must_have"][0]["acceptance_criteria"] = []
        errors = validate_product_plan(minimal_valid_plan)
        assert any("acceptance criterion" in e for e in errors)

    def test_invalid_risk_severity_fails(self, minimal_valid_plan):
        minimal_valid_plan["risks"][0]["severity"] = "critical"
        errors = validate_product_plan(minimal_valid_plan)
        assert any("severity" in e for e in errors)

    def test_invalid_approval_status_fails(self, minimal_valid_plan):
        minimal_valid_plan["approval_status"] = "unknown"
        errors = validate_product_plan(minimal_valid_plan)
        assert any("approval_status" in e for e in errors)

    def test_wrong_created_by_fails(self, minimal_valid_plan):
        minimal_valid_plan["created_by"] = "master_orchestrator"
        errors = validate_product_plan(minimal_valid_plan)
        assert any("created_by" in e for e in errors)

    def test_invalid_version_fails(self, minimal_valid_plan):
        minimal_valid_plan["version"] = 0
        errors = validate_product_plan(minimal_valid_plan)
        assert any("version" in e for e in errors)


# --- MoSCoW category tests ---

class TestMoSCoWCategories:

    def test_all_four_categories_present(self, plan_with_all_categories):
        req = plan_with_all_categories["requirements"]
        assert "must_have" in req
        assert "should_have" in req
        assert "could_have" in req
        assert "wont_have" in req

    def test_empty_categories_are_valid(self, minimal_valid_plan):
        # should_have, could_have, wont_have are all empty
        errors = validate_product_plan(minimal_valid_plan)
        assert errors == []

    def test_must_have_requirements_have_source_field(self, minimal_valid_plan):
        for req in minimal_valid_plan["requirements"]["must_have"]:
            assert "source" in req, "must_have requirements must trace to specification"


# --- Risk tests ---

class TestRisks:

    def test_valid_severities_accepted(self, minimal_valid_plan):
        for severity in ["low", "medium", "high"]:
            minimal_valid_plan["risks"][0]["severity"] = severity
            errors = validate_product_plan(minimal_valid_plan)
            assert not any("severity" in e for e in errors), (
                f"Severity '{severity}' should be valid"
            )

    def test_empty_risks_list_is_valid(self, minimal_valid_plan):
        minimal_valid_plan["risks"] = []
        errors = validate_product_plan(minimal_valid_plan)
        assert errors == []

    def test_risk_must_have_mitigation_field(self, minimal_valid_plan):
        del minimal_valid_plan["risks"][0]["mitigation"]
        errors = validate_product_plan(minimal_valid_plan)
        assert any("mitigation" in e for e in errors)


# --- Acceptance criteria tests ---

class TestAcceptanceCriteria:

    def test_acceptance_criteria_is_list(self, minimal_valid_plan):
        criteria = minimal_valid_plan["requirements"]["must_have"][0]["acceptance_criteria"]
        assert isinstance(criteria, list)

    def test_multiple_criteria_per_requirement(self, minimal_valid_plan):
        minimal_valid_plan["requirements"]["must_have"][0]["acceptance_criteria"] = [
            "Given X when Y then Z",
            "Given A when B then C",
        ]
        errors = validate_product_plan(minimal_valid_plan)
        assert errors == []


# --- YAML serialization tests ---

class TestYAMLSerialization:

    def test_plan_round_trips_through_yaml(self, minimal_valid_plan, tmp_path):
        plan_path = tmp_path / "product_plan.yaml"
        with open(plan_path, "w", encoding="utf-8") as f:
            yaml.dump(minimal_valid_plan, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)
        with open(plan_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded["project_id"] == minimal_valid_plan["project_id"]
        assert loaded["product_goal"] == minimal_valid_plan["product_goal"]
        errors = validate_product_plan(loaded)
        assert errors == []
