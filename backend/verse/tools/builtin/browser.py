from __future__ import annotations

import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright

_playwright: Playwright | None = None
_context: BrowserContext | None = None
_page: Page | None = None
_last_browser_result: dict[str, Any] = {
    "action": "none",
    "status": "unknown",
    "message": "No browser action has run yet.",
}

# Playwright's sync API binds its objects to the thread that created them. The
# orchestrator runs tools via asyncio.to_thread(), whose default pool may schedule
# successive calls on DIFFERENT threads — using a page created on thread A from
# thread B raises "object used from a different thread". Pinning every browser call
# to a single dedicated worker thread guarantees thread affinity across a multi-step
# session (navigate -> inspect -> click -> ...).
_browser_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verse-browser")

_T = TypeVar("_T")

WHATSAPP_WEB_URL = "https://web.whatsapp.com/"
WHATSAPP_SEARCH_SELECTORS = (
    "div[contenteditable='true'][data-tab='3']",
    "div[role='textbox'][aria-label*='Search']",
    "div[role='textbox'][aria-label*='Cari']",
    "div[contenteditable='true'][aria-label*='Search']",
    "div[contenteditable='true'][aria-label*='Cari']",
)
WHATSAPP_COMPOSE_SELECTORS = (
    "footer div[contenteditable='true'][role='textbox']",
    "footer div[contenteditable='true']",
    "div[role='textbox'][aria-label*='Type a message']",
    "div[role='textbox'][aria-label*='Ketik pesan']",
    "div[contenteditable='true'][aria-label*='Type a message']",
    "div[contenteditable='true'][aria-label*='Ketik pesan']",
)

SUBMIT_LABELS = (
    "submit", "send", "login", "continue", "search",
    "kirim", "masuk", "lanjut", "cari",
)

ERROR_PAGE_MARKERS = (
    "chrome-error://",
    "about:blank",
)


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


def _page_is_usable(page: Page | None) -> bool:
    if page is None:
        return False
    try:
        return not page.is_closed()
    except Exception:
        return False


def _context_pages(context: BrowserContext | None) -> list[Page]:
    if context is None:
        return []
    try:
        pages = getattr(context, "pages", [])
        return list(pages) if isinstance(pages, list) else []
    except Exception:
        return []


def _safe_page_url(page: Page | None) -> str:
    if page is None:
        return ""
    try:
        value = getattr(page, "url", "") or ""
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def _safe_page_title(page: Page | None) -> str:
    if page is None:
        return ""
    try:
        title = page.title()
        return title if isinstance(title, str) else ""
    except Exception:
        return ""


def _safe_wait_for_load(page: Page, state: str = "domcontentloaded", timeout: int = 3000) -> None:
    try:
        page.wait_for_load_state(state, timeout=timeout)
    except Exception:
        try:
            page.wait_for_timeout(min(timeout, 1000))
        except Exception:
            pass


def _settle_page(page: Page, *, timeout_ms: int = 1000) -> None:
    _safe_wait_for_load(page, timeout=timeout_ms)
    try:
        page.wait_for_timeout(min(timeout_ms, 1000))
    except Exception:
        pass


def _page_info(page: Page | None) -> dict[str, str]:
    return {
        "url": _safe_page_url(page),
        "title": _safe_page_title(page),
    }


def _page_readiness(page: Page | None, content: str = "") -> str:
    if page is None:
        return "not_started"
    if not _page_is_usable(page):
        return "closed"
    if _looks_like_error_page(page, content):
        return "error_or_blank"
    try:
        state = page.evaluate("() => document.readyState")
        if isinstance(state, str) and state:
            return state
    except Exception:
        pass
    return "unknown"


def _record_browser_result(action: str, status: str, message: str, page: Page | None = None) -> str:
    global _last_browser_result
    info = _page_info(page)
    _last_browser_result = {
        "action": action,
        "status": status,
        "message": message,
        **info,
    }
    return message


def _normalize_navigation_target(raw: str) -> str:
    target = (raw or "").strip()
    if not target:
        return ""
    if "://" in target:
        return target
    if target.startswith("www."):
        return f"https://{target}"
    if re.search(r"\s", target) or not re.search(r"(\.|localhost|:\d+)", target, flags=re.IGNORECASE):
        query = urllib.parse.quote_plus(target)
        return f"https://www.google.com/search?q={query}"
    return f"https://{target}"


def _looks_like_error_page(page: Page, content: str = "") -> bool:
    url = _safe_page_url(page).lower()
    if any(marker in url for marker in ERROR_PAGE_MARKERS):
        return True
    lowered = content.lower()
    return any(
        marker in lowered
        for marker in (
            "this site can't be reached",
            "this site can’t be reached",
            "dns_probe",
            "err_name_not_resolved",
            "situs ini tidak dapat dijangkau",
        )
    )


def _format_page_header(prefix: str, page: Page, *, fallback_url: str = "") -> str:
    final_url = _safe_page_url(page) or fallback_url
    title = _safe_page_title(page)
    lines = [prefix]
    if final_url:
        lines.append(f"URL: {final_url}")
    if title:
        lines.append(f"Title: {title}")
    return "\n".join(lines)


