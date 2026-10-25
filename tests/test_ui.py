"""
UI tests for Vocab Deck.

Covers:
- Icon/emoji encoding health (no mojibake in served HTML)
- Dashboard element visibility
- Profile dropdown interaction
- Settings modal open/close
- Practice page icon rendering and flashcard reveal
- Navigation between pages

Run with:
    uv run pytest tests/test_ui.py -v

Requires the Flask dev server to be running on http://localhost:5000.
"""
from __future__ import annotations

import re
from collections.abc import Generator

import pytest
import requests
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

BASE = "http://localhost:5000"

# Mojibake patterns that indicate encoding corruption in the served HTML.
# These are the Latin-1/CP1252 misinterpretations of multi-byte UTF-8 sequences.
MOJIBAKE_PATTERNS = [
    r"ðŸ",   # start of any 4-byte emoji encoded as cp1252 (🎯 👤 🧠 📚 🎉)
    r"â†",   # ← or → arrow  (U+2190/U+2192 → â† + control char)
    r"âš™",   # ⚙ gear
    r"â–¶",   # ▶ play
    r"â–¾",   # ▾ caret
    r"â€",   # ' or — curly quote / em-dash
]


# ---------------------------------------------------------------------------
# Server availability guard
# ---------------------------------------------------------------------------

def _server_running() -> bool:
    try:
        return requests.get(f"{BASE}/api/status", timeout=2).ok
    except requests.ConnectionError:
        return False


