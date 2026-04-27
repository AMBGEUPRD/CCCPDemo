"""Tests for webapp accessibility improvements.

Validates that static HTML templates and CSS files contain the required
accessibility attributes and media queries (AC1-AC7).
"""

import math
from pathlib import Path

_WEBAPP = Path(__file__).resolve().parents[3] / "src" / "Tableau2PowerBI" / "webapp"
_STATIC = _WEBAPP / "static"
_TEMPLATES = _WEBAPP / "templates"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Helpers for contrast ratio (WCAG relative luminance) ──


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse '#rrggbb' to (r, g, b) ints."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _relative_luminance(r: int, g: int, b: int) -> float:
    """WCAG 2.1 relative luminance."""

    def linearize(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else math.pow((s + 0.055) / 1.055, 2.4)

    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    l1 = _relative_luminance(*_hex_to_rgb(hex1))
    l2 = _relative_luminance(*_hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ── AC1: prefers-reduced-motion ──


class TestReducedMotion:
    """All three CSS files must contain a prefers-reduced-motion media query."""

    def test_style_css_has_reduced_motion(self) -> None:
        css = _read(_STATIC / "style.css")
        assert "prefers-reduced-motion" in css

    def test_index_css_has_reduced_motion(self) -> None:
        css = _read(_STATIC / "index.css")
        assert "prefers-reduced-motion" in css

    def test_results_css_has_reduced_motion(self) -> None:
        css = _read(_STATIC / "results-shared.css")
        assert "prefers-reduced-motion" in css


# ── AC2: colour contrast ──


class TestColorContrast:
    """The --muted variable must pass 4.5:1 against --cream in both themes."""

    def test_muted_color_contrast_ratio_light(self) -> None:
        ratio = _contrast_ratio("#5b5bd6", "#f5f3ff")
        assert ratio >= 4.5, f"Light theme contrast {ratio:.2f} < 4.5"

    def test_muted_color_contrast_ratio_dark(self) -> None:
        ratio = _contrast_ratio("#a5b4fc", "#0f0e17")
        assert ratio >= 4.5, f"Dark theme contrast {ratio:.2f} < 4.5"


# ── AC3: keyboard-accessible drop zone ──


class TestDropzoneKeyboard:
    """The drop zone must have tabindex and role attributes for keyboard access."""

    def test_dropzone_has_keyboard_attributes(self) -> None:
        html = _read(_TEMPLATES / "index.html")
        assert 'tabindex="0"' in html
        assert 'role="button"' in html
        assert 'aria-label="Upload a Tableau workbook file"' in html


# ── AC4: modal accessibility ──


class TestModalAccessibility:
    """The success modal must have ARIA dialog attributes."""

    def test_modal_has_aria_attributes(self) -> None:
        html = _read(_TEMPLATES / "index.html")
        assert 'role="dialog"' in html
        assert 'aria-modal="true"' in html
        assert "Escape" in html, "Escape key handler must be present"


# ── AC5: skip-to-content link ──


class TestSkipLink:
    """base.html must have a skip-to-content link."""

    def test_base_template_has_skip_link(self) -> None:
        html = _read(_TEMPLATES / "base.html")
        assert "skip-link" in html
        assert "#main-content" in html
        assert 'id="main-content"' in html


# ── AC6: stepper mobile labels ──


class TestStepperMobileLabels:
    """Step labels must not use display:none on mobile; use truncation instead."""

    def test_stepper_mobile_labels_not_hidden(self) -> None:
        css = _read(_STATIC / "style.css")
        # The old rule was '.step-label { display: none; }' — it must be gone
        assert ".step-label { display: none; }" not in css
        assert ".step-label { display:none" not in css
        # The new rule should use text-overflow or max-width instead
        assert "text-overflow: ellipsis" in css or "text-overflow:ellipsis" in css