def _ensure_browser() -> Page:
    """Lazily initialize and return the persistent browser context."""
    global _playwright, _context, _page
    if _page_is_usable(_page):
        return _page

    if _playwright is None:
        _playwright = sync_playwright().start()

    for candidate in reversed(_context_pages(_context)):
        if _page_is_usable(candidate):
            _page = candidate
            return _page

    brave_path = _find_brave_executable()
    launch_kwargs = {}
    if brave_path:
        launch_kwargs["executable_path"] = brave_path

    # User profile directory in ~/.verse/browser_profile
    user_data_dir = os.path.expanduser("~/.verse/browser_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    # Launch browser headfully (headless=False) so it is visible to the user
    if _context is None:
        _context = _playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            no_viewport=False,
            **launch_kwargs
        )
    
    pages = _context_pages(_context)
    open_pages = [page for page in pages if _page_is_usable(page)]
    if open_pages:
        _page = open_pages[-1]
    else:
        try:
            _page = _context.new_page()
        except Exception:
            _context = _playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                no_viewport=False,
                **launch_kwargs
            )
            _page = _context.new_page()
    return _page


def _extract_visible_text(page: Page) -> str:
    chunks: list[str] = []
    try:
        content = page.evaluate("""() => {
            const body = document.body;
            if (!body) return "";
            return body.innerText || body.textContent || "";
        }""")
        if isinstance(content, str) and content.strip():
            chunks.append(content)
    except Exception:
        pass

    frames = getattr(page, "frames", [])
    if isinstance(frames, list):
        for frame in frames:
            if frame is page:
                continue
            try:
                frame_text = frame.evaluate("""() => {
                    const body = document.body;
                    if (!body) return "";
                    return body.innerText || body.textContent || "";
                }""")
                if isinstance(frame_text, str) and frame_text.strip():
                    chunks.append(frame_text)
            except Exception:
                continue

    content = "\n".join(chunks)
    cleaned = "\n".join(line.strip() for line in content.splitlines() if line.strip())
    if len(cleaned) > 8000:
        cleaned = cleaned[:8000] + "\n\n[Content truncated...]"
    return cleaned


def _normalized_visible_text(page: Page) -> str:
    try:
        return _extract_visible_text(page).lower()
    except Exception:
        return ""


def _whatsapp_page_state(page: Page) -> str:
    text = _normalized_visible_text(page)
    login_markers = (
        "scan this qr code",
        "use whatsapp on your computer",
        "link a device",
        "pindai kode qr",
        "tautkan perangkat",
        "gunakan whatsapp di komputer",
    )
    ready_markers = (
        "search or start new chat",
        "cari atau mulai chat",
        "type a message",
        "ketik pesan",
        "chats",
        "chat",
    )
    if any(marker in text for marker in login_markers):
        return "login_required"
    if any(marker in text for marker in ready_markers):
        return "ready"
    return "unknown"


def _ensure_whatsapp_page() -> tuple[Page, str]:
    page = _ensure_browser()
    current_url = _safe_page_url(page).lower()
    if "web.whatsapp.com" not in current_url:
        page.goto(WHATSAPP_WEB_URL, wait_until="domcontentloaded", timeout=20000)
        _settle_page(page, timeout_ms=2500)
    return page, _whatsapp_page_state(page)


def _fill_first_available(page: Page, selectors: tuple[str, ...], text: str, *, timeout: int = 5000) -> tuple[str, Any]:
    last_error: Exception | None = None
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.click(timeout=timeout)
            locator.fill(text, timeout=timeout)
            try:
                actual = locator.input_value(timeout=1000)
                if isinstance(actual, str) and actual != text:
                    raise RuntimeError(f"field value is {actual!r}, expected {text!r}")
            except Exception:
                pass
            return selector, locator
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"No matching input was available: {last_error}")


def _click_matching_chat(page: Page, contact: str) -> None:
    try:
        page.get_by_text(contact, exact=False).first.click(timeout=8000)
        return
    except Exception:
        pass

    safe_contact = contact.replace("\\", "\\\\").replace('"', '\\"')
    page.locator(f'span[title="{safe_contact}"]').first.click(timeout=8000)


def _press_enter(locator: Any, *, timeout: int = 5000) -> None:
    try:
        locator.press("Enter", timeout=timeout)
    except TypeError:
        locator.press("Enter")


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _element_search_text(element: dict[str, Any]) -> str:
    parts = [
        element.get("text"),
        element.get("aria_label"),
        element.get("placeholder"),
        element.get("name"),
        element.get("label"),
        element.get("role"),
        element.get("tag"),
        element.get("type"),
    ]
    return _normalize_match_text(" ".join(str(part or "") for part in parts))


