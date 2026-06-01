from unittest.mock import MagicMock, patch
import pytest
import os
from verse.tools.builtin.browser import (
    _find_brave_executable,
    browser_navigate,
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
    yield
    # Cleanup after test
    b._playwright = None
    b._context = None
    b._page = None


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
