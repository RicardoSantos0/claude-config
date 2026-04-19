from pathlib import Path

from core.runtime_config import (
    get_database_backend,
    get_vector_backend,
)


def test_database_backend_falls_back_to_sqlite(monkeypatch):
    monkeypatch.delenv("MAS_DATABASE_URL", raising=False)
    monkeypatch.delenv("MAS_DATABASE_PROVIDER", raising=False)
    backend = get_database_backend()
    assert backend["configured_provider"] == "sqlite"
    assert backend["target_provider"] == "postgresql"
    assert backend["active_provider"] == "sqlite"
    assert backend["url"].startswith("sqlite:///")


def test_database_backend_uses_postgres_when_url_present(monkeypatch):
    monkeypatch.setenv("MAS_DATABASE_URL", "postgresql://user:pass@localhost:5432/mas")
    monkeypatch.setenv("MAS_DATABASE_PROVIDER", "postgresql")
    backend = get_database_backend()
    assert backend["configured_provider"] == "postgresql"
    assert backend["active_provider"] == "postgresql"
    assert backend["url"].startswith("postgresql://")


def test_vector_backend_defaults_disabled(monkeypatch):
    monkeypatch.delenv("MAS_VECTOR_ENABLED", raising=False)
    cfg = get_vector_backend()
    assert cfg["provider"] == "chromadb"
    assert cfg["enabled"] is False
    assert isinstance(cfg["persist_directory"], Path)