def _collect_interactive_elements(
    page: Page,
    *,
    badge: bool = False,
    include_frames: bool = False,
) -> list[dict[str, Any]]:
    """Collect visible interactive elements and optionally render numeric badges."""
    script = """
    (badge) => {
        document.querySelectorAll('.verse-element-badge').forEach(b => b.remove());

        if (badge) {
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
        }

        const interactiveSelector = [
            'a',
            'button',
            'input:not([type="hidden"])',
            'textarea',
            'select',
            '[role="button"]',
            '[role="link"]',
            '[role="checkbox"]',
            '[role="radio"]',
            '[role="textbox"]',
            '[role="combobox"]',
            '[contenteditable="true"]',
            '[contenteditable=""]'
        ].join(', ');
        const allElements = Array.from(document.querySelectorAll(interactiveSelector));

        const labelFor = (el) => {
            const labels = [];
            if (el.id) {
                document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`).forEach(label => {
                    const text = (label.innerText || label.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (text) labels.push(text);
                });
            }
            let parent = el.closest('label');
            if (parent) {
                const text = (parent.innerText || parent.textContent || '').replace(/\\s+/g, ' ').trim();
                if (text) labels.push(text);
            }
            const aria = el.getAttribute('aria-labelledby');
            if (aria) {
                aria.split(/\\s+/).forEach(id => {
                    const node = document.getElementById(id);
                    const text = node ? (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
                    if (text) labels.push(text);
                });
            }
            return [...new Set(labels)].join(' ');
        };

        const implicitRole = (el) => {
            const explicit = el.getAttribute('role') || '';
            if (explicit) return explicit;
            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute('type') || '').toLowerCase();
            if (tag === 'button') return 'button';
            if (tag === 'a') return 'link';
            if (tag === 'textarea') return 'textbox';
            if (tag === 'select') return 'combobox';
            if (tag === 'input') {
                if (type === 'checkbox') return 'checkbox';
                if (type === 'radio') return 'radio';
                if (type === 'submit' || type === 'button') return 'button';
                return 'textbox';
            }
            if (el.isContentEditable) return 'textbox';
            return '';
        };

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
            const rect = el.getBoundingClientRect();

            if (badge) {
                const badgeEl = document.createElement('span');
                badgeEl.className = 'verse-element-badge';
                badgeEl.innerText = String(id);
                badgeEl.style.top = (rect.top + window.scrollY) + 'px';
                badgeEl.style.left = (rect.left + window.scrollX) + 'px';
                document.body.appendChild(badgeEl);
            }

            let text = '';
            const tag = el.tagName.toLowerCase();
            if (tag === 'input' || tag === 'textarea') {
                text = el.value || '';
            } else {
                text = el.innerText || el.textContent || '';
            }
            text = text.replace(/\\s+/g, ' ').trim();
            if (text.length > 80) text = text.substring(0, 77) + '...';

            results.push({
                id,
                tag,
                role: implicitRole(el),
                type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '',
                placeholder: el.getAttribute('placeholder') || '',
                aria_label: el.getAttribute('aria-label') || '',
                label: labelFor(el),
                text,
                visible: true,
                bounding_box: {
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height
                }
            });
            id++;
        });

        return results;
    }
    """
    elements = page.evaluate(script, badge)
    results = elements if isinstance(elements, list) else []
    if not include_frames:
        return results

    next_id = len(results) + 1
    frames = getattr(page, "frames", [])
    if isinstance(frames, list):
        for frame in frames:
            if frame is page:
                continue
            try:
                frame_elements = frame.evaluate(script, False)
            except Exception:
                continue
            if not isinstance(frame_elements, list):
                continue
            for element in frame_elements:
                if not isinstance(element, dict):
                    continue
                element["id"] = next_id
                element["frame"] = True
                next_id += 1
                results.append(element)
    return results


def _summarize_elements(elements: list[dict[str, Any]], *, limit: int = 5) -> str:
    if not elements:
        return "No candidates found."
    lines = []
    for element in elements[:limit]:
        parts = []
        if element.get("role"):
            parts.append(f'role="{element["role"]}"')
        if element.get("name"):
            parts.append(f'name="{element["name"]}"')
        if element.get("placeholder"):
            parts.append(f'placeholder="{element["placeholder"]}"')
        if element.get("aria_label"):
            parts.append(f'aria-label="{element["aria_label"]}"')
        if element.get("label"):
            parts.append(f'label="{element["label"]}"')
        if element.get("text"):
            parts.append(f'text="{element["text"]}"')
        details = ", ".join(parts) or "no text metadata"
        lines.append(f"[{element.get('id')}] {element.get('tag', 'element')} - {details}")
    return "\n".join(lines)


def _score_element(query: str, element: dict[str, Any]) -> int:
    normalized_query = _normalize_match_text(query)
    if not normalized_query:
        return 0

    weighted_fields = (
        ("text", 95),
        ("aria_label", 90),
        ("label", 90),
        ("placeholder", 80),
        ("name", 70),
        ("role", 45),
        ("tag", 30),
        ("type", 25),
    )
    score = 0
    for field, weight in weighted_fields:
        value = _normalize_match_text(element.get(field))
        if not value:
            continue
        if value == normalized_query:
            score = max(score, weight + 35)
        elif normalized_query in value:
            score = max(score, weight + 15)
        elif value in normalized_query:
            score = max(score, weight)

    haystack = _element_search_text(element)
    query_tokens = set(normalized_query.split())
    haystack_tokens = set(haystack.split())
    if query_tokens:
        overlap = len(query_tokens & haystack_tokens)
        score += min(35, overlap * 10)

    role = _normalize_match_text(element.get("role"))
    if any(token in normalized_query for token in ("klik", "click", "tombol", "button")) and role == "button":
        score += 10
    if any(token in normalized_query for token in ("link", "tautan")) and role == "link":
        score += 10
    return score