pytestmark = pytest.mark.skipif(
    not _server_running(),
    reason="Flask dev server not running on localhost:5000",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser() -> Generator[Browser]:
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture()
def page(browser: Browser) -> Generator[Page]:
    ctx: BrowserContext = browser.new_context()
    p = ctx.new_page()
    yield p
    ctx.close()


# ---------------------------------------------------------------------------
# Encoding / HTML-level tests (no browser needed)
# ---------------------------------------------------------------------------

class TestEncodingHealth:
    """Verify served HTML contains correct Unicode, not mojibake."""

    def _html(self, path: str) -> str:
        r = requests.get(f"{BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.text

    @pytest.mark.parametrize("path,label", [
        ("/",                  "dashboard"),
        ("/static/practice.html", "practice"),
    ])
    def test_no_mojibake(self, path: str, label: str) -> None:
        html = self._html(path)
        for pattern in MOJIBAKE_PATTERNS:
            assert not re.search(pattern, html), (
                f"Mojibake pattern '{pattern}' found in {label} HTML — "
                "likely UTF-8/CP1252 double-encoding"
            )

    def test_dashboard_contains_target_emoji(self) -> None:
        html = self._html("/")
        assert "🎯" in html, "Brand icon 🎯 missing from dashboard"

    def test_dashboard_contains_profile_emoji(self) -> None:
        html = self._html("/")
        assert "👤" in html, "Profile icon 👤 missing from dashboard"

    def test_dashboard_contains_gear_emoji(self) -> None:
        html = self._html("/")
        assert "⚙" in html, "Gear icon ⚙ missing from dashboard"

    def test_practice_contains_brain_emoji(self) -> None:
        html = self._html("/static/practice.html")
        assert "🧠" in html, "Brain icon 🧠 missing from practice page"

    def test_practice_contains_books_emoji(self) -> None:
        html = self._html("/static/practice.html")
        assert "📚" in html, "Books icon 📚 missing from practice page"

    def test_html_declared_utf8(self) -> None:
        r = requests.get(f"{BASE}/", timeout=5)
        html_lower = r.text.lower()
        assert 'charset="utf-8"' in html_lower or "charset=utf-8" in html_lower, (
            "HTML should declare UTF-8 charset in <meta> tag"
        )


# ---------------------------------------------------------------------------
# Dashboard browser tests
# ---------------------------------------------------------------------------

class TestDashboard:
    """Verify the dashboard page renders key UI elements correctly."""

    def test_title(self, page: Page) -> None:
        page.goto(BASE)
        assert page.title() == "Vocab Deck - Daily Challenge"

    def test_brand_icon_visible(self, page: Page) -> None:
        page.goto(BASE)
        brand = page.locator(".brand-icon")
        assert brand.is_visible()
        # Confirm the emoji rendered correctly, not as a box or ?
        text = brand.inner_text()
        assert "🎯" in text, f"Brand icon text was '{text}', expected 🎯"

    def test_profile_button_visible(self, page: Page) -> None:
        page.goto(BASE)
        trigger = page.locator("#profile-trigger")
        assert trigger.is_visible()
        assert "👤" in trigger.inner_text()

    def test_settings_button_visible(self, page: Page) -> None:
        page.goto(BASE)
        btn = page.get_by_role("button", name=re.compile("Settings"))
        assert btn.is_visible()
        assert "⚙" in btn.inner_text()

    def test_start_challenge_button_visible(self, page: Page) -> None:
        page.goto(BASE)
        btn = page.locator("#start-challenge-btn")
        assert btn.is_visible()
        assert "▶" in btn.inner_text()

    def test_stats_bar_renders(self, page: Page) -> None:
        page.goto(BASE)
        page.wait_for_selector("#stats-bar", state="visible")
        assert page.locator(".stat-card").count() >= 4

    def test_carousel_nav_arrows(self, page: Page) -> None:
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        prev_btn = page.get_by_role("button", name=re.compile("Prev"))
        next_btn = page.get_by_role("button", name=re.compile("Next"))
        assert prev_btn.count() >= 1
        assert next_btn.count() >= 1
        assert "←" in prev_btn.first.inner_text()
        assert "→" in next_btn.first.inner_text()

    def test_profile_dropdown_opens(self, page: Page) -> None:
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        page.click("#profile-trigger")
        dropdown = page.locator("#profile-dropdown")
        page.wait_for_timeout(200)
        assert dropdown.is_visible()

    def test_settings_modal_opens_and_closes(self, page: Page) -> None:
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name=re.compile("Settings")).click()
        overlay = page.locator("#settings-overlay")
        page.wait_for_timeout(300)
        assert overlay.is_visible()
        # Close via Cancel button
        page.get_by_role("button", name="Cancel").click()
        page.wait_for_timeout(300)
        assert not overlay.is_visible()

    def test_dictionary_table_renders(self, page: Page) -> None:
        page.goto(BASE)
        page.wait_for_selector("#level-table", state="visible")
        headers = page.locator("#level-table thead th")
        expected = ["Word", "Type", "Attempts", "Correct", "Accuracy", "Level"]
        for i, label in enumerate(expected):
            assert headers.nth(i).inner_text() == label


# ---------------------------------------------------------------------------
# Practice page browser tests
# ---------------------------------------------------------------------------

class TestPracticePage:
    """Verify the practice page renders and the flashcard flow works."""

    def test_title(self, page: Page) -> None:
        page.goto(f"{BASE}/static/practice.html")
        assert page.title() == "Vocab Deck - Practice"

    def test_brain_icon_visible(self, page: Page) -> None:
        page.goto(f"{BASE}/static/practice.html")
        h1 = page.locator("h1")
        assert h1.is_visible()
        assert "🧠" in h1.inner_text(), f"Expected 🧠 in h1, got: {h1.inner_text()}"

    def test_books_icon_in_section_heading(self, page: Page) -> None:
        page.goto(f"{BASE}/static/practice.html")
        page.wait_for_selector("#lecture-container h2", state="visible")
        h2 = page.locator("#lecture-container h2")
        assert "📚" in h2.inner_text(), f"Expected 📚 in h2, got: {h2.inner_text()}"

    def test_back_button_has_arrow(self, page: Page) -> None:
        page.goto(f"{BASE}/static/practice.html")
        back = page.get_by_role("button", name=re.compile("Back"))
        assert back.is_visible()
        assert "←" in back.inner_text()

    def test_flashcard_reveal(self, page: Page) -> None:
        page.goto(f"{BASE}/static/practice.html")
        page.wait_for_selector(".fc-reveal-btn", state="visible")
        reveal_btn = page.locator(".fc-reveal-btn")
        assert "→" in reveal_btn.inner_text()
        reveal_btn.click()
        page.wait_for_selector("#flashcard-back", state="visible")
        # After reveal, confidence buttons should appear
        assert page.locator(".conf-btn").count() == 4

    def test_back_button_navigates_home(self, page: Page) -> None:
        page.goto(f"{BASE}/static/practice.html")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name=re.compile("Back")).click()
        page.wait_for_url(f"{BASE}/")
        assert "Vocab Deck - Daily Challenge" in page.title()
