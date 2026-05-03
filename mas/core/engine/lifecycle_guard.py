"""
MAS Lifecycle Guard

Evaluates lifecycle invariants from mas/policies/lifecycle_invariants.yaml
before phase transitions, project close, and spawn requests.
Blocks actions that violate hard invariants; warns on soft ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not locate repo root (pyproject.toml not found)")


@dataclass
class GuardResult:
    passed: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return not self.passed


class LifecycleGuard:
    """Checks lifecycle invariants and artifact contracts before key MAS actions."""

    _INVARIANTS_REL = Path("mas") / "policies" / "lifecycle_invariants.yaml"
    _CONTRACTS_REL = Path("mas") / "policies" / "artifact_contracts.yaml"

    def __init__(self) -> None:
        self._repo_root = _find_repo_root()
        self._invariants = self._load_invariants()
        self._contracts = self._load_contracts()

    def _load_invariants(self) -> list[dict]:
        path = self._repo_root / self._INVARIANTS_REL
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("invariants", [])

    def _load_contracts(self) -> dict:
        path = self._repo_root / self._CONTRACTS_REL
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("phases", {})

    def check_phase_artifacts(self, phase: str, project_dir: Path) -> GuardResult:
        """Check that required artifacts exist for the given phase."""
        contract = self._contracts.get(phase, {})
        required = contract.get("required", [])
        violations = []
        for artifact in required:
            if not (project_dir / artifact).exists():
                violations.append({
                    "invariant": f"artifact-contract:{phase}",
                    "missing": artifact,
                    "severity": "block",
                })
        return GuardResult(passed=len(violations) == 0, violations=violations)

    def check_close(self, project_dir: Path, shared_state: dict) -> GuardResult:
        """Run close-specific invariants against current state."""
        violations = []
        warnings = []

        # no-close-with-open-handoffs
        pending = shared_state.get("workflow", {}).get("pending_assignments", [])
        if pending:
            violations.append({
                "invariant": "no-close-with-open-handoffs",
                "detail": f"{len(pending)} pending assignment(s)",
                "severity": "block",
            })

        # no-close-with-open-questions
        open_q = shared_state.get("decisions", {}).get("open_questions", [])
        if open_q:
            warnings.append({
                "invariant": "no-close-with-open-questions",
                "detail": f"{len(open_q)} open question(s)",
                "severity": "warn",
            })

        # required closed-phase artifacts
        artifact_result = self.check_phase_artifacts("closed", project_dir)
        violations.extend(artifact_result.violations)

        return GuardResult(
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )

    def check_spawn(self, project_dir: Path) -> GuardResult:
        """Verify gap certificate exists before spawn."""
        cert_path = project_dir / "governance" / "gap_certificate.yaml"
        if not cert_path.exists():
            return GuardResult(
                passed=False,
                violations=[{
                    "invariant": "no-spawn-without-gap-certification",
                    "missing": "governance/gap_certificate.yaml",
                    "severity": "block",
                }],
            )
        return GuardResult(passed=True)