def _rank_elements(query: str, elements: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    ranked = [(_score_element(query, element), element) for element in elements]
    ranked = [(score, element) for score, element in ranked if score > 0]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _click_element_by_id(page: Page, element: dict[str, Any], original_query: str) -> str:
    element_id = element.get("id")
    if element_id is None:
        return f"Failed to click best match for '{original_query}': element has no verse id."
    _click_selector_verified(
        page,
        f"[data-verse-id='{element_id}']",
        f"best match for '{original_query}'",
        timeout=5000,
    )
    return f"Successfully clicked best match for '{original_query}': [{element_id}] {element.get('tag', 'element')}."


def _fallback_click_best_match(page: Page, query: str, *, role: str | None = None) -> str:
    elements = _collect_interactive_elements(page)
    if role:
        normalized_role = _normalize_match_text(role)
        elements = [
            element for element in elements
            if _normalize_match_text(element.get("role")) == normalized_role
        ]
    ranked = _rank_elements(query, elements)
    if not ranked:
        return f"Failed to click best match for '{query}': no matching interactive element found."

    top_score, top = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if top_score < 70:
        candidates = _summarize_elements([element for _, element in ranked])
        return f"Failed to click best match for '{query}': no confident match.\nCandidates:\n{candidates}"
    if second_score >= top_score - 8:
        candidates = _summarize_elements([element for _, element in ranked])
        return f"Failed to click best match for '{query}': match is ambiguous.\nCandidates:\n{candidates}"
    return _click_element_by_id(page, top, query)


def _is_truthy_form_value(value: str) -> bool:
    return _normalize_match_text(value) in ("true", "yes", "y", "on", "1", "checked", "aktif")


def _is_falsy_form_value(value: str) -> bool:
    return _normalize_match_text(value) in ("false", "no", "n", "off", "0", "unchecked", "mati")


def _read_selector_value(page: Page, selector: str) -> str | None:
    try:
        locator = page.locator(selector).first
    except Exception:
        locator = None

    if locator is not None:
        try:
            value = locator.input_value(timeout=1000)
            if isinstance(value, str):
                return value
        except Exception:
            pass
        try:
            value = locator.evaluate(
                """(el) => {
                    if ('value' in el) return el.value || '';
                    if (el.isContentEditable) return el.innerText || el.textContent || '';
                    return el.textContent || '';
                }"""
            )
            if isinstance(value, str):
                return value
        except Exception:
            pass

    try:
        value = page.evaluate(
            """(selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                if ('value' in el) return el.value || '';
                if (el.isContentEditable) return el.innerText || el.textContent || '';
                return el.textContent || '';
            }""",
            selector,
        )
        return value if isinstance(value, str) else None
    except Exception:
        return None


def _is_selector_checked(page: Page, selector: str) -> bool | None:
    try:
        locator = page.locator(selector).first
        checked = locator.is_checked(timeout=1000)
        if isinstance(checked, bool):
            return checked
    except Exception:
        pass
    try:
        checked = page.evaluate(
            """(selector) => {
                const el = document.querySelector(selector);
                return el && 'checked' in el ? Boolean(el.checked) : null;
            }""",
            selector,
        )
        return checked if isinstance(checked, bool) else None
    except Exception:
        return None


def _click_selector_verified(page: Page, selector: str, label: str, *, timeout: int = 5000) -> str:
    before_url = _safe_page_url(page)
    try:
        page.click(selector, timeout=timeout)
    except Exception as first_exc:
        try:
            locator = page.locator(selector).first
            try:
                locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            locator.click(timeout=timeout)
        except Exception as second_exc:
            try:
                page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) throw new Error('Element not found');
                        if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
                            throw new Error('Element is disabled');
                        }
                        el.click();
                    }""",
                    selector,
                )
            except Exception as third_exc:
                raise RuntimeError(
                    f"primary click failed: {first_exc}; locator fallback failed: "
                    f"{second_exc}; js fallback failed: {third_exc}"
                ) from third_exc

    _settle_page(page, timeout_ms=1000)
    after_url = _safe_page_url(page)
    if before_url and after_url and before_url != after_url:
        return f"Successfully clicked {label}. URL changed to {after_url}."
    return f"Successfully clicked {label}."


def _click_locator_verified(page: Page, locator: Any, label: str, *, timeout: int = 5000) -> str:
    before_url = _safe_page_url(page)
    try:
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        locator.click(timeout=timeout)
    except TypeError:
        locator.click()
    _settle_page(page, timeout_ms=1000)
    after_url = _safe_page_url(page)
    if before_url and after_url and before_url != after_url:
        return f"Successfully clicked {label}. URL changed to {after_url}."
    return f"Successfully clicked {label}."


def _fill_selector_verified(page: Page, selector: str, text: str, label: str, *, timeout: int = 5000) -> str:
    try:
        page.fill(selector, text, timeout=timeout)
    except Exception as first_exc:
        try:
            locator = page.locator(selector).first
            try:
                locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            locator.fill(text, timeout=timeout)
        except Exception as second_exc:
            raise RuntimeError(
                f"primary fill failed: {first_exc}; locator fallback failed: {second_exc}"
            ) from second_exc

    actual = _read_selector_value(page, selector)
    if actual is not None and actual != text:
        raise RuntimeError(f"fill verification failed: field value is {actual!r}, expected {text!r}")
    _settle_page(page, timeout_ms=500)
    return f"Successfully entered text into {label}."


def _verify_field_value(page: Page, selector: str, expected: str) -> str:
    actual = _read_selector_value(page, selector)
    if actual is None:
        return ""
    if actual == expected:
        return ""
    return f" verification failed: field value is {actual!r}, expected {expected!r}."


def _browser_status_impl() -> str:
    global _page
    page = _page if _page_is_usable(_page) else None
    if page is None:
        page = next((candidate for candidate in reversed(_context_pages(_context)) if _page_is_usable(candidate)), None)
        if page is not None:
            _page = page

    if page is None:
        return (
            "Browser session: not started or no active page.\n"
            f"Last action: {_last_browser_result.get('action')} "
            f"({_last_browser_result.get('status')}) - {_last_browser_result.get('message')}"
        )

    readiness = _page_readiness(page)
    info = _page_info(page)
    return (
        "Browser session: alive.\n"
        f"Readiness: {readiness}.\n"
        f"URL: {info['url'] or 'unknown'}.\n"
        f"Title: {info['title'] or 'unknown'}.\n"
        f"Last action: {_last_browser_result.get('action')} "
        f"({_last_browser_result.get('status')}) - {_last_browser_result.get('message')}"
    )


def _browser_navigate_impl(url: str) -> str:
    """Navigate to a URL and return the cleaned textual contents of the page."""
    try:
        page = _ensure_browser()
        target = _normalize_navigation_target(url)
        if not target:
            return _record_browser_result("browser_navigate", "failed", "Failed to navigate: URL or search query is required.", page)

        page.goto(target, wait_until="domcontentloaded", timeout=20000)
        _settle_page(page, timeout_ms=1500)

        cleaned = _extract_visible_text(page)
        header = _format_page_header(f"Successfully navigated to {target}.", page, fallback_url=target)
        if _looks_like_error_page(page, cleaned):
            message = f"{header}\n\nThe page appears to be blank or a browser error page."
            return _record_browser_result("browser_navigate", "failed", message, page)
        if not cleaned:
            message = f"{header}\n\nPage Content:\n[No visible text found.]"
            return _record_browser_result("browser_navigate", "success", message, page)
        message = f"{header}\n\nPage Content:\n{cleaned}"
        return _record_browser_result("browser_navigate", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_navigate", "failed", f"Failed to navigate to {url}: {exc}", _page)


def _browser_read_current_impl() -> str:
    """Read visible text from the active browser page without navigating."""
    try:
        page = _ensure_browser()
        _settle_page(page, timeout_ms=500)
        cleaned = _extract_visible_text(page)
        current_url = _safe_page_url(page) or "the current page"
        header = _format_page_header(f"Successfully read {current_url}.", page)
        if not cleaned:
            message = f"{header}\n\nPage Content:\n[No visible text found.]"
            return _record_browser_result("browser_read_current", "not_found", message, page)
        message = f"{header}\n\nPage Content:\n{cleaned}"
        return _record_browser_result("browser_read_current", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_read_current", "failed", f"Failed to read current page: {exc}", _page)


def _browser_click_impl(selector: str) -> str:
    """Click an element on the current page specified by selector (e.g. CSS selector, numeric ID, text, etc.)."""
    try:
        page = _ensure_browser()
        target_selector = selector.strip()
        if not target_selector:
            return _record_browser_result("browser_click", "failed", "Failed to click element: selector is required.", page)
        if target_selector.isdigit():
            target_selector = f"[data-verse-id='{target_selector}']"
        message = _click_selector_verified(page, target_selector, f"element '{selector}'", timeout=5000)
        return _record_browser_result("browser_click", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_click", "failed", f"Failed to click element '{selector}': {exc}", _page)


def _browser_input_impl(selector: str, text: str) -> str:
    """Type text into an input field specified by selector on the current page."""
    try:
        page = _ensure_browser()
        target_selector = selector.strip()
        if not target_selector:
            return _record_browser_result("browser_input", "failed", "Failed to enter text: selector is required.", page)
        if target_selector.isdigit():
            target_selector = f"[data-verse-id='{target_selector}']"
        message = _fill_selector_verified(page, target_selector, text, f"'{selector}'", timeout=5000)
        return _record_browser_result("browser_input", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_input", "failed", f"Failed to enter text into '{selector}': {exc}", _page)


def _browser_click_text_impl(text: str, exact: bool = False) -> str:
    """Click an element by visible text, falling back to metadata matching."""
    text = (text or "").strip()
    if not text:
        return _record_browser_result("browser_click_text", "failed", "Failed to click by text: text is required.", _page)
    try:
        page = _ensure_browser()
        try:
            message = _click_locator_verified(page, page.get_by_text(text, exact=exact).first, f"text '{text}'", timeout=5000)
            return _record_browser_result("browser_click_text", "success", message, page)
        except Exception:
            result = _fallback_click_best_match(page, text)
            status = "success" if result.startswith("Successfully") else ("ambiguous" if "ambiguous" in result.lower() else "not_found")
            return _record_browser_result("browser_click_text", status, result, page)
    except Exception as exc:
        return _record_browser_result("browser_click_text", "failed", f"Failed to click text '{text}': {exc}", _page)


def _browser_click_role_impl(role: str, name: str, exact: bool = False) -> str:
    """Click an element by accessibility role and accessible name."""
    role = (role or "").strip()
    name = (name or "").strip()
    if not role:
        return _record_browser_result("browser_click_role", "failed", "Failed to click by role: role is required.", _page)
    if not name:
        return _record_browser_result("browser_click_role", "failed", "Failed to click by role: name is required.", _page)
    try:
        page = _ensure_browser()
        try:
            message = _click_locator_verified(page, page.get_by_role(role, name=name, exact=exact).first, f"{role} '{name}'", timeout=5000)
            return _record_browser_result("browser_click_role", "success", message, page)
        except Exception:
            result = _fallback_click_best_match(page, name, role=role)
            status = "success" if result.startswith("Successfully") else ("ambiguous" if "ambiguous" in result.lower() else "not_found")
            return _record_browser_result("browser_click_role", status, result, page)
    except Exception as exc:
        return _record_browser_result("browser_click_role", "failed", f"Failed to click {role} '{name}': {exc}", _page)


def _browser_click_best_match_impl(query: str) -> str:
    """Click the best matching visible interactive element for a natural-language query."""
    query = (query or "").strip()
    if not query:
        return _record_browser_result("browser_click_best_match", "failed", "Failed to click best match: query is required.", _page)
    try:
        page = _ensure_browser()
        result = _fallback_click_best_match(page, query)
        status = "success" if result.startswith("Successfully") else ("ambiguous" if "ambiguous" in result.lower() else "not_found")
        return _record_browser_result("browser_click_best_match", status, result, page)
    except Exception as exc:
        return _record_browser_result("browser_click_best_match", "failed", f"Failed to click best match for '{query}': {exc}", _page)


def _fill_form_field(page: Page, target: str, value: str) -> str:
    elements = _collect_interactive_elements(page)
    fillable = []
    for element in elements:
        tag = _normalize_match_text(element.get("tag"))
        role = _normalize_match_text(element.get("role"))
        element_type = _normalize_match_text(element.get("type"))
        if (
            tag in ("input", "textarea", "select")
            or role in ("textbox", "combobox", "checkbox", "radio")
            or element_type in ("text", "email", "password", "search", "tel", "url", "number", "checkbox", "radio")
        ):
            fillable.append(element)

    ranked = _rank_elements(target, fillable)
    if not ranked:
        return f"Failed to fill '{target}': no matching field found."

    top_score, element = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if top_score < 60:
        return f"Failed to fill '{target}': no confident field match.\nCandidates:\n{_summarize_elements([item[1] for item in ranked])}"
    if second_score >= top_score - 8:
        return f"Failed to fill '{target}': field match is ambiguous.\nCandidates:\n{_summarize_elements([item[1] for item in ranked])}"

    element_id = element.get("id")
    if element_id is None:
        return f"Failed to fill '{target}': matched field has no verse id."

    selector = f"[data-verse-id='{element_id}']"
    tag = _normalize_match_text(element.get("tag"))
    role = _normalize_match_text(element.get("role"))
    element_type = _normalize_match_text(element.get("type"))

    if tag == "select" or role == "combobox":
        page.select_option(selector, value, timeout=5000)
        verification_error = _verify_field_value(page, selector, value)
        if verification_error:
            return f"Failed to fill '{target}':{verification_error}"
    elif element_type == "checkbox" or role == "checkbox":
        if _is_truthy_form_value(value):
            page.check(selector, timeout=5000)
            checked = _is_selector_checked(page, selector)
            if checked is False:
                return f"Failed to fill '{target}': checkbox did not become checked."
        elif _is_falsy_form_value(value):
            page.uncheck(selector, timeout=5000)
            checked = _is_selector_checked(page, selector)
            if checked is True:
                return f"Failed to fill '{target}': checkbox is still checked."
        else:
            return f"Failed to fill '{target}': checkbox value must be true/false/on/off."
    elif element_type == "radio" or role == "radio":
        if _is_falsy_form_value(value):
            return f"Failed to fill '{target}': radio fields can only be selected, not unset."
        page.check(selector, timeout=5000)
        checked = _is_selector_checked(page, selector)
        if checked is False:
            return f"Failed to fill '{target}': radio did not become selected."
    else:
        page.fill(selector, value, timeout=5000)
        verification_error = _verify_field_value(page, selector, value)
        if verification_error:
            return f"Failed to fill '{target}':{verification_error}"
    return f"Filled '{target}' with '{value}'."


def _browser_fill_form_impl(
    fields: list[dict[str, Any]],
    submit: bool = False,
    submit_label: str = "",
) -> str:
    """Fill multiple form fields by label/name/placeholder/aria text."""
    if not isinstance(fields, list) or not fields:
        return _record_browser_result("browser_fill_form", "failed", "Failed to fill form: fields must be a non-empty list.", _page)
    try:
        page = _ensure_browser()
        results: list[str] = []
        for field in fields:
            if not isinstance(field, dict):
                message = "Failed to fill form: each field must be an object with target and value."
                return _record_browser_result("browser_fill_form", "failed", message, page)
            target = str(field.get("target") or "").strip()
            value = str(field.get("value") or "")
            if not target:
                message = "Failed to fill form: every field needs a target."
                return _record_browser_result("browser_fill_form", "failed", message, page)
            result = _fill_form_field(page, target, value)
            results.append(result)
            if result.startswith("Failed"):
                return _record_browser_result("browser_fill_form", "failed", "\n".join(results), page)

        _settle_page(page, timeout_ms=500)
        if submit:
            labels = [submit_label.strip()] if submit_label.strip() else list(SUBMIT_LABELS)
            submit_result = ""
            for label in labels:
                submit_result = _fallback_click_best_match(page, label, role="button")
                if submit_result.startswith("Successfully"):
                    break
            results.append(f"Submit result: {submit_result}")
            if not submit_result.startswith("Successfully"):
                return _record_browser_result("browser_fill_form", "failed", "\n".join(results), page)

        message = "Successfully filled form.\n" + "\n".join(results)
        return _record_browser_result("browser_fill_form", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_fill_form", "failed", f"Failed to fill form: {exc}", _page)


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
    return _record_browser_result("browser_close", "success", "Browser session closed successfully.", None)


def _browser_inspect_impl() -> str:
    """Inspect the current page, assign numeric IDs to all visible interactive elements,
    render visual badges on the page, and return a text summary of these elements."""
    try:
        page = _ensure_browser()
        elements = _collect_interactive_elements(page, badge=True, include_frames=True)
        if not elements:
            message = "No interactive elements found on the current page."
            return _record_browser_result("browser_inspect", "not_found", message, page)
            
        summary_lines = ["Interactive elements on the page:"]
        for el in elements:
            parts = []
            if el["name"]:
                parts.append(f'name="{el["name"]}"')
            if el["placeholder"]:
                parts.append(f'placeholder="{el["placeholder"]}"')
            if el["aria_label"]:
                parts.append(f'aria-label="{el["aria_label"]}"')
            if el.get("label"):
                parts.append(f'label="{el["label"]}"')
            if el.get("role"):
                parts.append(f'role="{el["role"]}"')
            if el["text"]:
                parts.append(f'text="{el["text"]}"')
            
            details = ", ".join(parts)
            summary_lines.append(f"[{el['id']}] {el['tag']}{' (' + el['type'] + ')' if el['type'] else ''} - {details}")
            
        message = "\n".join(summary_lines)
        return _record_browser_result("browser_inspect", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_inspect", "failed", f"Failed to inspect page: {exc}", _page)


def _browser_scroll_impl(direction: str, amount: str = "window") -> str:
    """Scroll the current page in the specified direction ('up', 'down', 'top', 'bottom').
    The amount can be 'window' (scrolls one window height), 'half' (scrolls half window height), or a number of pixels."""
    try:
        page = _ensure_browser()
        direction = (direction or "").strip().lower()
        amount = (amount or "window").strip().lower()
        if direction not in {"up", "down", "top", "bottom"}:
            message = "Failed to scroll page: direction must be up, down, top, or bottom."
            return _record_browser_result("browser_scroll", "failed", message, page)
        
        # Resolve scroll amount in JS
        safe_direction = repr(direction).replace("'", '"')
        safe_amount = repr(amount).replace("'", '"')
        script = f"""
        () => {{
            const before = window.scrollY;
            let scrollPixels = 0;
            if ({safe_amount} === "window") {{
                scrollPixels = window.innerHeight;
            }} else if ({safe_amount} === "half") {{
                scrollPixels = window.innerHeight / 2;
            }} else {{
                let parsed = parseInt({safe_amount}, 10);
                scrollPixels = isNaN(parsed) ? window.innerHeight : parsed;
            }}
            
            if ({safe_direction} === "down") {{
                window.scrollBy({{ top: scrollPixels, behavior: 'instant' }});
            }} else if ({safe_direction} === "up") {{
                window.scrollBy({{ top: -scrollPixels, behavior: 'instant' }});
            }} else if ({safe_direction} === "top") {{
                window.scrollTo({{ top: 0, behavior: 'instant' }});
            }} else if ({safe_direction} === "bottom") {{
                window.scrollTo({{ top: document.body.scrollHeight, behavior: 'instant' }});
            }}
            return {{ before, after: window.scrollY }};
        }}
        """
        result = page.evaluate(script)
        page.wait_for_timeout(1000)  # Wait for smooth scroll to settle
        message = f"Successfully scrolled page {direction} by {amount}."
        if isinstance(result, dict):
            before = result.get("before")
            after = result.get("after")
            if isinstance(before, (int, float)) and isinstance(after, (int, float)) and before == after:
                message = f"Failed to scroll page {direction} by {amount}: scroll position did not change."
                return _record_browser_result("browser_scroll", "failed", message, page)
        return _record_browser_result("browser_scroll", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_scroll", "failed", f"Failed to scroll page: {exc}", _page)


def _browser_go_back_impl() -> str:
    """Navigate back one step in the browser's history."""
    try:
        page = _ensure_browser()
        before_url = _safe_page_url(page)
        response = page.go_back(wait_until="domcontentloaded")
        _settle_page(page, timeout_ms=1500)
        after_url = _safe_page_url(page)
        if response is None and before_url and after_url and before_url == after_url:
            message = "Failed to navigate back: browser history did not change."
            return _record_browser_result("browser_go_back", "failed", message, page)
        message = "Successfully navigated back in history."
        if after_url:
            message += f" URL: {after_url}."
        return _record_browser_result("browser_go_back", "success", message, page)
    except Exception as exc:
        return _record_browser_result("browser_go_back", "failed", f"Failed to navigate back: {exc}", _page)


