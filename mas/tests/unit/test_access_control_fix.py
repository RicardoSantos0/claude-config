"""
Tests for access_control.py fixes — proj-20260415-001-db-semantic-and-acl-fix

Verifies that the four recurring violation patterns are now authorized:
  AC1  master_orchestrator → artifacts.deliverables
  AC2  master_orchestrator → decisions.decision_log
  AC3  system              → workflow.completed_phases
  AC4  inquirer_agent      → project_definition.project_goal (and related fields)
"""

import pytest
from core.engine.access_control import is_authorized


class TestMasterArtifactsWrite:
    """AC1: master_orchestrator may write artifacts fields."""

    def test_master_can_write_artifacts_deliverables(self):
        assert is_authorized("master_orchestrator", "artifacts.deliverables") is True

    def test_master_can_write_artifacts_documents(self):
        assert is_authorized("master_orchestrator", "artifacts.documents") is True

    def test_master_can_write_artifacts_change_log(self):
        assert is_authorized("master_orchestrator", "artifacts.change_log") is True

    def test_scribe_still_authorized_artifacts(self):
        """Existing scribe_agent permission must not be removed."""
        assert is_authorized("scribe_agent", "artifacts.deliverables") is True

    def test_random_agent_cannot_write_artifacts(self):
        assert is_authorized("inquirer_agent", "artifacts.deliverables") is False


class TestMasterDecisionLog:
    """AC2: master_orchestrator may write decisions.decision_log."""

    def test_master_can_write_decision_log(self):
        assert is_authorized("master_orchestrator", "decisions.decision_log") is True

    def test_scribe_still_authorized_decision_log(self):
        assert is_authorized("scribe_agent", "decisions.decision_log") is True

    def test_hr_cannot_write_decision_log(self):
        assert is_authorized("hr_agent", "decisions.decision_log") is False


class TestSystemCompletedPhases:
    """AC3: system sentinel may write workflow.completed_phases."""

    def test_system_can_write_completed_phases(self):
        assert is_authorized("system", "workflow.completed_phases") is True

    def test_master_still_authorized_completed_phases(self):
        assert is_authorized("master_orchestrator", "workflow.completed_phases") is True

    def test_scribe_cannot_write_completed_phases(self):
        assert is_authorized("scribe_agent", "workflow.completed_phases") is False


class TestInquirerProjectDefinition:
    """AC4: inquirer_agent may write project_definition fields it co-owns."""

    def test_inquirer_can_write_project_goal(self):
        assert is_authorized("inquirer_agent", "project_definition.project_goal") is True

    def test_inquirer_can_write_problem_statement(self):
        assert is_authorized("inquirer_agent", "project_definition.problem_statement") is True

    def test_inquirer_can_write_scope(self):
        assert is_authorized("inquirer_agent", "project_definition.scope") is True

    def test_inquirer_can_write_constraints(self):
        assert is_authorized("inquirer_agent", "project_definition.constraints") is True

    def test_inquirer_can_write_success_criteria(self):
        assert is_authorized("inquirer_agent", "project_definition.success_criteria") is True

    def test_inquirer_can_write_acceptance_criteria(self):
        assert is_authorized("inquirer_agent", "project_definition.acceptance_criteria") is True

    def test_pm_still_authorized_project_goal(self):
        """product_manager_agent co-ownership must be preserved."""
        assert is_authorized("product_manager_agent", "project_definition.project_goal") is True

    def test_pm_still_authorized_problem_statement(self):
        assert is_authorized("product_manager_agent", "project_definition.problem_statement") is True

    def test_evaluator_cannot_write_project_goal(self):
        assert is_authorized("evaluator_agent", "project_definition.project_goal") is False


class TestMasterOrchestratorProjectDefinition:
    """AC5 (proj-007): master_orchestrator may write project_definition fields.

    Master is the offline coordinator — it must be able to set brief, spec, and
    criteria when inquirer/PM agents haven't run (dry-run / offline projects).
    """

    def test_master_can_write_original_brief(self):
        assert is_authorized("master_orchestrator", "project_definition.original_brief") is True

    def test_master_can_write_brief_summary(self):
        assert is_authorized("master_orchestrator", "project_definition.brief_summary") is True

    def test_master_can_write_clarified_specification(self):
        assert is_authorized("master_orchestrator", "project_definition.clarified_specification") is True

    def test_master_can_write_project_goal(self):
        assert is_authorized("master_orchestrator", "project_definition.project_goal") is True

    def test_master_can_write_problem_statement(self):
        assert is_authorized("master_orchestrator", "project_definition.problem_statement") is True

    def test_master_can_write_scope(self):
        assert is_authorized("master_orchestrator", "project_definition.scope") is True

    def test_master_can_write_constraints(self):
        assert is_authorized("master_orchestrator", "project_definition.constraints") is True

    def test_master_can_write_success_criteria(self):
        assert is_authorized("master_orchestrator", "project_definition.success_criteria") is True

    def test_master_can_write_acceptance_criteria(self):
        assert is_authorized("master_orchestrator", "project_definition.acceptance_criteria") is True

    def test_master_can_write_expected_outputs(self):
        assert is_authorized("master_orchestrator", "project_definition.expected_outputs") is True

    def test_inquirer_still_authorized_original_brief(self):
        """Existing inquirer_agent ownership must not be removed."""
        assert is_authorized("inquirer_agent", "project_definition.original_brief") is True

    def test_pm_still_authorized_success_criteria(self):
        """product_manager_agent co-ownership must be preserved."""
        assert is_authorized("product_manager_agent", "project_definition.success_criteria") is True

    def test_evaluator_still_cannot_write_original_brief(self):
        """Adding master must not open the field to unrelated agents."""
        assert is_authorized("evaluator_agent", "project_definition.original_brief") is False
