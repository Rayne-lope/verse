from __future__ import annotations

import os
from typing import Any
from playwright.sync_api import sync_playwright, Browser, Page, Playwright

_playwright: Playwright | None = None
_browser: Browser | None = None
_page: Page | None = None


def _find_brave_executable() -> str:
    """Locate the Brave Browser executable on macOS."""
    paths = [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return ""


def _ensure_browser() -> Page:
    """Lazily initialize and return the persistent browser context."""
    global _playwright, _browser, _page
    if _page is not None and not _page.is_closed():
        return _page

    if _playwright is None:
        _playwright = sync_playwright().start()

    brave_path = _find_brave_executable()
    launch_kwargs = {}
    if brave_path:
        launch_kwargs["executable_path"] = brave_path

    # Launch browser (headless by default for background performance)
    _browser = _playwright.chromium.launch(headless=True, **launch_kwargs)
    _page = _browser.new_page()
    return _page


def browser_navigate(url: str) -> str:
    """Navigate to a URL and return the cleaned textual contents of the page."""
    try:
        page = _ensure_browser()
        target = url.strip()
        if "://" not in target:
            target = f"https://{target}"

        page.goto(target, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)  # Wait for SPA/dynamic content to load

        # Clean non-text tags and return page body
        content = page.evaluate("""() => {
            const selectors = ['script', 'style', 'svg', 'noscript', 'iframe'];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.remove());
            });
            return document.body.innerText;
        }""")

        cleaned = "\n".join(line.strip() for line in content.splitlines() if line.strip())
        if len(cleaned) > 8000:
            cleaned = cleaned[:8000] + "\n\n[Content truncated...]"
        return f"Successfully navigated to {target}.\n\nPage Content:\n{cleaned}"
    except Exception as exc:
        return f"Failed to navigate to {url}: {exc}"


def browser_click(selector: str) -> str:
    """Click an element on the current page specified by selector (e.g. CSS selector, text, etc.)."""
    try:
        page = _ensure_browser()
        page.click(selector, timeout=5000)
        page.wait_for_timeout(2000)
        return f"Successfully clicked element '{selector}'."
    except Exception as exc:
        return f"Failed to click element '{selector}': {exc}"


def browser_input(selector: str, text: str) -> str:
    """Type text into an input field specified by selector on the current page."""
    try:
        page = _ensure_browser()
        page.fill(selector, text, timeout=5000)
        page.wait_for_timeout(1000)
        return f"Successfully entered text into '{selector}'."
    except Exception as exc:
        return f"Failed to enter text into '{selector}': {exc}"


def browser_close() -> str:
    """Close the active browser session and release all associated processes."""
    global _playwright, _browser, _page
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
    _playwright = None
    _browser = None
    _page = None
    return "Browser session closed successfully."
