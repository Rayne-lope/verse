from unittest.mock import MagicMock, patch
import pytest
import os
from verse.tools.builtin.browser import (
    _find_brave_executable,
    browser_navigate,
    browser_status,
    browser_click,
    browser_input,
    browser_close,
)

@pytest.fixture(autouse=True)
def cleanup_browser_state():
    """Reset the module-level globals in browser.py to ensure test isolation."""
    import verse.tools.builtin.browser as b
    b._playwright = None
    b._context = None
    b._page = None
    b._last_browser_result = {
        "action": "none",
        "status": "unknown",
        "message": "No browser action has run yet.",
    }
    yield
    # Cleanup after test
    b._playwright = None
    b._context = None
    b._page = None
    b._last_browser_result = {
        "action": "none",
        "status": "unknown",
        "message": "No browser action has run yet.",
    }


def test_find_brave_executable_mocked():
    with patch("os.path.exists", return_value=True) as mock_exists:
        path = _find_brave_executable()
        assert path != ""
        assert "Brave Browser" in path


def test_browser_navigate_success():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = "Line 1\nLine 2\nLine 3"
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw, \
         patch("verse.tools.builtin.browser._find_brave_executable", return_value="/Applications/Brave.app"):
        
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_navigate("wikipedia.org")
        assert "Successfully navigated to https://wikipedia.org" in res
        assert "Line 1" in res
        assert "Line 2" in res
        assert "Line 3" in res
        
        # Verify launch parameters
        mock_pw_instance.chromium.launch_persistent_context.assert_called_once()
        args, kwargs = mock_pw_instance.chromium.launch_persistent_context.call_args
        assert kwargs["headless"] is False
        assert kwargs["executable_path"] == "/Applications/Brave.app"
        mock_page.goto.assert_called_once_with("https://wikipedia.org", wait_until="domcontentloaded", timeout=20000)


def test_browser_navigate_truncation():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.evaluate.return_value = "A" * 9000
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_navigate("https://google.com")
        assert "[Content truncated...]" in res
        assert len(res) > 8000


def test_browser_navigate_reports_blank_or_error_page():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "about:blank"
    mock_page.evaluate.return_value = ""

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_navigate("example.invalid")
        assert "Successfully navigated to https://example.invalid" in res
        assert "blank or a browser error page" in res


def test_browser_click_success():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_click("button#submit")
        assert "Successfully clicked element 'button#submit'." in res
        mock_page.click.assert_called_once_with("button#submit", timeout=5000)


def test_browser_input_success():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        res = browser_input("input#search", "gold price")
        assert "Successfully entered text into 'input#search'." in res
        mock_page.fill.assert_called_once_with("input#search", "gold price", timeout=5000)


def test_browser_input_reports_verification_mismatch():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    locator = MagicMock()
    locator.input_value.return_value = "old value"
    mock_page.locator.return_value.first = locator

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_input("input#search", "gold price")
        assert "Failed to enter text into 'input#search'" in res
        assert "fill verification failed" in res


def test_browser_status_without_session():
    res = browser_status()
    assert "Browser session: not started" in res
    assert "Last action: none" in res


def test_browser_status_reports_last_action():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "https://example.com"
    mock_page.title.return_value = "Example"
    mock_page.evaluate.side_effect = ["Ready text", "complete"]

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        browser_navigate("example.com")
        res = browser_status()
        assert "Browser session: alive" in res
        assert "URL: https://example.com" in res
        assert "Title: Example" in res
        assert "Last action: browser_navigate (success)" in res


def test_browser_recovers_closed_active_page_from_context():
    import verse.tools.builtin.browser as b

    closed_page = MagicMock()
    closed_page.is_closed.return_value = True
    open_page = MagicMock()
    open_page.is_closed.return_value = False
    open_page.url = "https://example.com/recovered"
    open_page.evaluate.return_value = "Recovered text"

    mock_context = MagicMock()
    mock_context.pages = [closed_page, open_page]
    b._context = mock_context
    b._page = closed_page

    mock_pw_instance = MagicMock()

    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance

        res = browser_status()
        assert "Browser session: alive" in res
        assert "https://example.com/recovered" in res
        assert b._page is open_page
        mock_pw_instance.chromium.launch_persistent_context.assert_not_called()


def test_browser_close_success():
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    
    mock_context = MagicMock()
    mock_context.pages = [mock_page]
    
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context
    
    with patch("verse.tools.builtin.browser.sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.start.return_value = mock_pw_instance
        
        # Open browser first
        browser_navigate("google.com")
        
        # Now close it
        res = browser_close()
        assert "Browser session closed successfully." in res
        mock_context.close.assert_called_once()
        mock_pw_instance.stop.assert_called_once()
