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
