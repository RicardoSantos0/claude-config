"""
Unit Tests — MessageBus (DirectCallBus)
"""
import pytest
from core.engine.message_bus import DirectCallBus, Message, MessageType, MessageResult


@pytest.fixture
def bus():
    return DirectCallBus()


def make_message(from_agent="master_orchestrator", to_agent="scribe_agent",
                 msg_type=MessageType.DIRECTIVE):
    return Message(
        message_id="msg-001",
        message_type=msg_type,
        from_agent=from_agent,
        to_agent=to_agent,
        project_id="proj-test-003",
        payload={"test": True},
    )


def test_register_and_send(bus):
    received = []

    def handler(msg):
        received.append(msg)
        return {"ok": True}

    bus.register_agent("scribe_agent", handler)
    result = bus.send(make_message())
    assert result.success
    assert len(received) == 1


def test_send_to_unregistered_agent_fails(bus):
    result = bus.send(make_message(to_agent="nobody"))
    assert not result.success
    assert "No handler registered" in result.error


def test_handler_exception_returns_failure(bus):
    def bad_handler(msg):
        raise ValueError("Handler exploded")

    bus.register_agent("scribe_agent", bad_handler)
    result = bus.send(make_message())
    assert not result.success
    assert "Handler exploded" in result.error


def test_message_logged_on_send(bus):
    bus.register_agent("scribe_agent", lambda m: None)
    bus.send(make_message())
    log = bus.get_message_log("proj-test-003")
    assert len(log) == 1
    assert log[0].message_id == "msg-001"


def test_get_message_log_filtered_by_project(bus):
    bus.register_agent("scribe_agent", lambda m: None)

    msg1 = make_message()
    msg2 = Message(message_id="msg-002", message_type=MessageType.HANDOFF,
                   from_agent="master_orchestrator", to_agent="scribe_agent",
                   project_id="proj-other-999", payload={})

    bus.send(msg1)
    bus.send(msg2)

    log = bus.get_message_log("proj-test-003")
    assert len(log) == 1

    log_other = bus.get_message_log("proj-other-999")
    assert len(log_other) == 1


def test_multiple_message_types(bus):
    bus.register_agent("scribe_agent", lambda m: None)
    for msg_type in [MessageType.HANDOFF, MessageType.RECORD, MessageType.DIRECTIVE]:
        msg = Message(message_id=f"msg-{msg_type.value}",
                      message_type=msg_type,
                      from_agent="master_orchestrator",
                      to_agent="scribe_agent",
                      project_id="proj-test-003",
                      payload={})
        result = bus.send(msg)
        assert result.success


def test_registered_agents_list(bus):
    bus.register_agent("scribe_agent", lambda m: None)
    bus.register_agent("inquirer_agent", lambda m: None)
    agents = bus.registered_agents()
    assert "scribe_agent" in agents
    assert "inquirer_agent" in agents


def test_unregister_agent(bus):
    bus.register_agent("scribe_agent", lambda m: None)
    bus.unregister_agent("scribe_agent")
    result = bus.send(make_message())
    assert not result.success


def test_message_result_bool(bus):
    assert MessageResult(success=True)
    assert not MessageResult(success=False)
