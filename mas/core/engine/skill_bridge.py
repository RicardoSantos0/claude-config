"""
Skill Bridge (migrated)

Gateway between MAS agents and the skills/ repository.
"""

from __future__ import annotations

import sys
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from core.utils.token_counter import TokenCounter as _TokenCounter
    _tc = _TokenCounter()
except ImportError:
    _tc = None  # type: ignore

ROOT = Path(__file__).parent.parent.parent  # mas/
REPO_ROOT = ROOT.parent                    # claude-config/
SKILLS_DIR = REPO_ROOT / "skills"

SKILL_ACCESS: dict[str, list[str]] = {
    "master_orchestrator": ["*"],
    "scribe_agent": ["research-extract", "research-sync"],
    "inquirer_agent": ["research-extract"],
    "product_manager_agent": ["research-extract", "research-sync"],
    "project_manager_agent": ["research-extract"],
    "hr_agent": [],
    "evaluator_agent": ["research-extract"],
    "trainer_agent": [],
    "spawner_agent": ["skill-builder"],
    "risk_advisor": [],
    "quality_advisor": [],
    "devils_advocate": [],
    "domain_expert": ["research-extract"],
    "efficiency_advisor": [],
}


class SkillMetadata:
    def __init__(self, name: str, description: str, path: Path):
        self.name = name
        self.description = description
        self.path = path

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "path": str(self.path)}


class InvocationResult:
    def __init__(
        self,
        success: bool,
        skill_name: str,
        agent_id: str,
        outcome: str,
        message: str = "",
        tokens_used: int = 0,
        audit_entry: dict | None = None,
    ):
        self.success = success
        self.skill_name = skill_name
        self.agent_id = agent_id
        self.outcome = outcome
        self.message = message
        self.tokens_used = tokens_used
        self.audit_entry = audit_entry or {}

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "skill_name": self.skill_name,
            "agent_id": self.agent_id,
            "outcome": self.outcome,
            "message": self.message,
            "tokens_used": self.tokens_used,
        }