def _whatsapp_open_impl() -> str:
    """Open WhatsApp Web and report whether the user is logged in."""
    try:
        page = _ensure_browser()
        page.goto(WHATSAPP_WEB_URL, wait_until="domcontentloaded", timeout=20000)
        _settle_page(page, timeout_ms=2500)
        state = _whatsapp_page_state(page)
        if state == "login_required":
            message = "WhatsApp Web opened, but login is required. Please scan the QR code first."
            return _record_browser_result("whatsapp_open", "login_required", message, page)
        if state == "ready":
            message = "WhatsApp Web is open and ready."
            return _record_browser_result("whatsapp_open", "success", message, page)
        message = "WhatsApp Web opened. I could not confirm whether it is ready yet."
        return _record_browser_result("whatsapp_open", "unknown", message, page)
    except Exception as exc:
        return _record_browser_result("whatsapp_open", "failed", f"Failed to open WhatsApp Web: {exc}", _page)


def _whatsapp_find_chat_impl(contact: str) -> str:
    """Open a matching chat in WhatsApp Web."""
    contact = (contact or "").strip()
    if not contact:
        return _record_browser_result("whatsapp_find_chat", "failed", "Failed to find WhatsApp chat: contact is required.", _page)
    try:
        page, state = _ensure_whatsapp_page()
        if state == "login_required":
            message = "WhatsApp Web login is required. Please scan the QR code first."
            return _record_browser_result("whatsapp_find_chat", "login_required", message, page)

        _fill_first_available(page, WHATSAPP_SEARCH_SELECTORS, contact, timeout=7000)
        page.wait_for_timeout(1000)
        _click_matching_chat(page, contact)
        _settle_page(page, timeout_ms=1000)
        message = f"Opened WhatsApp chat with {contact}."
        return _record_browser_result("whatsapp_find_chat", "success", message, page)
    except Exception as exc:
        return _record_browser_result("whatsapp_find_chat", "failed", f"Failed to find WhatsApp chat for {contact}: {exc}", _page)


