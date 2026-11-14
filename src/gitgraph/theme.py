"""Colour palettes and light/dark theme tokens."""

from __future__ import annotations

# Four accent colours plus three muted neutrals. The first is the primary branch. All keep at
# least 3:1 contrast (WCAG graphical objects) on white (#ffffff) and on dark (#0d1117), and
# 4.5:1 against white label text on a filled "line sign". Checked in tests/test_units.py.
DEFAULT_PALETTE: tuple[str, ...] = (
    "#2563eb",  # blue (primary branch)
    "#c2410c",  # vermilion
    "#0f766e",  # green
    "#7c3aed",  # violet
    "#6b7280",  # slate
    "#8b6f47",  # khaki
    "#4d7c0f",  # olive
)

# Used for lines that no ref names (e.g. merged-and-deleted branches). Always drawn dashed.
MUTED_PALETTE: tuple[str, ...] = ("#8a919c", "#9a8f85", "#8793a3", "#939393")

THEME_NAMES = ("auto", "light", "dark")

# token -> (light, dark)
TOKENS: dict[str, tuple[str, str]] = {
    "bg": ("#ffffff", "#0d1117"),
    "surface": ("#f6f8fa", "#161b22"),
    "border": ("#d1d9e0", "#3d444d"),
    "text": ("#1f2328", "#e6edf3"),
    "muted": ("#59636e", "#9198a1"),
    "node": ("#ffffff", "#0d1117"),
    "ink": ("#1f2328", "#e6edf3"),
    "accent": ("#8a5200", "#e3b341"),
}

_PROPERTY = {
    "bg": "fill",
    "surface": "fill",
    "border": "stroke",
    "text": "fill",
    "muted": "fill",
    "node": "fill",
    "ink": "stroke",
    "accent": "fill",
}


def theme_css(name: str) -> str:
    """CSS for the embedded stylesheet. ``auto`` follows the viewer's colour scheme."""
    if name not in THEME_NAMES:
        raise ValueError(f"unknown theme {name!r}; choose one of {', '.join(THEME_NAMES)}")
    index = 1 if name == "dark" else 0
    rules = [f".{tok}{{{_PROPERTY[tok]}:{vals[index]}}}" for tok, vals in TOKENS.items()]
    rules.append(".onsign{fill:#ffffff}")
    if name == "auto":
        dark = [f".{tok}{{{_PROPERTY[tok]}:{vals[1]}}}" for tok, vals in TOKENS.items()]
        rules.append("@media (prefers-color-scheme:dark){" + "".join(dark) + "}")
    return "\n".join(rules)
