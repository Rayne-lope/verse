from verse.persistence.db import ConversationStore


def test_save_20_messages_and_load_last_10(tmp_path):
    store = ConversationStore(tmp_path / "history.db")
    conv_id = store.new_conversation()

    for index in range(20):
        store.save_message(conv_id, "user", f"message-{index}")

    messages = store.load_recent_messages(limit=10)

    assert [message["content"] for message in messages] == [
        f"message-{index}" for index in range(10, 20)
    ]
    assert all(message["conv_id"] == conv_id for message in messages)
    store.close()


def test_tool_calls_round_trip_as_json(tmp_path):
    store = ConversationStore(tmp_path / "history.db")
    conv_id = store.new_conversation()

    store.save_message(
        conv_id,
        "assistant",
        "Calling a tool",
        tool_calls=[{"name": "open_app", "arguments": {"app_name": "Music"}}],
    )

    messages = store.load_recent_messages(limit=1)

    assert messages[0]["tool_calls"] == [
        {"name": "open_app", "arguments": {"app_name": "Music"}}
    ]
    store.close()
