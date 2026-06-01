from unittest.mock import MagicMock, patch
import pytest
from verse.tools.builtin.browser import (
    browser_inspect,
    browser_read_current,
    browser_click,
    browser_input,
    browser_scroll,
    browser_go_back,
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
