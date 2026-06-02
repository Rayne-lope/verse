from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from verse.config import AppConfig, DebugConfig, MemoryConfig, ToolsConfig
from verse.intent import IntentCategory, fast_intent_classifier
from verse.tools import ToolSelector
from verse.orchestrator import Orchestrator, build_orchestrator
from verse.tools.registry import build_default_registry


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


def test_classifier_web_action_beats_app_launch():
    """Regression: requests that open an app AND act on the web must route to
    BROWSER, not APP (which only exposes open_app/close_app to the LLM)."""
    # App verb + web read intent -> BROWSER
    cat, _, _ = fast_intent_classifier("buka wikipedia dan rangkum artikel antartika")
    assert cat == IntentCategory.BROWSER

    # App name + web search intent -> BROWSER
    cat, _, _ = fast_intent_classifier("buka brave dan cari mobil listrik terbaru")
    assert cat == IntentCategory.BROWSER

    # WhatsApp in Brave is browser automation, not a plain app launch/iMessage.
    cat, _, _ = fast_intent_classifier("Tolong buka WhatsApp di Brave")
    assert cat == IntentCategory.BROWSER

    cat, _, _ = fast_intent_classifier("Tolong buat balasan ke Ridho Maulana di WhatsApp aku di Brave")
    assert cat == IntentCategory.BROWSER

    # Standalone web search -> BROWSER
    cat, _, _ = fast_intent_classifier("cari fakta menarik tentang antartika")
    assert cat == IntentCategory.BROWSER

    # Pure app launch (no web action) stays APP
    cat, _, _ = fast_intent_classifier("buka kalkulator")
    assert cat == IntentCategory.APP
    cat, _, _ = fast_intent_classifier("tutup chrome")
    assert cat == IntentCategory.APP

    # Guard: notes/calendar phrasing is NOT stolen by web-action keywords
    cat, _, _ = fast_intent_classifier("baca catatan belanja")
    assert cat == IntentCategory.NOTES
    cat, _, _ = fast_intent_classifier("cari acara di kalender minggu ini")
    assert cat == IntentCategory.CALENDAR


def test_selector_includes_full_browser_toolset():
    """Regression: browser_inspect/scroll/go_back must be selectable, and the
    BROWSER category must not be truncated to 5 tools (inspect is required for
    numeric-ID clicks)."""
    browser_tools = [
        "open_app", "close_app", "web_search", "open_url",
        "browser_navigate", "browser_read_current", "browser_status", "browser_inspect",
        "browser_click_best_match", "browser_click_text", "browser_click_role",
        "browser_fill_form",
        "browser_click", "browser_input", "browser_scroll", "browser_go_back",
        "browser_close",
    ]
    selector = ToolSelector(browser_tools)

    selected = selector.select("cari mobil listrik dan klik hasil pertama", IntentCategory.BROWSER)
    # The newly implemented tools must be present.
    assert selected[:13] == [
        "browser_navigate",
        "browser_read_current",
        "browser_status",
        "browser_inspect",
        "browser_click_best_match",
        "browser_click_text",
        "browser_click_role",
        "browser_fill_form",
        "browser_click",
        "browser_input",
        "browser_scroll",
        "browser_go_back",
        "browser_close",
    ]
    assert "browser_inspect" in selected
    assert "browser_read_current" in selected
    assert "browser_status" in selected
    assert "browser_click_best_match" in selected
    assert "browser_click_text" in selected
    assert "browser_click_role" in selected
    assert "browser_fill_form" in selected
    assert "browser_scroll" in selected
    assert "browser_go_back" in selected
    assert "open_app" not in selected
    assert "open_url" not in selected
    assert "close_app" not in selected
    # Browser turns get a higher cap so the full toolset survives.
    assert len(selected) > 5

    default_selector = ToolSelector(ToolsConfig().enabled)
    default_selected = default_selector.select("buka wikipedia dan rangkum artikelnya", IntentCategory.BROWSER)
    assert "browser_read_current" in default_selected
    assert "browser_status" in default_selected
    assert "browser_click_best_match" in default_selected
    assert "browser_fill_form" in default_selected
    assert "browser_go_back" in default_selected

    whatsapp_selected = default_selector.select("Tolong buka WhatsApp di Brave", IntentCategory.BROWSER)
    assert "browser_navigate" in whatsapp_selected
    assert "browser_status" in whatsapp_selected
    assert "browser_go_back" in whatsapp_selected
    assert "whatsapp_open" in whatsapp_selected
    assert "whatsapp_find_chat" in whatsapp_selected
    assert "whatsapp_draft_message" in whatsapp_selected
    assert "whatsapp_send_message" in whatsapp_selected
    assert "open_app" not in whatsapp_selected
    assert "open_url" not in whatsapp_selected

    # Non-browser categories keep the tight 5-tool cap.
    capped = selector.select("buka spotify, setel musik, pengingat, pesan, catatan", IntentCategory.CHAT)
    assert len(capped) <= 5


def test_default_registry_exposes_browser_intent_tools():
    registry = build_default_registry(ToolsConfig().enabled)
    definitions = {
        tool["function"]["name"]: tool["function"]
        for tool in registry.list_definitions()
    }
    assert "browser_click_best_match" in definitions
    assert "browser_status" in definitions
    assert "browser_click_text" in definitions
    assert "browser_click_role" in definitions
    assert "browser_fill_form" in definitions
    assert definitions["browser_fill_form"]["parameters"]["properties"]["fields"]["type"] == "array"


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
    config = AppConfig(
        debug=DebugConfig(session_logging=False),
        memory=MemoryConfig(enabled=False),
    )
    with patch("verse.persistence.db.default_store") as mock_default_store:
        orchestrator = build_orchestrator(config)
    mock_default_store.assert_not_called()
    
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
