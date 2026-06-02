from unittest.mock import MagicMock, call, patch
import pytest
from verse.tools.builtin.browser import (
    browser_inspect,
    browser_read_current,
    browser_click,
    browser_click_best_match,
    browser_click_role,
    browser_click_text,
    browser_fill_form,
    browser_input,
    browser_scroll,
    browser_go_back,
    whatsapp_open,
    whatsapp_find_chat,
    whatsapp_draft_message,
    whatsapp_send_message,
)

@pytest.fixture(autouse=True)
def cleanup_browser_state():
    """Reset the module-level globals in browser.py to ensure test isolation."""
    import verse.tools.builtin.browser as b
    b._playwright = None
    b._context = None
    b._page = None
    yield
    # Cleanup after test
    b._playwright = None
    b._context = None
    b._page = None


def test_browser_inspect_no_elements():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = []
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_inspect()
        assert "No interactive elements found" in res


def test_browser_inspect_with_elements():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = [
        {
            "id": 1,
            "tag": "input",
            "type": "text",
            "name": "q",
            "placeholder": "Search...",
            "aria_label": "Search Query",
            "text": ""
        },
        {
            "id": 2,
            "tag": "button",
            "type": "submit",
            "name": "submit",
            "placeholder": "",
            "aria_label": "",
            "text": "Go"
        }
    ]
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_inspect()
        assert "[1] input (text) - name=\"q\", placeholder=\"Search...\", aria-label=\"Search Query\"" in res
        assert "[2] button (submit) - name=\"submit\", text=\"Go\"" in res


def test_browser_read_current_reads_active_page():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "https://example.com/article"
    mock_page.evaluate.return_value = "Title\n\nParagraph one\nParagraph two"

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_read_current()
        assert "Successfully read https://example.com/article" in res
        assert "Title" in res
        assert "Paragraph one" in res
        mock_page.wait_for_timeout.assert_called_once_with(500)


def test_browser_click_numeric_conversion():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_click("12")
        assert "Successfully clicked element '12'" in res
        mock_page.click.assert_called_once_with("[data-verse-id='12']", timeout=5000)


def test_browser_input_numeric_conversion():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_input("5", "hello world")
        assert "Successfully entered text into '5'" in res
        mock_page.fill.assert_called_once_with("[data-verse-id='5']", "hello world", timeout=5000)


def test_browser_click_text_uses_visible_text_locator():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    text_locator = MagicMock()
    mock_page.get_by_text.return_value.first = text_locator

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_click_text("Login")
        assert "Successfully clicked text 'Login'" in res
        mock_page.get_by_text.assert_called_once_with("Login", exact=False)
        text_locator.click.assert_called_once_with(timeout=5000)


def test_browser_click_text_falls_back_to_metadata_match():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.get_by_text.return_value.first.click.side_effect = RuntimeError("not found")
    mock_page.evaluate.return_value = [
        {
            "id": 3,
            "tag": "button",
            "role": "button",
            "type": "",
            "name": "",
            "placeholder": "",
            "aria_label": "",
            "label": "",
            "text": "Login",
            "visible": True,
            "bounding_box": {"x": 0, "y": 0, "width": 80, "height": 30},
        }
    ]

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_click_text("Login")
        assert "Successfully clicked best match" in res
        mock_page.click.assert_called_once_with("[data-verse-id='3']", timeout=5000)


def test_browser_click_role_uses_role_locator():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    role_locator = MagicMock()
    mock_page.get_by_role.return_value.first = role_locator

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_click_role("button", "Kirim", exact=True)
        assert "Successfully clicked button 'Kirim'" in res
        mock_page.get_by_role.assert_called_once_with("button", name="Kirim", exact=True)
        role_locator.click.assert_called_once_with(timeout=5000)


