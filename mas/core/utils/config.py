"""
System configuration loader (utils copy)

Copied into `core.utils`. Adjusted path calculations so `ROOT`
resolves correctly when the module lives under `mas/core/utils/`.
"""

import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

# mas/ root when this file is located at mas/core/utils/config.py
ROOT = Path(__file__).parents[2]
REPO_ROOT = ROOT.parent


def _find_root() -> Path:
    """Find system root by locating system_config.yaml."""
    candidate = Path(__file__).parents[2]
    if (candidate / "system_config.yaml").exists():
        return candidate
    raise FileNotFoundError(f"system_config.yaml not found under {candidate}")


def load_config() -> dict:
    """Load and return the full system configuration."""
    load_dotenv(REPO_ROOT / ".env")
    config_path = ROOT / "system_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_master_model() -> str:
    config = load_config()
    return os.getenv("MAS_MASTER_MODEL", config["llm"]["master_model"])


def get_default_model() -> str:
    config = load_config()
    return os.getenv("MAS_DEFAULT_MODEL", config["llm"]["default_model"])


def get_model_for_agent(agent_id: str) -> str:
    """Return the appropriate model for a given agent."""
    if agent_id == "master_orchestrator":
        return get_master_model()
    return get_default_model()


def get_api_key() -> str:
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key."
        )
    return key


def get_projects_dir() -> Path:
    config = load_config()
    return ROOT / config["paths"]["projects"]


def get_governance_mode() -> str:
    config = load_config()
    return os.getenv("MAS_GOVERNANCE_MODE", config["system"]["governance_mode"])


def get_defaults() -> dict:
    return load_config()["defaults"]