def _whatsapp_draft_message_impl(contact: str, text: str) -> str:
    """Fill the WhatsApp compose box without sending."""
    contact = (contact or "").strip()
    text = (text or "").strip()
    if not contact:
        return _record_browser_result("whatsapp_draft_message", "failed", "Failed to draft WhatsApp message: contact is required.", _page)
    if not text:
        return _record_browser_result("whatsapp_draft_message", "failed", "Failed to draft WhatsApp message: text is required.", _page)
    try:
        opened = _whatsapp_find_chat_impl(contact)
        if not opened.startswith("Opened WhatsApp chat"):
            return opened

        page = _ensure_browser()
        _, compose = _fill_first_available(page, WHATSAPP_COMPOSE_SELECTORS, text, timeout=7000)
        try:
            actual = compose.input_value(timeout=1000)
            if isinstance(actual, str) and actual != text:
                message = f"Failed to draft WhatsApp message for {contact}: draft verification failed."
                return _record_browser_result("whatsapp_draft_message", "failed", message, page)
        except Exception:
            pass
        _settle_page(page, timeout_ms=500)
        message = f"Drafted WhatsApp message to {contact}: {text}"
        return _record_browser_result("whatsapp_draft_message", "success", message, page)
    except Exception as exc:
        return _record_browser_result("whatsapp_draft_message", "failed", f"Failed to draft WhatsApp message for {contact}: {exc}", _page)


