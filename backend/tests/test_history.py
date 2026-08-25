"""The session history has to survive two things it doesn't control:
plain role dicts appended by the confirm and decline endpoints, and being
cut short when a conversation runs long. Neither may orphan a tool result
from the tool call it answers.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.history import to_messages, trim


def a_round(n):
    """One tool round: the model calls a tool, the tool answers, the model replies."""
    return [
        AIMessage(content="", tool_calls=[{"name": "get_my_units", "args": {}, "id": f"t{n}"}]),
        ToolMessage(content="{}", tool_call_id=f"t{n}"),
        AIMessage(content=f"answer {n}"),
    ]


def test_endpoint_dicts_convert_alongside_message_objects():
    """confirm and decline append raw dicts. They must land as real turns."""
    history = [
        HumanMessage("I want to move out"),
        AIMessage("Sure, when?"),
        {"role": "user", "content": "[app note] The resident tapped Confirm. Request req-1 is now filed."},
    ]

    converted = to_messages(history)

    assert len(converted) == 3
    assert isinstance(converted[2], HumanMessage)
    assert converted[2].content.startswith("[app note]")


def test_short_history_is_left_alone():
    history = [HumanMessage("hi"), AIMessage("hello")]
    assert trim(history, keep=40) == history


def test_trim_cuts_at_a_real_user_turn():
    history = []
    for i in range(10):
        history.append(HumanMessage(f"question {i}"))
        history.extend(a_round(i))

    trimmed = trim(history, keep=12)

    assert len(trimmed) < len(history)
    assert isinstance(trimmed[0], HumanMessage)
    assert isinstance(trimmed[0].content, str)


def test_trim_never_orphans_a_tool_result():
    """A ToolMessage without its AIMessage is a 400 from the provider."""
    history = []
    for i in range(10):
        history.append(HumanMessage(f"question {i}"))
        history.extend(a_round(i))

    for keep in range(2, len(history)):
        trimmed = trim(history, keep=keep)
        open_calls = set()
        for msg in trimmed:
            if isinstance(msg, AIMessage):
                open_calls.update(c["id"] for c in msg.tool_calls)
            elif isinstance(msg, ToolMessage):
                assert msg.tool_call_id in open_calls, f"orphaned tool result at keep={keep}"


def test_a_tool_result_is_not_mistaken_for_a_user_turn():
    """The cut point is a user turn with string content, and a ToolMessage
    is not one, even though it rides in the user role on the wire."""
    history = [
        HumanMessage("start"),
        *a_round(1),
        ToolMessage(content="{}", tool_call_id="t1"),
        HumanMessage("second real turn"),
        AIMessage("done"),
    ]

    trimmed = trim(history, keep=3)

    assert trimmed[0].content == "second real turn"
