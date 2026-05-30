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


def test_memory_upsert_dedup_and_load(tmp_path):
    store = ConversationStore(tmp_path / "history.db")

    store.upsert_memory("User's name is Rapi")
    store.upsert_memory("User likes jazz")
    # Same fact, different casing/whitespace -> de-duplicated, not a second row.
    store.upsert_memory("  user's NAME is rapi ")

    facts = store.load_memories(limit=10)
    assert "User likes jazz" in facts
    assert sum(1 for f in facts if f.lower().startswith("user's name")) == 1
    store.close()


def test_memory_blank_is_ignored(tmp_path):
    store = ConversationStore(tmp_path / "history.db")
    assert store.upsert_memory("   ") is None
    assert store.load_memories(limit=10) == []
    store.close()


def test_memory_prune_keeps_top_n(tmp_path):
    store = ConversationStore(tmp_path / "history.db")
    for i in range(10):
        store.upsert_memory(f"fact number {i}")

    removed = store.prune_memories(max_count=4)
    assert removed == 6
    assert len(store.load_memories(limit=100)) == 4
    store.close()


def test_memory_salience_orders_results(tmp_path):
    store = ConversationStore(tmp_path / "history.db")
    store.upsert_memory("low priority fact", salience=1.0)
    store.upsert_memory("high priority fact", salience=5.0)

    facts = store.load_memories(limit=10)
    assert facts[0] == "high priority fact"
    store.close()