def _whatsapp_send_message_impl(contact: str, text: str) -> str:
    """Fill and send a WhatsApp message using WhatsApp Web."""
    contact = (contact or "").strip()
    text = (text or "").strip()
    if not contact:
        return _record_browser_result("whatsapp_send_message", "failed", "Failed to send WhatsApp message: contact is required.", _page)
    if not text:
        return _record_browser_result("whatsapp_send_message", "failed", "Failed to send WhatsApp message: text is required.", _page)
    try:
        opened = _whatsapp_find_chat_impl(contact)
        if not opened.startswith("Opened WhatsApp chat"):
            return opened

        page = _ensure_browser()
        _, compose = _fill_first_available(page, WHATSAPP_COMPOSE_SELECTORS, text, timeout=7000)
        _press_enter(compose)
        _settle_page(page, timeout_ms=1000)
        try:
            remaining = compose.input_value(timeout=1000)
            if isinstance(remaining, str) and remaining.strip() == text:
                message = f"Failed to send WhatsApp message for {contact}: compose box still contains the message."
                return _record_browser_result("whatsapp_send_message", "failed", message, page)
        except Exception:
            pass
        message = f"Sent WhatsApp message to {contact}: {text}"
        return _record_browser_result("whatsapp_send_message", "success", message, page)
    except Exception as exc:
        return _record_browser_result("whatsapp_send_message", "failed", f"Failed to send WhatsApp message for {contact}: {exc}", _page)


