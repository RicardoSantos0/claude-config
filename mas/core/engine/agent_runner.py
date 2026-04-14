"""
Agent Runner
Real Anthropic SDK calls for MAS agents.

Gated on ANTHROPIC_API_KEY — falls back to dry-run mode transparently when
the key is absent. This means every code path works without a live key;
the difference is whether an actual LLM call is made.

Every real call is logged to the SQLite event store (mas/data/episodic.db).

Default model: claude-haiku-4-5-20251001 (fast + cheap — right for scaffolding).
Override with AgentRunner(model="claude-sonnet-4-6") or per-call dry_run=False.

Usage:
    from core.engine.agent_runner import AgentRunner
    runner = AgentRunner()
    result = runner.run(
        agent_id="inquirer_agent",
        prompt="You are an intake agent. Summarize this brief: ...",
        project_id="proj-20260414-001-true-mas-integration",
    )
    print(result["text"])
    print(result["tokens_used"])
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS_DEFAULT = 1024


class AgentRunner:
    """
    Thin wrapper around the Anthropic SDK for MAS agent calls.
    Thread-safe: one client instance, stateless per call.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        db_path: Optional[Path] = None,
    ):
        self.model = model
        self._db_path = db_path
        self._client = None
        self._init_client()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=key)
        except ImportError:
            pass  # anthropic package not installed — dry-run only

    @property
    def available(self) -> bool:
        """True if the Anthropic client is ready (key set + package installed)."""
        return self._client is not None

    # ------------------------------------------------------------------
    # Core call
    # ------------------------------------------------------------------

    def run(
        self,
        agent_id: str,
        prompt: str,
        project_id: str = "",
        dry_run: bool = False,
        max_tokens: int = _MAX_TOKENS_DEFAULT,
        system_prompt: str = "",
    ) -> dict:
        """
        Call an agent via the Anthropic API.

        Returns:
            {
                "text":        str   — response text (empty on error)
                "tokens_used": int   — total tokens consumed
                "model":       str   — model that was called
                "dry_run":     bool  — True if no real call was made
                "error":       str   — set on API error (absent on success)
            }
        """
        if dry_run or not self.available:
            return {
                "text": f"[dry_run] {agent_id}: set ANTHROPIC_API_KEY for live calls",
                "tokens_used": 0,
                "model": self.model,
                "dry_run": True,
            }

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        try:
            msg = self._client.messages.create(**kwargs)  # type: ignore[union-attr]
            text = msg.content[0].text if msg.content else ""
            tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

            self._log_event(project_id, agent_id, prompt, tokens)

            return {
                "text": text,
                "tokens_used": tokens,
                "model": self.model,
                "dry_run": False,
            }

        except Exception as exc:
            return {
                "text": "",
                "tokens_used": 0,
                "model": self.model,
                "dry_run": False,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # SQLite logging
    # ------------------------------------------------------------------

    def _log_event(
        self,
        project_id: str,
        agent_id: str,
        prompt: str,
        tokens: int,
    ) -> None:
        """Write an agent_call event to SQLite. Non-fatal."""
        if not project_id:
            return
        try:
            from core.db import append_event
            kwargs: dict = {}
            if self._db_path:
                kwargs["db_path"] = self._db_path
            append_event(
                project_id=project_id,
                agent_id=agent_id,
                action_type="agent_call",
                intent=prompt[:120],
                result_shape=f"tokens={tokens}",
                payload={"model": self.model, "tokens": tokens},
                **kwargs,
            )
        except Exception:
            pass
