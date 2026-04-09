"""
Agent Communication Bus

All agent-to-agent communication flows through this bus.
V1 implementation is synchronous direct calls.
The abstraction allows migration to async messaging later.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageType(Enum):
    HANDOFF = "handoff"
    CAPABILITY_QUERY = "capability_query"
    CAPABILITY_RESPONSE = "capability_response"
    CONSULTATION_REQUEST = "consultation_request"
    CONSULTATION_RESPONSE = "consultation_response"
    RECORD = "record"
    DIRECTIVE = "directive"
    ERROR = "error"
    ESCALATION = "escalation"


@dataclass
class Message:
    message_id: str
    message_type: MessageType
    from_agent: str
    to_agent: str
    project_id: str
    timestamp: str = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    payload: dict = field(default_factory=dict)
    requires_response: bool = False
    correlation_id: Optional[str] = None  # Links request/response pairs


@dataclass
class MessageResult:
    success: bool
    response: Optional[dict] = None
    error: Optional[str] = None


class MessageBus(ABC):
    """Abstract message bus interface."""

    @abstractmethod
    def send(self, message: Message) -> MessageResult:
        """Send a message and optionally wait for response."""
        pass

    @abstractmethod
    def register_agent(self, agent_id: str, handler: callable) -> None:
        """Register an agent's message handler."""
        pass

    @abstractmethod
    def get_message_log(self, project_id: str) -> list:
        """Get all messages for a project."""
        pass


class DirectCallBus(MessageBus):
    """
    V1 implementation: synchronous direct function calls.
    Messages are delivered immediately and responses are returned
    synchronously.
    """

    def __init__(self, audit_logger=None):
        self._handlers: dict[str, callable] = {}
        self._message_log: list[Message] = []
        self._audit_logger = audit_logger

    def register_agent(self, agent_id: str, handler: callable) -> None:
        """Register an agent's message handler."""
        self._handlers[agent_id] = handler

    def send(self, message: Message) -> MessageResult:
        """
        Send a message synchronously.
        The receiving agent's handler is called directly.
        """
        # Log the message
        self._message_log.append(message)

        # Audit log
        if self._audit_logger:
            self._audit_logger.log(
                event="message_sent",
                from_agent=message.from_agent,
                to_agent=message.to_agent,
                message_type=message.message_type.value,
                project_id=message.project_id,
                message_id=message.message_id,
            )

        # Find the handler
        handler = self._handlers.get(message.to_agent)
        if handler is None:
            return MessageResult(
                success=False,
                error=f"No handler registered for agent: {message.to_agent}",
            )

        # Deliver the message
        try:
            response = handler(message)
            return MessageResult(success=True, response=response)
        except Exception as e:
            return MessageResult(success=False, error=str(e))

    def get_message_log(self, project_id: str) -> list:
        """Get all messages for a project."""
        return [m for m in self._message_log if m.project_id == project_id]