# ----------------------------------------------------------------------------
# Public tool entrypoints — every call is pinned to the single browser thread so
# Playwright's thread-bound sync objects stay valid across a multi-step session.
# ----------------------------------------------------------------------------

def browser_navigate(url: str) -> str:
    return _run_on_browser_thread(_browser_navigate_impl, url)


def browser_read_current() -> str:
    return _run_on_browser_thread(_browser_read_current_impl)


def browser_status() -> str:
    return _run_on_browser_thread(_browser_status_impl)


def browser_click(selector: str) -> str:
    return _run_on_browser_thread(_browser_click_impl, selector)


def browser_input(selector: str, text: str) -> str:
    return _run_on_browser_thread(_browser_input_impl, selector, text)


def browser_click_text(text: str, exact: bool = False) -> str:
    return _run_on_browser_thread(_browser_click_text_impl, text, exact)


def browser_click_role(role: str, name: str, exact: bool = False) -> str:
    return _run_on_browser_thread(_browser_click_role_impl, role, name, exact)


def browser_click_best_match(query: str) -> str:
    return _run_on_browser_thread(_browser_click_best_match_impl, query)


def browser_fill_form(
    fields: list[dict[str, Any]],
    submit: bool = False,
    submit_label: str = "",
) -> str:
    return _run_on_browser_thread(_browser_fill_form_impl, fields, submit, submit_label)


def browser_close() -> str:
    return _run_on_browser_thread(_browser_close_impl)


def browser_inspect() -> str:
    return _run_on_browser_thread(_browser_inspect_impl)


def browser_scroll(direction: str, amount: str = "window") -> str:
    return _run_on_browser_thread(_browser_scroll_impl, direction, amount)


def browser_go_back() -> str:
    return _run_on_browser_thread(_browser_go_back_impl)


def whatsapp_open() -> str:
    return _run_on_browser_thread(_whatsapp_open_impl)


def whatsapp_find_chat(contact: str) -> str:
    return _run_on_browser_thread(_whatsapp_find_chat_impl, contact)


def whatsapp_draft_message(contact: str, text: str) -> str:
    return _run_on_browser_thread(_whatsapp_draft_message_impl, contact, text)


def whatsapp_send_message(contact: str, text: str) -> str:
    return _run_on_browser_thread(_whatsapp_send_message_impl, contact, text)
