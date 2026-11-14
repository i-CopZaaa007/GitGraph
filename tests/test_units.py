from __future__ import annotations

from pathlib import Path

import pytest

from gitgraph.config import STARTER_CONFIG, Config, ConfigError, config_from_dict, load_config
from gitgraph.models import Tag
from gitgraph.tags import parse_version, select_latest, sort_tags
from gitgraph.text import clean_text, text_width, truncate_to_width, wrap_limited, wrap_paragraph
from gitgraph.theme import DEFAULT_PALETTE, MUTED_PALETTE, theme_css
from gitgraph.urls import format_link, normalize_repository_url


def tag(name: str, at: int = 0, annotated: bool = False, sha: str = "a" * 40) -> Tag:
    return Tag(name, sha, annotated, sha, tagged_at=at or None)


# ---- tags -----------------------------------------------------------------------------------
def test_version_comparison_is_numeric_not_lexicographic() -> None:
    tags = [tag("v1.9.0"), tag("v1.10.0"), tag("v1.2.0"), tag("v1.10.0-rc.1")]
    assert [t.name for t in sort_tags(tags, {})] == ["v1.10.0", "v1.10.0-rc.1", "v1.9.0", "v1.2.0"]


def test_prerelease_ordering() -> None:
    names = ["1.0.0", "1.0.0-rc.10", "1.0.0-rc.2", "1.0.0-beta", "1.0.0-alpha.1"]
    ordered = [t.name for t in sort_tags([tag(n) for n in names], {})]
    assert ordered == ["1.0.0", "1.0.0-rc.10", "1.0.0-rc.2", "1.0.0-beta", "1.0.0-alpha.1"]


def test_trailing_zero_versions_tie_break_by_name() -> None:
    assert parse_version("1.0") is not None
    assert parse_version("1.0").key() == parse_version("v1.0.0").key()  # type: ignore[union-attr]
    ordered = [t.name for t in sort_tags([tag("1.0"), tag("v1.0.0")], {})]
    assert ordered == sorted(ordered, reverse=True)


def test_non_version_tags_use_dates_and_names() -> None:
    tags = [tag("nightly", at=300), tag("beta-x", at=200), tag("old", at=100), tag("zzz", at=300)]
    assert [t.name for t in sort_tags(tags, {})] == ["nightly", "zzz", "beta-x", "old"]


def test_latest_prefers_stable_version_over_newer_date() -> None:
    tags = [tag("v2.0.0-rc.1", at=900), tag("v1.5.0", at=100), tag("nightly", at=1000)]
    assert select_latest(tags, {}).name == "v1.5.0"  # type: ignore[union-attr]
    assert select_latest(tags, {}, "date").name == "nightly"  # type: ignore[union-attr]
    assert select_latest([tag("v2.0.0-rc.1"), tag("v1.0.0-rc.1")], {}).name == "v2.0.0-rc.1"  # type: ignore[union-attr]
    assert select_latest([], {}) is None


def test_date_tags_are_not_mistaken_for_versions() -> None:
    assert parse_version("2024-05-01") is None
    assert parse_version("release") is None
    assert parse_version("v1.2.3+build.5").is_stable  # type: ignore[union-attr]


# ---- text -----------------------------------------------------------------------------------
def test_clean_text_removes_dangerous_characters() -> None:
    assert clean_text("a\x00b\x1b[0m‮c⁦d\ud800e￾\t f\r\n g") == "ab[0mcde  f  g"
    assert clean_text("a\nb", keep_newlines=True) == "a\nb"
    assert clean_text("café 日本語 ก็") == "café 日本語 ก็"  # nothing else is rewritten


def test_width_estimates() -> None:
    assert text_width("日本", 10) > text_width("ab", 10)
    assert text_width("é", 10) == text_width("e", 10)  # combining mark has no advance
    assert text_width("iii", 10) < text_width("MMM", 10)


def test_wrapping_respects_width_and_breaks_long_words() -> None:
    lines = wrap_paragraph("alpha beta gamma delta " * 5, 120, 13)
    assert all(text_width(line, 13) <= 120 for line in lines)
    long = wrap_paragraph("x" * 200, 100, 13)
    assert len(long) > 1 and all(text_width(line, 13) <= 100 for line in long)
    assert "".join(long) == "x" * 200