class SkillBridge:
    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self._cache: dict[str, SkillMetadata] | None = None

    def discover(self, force_refresh: bool = False) -> list[SkillMetadata]:
        if self._cache is not None and not force_refresh:
            return list(self._cache.values())

        found: dict[str, SkillMetadata] = {}

        if not self.skills_dir.exists():
            self._cache = {}
            return []

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            meta = self._parse_skill_md(skill_md)
            if meta:
                found[meta.name] = meta

        self._cache = found
        return list(found.values())

    def get_skill(self, skill_name: str) -> SkillMetadata | None:
        if self._cache is None:
            self.discover()
        return self._cache.get(skill_name)  # type: ignore[union-attr]

    def is_skill_authorized(self, agent_id: str, skill_name: str) -> bool:
        allowed = SKILL_ACCESS.get(agent_id)
        if allowed is None:
            return False
        if "*" in allowed:
            return True
        return skill_name in allowed

    def authorized_skills(self, agent_id: str) -> list[SkillMetadata]:
        all_skills = self.discover()
        if agent_id not in SKILL_ACCESS:
            return []
        allowed = SKILL_ACCESS[agent_id]
        if "*" in allowed:
            return all_skills
        return [s for s in all_skills if s.name in allowed]

    def invoke(
        self,
        agent_id: str,
        skill_name: str,
        query: str,
        project_id: str = "",
    ) -> InvocationResult:
        timestamp = datetime.now(timezone.utc).isoformat()
        tokens_used = _tc.count(query) if _tc else 0

        if not self.is_skill_authorized(agent_id, skill_name):
            audit = self._make_audit(
                agent_id, skill_name, query, project_id,
                outcome="denied", tokens_used=0, timestamp=timestamp,
            )
            return InvocationResult(
                success=False,
                skill_name=skill_name,
                agent_id=agent_id,
                outcome="denied",
                message=f"Agent '{agent_id}' is not authorized to invoke skill '{skill_name}'.",
                tokens_used=0,
                audit_entry=audit,
            )

        skill_meta = self.get_skill(skill_name)
        if skill_meta is None:
            audit = self._make_audit(
                agent_id, skill_name, query, project_id,
                outcome="skill_not_found", tokens_used=0, timestamp=timestamp,
            )
            return InvocationResult(
                success=False,
                skill_name=skill_name,
                agent_id=agent_id,
                outcome="skill_not_found",
                message=f"Skill '{skill_name}' not found in {self.skills_dir}.",
                tokens_used=0,
                audit_entry=audit,
            )

        audit = self._make_audit(
            agent_id, skill_name, query, project_id,
            outcome="ok", tokens_used=tokens_used, timestamp=timestamp,
        )

        return InvocationResult(
            success=True,
            skill_name=skill_name,
            agent_id=agent_id,
            outcome="ok",
            message=(
                f"Skill '{skill_name}' authorized for agent '{agent_id}'. "
                f"Invoke via: /{skill_name} {query}"
            ),
            tokens_used=tokens_used,
            audit_entry=audit,
        )

    def get_audit_log(self, project_id: str) -> list[dict]:
        log_path = self._audit_path(project_id)
        if not log_path.exists():
            return []
        with log_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("entries", [])

    def write_audit_entry(self, project_id: str, entry: dict) -> None:
        if not project_id:
            return
        log_path = self._audit_path(project_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        existing = self.get_audit_log(project_id)
        existing.append(entry)

        data = {
            "project_id": project_id,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "entries": existing,
        }
        with log_path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _parse_skill_md(self, path: Path) -> SkillMetadata | None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None

        if not content.startswith("---"):
            return None

        end = content.find("---", 3)
        if end == -1:
            return None

        frontmatter = content[3:end].strip()
        try:
            meta = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            return None

        name = meta.get("name") or path.parent.name
        description = meta.get("description", "")
        return SkillMetadata(name=name, description=description, path=path)

    def _make_audit(
        self,
        agent_id: str,
        skill_name: str,
        query: str,
        project_id: str,
        outcome: str,
        tokens_used: int,
        timestamp: str,
    ) -> dict:
        return {
            "timestamp": timestamp,
            "agent_id": agent_id,
            "skill_name": skill_name,
            "project_id": project_id or "unknown",
            "query_preview": query[:100] + ("..." if len(query) > 100 else ""),
            "outcome": outcome,
            "tokens_used": tokens_used,
        }

    def _audit_path(self, project_id: str) -> Path:
        return ROOT / "projects" / project_id / "skill_audit_log.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Skill Bridge — MAS agent-to-skills gateway",
        epilog="uv run python mas/core/skill_bridge.py discover",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("discover", help="List all discovered skills")

    inv = sub.add_parser("invoke", help="Simulate a skill invocation")
    inv.add_argument("--agent", required=True, help="Agent ID")
    inv.add_argument("--skill", required=True, help="Skill name")
    inv.add_argument("--query", required=True, help="Query string")
    inv.add_argument("--project-id", default="", help="Project ID (for audit log)")

    auth = sub.add_parser("authorized", help="List skills authorized for an agent")
    auth.add_argument("--agent", required=True, help="Agent ID")

    check = sub.add_parser("check", help="Check if an agent can invoke a skill")
    check.add_argument("--agent", required=True)
    check.add_argument("--skill", required=True)

    ns = parser.parse_args()
    bridge = SkillBridge()

    if ns.command == "discover":
        skills = bridge.discover()
        if not skills:
            print("[info] No skills found.")
            return 0
        for s in skills:
            print(f"  {s.name:<30} {s.description[:80]}")
        print(f"\n{len(skills)} skill(s) found.")
    elif ns.command == "invoke":
        res = bridge.invoke(ns.agent, ns.skill, ns.query, ns.project_id)
        print(json.dumps(res.to_dict(), indent=2))
    elif ns.command == "authorized":
        skills = bridge.authorized_skills(ns.agent)
        for s in skills:
            print(f"  {s.name:<30} {s.description[:60]}")
    elif ns.command == "check":
        ok = bridge.is_skill_authorized(ns.agent, ns.skill)
        status = "AUTHORIZED" if ok else "DENIED"
        print(f"[{status}] agent='{ns.agent}' skill='{ns.skill}'")
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
