from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright

_playwright: Playwright | None = None
_context: BrowserContext | None = None
_page: Page | None = None

# Playwright's sync API binds its objects to the thread that created them. The
# orchestrator runs tools via asyncio.to_thread(), whose default pool may schedule
# successive calls on DIFFERENT threads — using a page created on thread A from
# thread B raises "object used from a different thread". Pinning every browser call
# to a single dedicated worker thread guarantees thread affinity across a multi-step
# session (navigate -> inspect -> click -> ...).
_browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verse-browser")

_T = TypeVar("_T")


def _run_on_browser_thread(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Execute a browser operation on the single dedicated Playwright thread."""
    return _browser_executor.submit(fn, *args, **kwargs).result()


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
    global _playwright, _context, _page
    if _page is not None and not _page.is_closed():
        return _page

    if _playwright is None:
        _playwright = sync_playwright().start()

    brave_path = _find_brave_executable()
    launch_kwargs = {}
    if brave_path:
        launch_kwargs["executable_path"] = brave_path

    # User profile directory in ~/.verse/browser_profile
    user_data_dir = os.path.expanduser("~/.verse/browser_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    # Launch browser headfully (headless=False) so it is visible to the user
    _context = _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        no_viewport=False,
        **launch_kwargs
    )
    
    if _context.pages:
        _page = _context.pages[0]
    else:
        _page = _context.new_page()
    return _page


def _browser_navigate_impl(url: str) -> str:
    """Navigate to a URL and return the cleaned textual contents of the page."""
    try:
        page = _ensure_browser()
        target = url.strip()
        if "://" not in target:
            target = f"https://{target}"

        page.goto(target, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)  # Brief settle for SPA/dynamic content

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


def _browser_click_impl(selector: str) -> str:
    """Click an element on the current page specified by selector (e.g. CSS selector, numeric ID, text, etc.)."""
    try:
        page = _ensure_browser()
        target_selector = selector.strip()
        if target_selector.isdigit():
            target_selector = f"[data-verse-id='{target_selector}']"
        page.click(target_selector, timeout=5000)
        page.wait_for_timeout(2000)
        return f"Successfully clicked element '{selector}'."
    except Exception as exc:
        return f"Failed to click element '{selector}': {exc}"


def _browser_input_impl(selector: str, text: str) -> str:
    """Type text into an input field specified by selector on the current page."""
    try:
        page = _ensure_browser()
        target_selector = selector.strip()
        if target_selector.isdigit():
            target_selector = f"[data-verse-id='{target_selector}']"
        page.fill(target_selector, text, timeout=5000)
        page.wait_for_timeout(1000)
        return f"Successfully entered text into '{selector}'."
    except Exception as exc:
        return f"Failed to enter text into '{selector}': {exc}"


def _browser_close_impl() -> str:
    """Close the active browser session and release all associated processes."""
    global _playwright, _context, _page
    if _context is not None:
        try:
            _context.close()
        except Exception:
            pass
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
    _playwright = None
    _context = None
    _page = None
    return "Browser session closed successfully."


def _browser_inspect_impl() -> str:
    """Inspect the current page, assign numeric IDs to all visible interactive elements,
    render visual badges on the page, and return a text summary of these elements."""
    try:
        page = _ensure_browser()
        
        # JS script to tag visible interactive elements and collect metadata
        script = """
        () => {
            // Remove existing badges
            document.querySelectorAll('.verse-element-badge').forEach(b => b.remove());
            
            // Inject CSS styles if missing
            let styleEl = document.getElementById('verse-badge-styles');
            if (!styleEl) {
                styleEl = document.createElement('style');
                styleEl.id = 'verse-badge-styles';
                styleEl.innerHTML = `
                    .verse-element-badge {
                        position: absolute;
                        background-color: #ff3366 !important;
                        color: white !important;
                        font-size: 11px !important;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
                        font-weight: bold !important;
                        padding: 2px 5px !important;
                        border-radius: 4px !important;
                        box-shadow: 0 2px 5px rgba(0,0,0,0.3) !important;
                        z-index: 100000000 !important;
                        pointer-events: none !important;
                        text-shadow: none !important;
                        border: 1px solid white !important;
                        line-height: 1 !important;
                    }
                `;
                document.head.appendChild(styleEl);
            }
            
            const interactiveSelector = 'a, button, input:not([type="hidden"]), textarea, select, [role="button"], [role="link"], [role="checkbox"], [contenteditable="true"], [contenteditable=""]';
            const allElements = Array.from(document.querySelectorAll(interactiveSelector));
            
            const visibleElements = allElements.filter(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) return false;
                
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                
                return true;
            });
            
            const results = [];
            let id = 1;
            
            visibleElements.forEach(el => {
                el.setAttribute('data-verse-id', String(id));
                
                // Calculate position for badge
                const rect = el.getBoundingClientRect();
                const badge = document.createElement('span');
                badge.className = 'verse-element-badge';
                badge.innerText = String(id);
                badge.style.top = (rect.top + window.scrollY) + 'px';
                badge.style.left = (rect.left + window.scrollX) + 'px';
                document.body.appendChild(badge);
                
                // Get display text
                let text = '';
                if (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea') {
                    text = el.value || '';
                } else {
                    text = el.innerText || el.textContent || '';
                }
                text = text.replace(/\\s+/g, ' ').trim();
                if (text.length > 60) text = text.substring(0, 57) + '...';
                
                results.push({
                    id: id,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    aria_label: el.getAttribute('aria-label') || '',
                    text: text
                });
                id++;
            });
            
            return results;
        }
        """
        
        elements = page.evaluate(script)
        if not elements:
            return "No interactive elements found on the current page."
            
        summary_lines = ["Interactive elements on the page:"]
        for el in elements:
            parts = []
            if el["name"]:
                parts.append(f'name="{el["name"]}"')
            if el["placeholder"]:
                parts.append(f'placeholder="{el["placeholder"]}"')
            if el["aria_label"]:
                parts.append(f'aria-label="{el["aria_label"]}"')
            if el["text"]:
                parts.append(f'text="{el["text"]}"')
            
            details = ", ".join(parts)
            summary_lines.append(f"[{el['id']}] {el['tag']}{' (' + el['type'] + ')' if el['type'] else ''} - {details}")
            
        return "\n".join(summary_lines)
    except Exception as exc:
        return f"Failed to inspect page: {exc}"


def _browser_scroll_impl(direction: str, amount: str = "window") -> str:
    """Scroll the current page in the specified direction ('up', 'down', 'top', 'bottom').
    The amount can be 'window' (scrolls one window height), 'half' (scrolls half window height), or a number of pixels."""
    try:
        page = _ensure_browser()
        
        # Resolve scroll amount in JS
        script = f"""
        () => {{
            let scrollPixels = 0;
            if ("{amount}" === "window") {{
                scrollPixels = window.innerHeight;
            }} else if ("{amount}" === "half") {{
                scrollPixels = window.innerHeight / 2;
            }} else {{
                let parsed = parseInt("{amount}", 10);
                scrollPixels = isNaN(parsed) ? window.innerHeight : parsed;
            }}
            
            if ("{direction}" === "down") {{
                window.scrollBy({{ top: scrollPixels, behavior: 'smooth' }});
            }} else if ("{direction}" === "up") {{
                window.scrollBy({{ top: -scrollPixels, behavior: 'smooth' }});
            }} else if ("{direction}" === "top") {{
                window.scrollTo({{ top: 0, behavior: 'smooth' }});
            }} else if ("{direction}" === "bottom") {{
                window.scrollTo({{ top: document.body.scrollHeight, behavior: 'smooth' }});
            }}
        }}
        """
        page.evaluate(script)
        page.wait_for_timeout(1000)  # Wait for smooth scroll to settle
        return f"Successfully scrolled page {direction} by {amount}."
    except Exception as exc:
        return f"Failed to scroll page: {exc}"


def _browser_go_back_impl() -> str:
    """Navigate back one step in the browser's history."""
    try:
        page = _ensure_browser()
        page.go_back(wait_until="domcontentloaded")
        page.wait_for_timeout(2000)  # Wait for page to render
        return "Successfully navigated back in history."
    except Exception as exc:
        return f"Failed to navigate back: {exc}"


# ----------------------------------------------------------------------------
# Public tool entrypoints — every call is pinned to the single browser thread so
# Playwright's thread-bound sync objects stay valid across a multi-step session.
# ----------------------------------------------------------------------------

def browser_navigate(url: str) -> str:
    return _run_on_browser_thread(_browser_navigate_impl, url)


def browser_click(selector: str) -> str:
    return _run_on_browser_thread(_browser_click_impl, selector)


def browser_input(selector: str, text: str) -> str:
    return _run_on_browser_thread(_browser_input_impl, selector, text)


def browser_close() -> str:
    return _run_on_browser_thread(_browser_close_impl)


def browser_inspect() -> str:
    return _run_on_browser_thread(_browser_inspect_impl)


def browser_scroll(direction: str, amount: str = "window") -> str:
    return _run_on_browser_thread(_browser_scroll_impl, direction, amount)


def browser_go_back() -> str:
    return _run_on_browser_thread(_browser_go_back_impl)