def test_wrap_limited_truncates_with_ellipsis() -> None:
    lines = wrap_limited(["word " * 100], 100, 13, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert text_width(lines[-1], 13) <= 100
    assert truncate_to_width("short", 500, 13) == "short"


def test_wrap_keeps_combining_marks_with_base() -> None:
    lines = wrap_paragraph("ก็" * 100, 60, 13)
    assert all(not line.startswith("็") for line in lines)


# ---- theme ----------------------------------------------------------------------------------
def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("colour", [*DEFAULT_PALETTE, *MUTED_PALETTE])
@pytest.mark.parametrize("background", ["#ffffff", "#0d1117"])
def test_palette_has_graphical_contrast_on_light_and_dark(colour: str, background: str) -> None:
    assert contrast(colour, background) >= 3.0


@pytest.mark.parametrize("colour", DEFAULT_PALETTE)
def test_line_sign_text_is_readable(colour: str) -> None:
    assert contrast("#ffffff", colour) >= 4.5  # white label text on a filled branch sign


def test_text_tokens_have_text_contrast() -> None:
    from gitgraph.theme import TOKENS

    for token in ("text", "muted", "accent"):
        light, dark = TOKENS[token]
        assert contrast(light, TOKENS["bg"][0]) >= 4.5
        assert contrast(dark, TOKENS["bg"][1]) >= 4.5


def test_unknown_theme_rejected() -> None:
    with pytest.raises(ValueError):
        theme_css("neon")


# ---- urls -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com/o/r.git", "https://github.com/o/r"),
        ("git@github.com:o/r.git", "https://github.com/o/r"),
        ("ssh://git@gitlab.com/g/p.git", "https://gitlab.com/g/p"),
        ("https://user:secret@github.com/o/r", "https://github.com/o/r"),
        ("http://example.com/o/r/", "http://example.com/o/r"),
        ("/local/path/repo", None),
        ("file:///tmp/repo", None),
        ("", None),
        ("https://host/../x", None),
    ],
)
def test_normalize_repository_url(raw: str, expected: str | None) -> None:
    result = normalize_repository_url(raw)
    assert result == expected
    assert result is None or "secret" not in result


def test_format_link_encodes_values() -> None:
    assert format_link("{repo}/commit/{sha}", "https://h/o/r/", sha="ab/../c") == (
        "https://h/o/r/commit/ab%2F..%2Fc"
    )


# ---- config ---------------------------------------------------------------------------------
def test_starter_config_is_valid_and_matches_defaults(tmp_path: Path) -> None:
    path = tmp_path / "gitgraph.toml"
    path.write_text(STARTER_CONFIG, encoding="utf-8")
    config, source = load_config(None, tmp_path)
    assert source == path
    assert config == Config()


def test_unknown_keys_and_sections_are_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown key"):
        config_from_dict({"layout": {"label_widht": 100}})
    with pytest.raises(ConfigError, match="unknown section"):
        config_from_dict({"nope": {}})


@pytest.mark.parametrize(
    "data",
    [
        {"layout": {"font_size": "big"}},
        {"layout": {"font_size": 2}},
        {"display": {"sha": "yes"}},
        {"display": {"message_mode": "everything"}},
        {"theme": {"name": "neon"}},
        {"theme": {"palette": ["red"]}},
        {"theme": {"palette": []}},
        {"history": {"include": "main"}},
        {"history": {"max_commits": -1}},
        {"readme": {"insert": "middle"}},
        {"readme": {"heading_level": 9}},
        {"links": {"commit_url": "https://example.com/x"}},
    ],
)
def test_invalid_values_are_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ConfigError):
        config_from_dict(data)


def test_config_errors_for_bad_files(tmp_path: Path) -> None:
    bad = tmp_path / "gitgraph.toml"
    bad.write_text("[layout\nx=", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot parse"):
        load_config(None, tmp_path)
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.toml", tmp_path)


def test_integers_accepted_for_floats_and_options_flow_through() -> None:
    config = config_from_dict(
        {
            "layout": {"label_width": 400},
            "display": {"sha": False},
            "theme": {"palette": ["#112233"]},
        }
    )
    options = config.layout_options()
    assert options.label_width == 400.0 and options.show_sha is False
    assert options.palette == ("#112233",)