def test_browser_click_best_match_refuses_ambiguous_match():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = [
        {
            "id": 1,
            "tag": "button",
            "role": "button",
            "type": "",
            "name": "",
            "placeholder": "",
            "aria_label": "Login",
            "label": "",
            "text": "Login",
            "visible": True,
            "bounding_box": {"x": 0, "y": 0, "width": 80, "height": 30},
        },
        {
            "id": 2,
            "tag": "button",
            "role": "button",
            "type": "",
            "name": "",
            "placeholder": "",
            "aria_label": "Login",
            "label": "",
            "text": "Login",
            "visible": True,
            "bounding_box": {"x": 0, "y": 40, "width": 80, "height": 30},
        },
    ]

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_click_best_match("Login")
        assert "ambiguous" in res
        assert "Candidates" in res
        mock_page.click.assert_not_called()


def test_browser_click_best_match_returns_candidates_on_low_confidence():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = [
        {
            "id": 1,
            "tag": "button",
            "role": "button",
            "type": "",
            "name": "",
            "placeholder": "",
            "aria_label": "",
            "label": "",
            "text": "Settings",
            "visible": True,
            "bounding_box": {"x": 0, "y": 0, "width": 80, "height": 30},
        }
    ]

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_click_best_match("Checkout")
        assert "no matching interactive element" in res
        mock_page.click.assert_not_called()


def test_browser_fill_form_fills_text_select_checkbox_and_submits():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = [
        {
            "id": 1,
            "tag": "input",
            "role": "textbox",
            "type": "email",
            "name": "email",
            "placeholder": "Email",
            "aria_label": "",
            "label": "Email",
            "text": "",
            "visible": True,
            "bounding_box": {"x": 0, "y": 0, "width": 100, "height": 30},
        },
        {
            "id": 2,
            "tag": "textarea",
            "role": "textbox",
            "type": "",
            "name": "notes",
            "placeholder": "Notes",
            "aria_label": "",
            "label": "Notes",
            "text": "",
            "visible": True,
            "bounding_box": {"x": 0, "y": 40, "width": 100, "height": 60},
        },
        {
            "id": 3,
            "tag": "div",
            "role": "textbox",
            "type": "",
            "name": "",
            "placeholder": "",
            "aria_label": "Message",
            "label": "Message",
            "text": "",
            "visible": True,
            "bounding_box": {"x": 0, "y": 110, "width": 100, "height": 60},
        },
        {
            "id": 4,
            "tag": "select",
            "role": "combobox",
            "type": "",
            "name": "country",
            "placeholder": "",
            "aria_label": "",
            "label": "Country",
            "text": "",
            "visible": True,
            "bounding_box": {"x": 0, "y": 180, "width": 100, "height": 30},
        },
        {
            "id": 5,
            "tag": "input",
            "role": "checkbox",
            "type": "checkbox",
            "name": "agree",
            "placeholder": "",
            "aria_label": "",
            "label": "Agree",
            "text": "",
            "visible": True,
            "bounding_box": {"x": 0, "y": 220, "width": 20, "height": 20},
        },
        {
            "id": 6,
            "tag": "input",
            "role": "radio",
            "type": "radio",
            "name": "priority",
            "placeholder": "",
            "aria_label": "",
            "label": "Priority",
            "text": "",
            "visible": True,
            "bounding_box": {"x": 0, "y": 250, "width": 20, "height": 20},
        },
        {
            "id": 7,
            "tag": "button",
            "role": "button",
            "type": "submit",
            "name": "",
            "placeholder": "",
            "aria_label": "",
            "label": "",
            "text": "Send",
            "visible": True,
            "bounding_box": {"x": 0, "y": 290, "width": 80, "height": 30},
        },
    ]

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_fill_form(
            [
                {"target": "Email", "value": "rayne@example.com"},
                {"target": "Notes", "value": "hello textarea"},
                {"target": "Message", "value": "hello contenteditable"},
                {"target": "Country", "value": "ID"},
                {"target": "Agree", "value": "true"},
                {"target": "Priority", "value": "true"},
            ],
            submit=True,
            submit_label="Send",
        )
        assert "Successfully filled form" in res
        mock_page.fill.assert_has_calls([
            call("[data-verse-id='1']", "rayne@example.com", timeout=5000),
            call("[data-verse-id='2']", "hello textarea", timeout=5000),
            call("[data-verse-id='3']", "hello contenteditable", timeout=5000),
        ])
        mock_page.select_option.assert_called_once_with("[data-verse-id='4']", "ID", timeout=5000)
        mock_page.check.assert_has_calls([
            call("[data-verse-id='5']", timeout=5000),
            call("[data-verse-id='6']", timeout=5000),
        ])
        mock_page.click.assert_called_once_with("[data-verse-id='7']", timeout=5000)


