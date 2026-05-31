from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from verse.config import AppConfig
from verse.intent import IntentCategory, fast_intent_classifier
from verse.tools import ToolSelector
from verse.orchestrator import Orchestrator, build_orchestrator


def test_fast_intent_classifier():
    # 1. Local system
    cat, conf, conf_req = fast_intent_classifier("setel volume ke 80")
    assert cat == IntentCategory.LOCAL_SYSTEM
    assert conf >= 0.90
    assert not conf_req

    cat, conf, conf_req = fast_intent_classifier("matikan dnd")
    assert cat == IntentCategory.LOCAL_SYSTEM
    assert conf >= 0.90
    assert not conf_req

    # 2. Music
    cat, conf, conf_req = fast_intent_classifier("putar lagu chill lofi")
    assert cat == IntentCategory.MUSIC
    assert not conf_req

    # 3. Calendar
    cat, conf, conf_req = fast_intent_classifier("buat meeting jam 2 siang")
    assert cat == IntentCategory.CALENDAR
    assert conf_req  # creation requires confirmation

    cat, conf, conf_req = fast_intent_classifier("baca jadwal kalender hari ini")
    assert cat == IntentCategory.CALENDAR
    assert not conf_req

    # 4. Message (requires confirmation)
    cat, conf, conf_req = fast_intent_classifier("kirim pesan ke Budi berisi halo apa kabar")
    assert conf_req

    # 5. Notes
    cat, conf, conf_req = fast_intent_classifier("buat catatan beli susu besok pagi")
    assert cat == IntentCategory.NOTES
    assert not conf_req


def test_tool_selector():
    all_tools = [
        "play_music", "pause_music", "remember", "open_app", "close_app",
        "get_time", "web_search", "open_url", "get_weather", "take_note",
        "read_calendar", "create_event", "send_message", "find_contact"
    ]
    selector = ToolSelector(all_tools)

    # Music category should only select music tools
    selected = selector.select("play some jazz", IntentCategory.MUSIC)
    assert "play_music" in selected
    assert "pause_music" in selected
    assert len(selected) <= 5

    # Keyword match weather
    selected = selector.select("bagaimana cuaca hari ini", IntentCategory.CHAT)
    assert selected == ["get_weather"]

    # Maximum limit check (should not exceed 5 tools)
    selected = selector.select("buka spotify, setel musik, tambah pengingat, kirim pesan, buat catatan", IntentCategory.CHAT)
    assert len(selected) <= 5


@pytest.mark.anyio
async def test_orchestrator_classification_and_routing():
    # Setup orchestrator with mocks
    config = AppConfig()
    orchestrator = build_orchestrator(config)
    
    # Mock self.llm.chat
    mock_chat = AsyncMock()
    mock_chat.return_value = MagicMock(text="Mocked LLM reply", tool_calls=[])
    orchestrator.llm.chat = mock_chat
    
    # Mock self.local_intent_router.route
    # For a high-risk action like send_message or deletion, we flag it or confirm it.
    # In orchestrator, if requires_confirmation is True, it returns None.
    # Let's test that sending a message goes to LLM, not local execution:
    with patch("verse.orchestrator.fast_intent_classifier", return_value=(IntentCategory.UNKNOWN, 0.95, True)):
        reply = await orchestrator._respond("kirim pesan ke budi", [])
        assert reply == "Mocked LLM reply"
        # Verify it went to LLM and not local router
        mock_chat.assert_called_once()
        
    # Verify dynamic thresholds:
    # A volume match with confidence 0.68 should execute locally because threshold is 0.65.
    mock_chat.reset_mock()
    vol_match = MagicMock(intent="system.set_volume", confidence=0.68, tool_name="set_volume", arguments={"level": 50})
    orchestrator.local_intent_router.route = MagicMock(return_value=vol_match)
    orchestrator._execute_local_intent = MagicMock(return_value="Siap, volume aku set ke 50%.")
    
    reply = await orchestrator._respond("volume 50", [])
    assert reply == "Siap, volume aku set ke 50%."
    mock_chat.assert_not_called()  # Executed locally
    
    # A calendar match with confidence 0.75 should NOT execute locally because threshold is 0.85.
    mock_chat.reset_mock()
    cal_match = MagicMock(intent="calendar.create", confidence=0.75, tool_name="create_event", arguments={})
    orchestrator.local_intent_router.route = MagicMock(return_value=cal_match)
    
    reply = await orchestrator._respond("buat meeting", [])
    assert reply == "Mocked LLM reply"
    mock_chat.assert_called_once()  # Skipped local and fell back to LLM