def test_browser_scroll():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_scroll("down", "half")
        assert "Successfully scrolled page down by half" in res
        
        # Verify page evaluate was called with down and half
        mock_page.evaluate.assert_called_once()
        script = mock_page.evaluate.call_args[0][0]
        assert '"down" === "down"' in script
        assert '"half" === "half"' in script


def test_browser_go_back():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_go_back()
        assert "Successfully navigated back" in res
        mock_page.go_back.assert_called_once_with(wait_until="domcontentloaded")


def test_whatsapp_open_detects_login_required():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = "Use WhatsApp on your computer\nScan this QR code"

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = whatsapp_open()
        assert "login is required" in res
        mock_page.goto.assert_called_once_with(
            "https://web.whatsapp.com/",
            wait_until="domcontentloaded",
            timeout=20000,
        )


def test_whatsapp_open_detects_ready_state():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = "Chats\nSearch or start new chat"

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = whatsapp_open()
        assert "open and ready" in res


def test_whatsapp_find_chat_searches_and_opens_match():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "https://web.whatsapp.com/"
    mock_page.evaluate.return_value = "Chats\nSearch or start new chat"
    search_locator = MagicMock()
    mock_page.locator.return_value.first = search_locator
    chat_locator = MagicMock()
    mock_page.get_by_text.return_value.first = chat_locator

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = whatsapp_find_chat("Ridho Maulana")
        assert "Opened WhatsApp chat with Ridho Maulana" in res
        search_locator.fill.assert_called_once_with("Ridho Maulana", timeout=7000)
        chat_locator.click.assert_called_once_with(timeout=8000)


def test_whatsapp_draft_message_fills_compose_without_sending():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "https://web.whatsapp.com/"
    mock_page.evaluate.return_value = "Chats\nSearch or start new chat"
    search_wrapper = MagicMock()
    search_locator = MagicMock()
    search_wrapper.first = search_locator
    compose_wrapper = MagicMock()
    compose_locator = MagicMock()
    compose_wrapper.first = compose_locator
    mock_page.locator.side_effect = [search_wrapper, compose_wrapper]
    mock_page.get_by_text.return_value.first = MagicMock()

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = whatsapp_draft_message("Ridho Maulana", "oke gas")
        assert "Drafted WhatsApp message to Ridho Maulana" in res
        compose_locator.fill.assert_called_once_with("oke gas", timeout=7000)
        compose_locator.press.assert_not_called()


def test_whatsapp_send_message_fills_compose_and_presses_enter():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "https://web.whatsapp.com/"
    mock_page.evaluate.return_value = "Chats\nSearch or start new chat"
    search_wrapper = MagicMock()
    search_locator = MagicMock()
    search_wrapper.first = search_locator
    compose_wrapper = MagicMock()
    compose_locator = MagicMock()
    compose_wrapper.first = compose_locator
    mock_page.locator.side_effect = [search_wrapper, compose_wrapper]
    mock_page.get_by_text.return_value.first = MagicMock()

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = whatsapp_send_message("Ridho Maulana", "oke gas")
        assert "Sent WhatsApp message to Ridho Maulana" in res
        compose_locator.fill.assert_called_once_with("oke gas", timeout=7000)
        compose_locator.press.assert_called_once_with("Enter", timeout=5000)
