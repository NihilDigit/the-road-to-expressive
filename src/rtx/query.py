"""Query, spec extraction, Kotlin source lookup, status, and corpus health (`doctor`) helpers for `rtx`."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rtx.config import MAX_LINE_LENGTH, RepoPaths, discover_sources
from rtx.index import build_index
from rtx.models import SourceManifest, parse_page_frontmatter

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BALANCED_ALT_RE = r"(?:[^\[\]\n]|\[[^\[\]\n]*\])*"
_BALANCED_URL_RE = r"(?:[^()\n]|\([^()\n]*\))*"
_IMAGE_RE = re.compile(rf"!\[{_BALANCED_ALT_RE}\]\({_BALANCED_URL_RE}\)")
_VIDEO_RE = re.compile(rf"\[Video\]\({_BALANCED_URL_RE}\)", re.IGNORECASE)
_INTERNAL_M3_LINK_RE = re.compile(rf"\[([^\]]+)\]\(/m3/pages/{_BALANCED_URL_RE}\)")
_LOCAL_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([A-Za-z0-9_./-]+\.md(?:#[^)]*)?\)")
_INTERNAL_DECL_RE = re.compile(
    r"\binternal\s+(?:(?:open|abstract|sealed|data|value|enum|inline|expect|actual|suspend)\s+)*(?:fun|class|object|interface|val|var|typealias)\b"
)
_APPLE_NO_PLATFORM_RE = re.compile(
    r"^\s*\*No additional considerations for (?:visionOS|watchOS|tvOS|iOS|iPadOS|macOS)[^*]*\*\s*\.?\s*$",
    re.IGNORECASE,
)
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "to",
        "use",
        "using",
        "versus",
        "vs",
        "what",
        "when",
        "with",
    }
)

_SPEC_SOURCES: tuple[str, ...] = (
    "m3-expressive",
    "google-design",
    "compose-android",
    "apple-hig",
    "windows-fluent",
    "linux-hig",
)

_EXCLUDED_PLATFORM_TERMS = frozenset({"xr", "watchos", "tvos", "visionos", "carplay", "watch"})

_EXCLUDED_PATH_FRAGMENTS: tuple[str, ...] = (
    "/develop/flutter.md",
    "/develop/web.md",
    "/foundations/xr/",
    "/foundations/watches.md",
    "designing-for-watchos",
    "designing-for-tvos",
    "designing-for-visionos",
    "/watch-faces.md",
    "/complications.md",
    "/digital-crown.md",
    "/always-on.md",
    "/carplay.md",
    "/spatial-layout.md",
)

_SKIP_HEADING_PREFIXES: tuple[str, ...] = (
    "implementation status",
    "availability & resources",
    "component design tokens",
    "tokens and specs",
    "tokens & specs",
    "differences from m2",
    "baseline tokens",
    "change log",
    "revision history",
    "resources",
)

_EXCLUDED_PLATFORM_HEADINGS = frozenset(
    {
        "xr",
        "watchos",
        "tvos",
        "visionos",
        "carplay",
        "spatial dialogs",
        "spatialized fab",
    }
)

_DO_DONT_KEYWORDS = (
    "don't",
    "don’t",
    "avoid",
    "never",
    "shouldn't",
    "shouldn’t",
    "should ",
    "must ",
    "use ",
    "only ",
    "keep ",
    "place ",
    "offset ",
    "maximum",
    "instead",
    "adjust ",
    "break up",
    "combine ",
    "don't ",
    "in wide",
    "on smaller",
    "on larger",
    "a dismiss action",
    "to allow",
    "to distinguish",
    "to separate",
    "also communicate",
    "reduces contrast",
    "may affect accessibility",
    "unnecessary",
    "when focused",
    "for global search",
)

# Alias map from common Compose/M3 component names (lowercased, stripped of punctuation) to M3 component slugs.
_M3_COMPONENT_ALIASES: dict[str, list[str]] = {
    "search": ["search", "app-bars"],
    "searchbar": ["search", "app-bars"],
    "dockedsearchbar": ["search"],
    "expandeddockedsearchbar": ["search"],
    "expandedfullscreensearchbar": ["search"],
    "searchview": ["search"],
    "searchappbar": ["search", "app-bars"],
    "tab": ["tabs"],
    "tabs": ["tabs"],
    "tabrow": ["tabs"],
    "primarytabrow": ["tabs"],
    "secondarytabrow": ["tabs"],
    "scrollabletabrow": ["tabs"],
    "primaryscrollabletabrow": ["tabs"],
    "secondaryscrollabletabrow": ["tabs"],
    "tabrowdefaults": ["tabs"],
    "primaryindicator": ["tabs"],
    "secondaryindicator": ["tabs"],
    "carousel": ["carousel"],
    "horizontalmultibrowsecarousel": ["carousel"],
    "horizontaluncontainedcarousel": ["carousel"],
    "horizontalcenteredherocarousel": ["carousel"],
    "carouselstate": ["carousel"],
    "carouseldefaults": ["carousel"],
    "navigationrail": ["navigation-rail"],
    "widenavigationrail": ["navigation-rail"],
    "modalwidenavigationrail": ["navigation-rail"],
    "widenavigationrailitem": ["navigation-rail"],
    "navigationrailitem": ["navigation-rail"],
    "navigationbar": ["navigation-bar"],
    "shortnavigationbar": ["navigation-bar"],
    "shortnavigationbaritem": ["navigation-bar"],
    "navigationbaritem": ["navigation-bar"],
    "bottomnavigation": ["navigation-bar"],
    "navigationdrawer": ["navigation-drawer"],
    "modalnavigationdrawer": ["navigation-drawer"],
    "permanentnavigationdrawer": ["navigation-drawer"],
    "dismissiblenavigationdrawer": ["navigation-drawer"],
    "navigationsuitescaffold": ["navigation-rail", "navigation-bar"],
    "appbar": ["app-bars"],
    "appbars": ["app-bars"],
    "topappbar": ["app-bars"],
    "smalltopappbar": ["app-bars"],
    "centeralignedtopappbar": ["app-bars"],
    "mediumtopappbar": ["app-bars"],
    "largetopappbar": ["app-bars"],
    "mediumflexibletopappbar": ["app-bars"],
    "largeflexibletopappbar": ["app-bars"],
    "bottomappbar": ["toolbars", "app-bars"],
    "snackbar": ["snackbar"],
    "snackbarhost": ["snackbar"],
    "snackbarhoststate": ["snackbar"],
    "toast": ["snackbar"],
    "toolbar": ["toolbars"],
    "toolbars": ["toolbars"],
    "floatingtoolbar": ["toolbars"],
    "horizontalfloatingtoolbar": ["toolbars"],
    "verticalfloatingtoolbar": ["toolbars"],
    "dockedtoolbar": ["toolbars"],
    "floatingtoolbarcolors": ["toolbars"],
    "buttongroup": ["button-groups"],
    "buttongroups": ["button-groups"],
    "buttongroupdefaults": ["button-groups"],
    "connectedbuttongroup": ["button-groups"],
    "standardbuttongroup": ["button-groups"],
    "splitbutton": ["split-button"],
    "splitbuttonlayout": ["split-button"],
    "splitbuttondefaults": ["split-button"],
    "button": ["buttons", "all-buttons"],
    "buttons": ["buttons", "all-buttons"],
    "allbuttons": ["all-buttons", "buttons"],
    "togglebutton": ["buttons"],
    "filledbutton": ["buttons", "all-buttons"],
    "tonalbutton": ["buttons", "all-buttons"],
    "filledtonalbutton": ["buttons", "all-buttons"],
    "outlinedbutton": ["buttons", "all-buttons"],
    "elevatedbutton": ["buttons", "all-buttons"],
    "textbutton": ["buttons", "all-buttons"],
    "iconbutton": ["icon-buttons"],
    "iconbuttons": ["icon-buttons"],
    "icontogglebutton": ["icon-buttons"],
    "fab": ["floating-action-button"],
    "floatingactionbutton": ["floating-action-button"],
    "smallfloatingactionbutton": ["floating-action-button"],
    "largefloatingactionbutton": ["floating-action-button"],
    "extendedfab": ["extended-fab"],
    "extendedfloatingactionbutton": ["extended-fab"],
    "fabmenu": ["fab-menu"],
    "floatingactionbuttonmenu": ["fab-menu"],
    "floatingactionbuttonmenuitem": ["fab-menu"],
    "sheet": ["bottom-sheets", "side-sheets"],
    "sheets": ["bottom-sheets", "side-sheets"],
    "bottomsheet": ["bottom-sheets"],
    "bottomsheets": ["bottom-sheets"],
    "modalbottomsheet": ["bottom-sheets"],
    "bottomsheetscaffold": ["bottom-sheets"],
    "sidesheet": ["side-sheets"],
    "sidesheets": ["side-sheets"],
    "modalsidesheet": ["side-sheets"],
    "dialog": ["dialogs"],
    "dialogs": ["dialogs"],
    "alertdialog": ["dialogs"],
    "basicdialog": ["dialogs"],
    "fullscreendialog": ["dialogs"],
    "chip": ["chips"],
    "chips": ["chips"],
    "filterchip": ["chips"],
    "assistchip": ["chips"],
    "inputchip": ["chips"],
    "suggestionchip": ["chips"],
    "list": ["lists"],
    "lists": ["lists"],
    "listitem": ["lists"],
    "segmentedlistitem": ["lists"],
    "card": ["cards"],
    "cards": ["cards"],
    "elevatedcard": ["cards"],
    "filledcard": ["cards"],
    "outlinedcard": ["cards"],
    "menu": ["menus"],
    "menus": ["menus"],
    "dropdownmenu": ["menus"],
    "exposeddropdownmenubox": ["menus"],
    "contextmenu": ["menus"],
    "loadingindicator": ["loading-indicator"],
    "containedloadingindicator": ["loading-indicator"],
    "progressindicator": ["progress-indicators"],
    "linearprogressindicator": ["progress-indicators"],
    "circularprogressindicator": ["progress-indicators"],
    "linearwavyprogressindicator": ["progress-indicators"],
    "circularwavyprogressindicator": ["progress-indicators"],
    "slider": ["sliders"],
    "sliders": ["sliders"],
    "rangeslider": ["sliders"],
    "verticalslider": ["sliders"],
    "switch": ["switch"],
    "checkbox": ["checkbox"],
    "tristatecheckbox": ["checkbox"],
    "radiobutton": ["radio-button"],
    "segmentedbutton": ["segmented-buttons"],
    "segmentedbuttons": ["segmented-buttons"],
    "singlechoicesegmentedbuttonrow": ["segmented-buttons"],
    "multichoicesegmentedbuttonrow": ["segmented-buttons"],
    "textfield": ["text-fields"],
    "textfields": ["text-fields"],
    "outlinedtextfield": ["text-fields"],
    "tooltip": ["tooltips"],
    "tooltips": ["tooltips"],
    "plaintooltip": ["tooltips"],
    "richtooltip": ["tooltips"],
    "tooltipbox": ["tooltips"],
    "badge": ["badges"],
    "badges": ["badges"],
    "badgedbox": ["badges"],
    "divider": ["divider"],
    "horizontaldivider": ["divider"],
    "verticaldivider": ["divider"],
    "datepicker": ["date-pickers"],
    "daterangepicker": ["date-pickers"],
    "timepicker": ["time-pickers"],
    "timeinput": ["time-pickers"],
}

# Maps M3 component slug -> matching upstream HIG page paths relative to `.corpus/<source_id>/pages/`.
_HIG_COMPONENT_MAP: dict[str, list[tuple[str, str]]] = {
    "search": [
        ("apple-hig", "search-fields.md"),
        ("windows-fluent", "fluent2/components/web/react/core/searchbox/usage.md"),
        ("linux-hig", "gnome/patterns/nav/search.md"),
    ],
    "tabs": [
        ("apple-hig", "tab-views.md"),
        ("windows-fluent", "windows/develop/ui/controls/tab-view.md"),
        ("linux-hig", "gnome/patterns/nav/tabs.md"),
    ],
    "carousel": [
        ("windows-fluent", "fluent2/components/web/react/core/carousel/usage.md"),
        ("apple-hig", "collections.md"),
    ],
    "navigation-rail": [
        ("apple-hig", "sidebars.md"),
        ("windows-fluent", "windows/develop/ui/controls/navigationview.md"),
        ("linux-hig", "gnome/patterns/nav/sidebars.md"),
    ],
    "navigation-bar": [
        ("apple-hig", "tab-bars.md"),
        ("linux-hig", "gnome/patterns/nav/view-switchers.md"),
    ],
    "navigation-drawer": [
        ("apple-hig", "sidebars.md"),
        ("windows-fluent", "windows/develop/ui/controls/navigationview.md"),
        ("linux-hig", "gnome/patterns/nav/sidebars.md"),
    ],
    "app-bars": [
        ("apple-hig", "toolbars.md"),
        ("linux-hig", "gnome/patterns/containers/header-bars.md"),
    ],
    "toolbars": [
        ("apple-hig", "toolbars.md"),
        ("windows-fluent", "fluent2/components/web/react/core/toolbar/usage.md"),
        ("linux-hig", "gnome/patterns/containers/header-bars.md"),
    ],
    "snackbar": [
        ("windows-fluent", "fluent2/components/web/react/core/toast/usage.md"),
        ("linux-hig", "gnome/patterns/feedback/toasts.md"),
        ("apple-hig", "feedback.md"),
    ],
    "dialogs": [
        ("apple-hig", "alerts.md"),
        ("windows-fluent", "windows/develop/ui/controls/dialogs-and-flyouts/dialogs.md"),
        ("linux-hig", "gnome/patterns/feedback/dialogs.md"),
    ],
    "bottom-sheets": [
        ("apple-hig", "sheets.md"),
        ("linux-hig", "gnome/patterns/containers/utility-panes.md"),
    ],
    "side-sheets": [
        ("apple-hig", "sheets.md"),
        ("linux-hig", "gnome/patterns/containers/utility-panes.md"),
    ],
    "buttons": [
        ("apple-hig", "buttons.md"),
        ("windows-fluent", "windows/develop/ui/controls/buttons.md"),
        ("linux-hig", "gnome/patterns/controls/buttons.md"),
    ],
    "all-buttons": [
        ("apple-hig", "buttons.md"),
        ("windows-fluent", "windows/develop/ui/controls/buttons.md"),
        ("linux-hig", "gnome/patterns/controls/buttons.md"),
    ],
    "button-groups": [
        ("apple-hig", "segmented-controls.md"),
        ("windows-fluent", "windows/develop/ui/controls/buttons.md"),
        ("linux-hig", "gnome/patterns/controls/buttons.md"),
    ],
    "split-button": [
        ("apple-hig", "pull-down-buttons.md"),
        ("windows-fluent", "windows/develop/ui/controls/buttons.md"),
    ],
    "menus": [
        ("apple-hig", "context-menus.md"),
        ("windows-fluent", "windows/develop/ui/controls/dialogs-and-flyouts/flyouts.md"),
        ("linux-hig", "gnome/patterns/containers/popovers.md"),
    ],
    "lists": [
        ("apple-hig", "lists-and-tables.md"),
        ("linux-hig", "gnome/patterns/containers/boxed-lists.md"),
    ],
    "loading-indicator": [
        ("apple-hig", "loading.md"),
        ("windows-fluent", "fluent2/wait-ux.md"),
    ],
    "progress-indicators": [
        ("apple-hig", "progress-indicators.md"),
        ("windows-fluent", "fluent2/wait-ux.md"),
    ],
}

# Topic-to-canonical-upstream-page hints for `rtx spec` (points dynamically into `.corpus/`, zero static prose).
_SPEC_TOPIC_HINTS: tuple[tuple[frozenset[str], tuple[str, ...]], ...] = (
    (
        frozenset({"canonical", "layout", "layouts", "breakpoint", "breakpoints", "scaffold", "pane", "detail", "feed", "desktop", "skeleton", "adaptive"}),
        (
            "foundations/layout/canonical-examples.md",
            "foundations/layout/scaffold.md",
            "foundations/layout/breakpoints.md",
            "foundations/desktop.md",
            "across-form-factors.md",
            "common-layouts.md",
            "adapt-layout.md",
            "apple-hig/pages/layout.md",
        ),
    ),
    (
        frozenset({"button", "buttons", "emphasis", "hierarchy", "fab", "tonal", "filled", "outlined", "action", "actions", "choosing"}),
        (
            "components/all-buttons.md",
            "components/buttons.md",
            "components/button-groups.md",
            "components/floating-action-button.md",
        ),
    ),
    (
        frozenset({"selection", "select", "filter", "filtering", "sort", "sorting", "checkbox", "switch", "radio", "chip", "chips", "toggle"}),
        (
            "foundations/interaction/selection.md",
            "components/chips.md",
            "components/button-groups.md",
            "components/all-buttons.md",
            "apple-hig/pages/searching.md",
        ),
    ),
    (
        frozenset({"snackbar", "toast", "toasts", "dialog", "dialogs", "alert", "modality", "modal", "transient", "feedback", "banner", "sheet"}),
        (
            "components/snackbar.md",
            "components/dialogs.md",
            "apple-hig/pages/modality.md",
            "apple-hig/pages/feedback.md",
            "gnome/patterns/feedback/toasts.md",
            "fluent2/components/web/react/core/toast/usage.md",
        ),
    ),
    (
        frozenset({"navigation", "rail", "bar", "toolbar", "toolbars", "duplicate", "sidebar", "tabs", "tab", "drawer", "nav"}),
        (
            "components/navigation-rail.md",
            "components/navigation-bar.md",
            "components/toolbars.md",
            "components/app-bars.md",
            "apple-hig/pages/tab-bars.md",
            "apple-hig/pages/sidebars.md",
        ),
    ),
    (
        frozenset({"search", "searching", "docked", "fullscreen", "full", "suggestions", "query"}),
        (
            "components/search.md",
            "components/app-bars.md",
            "apple-hig/pages/search-fields.md",
            "apple-hig/pages/searching.md",
            "gnome/patterns/nav/search.md",
        ),
    ),
    (
        frozenset({"settings", "setting", "preferences", "configuration", "options"}),
        (
            "patterns/settings.md",
            "apple-hig/pages/settings.md",
            "guidelines-for-app-settings.md",
        ),
    ),
    (
        frozenset({"video", "audio", "media", "player", "playback", "immersive", "fullscreen"}),
        (
            "apple-hig/pages/playing-video.md",
            "apple-hig/pages/playing-audio.md",
            "apple-hig/pages/going-full-screen.md",
            "immersive-content.md",
        ),
    ),
    (
        frozenset({"input", "inputs", "gesture", "gestures", "drag", "drop", "keyboard", "pointer", "mouse", "hover", "cursor"}),
        (
            "foundations/interaction/inputs.md",
            "foundations/interaction/gestures.md",
            "apple-hig/pages/drag-and-drop.md",
            "pointer-interactions.md",
            "desktop/guides/interaction/keyboard.md",
        ),
    ),
    (
        frozenset({"motion", "spring", "springs", "physics", "transition", "transitions", "animation", "expressive"}),
        (
            "styles/motion/",
        ),
    ),
    (
        frozenset({"loading", "progress", "spinner", "wait", "skeleton"}),
        (
            "apple-hig/pages/loading.md",
            "components/loading-indicator.md",
            "components/progress-indicators.md",
            "fluent2/wait-ux.md",
        ),
    ),
)


def ensure_index(paths: RepoPaths) -> Path:
    """Ensure `.corpus/index.db` exists, building it on demand if missing."""
    if not paths.index_db.is_file():
        build_index(paths)
    return paths.index_db


def _query_wants_excluded_platform(query: str) -> bool:
    tokens = {t.lower() for t in _TOKEN_RE.findall(query)}
    return bool(tokens & _EXCLUDED_PLATFORM_TERMS)


def _is_excluded_path(path: str, *, include_excluded_platforms: bool = False) -> bool:
    low = path.replace("\\", "/").lower()
    if include_excluded_platforms:
        return "/develop/flutter.md" in low or "/develop/web.md" in low
    return any(frag in low for frag in _EXCLUDED_PATH_FRAGMENTS)


def _is_skip_heading(heading: str, *, include_excluded_platforms: bool = False) -> bool:
    low = heading.strip().lower()
    if not low:
        return False
    if any(low.startswith(prefix) for prefix in _SKIP_HEADING_PREFIXES):
        return True
    if not include_excluded_platforms and low in _EXCLUDED_PLATFORM_HEADINGS:
        return True
    return False


def _strip_impl_status_tables(lines: list[str]) -> list[str]:
    """Remove Flutter/Web/MDC-Android Implementation Status tables while preserving design comparison tables."""
    out: list[str] = []
    idx = 0
    n = len(lines)
    while idx < n:
        line = lines[idx]
        if line.lstrip().startswith("|"):
            block: list[str] = []
            while idx < n and lines[idx].lstrip().startswith("|"):
                block.append(lines[idx])
                idx += 1
            joined = "\n".join(block)
            if (
                "FLUTTER_IMPLEMENTATION" in joined
                or "LIT_IMPLEMENTATION" in joined
                or "ANDROID_IMPLEMENTATION" in joined
                or "Platform / Library" in block[0]
            ):
                continue
            out.extend(block)
            continue
        out.append(line)
        idx += 1
    return out


def clean_spec_markdown(text: str, *, include_excluded_platforms: bool = False) -> str:
    """Strip image/video URLs, Implementation Status tables, and watchOS/tvOS/visionOS/XR blocks while keeping italic captions."""
    raw_lines = text.splitlines()
    raw_lines = _strip_impl_status_tables(raw_lines)

    out: list[str] = []
    skip_until_level: int | None = None
    in_m3_xr_block = False
    in_fence = False
    fence_char = ""

    for line in raw_lines:
        fm = _FENCE_RE.match(line)
        if fm:
            marker = fm.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
                fence_char = ""
            if skip_until_level is None and not in_m3_xr_block:
                out.append(line)
            continue

        if not in_fence:
            hm = _HEADING_RE.match(line)
            if hm:
                level = len(hm.group(1))
                title = hm.group(2).strip()
                low_title = title.lower()

                if in_m3_xr_block:
                    if level <= 2 and low_title in ("accessibility", "component design tokens"):
                        in_m3_xr_block = False
                    else:
                        continue

                if skip_until_level is not None:
                    if level <= skip_until_level:
                        skip_until_level = None
                    else:
                        continue

                if not include_excluded_platforms and level == 2 and low_title == "xr":
                    in_m3_xr_block = True
                    continue

                if _is_skip_heading(title, include_excluded_platforms=include_excluded_platforms):
                    skip_until_level = level
                    continue

        if skip_until_level is not None or in_m3_xr_block:
            continue

        if _APPLE_NO_PLATFORM_RE.match(line):
            continue

        cleaned = _IMAGE_RE.sub("", line)
        cleaned = _VIDEO_RE.sub("", cleaned)
        cleaned = _INTERNAL_M3_LINK_RE.sub(r"\1", cleaned)
        cleaned = _LOCAL_MD_LINK_RE.sub(r"\1", cleaned)
        stripped = cleaned.strip()

        if stripped in ("__", "star"):
            continue
        if not stripped and (not out or not out[-1].strip()):
            continue
        out.append(cleaned.rstrip())

    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _truncate_clean(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n\n", 0, max_chars)
    if cut < max_chars // 2:
        cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars // 2:
        cut = text.rfind(" ", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    return text[:cut].rstrip() + "\n..."


def _fts_query(raw: str, *, use_or: bool = False, drop_stopwords: bool = False) -> str:
    tokens = _TOKEN_RE.findall(raw)
    if not tokens:
        return ""
    seen: set[str] = set()
    uniq: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if drop_stopwords and low in _STOPWORDS:
            continue
        if low not in seen:
            seen.add(low)
            uniq.append(tok)
    if not uniq:
        uniq = list(dict.fromkeys(tokens))
    joiner = " OR " if use_or else " AND "
    return joiner.join(f'"{t}"*' for t in uniq)


def _find_best_line(content: str, start_line: int, terms: list[str]) -> int:
    if not terms:
        return start_line
    lower_terms = [t.lower() for t in terms]
    for offset, line in enumerate(content.splitlines()):
        stripped = line.strip()
        if stripped.startswith(("![", "[Video](")):
            continue
        low = line.lower()
        if any(t in low for t in lower_terms):
            return start_line + offset
    return start_line


def _make_snippet(content: str, terms: list[str], max_chars: int = 240) -> str:
    cleaned = clean_spec_markdown(content)
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    chosen = ""
    lower_terms = [t.lower() for t in terms if t.lower() not in _STOPWORDS] or [t.lower() for t in terms]
    for ln in lines:
        low = ln.lower()
        if any(t in low for t in lower_terms):
            chosen = ln
            break
    if not chosen and lines:
        chosen = lines[0]
    if len(chosen) > max_chars:
        return chosen[: max_chars - 3].rstrip() + "..."
    return chosen


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


@dataclass(slots=True)
class SearchHit:
    """Single BM25 or structured search hit."""

    layer: str
    source_id: str
    path: str
    line: int
    end_line: int
    title: str
    heading: str
    url: str
    score: float
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_corpus(
    paths: RepoPaths,
    query: str,
    *,
    source: str | None = None,
    layer: str | None = None,
    limit: int = 15,
) -> list[SearchHit]:
    """Run BM25 FTS5 search across `knowledge`, `mirror`, `api`, and/or `tokens`."""
    db_path = ensure_index(paths)
    terms = _TOKEN_RE.findall(query)
    fts_and = _fts_query(query, use_or=False)
    fts_or = _fts_query(query, use_or=True)

    hits: list[SearchHit] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if layer in (None, "knowledge", "mirror"):
            hits.extend(_search_docs(conn, fts_and, terms, source=source, layer=layer, limit=limit))
            if not hits and fts_or and fts_or != fts_and:
                hits.extend(_search_docs(conn, fts_or, terms, source=source, layer=layer, limit=limit))

        if layer in (None, "api") and source is None:
            api_limit = limit if layer == "api" else max(3, limit // 3)
            api_hits = _search_api_as_hits(conn, fts_and or fts_or, query, limit=api_limit)
            hits.extend(api_hits)

        if layer in (None, "tokens") and source is None:
            tok_limit = limit if layer == "tokens" else max(3, limit // 3)
            tok_hits = _search_tokens_as_hits(conn, fts_and or fts_or, query, limit=tok_limit)
            hits.extend(tok_hits)
    finally:
        conn.close()

    def sort_key(h: SearchHit) -> tuple[float, int]:
        bias = -0.25 if (layer is None and h.layer == "knowledge") else 0.0
        return (h.score + bias, h.line)

    hits.sort(key=sort_key)
    return hits[:limit]


def _search_docs(
    conn: sqlite3.Connection,
    fts_expr: str,
    terms: list[str],
    *,
    source: str | None,
    layer: str | None,
    limit: int,
) -> list[SearchHit]:
    if not fts_expr:
        return []
    clauses = ["docs_fts MATCH ?"]
    params: list[Any] = [fts_expr]
    if source:
        clauses.append("m.source_id = ?")
        params.append(source)
    if layer in ("knowledge", "mirror"):
        clauses.append("m.layer = ?")
        params.append(layer)
    params.append(limit)

    sql = f"""
        SELECT
            m.layer, m.source_id, m.path, m.title, m.heading, m.url,
            m.start_line, m.end_line, m.content,
            bm25(docs_fts, 4.0, 6.0, 2.0, 1.0, 0.5, 0.5) AS rank
        FROM docs_fts
        JOIN docs_meta m ON docs_fts.rowid = m.id
        WHERE {' AND '.join(clauses)}
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[SearchHit] = []
    for row in rows:
        best_line = _find_best_line(row["content"], int(row["start_line"]), terms)
        out.append(
            SearchHit(
                layer=row["layer"],
                source_id=row["source_id"],
                path=row["path"],
                line=best_line,
                end_line=int(row["end_line"]),
                title=row["title"],
                heading=row["heading"],
                url=row["url"],
                score=float(row["rank"]),
                snippet=_make_snippet(row["content"], terms),
            )
        )
    return out


def _search_api_as_hits(conn: sqlite3.Connection, fts_expr: str, raw_query: str, *, limit: int) -> list[SearchHit]:
    rows: list[sqlite3.Row] = []
    if fts_expr:
        try:
            rows = conn.execute(
                """
                SELECT a.*, bm25(api_fts, 6.0, 2.0, 3.0, 2.0, 1.0, 1.0, 1.0, 1.0) AS rank
                FROM api_fts
                JOIN api_symbols a ON api_fts.rowid = a.id
                WHERE api_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows and raw_query.strip():
        like = f"%{raw_query.strip()}%"
        rows = conn.execute(
            """
            SELECT *, -1.0 AS rank FROM api_symbols
            WHERE name LIKE ? OR signature LIKE ? OR annotations LIKE ?
            LIMIT ?
            """,
            (like, like, like, limit),
        ).fetchall()

    out: list[SearchHit] = []
    for r in rows:
        ann = ", ".join(json.loads(r["annotations"]))
        snippet = r["signature"] or r["androidx_signature"] or r["cmp_signature"]
        if ann:
            snippet = f"[{ann}] {snippet}"
        out.append(
            SearchHit(
                layer="api",
                source_id="compose-maven-api",
                path=r["source_file"],
                line=1,
                end_line=1,
                title=r["name"],
                heading=f"{r['package']} ({r['artifact']})" if r["package"] else r["artifact"],
                url="",
                score=float(r["rank"]),
                snippet=snippet[:240],
            )
        )
    return out


def _search_tokens_as_hits(conn: sqlite3.Connection, fts_expr: str, raw_query: str, *, limit: int) -> list[SearchHit]:
    rows: list[sqlite3.Row] = []
    if fts_expr:
        try:
            rows = conn.execute(
                """
                SELECT t.*, bm25(tokens_fts, 6.0, 3.0, 2.0, 2.0, 3.0, 1.0, 1.0) AS rank
                FROM tokens_fts
                JOIN design_tokens t ON tokens_fts.rowid = t.id
                WHERE tokens_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    if not rows and raw_query.strip():
        like = f"%{raw_query.strip()}%"
        rows = conn.execute(
            """
            SELECT *, -1.0 AS rank FROM design_tokens
            WHERE name LIKE ? OR category LIKE ? OR compose_token LIKE ? OR role LIKE ?
            LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()

    out: list[SearchHit] = []
    for r in rows:
        snippet_parts = [p for p in (r["value"], r["compose_token"], r["notes"]) if p]
        out.append(
            SearchHit(
                layer="tokens",
                source_id="m3-expressive",
                path=r["source_file"],
                line=1,
                end_line=1,
                title=r["name"],
                heading=r["category"] or r["role"] or "token",
                url="",
                score=float(r["rank"]),
                snippet=" | ".join(snippet_parts)[:240],
            )
        )
    return out


def _lookup_kotlin_signatures_for_symbol(
    conn: sqlite3.Connection,
    name: str,
    package: str = "",
    *,
    limit: int = 3,
    public_only: bool = False,
) -> list[str]:
    """Fetch Kotlin signatures (with default parameter values) from `kotlin_sources` for a symbol."""
    if not _has_table(conn, "kotlin_sources") or not name:
        return []
    low = name.strip().lower()
    vis_clause = " AND visibility = 'public'" if public_only else ""
    if "." in low:
        rows = conn.execute(
            f"""
            SELECT kotlin_signature, fq_package, visibility, has_defaults, is_composable
            FROM kotlin_sources
            WHERE lower(qualified_name) = ?{vis_clause}
            ORDER BY (visibility = 'public') DESC, has_defaults DESC, is_composable DESC
            LIMIT 12
            """,
            (low,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT kotlin_signature, fq_package, visibility, has_defaults, is_composable
            FROM kotlin_sources
            WHERE (lower(name) = ? OR lower(qualified_name) = ?){vis_clause}
            ORDER BY (visibility = 'public') DESC, has_defaults DESC, is_composable DESC
            LIMIT 16
            """,
            (low, low),
        ).fetchall()

    if package:
        pkg_low = package.lower()
        pkg_matched = [r for r in rows if r["fq_package"].lower() == pkg_low]
        if pkg_matched:
            rows = pkg_matched

    sigs: list[str] = []
    seen: set[str] = set()
    for r in rows:
        sig = str(r["kotlin_signature"] or "").strip()
        if not sig:
            continue
        if public_only and _INTERNAL_DECL_RE.search(sig):
            continue
        norm = re.sub(r"\s+", " ", sig)
        if norm in seen:
            continue
        seen.add(norm)
        sigs.append(sig)
        if len(sigs) >= limit:
            break
    return sigs


def _is_internal_symbol(conn: sqlite3.Connection, name: str, package: str, kotlin_sigs: list[str]) -> bool:
    """Return True if a symbol is an internal-only implementation detail rather than public API."""
    clean_name = name.strip()
    if not clean_name:
        return True
    if _has_table(conn, "kotlin_sources"):
        low = clean_name.lower()
        rows = conn.execute(
            """
            SELECT visibility, fq_package, kotlin_signature
            FROM kotlin_sources
            WHERE lower(name) = ? OR lower(qualified_name) = ?
            LIMIT 20
            """,
            (low, low),
        ).fetchall()
        if package:
            pkg_rows = [r for r in rows if str(r["fq_package"]).lower() == package.lower()]
            if pkg_rows:
                rows = pkg_rows
        if rows:
            has_public = any(
                str(r["visibility"]).lower() == "public" and not _INTERNAL_DECL_RE.search(str(r["kotlin_signature"] or ""))
                for r in rows
            )
            return not has_public
    if kotlin_sigs and all(_INTERNAL_DECL_RE.search(s) for s in kotlin_sigs):
        return True
    if clean_name.endswith(("Impl", "Tokens", "StyleScope")):
        return True
    return False


def query_api(
    paths: RepoPaths,
    symbol_or_query: str,
    *,
    target: str | None = None,
    diff_only: bool = False,
    limit: int = 30,
) -> dict[str, Any]:
    """Query API symbols (enriched with Kotlin default parameters) and Maven version pins across AndroidX & CMP."""
    db_path = ensure_index(paths)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        fts_expr = _fts_query(symbol_or_query, use_or=False)
        rows: list[sqlite3.Row] = []
        if fts_expr:
            try:
                rows = conn.execute(
                    """
                    SELECT a.*, bm25(api_fts, 6.0, 2.0, 3.0, 2.0, 1.0, 1.0, 1.0, 1.0) AS rank
                    FROM api_fts
                    JOIN api_symbols a ON api_fts.rowid = a.id
                    WHERE api_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_expr, limit * 3),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

        if not rows:
            like = f"%{symbol_or_query.strip()}%"
            rows = conn.execute(
                """
                SELECT *, 0.0 AS rank FROM api_symbols
                WHERE name LIKE ? OR package LIKE ? OR signature LIKE ? OR annotations LIKE ?
                LIMIT ?
                """,
                (like, like, like, like, limit * 3),
            ).fetchall()

        filtered_symbols: list[dict[str, Any]] = []
        has_kt_col = False
        if rows:
            has_kt_col = "kotlin_defaults_signature" in rows[0].keys()

        for r in rows:
            targets = json.loads(r["targets"])
            if target:
                t_low = target.lower()
                target_strs = [str(t).lower() for t in targets]
                if t_low not in target_strs and not (t_low in ("android", "desktop", "ios") and "common" in target_strs):
                    continue
            parity = r["parity_status"]
            androidx_sig = r["androidx_signature"]
            cmp_sig = r["cmp_signature"]
            has_diff = bool(
                (parity and parity.lower() not in ("parity", "identical", "exact"))
                or (androidx_sig and cmp_sig and androidx_sig != cmp_sig)
                or (bool(androidx_sig) != bool(cmp_sig))
            )
            if diff_only and not has_diff:
                continue

            kt_sigs = _lookup_kotlin_signatures_for_symbol(conn, r["name"], r["package"], limit=3)
            manifest_kt = str(r["kotlin_defaults_signature"] or "").strip() if has_kt_col else ""
            if manifest_kt and not kt_sigs:
                kt_sigs.append(manifest_kt)

            filtered_symbols.append(
                {
                    "name": r["name"],
                    "package": r["package"],
                    "kind": r["kind"],
                    "signature": r["signature"],
                    "kotlin_signatures": kt_sigs[:3],
                    "annotations": json.loads(r["annotations"]),
                    "artifact": r["artifact"],
                    "version": r["version"],
                    "targets": targets,
                    "androidx_signature": androidx_sig,
                    "cmp_signature": cmp_sig,
                    "parity_status": parity,
                    "doc": r["doc"],
                    "source_file": r["source_file"],
                }
            )
            if len(filtered_symbols) >= limit:
                break

        # Fallback to `kotlin_sources` for symbols outside material3-expressive-surface.json (e.g. foundation, ui, skiko, nav3)
        if not filtered_symbols and not diff_only and _has_table(conn, "kotlin_sources"):
            ks_rows = _find_kotlin_source_rows(conn, symbol_or_query, artifact=None, limit=limit)
            seen_keys: set[tuple[str, str, str]] = set()
            for r in ks_rows:
                plat = str(r["platform"] or "common")
                targets = [plat] if plat else ["common"]
                if target:
                    t_low = target.lower()
                    if t_low != plat.lower() and plat.lower() != "common":
                        continue
                sig = str(r["kotlin_signature"] or "").strip()
                dedup = (str(r["qualified_name"]), str(r["fq_package"]), re.sub(r"\s+", " ", sig))
                if dedup in seen_keys:
                    continue
                seen_keys.add(dedup)
                filtered_symbols.append(
                    {
                        "name": r["qualified_name"] or r["name"],
                        "package": r["fq_package"],
                        "kind": r["kind"],
                        "signature": sig,
                        "kotlin_signatures": [sig] if sig else [],
                        "annotations": json.loads(r["annotations"]),
                        "artifact": r["coordinate"] or r["artifact_key"],
                        "version": r["version"],
                        "targets": targets,
                        "androidx_signature": "",
                        "cmp_signature": "",
                        "parity_status": "",
                        "doc": r["kdoc"][:240] if r["kdoc"] else "",
                        "source_file": f".corpus/compose-maven-api/sources/{r['jar_name']}!{r['entry_path']}:{r['start_line']}",
                    }
                )
                if len(filtered_symbols) >= limit:
                    break

        like_ver = f"%{symbol_or_query.strip()}%"
        ver_rows = conn.execute(
            """
            SELECT * FROM api_versions
            WHERE coordinate LIKE ? OR artifact_id LIKE ? OR ecosystem LIKE ?
            ORDER BY ecosystem, coordinate
            LIMIT 20
            """,
            (like_ver, like_ver, like_ver),
        ).fetchall()
        versions = [
            {
                "coordinate": v["coordinate"],
                "ecosystem": v["ecosystem"],
                "stable": v["stable"],
                "rc": v["rc"],
                "beta": v["beta"],
                "alpha": v["alpha"],
                "latest": v["latest"],
                "source_file": v["source_file"],
            }
            for v in ver_rows
        ]
    finally:
        conn.close()

    return {
        "query": symbol_or_query,
        "target": target,
        "diff_only": diff_only,
        "symbols": filtered_symbols,
        "versions": versions,
    }


def query_tokens(
    paths: RepoPaths,
    query: str,
    *,
    category: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Query design tokens from `manifests/tokens/*.json` plus related docs."""
    db_path = ensure_index(paths)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tokens: list[dict[str, Any]] = []
    try:
        fts_expr = _fts_query(query, use_or=False)
        rows: list[sqlite3.Row] = []
        cat_clause = " AND lower(t.category) LIKE ?" if category else ""
        cat_params: list[Any] = [f"%{category.lower()}%"] if category else []
        if fts_expr:
            try:
                rows = conn.execute(
                    f"""
                    SELECT t.*, bm25(tokens_fts, 6.0, 3.0, 2.0, 2.0, 3.0, 1.0, 1.0) AS rank
                    FROM tokens_fts
                    JOIN design_tokens t ON tokens_fts.rowid = t.id
                    WHERE tokens_fts MATCH ?{cat_clause}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_expr, *cat_params, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

        if not rows:
            like = f"%{query.strip()}%"
            cat_clause_plain = " AND lower(category) LIKE ?" if category else ""
            rows = conn.execute(
                f"""
                SELECT *, 0.0 AS rank FROM design_tokens
                WHERE (name LIKE ? OR category LIKE ? OR value LIKE ? OR role LIKE ? OR compose_token LIKE ? OR notes LIKE ?)
                {cat_clause_plain}
                LIMIT ?
                """,
                (like, like, like, like, like, like, *cat_params, limit),
            ).fetchall()

        for r in rows:
            tokens.append(
                {
                    "name": r["name"],
                    "category": r["category"],
                    "value": r["value"],
                    "role": r["role"],
                    "compose_token": r["compose_token"],
                    "spec_version": r["spec_version"],
                    "notes": r["notes"],
                    "source_file": r["source_file"],
                }
            )
    finally:
        conn.close()

    doc_hits = [h.to_dict() for h in search_corpus(paths, query, layer="knowledge", limit=6)]
    return {
        "query": query,
        "category": category,
        "tokens": tokens,
        "knowledge_refs": doc_hits,
    }


# ---------------------------------------------------------------------------
# Upstream Component Dossier (`rtx component`)
# ---------------------------------------------------------------------------


def _normalize_component_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _camel_to_words(name: str) -> list[str]:
    spaced = _CAMEL_SPLIT_RE.sub(" ", name)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]


def _resolve_m3_component_pages(paths: RepoPaths, name: str) -> list[tuple[str, Path]]:
    """Resolve a component query (e.g. `SearchBar`, `PrimaryTabRow`, `Carousel`) to `.corpus/m3-expressive` pages."""
    pages_root = paths.source_pages_dir("m3-expressive")
    if not pages_root.is_dir():
        return []
    comp_dir = pages_root / "components"
    search_dirs = [comp_dir, pages_root] if comp_dir.is_dir() else [pages_root]

    available: dict[str, Path] = {}
    for sdir in search_dirs:
        for p in sorted(sdir.glob("*.md")):
            if p.name == "INDEX.md":
                continue
            available.setdefault(p.stem.lower(), p)

    resolved: list[tuple[str, Path]] = []
    seen_slugs: set[str] = set()

    def add_slug(slug: str) -> None:
        if slug in available and slug not in seen_slugs:
            seen_slugs.add(slug)
            resolved.append((slug, available[slug]))

    key = _normalize_component_key(name)
    for slug in _M3_COMPONENT_ALIASES.get(key, []):
        add_slug(slug)

    if not resolved:
        words = _camel_to_words(name)
        kebab = "-".join(words)
        candidates = [kebab, f"{kebab}s", kebab.rstrip("s")]
        # Strip common Compose suffixes/prefixes to find canonical M3 component page
        strip_tokens = {
            "layout",
            "defaults",
            "state",
            "item",
            "row",
            "host",
            "indicator",
            "colors",
            "horizontal",
            "vertical",
            "primary",
            "secondary",
            "modal",
            "standard",
            "docked",
            "wide",
            "short",
            "medium",
            "large",
            "small",
            "flexible",
            "scrollable",
            "centered",
            "center",
            "aligned",
            "multi",
            "browse",
            "uncontained",
            "hero",
            "full",
            "screen",
            "expanded",
            "outlined",
            "filled",
            "tonal",
            "elevated",
            "plain",
            "rich",
            "box",
        }
        core = [w for w in words if w not in strip_tokens]
        if core:
            core_kebab = "-".join(core)
            candidates.extend([core_kebab, f"{core_kebab}s", core_kebab.rstrip("s")])
            core_key = "".join(core)
            for slug in _M3_COMPONENT_ALIASES.get(core_key, []):
                add_slug(slug)

        for cand in candidates:
            if cand:
                add_slug(cand)

    if not resolved:
        # Substring fallback across available component stems
        words = _camel_to_words(name)
        for slug in sorted(available):
            slug_compact = slug.replace("-", "")
            if key and (slug_compact in key or key in slug_compact):
                add_slug(slug)
            elif len(words) >= 1 and all(w in slug for w in words if len(w) >= 3):
                add_slug(slug)

    return resolved[:2]


def _parse_page_h2_sections(
    text: str,
    *,
    include_excluded_platforms: bool = False,
) -> list[dict[str, Any]]:
    """Parse a markdown file into top-level H2 sections (aggregating H3+ subsections inside each H2)."""
    _, body_start = parse_page_frontmatter(text)
    lines = text.splitlines()
    sections: list[dict[str, Any]] = []

    current_heading = "Overview"
    current_start = body_start
    buf: list[str] = []
    in_fence = False
    fence_char = ""
    in_m3_xr = False
    skip_h2 = False

    def flush(end_line: int) -> None:
        if not buf or skip_h2 or in_m3_xr:
            return
        raw = "\n".join(buf)
        cleaned = clean_spec_markdown(raw, include_excluded_platforms=include_excluded_platforms)
        # Skip bare H1-only prelude chunks (e.g. just `# Search` before `## Overview`)
        non_h1 = "\n".join(ln for ln in cleaned.splitlines() if not ln.lstrip().startswith("# ")).strip()
        if non_h1:
            sections.append(
                {
                    "heading": current_heading,
                    "start_line": current_start,
                    "end_line": end_line,
                    "raw": raw,
                    "clean": cleaned,
                }
            )

    for idx in range(max(0, body_start - 1), len(lines)):
        line = lines[idx]
        line_no = idx + 1
        fm = _FENCE_RE.match(line)
        if fm:
            marker = fm.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_fence = False
                fence_char = ""
            buf.append(line)
            continue

        hm = None if in_fence else _HEADING_RE.match(line)
        if hm and len(hm.group(1)) == 2:
            flush(line_no - 1)
            heading = hm.group(2).strip()
            low = heading.lower()

            if in_m3_xr:
                if low in ("accessibility", "component design tokens"):
                    in_m3_xr = False
                else:
                    buf = []
                    continue

            if not include_excluded_platforms and low == "xr":
                in_m3_xr = True
                skip_h2 = True
                buf = []
                continue

            skip_h2 = _is_skip_heading(heading, include_excluded_platforms=include_excluded_platforms)
            current_heading = heading
            current_start = line_no
            buf = [line]
        else:
            if not skip_h2 and not in_m3_xr:
                buf.append(line)

    flush(len(lines))
    return sections


def _extract_do_dont_captions(sections: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    """Extract official `_Do / Don't / Avoid / Use ..._` italic figure captions from M3 sections."""
    captions: list[str] = []
    seen: set[str] = set()

    skip_headings = {"differences from m2", "differences from m2 to m3 baseline", "measurements", "color", "states"}

    for sec in sections:
        if sec["heading"].strip().lower() in skip_headings:
            continue
        lines = sec["clean"].splitlines()
        idx = 0
        while idx < len(lines):
            stripped = lines[idx].strip()
            if stripped.startswith("_") and not stripped.startswith("__"):
                block = [stripped]
                while not block[-1].endswith("_") and idx + 1 < len(lines) and len(block) < 5:
                    idx += 1
                    nxt = lines[idx].strip()
                    if not nxt:
                        break
                    block.append(nxt)
                joined = " ".join(block).strip()
                if joined.startswith("_") and joined.endswith("_") and len(joined) > 12:
                    inner = joined[1:-1].strip()
                    low = inner.lower()
                    # Exclude measurement/M2/generic diagram captions
                    if (
                        "measurement" not in low
                        and not low.startswith(("m2:", "m2 "))
                        and any(kw in low for kw in _DO_DONT_KEYWORDS)
                    ):
                        norm = re.sub(r"\s+", " ", inner)
                        if norm.lower() not in seen:
                            seen.add(norm.lower())
                            captions.append(f"_{norm}_")
            idx += 1

    # Prioritize hard negative rules ("Don't", "Avoid", "Never", "shouldn't") first!
    def caption_priority(cap: str) -> tuple[int, int]:
        low = cap.lower()
        if any(w in low for w in ("don't", "don’t", "never", "avoid", "shouldn't", "shouldn’t", "not recommended")):
            return (0, len(cap))
        return (1, len(cap))

    captions.sort(key=caption_priority)
    return captions[:limit]


def _strip_leading_h2(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith("## "):
        return "\n".join(lines[1:]).strip()
    return text.strip()


def _extract_m3_component_dossier(
    paths: RepoPaths,
    md_path: Path,
    *,
    include_excluded_platforms: bool = False,
) -> dict[str, Any]:
    """Extract a clean, lossless official M3 Expressive design dossier from a component mirror page."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    meta, _ = parse_page_frontmatter(text)
    rel_path = md_path.relative_to(paths.root).as_posix()
    title = meta.title if meta and meta.title else md_path.stem.replace("-", " ").title()
    url = meta.url if meta else ""

    sections = _parse_page_h2_sections(text, include_excluded_platforms=include_excluded_platforms)

    overview_parts: list[str] = []
    usage_parts: list[str] = []
    adaptive_parts: list[str] = []
    behavior_parts: list[str] = []

    for sec in sections:
        h = sec["heading"].strip().lower()
        body = _strip_leading_h2(sec["clean"])
        if not body:
            continue
        if h in ("overview", "m3 expressive update", "updates", "variants", "configurations", "configuration", "choosing buttons", "hierarchy"):
            overview_parts.append(f"### {sec['heading']}\n{body}")
        elif h in ("usage", "guidelines", "search app bar", "toggle buttons", "standard bottom sheets", "modal bottom sheets", "basic dialog", "full-screen dialog", "cards in a collection", "assist chips", "filter chips", "input chips", "suggestion chips"):
            usage_parts.append(f"### {sec['heading']}\n{body}")
        elif h in ("adaptive design", "placement", "responsive layout", "adaptive layout", "position & orientation"):
            adaptive_parts.append(f"### {sec['heading']}\n{body}")
        elif h in ("behavior", "behaviors", "selection & activation", "actions"):
            behavior_parts.append(f"### {sec['heading']}\n{body}")

    # Fallback: if a short page (like test fixtures) only had an Overview/intro without H2 sections
    if not any((overview_parts, usage_parts, adaptive_parts, behavior_parts)) and sections:
        overview_parts.append(sections[0]["clean"])

    do_dont_rules = _extract_do_dont_captions(sections, limit=12)

    return {
        "title": title,
        "path": rel_path,
        "url": url,
        "overview_and_variants": _truncate_clean("\n\n".join(overview_parts), 1200) if overview_parts else "",
        "usage": _truncate_clean("\n\n".join(usage_parts), 1600) if usage_parts else "",
        "do_dont_rules": do_dont_rules,
        "adaptive_and_placement": _truncate_clean("\n\n".join(adaptive_parts), 1300) if adaptive_parts else "",
        "behavior": _truncate_clean("\n\n".join(behavior_parts), 1000) if behavior_parts else "",
    }


def _extract_hig_counterpart(
    paths: RepoPaths,
    source_id: str,
    md_path: Path,
    *,
    include_excluded_platforms: bool = False,
) -> dict[str, Any] | None:
    """Extract clean overview + best practices / usage guidance from an Apple/Windows/Linux HIG page."""
    if not md_path.is_file():
        return None
    text = md_path.read_text(encoding="utf-8", errors="replace")
    meta, _ = parse_page_frontmatter(text)
    rel_path = md_path.relative_to(paths.root).as_posix()
    title = meta.title if meta and meta.title else md_path.stem.replace("-", " ").title()
    url = meta.url if meta else ""

    sections = _parse_page_h2_sections(text, include_excluded_platforms=include_excluded_platforms)
    parts: list[str] = []
    preferred = ("overview", "best practices", "usage", "guidelines", "when to use", "dos and don'ts", "do's and don'ts", "platform considerations", "design", "recommendations", "behavior")
    for sec in sections:
        h = sec["heading"].strip().lower()
        if any(p in h for p in preferred) or sec["heading"] == "Overview":
            body = _strip_leading_h2(sec["clean"])
            if body:
                if sec["heading"] == "Overview":
                    parts.append(body)
                else:
                    parts.append(f"**{sec['heading']}**: {body}")
        if sum(len(p) for p in parts) >= 750:
            break

    if not parts and sections:
        parts.append(sections[0]["clean"])

    summary = _truncate_clean("\n\n".join(parts), 750)
    if not summary:
        return None
    return {
        "source_id": source_id,
        "title": title,
        "path": rel_path,
        "url": url,
        "summary": summary,
    }


def query_component(paths: RepoPaths, name: str) -> dict[str, Any]:
    """Lossless official component dossier: M3E spec (Usage/Variants/Do-Don'ts/Adaptive/Behavior), HIG counterparts, knowledge, tokens, and Kotlin API signatures with defaults."""
    include_excluded = _query_wants_excluded_platform(name)
    resolved_m3 = _resolve_m3_component_pages(paths, name)
    m3_dossiers = [
        _extract_m3_component_dossier(paths, p, include_excluded_platforms=include_excluded)
        for _, p in resolved_m3
    ]

    # Resolve matching Desktop/Mobile HIG counterpart pages directly
    hig_counterparts: list[dict[str, Any]] = []
    seen_hig_paths: set[str] = set()
    for slug, _ in resolved_m3:
        for src_id, rel in _HIG_COMPONENT_MAP.get(slug, []):
            candidate = paths.source_pages_dir(src_id) / rel
            if candidate.is_file():
                key = f"{src_id}:{rel}"
                if key not in seen_hig_paths:
                    seen_hig_paths.add(key)
                    item = _extract_hig_counterpart(paths, src_id, candidate, include_excluded_platforms=include_excluded)
                    if item:
                        hig_counterparts.append(item)

    # Fallback clean HIG search if no direct counterpart page was mapped
    words_query = " ".join(_camel_to_words(name)) or name
    if not hig_counterparts:
        for src_id in ("apple-hig", "windows-fluent", "linux-hig"):
            hits = search_corpus(paths, words_query, source=src_id, layer="mirror", limit=4)
            for h in hits:
                if _is_excluded_path(h.path, include_excluded_platforms=include_excluded):
                    continue
                if _is_skip_heading(h.heading, include_excluded_platforms=include_excluded):
                    continue
                p = paths.root / h.path
                if p.is_file() and h.path not in seen_hig_paths:
                    seen_hig_paths.add(h.path)
                    item = _extract_hig_counterpart(paths, src_id, p, include_excluded_platforms=include_excluded)
                    if item:
                        hig_counterparts.append(item)
                        break

    # API symbols: collect public Compose entry points (including prefixed/suffixed M3E composables like
    # WideNavigationRail, ModalWideNavigationRail, DockedSearchBar, HorizontalMultiBrowseCarousel) and exclude internals.
    comp_key_low = _normalize_component_key(name)
    slug_key_low = resolved_m3[0][0].replace("-", "") if resolved_m3 else comp_key_low
    # Singularized slug key (e.g. `tabs` -> `tab`, `toolbars` -> `toolbar`, `dialogs` -> `dialog`)
    slug_stem = slug_key_low[:-1] if len(slug_key_low) > 3 and slug_key_low.endswith("s") else slug_key_low

    db_path = ensure_index(paths)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        candidates_by_key: dict[tuple[str, str], dict[str, Any]] = {}

        def _add_api_candidate(sym: dict[str, Any]) -> None:
            sname = str(sym.get("name") or "").strip()
            spkg = str(sym.get("package") or "").strip()
            if not sname:
                return
            if _is_internal_symbol(conn, sname, spkg, list(sym.get("kotlin_signatures") or [])):
                return
            pub_kt = _lookup_kotlin_signatures_for_symbol(conn, sname, spkg, limit=3, public_only=True)
            if not pub_kt:
                pub_kt = [s for s in (sym.get("kotlin_signatures") or []) if not _INTERNAL_DECL_RE.search(s)]
            sym_copy = dict(sym)
            sym_copy["kotlin_signatures"] = pub_kt
            key = (spkg.lower(), sname.lower())
            if key not in candidates_by_key or (
                not candidates_by_key[key].get("parity_status") and sym_copy.get("parity_status")
            ):
                candidates_by_key[key] = sym_copy

        # 1. FTS / exact query_api hits
        for sym in query_api(paths, name, limit=50)["symbols"]:
            _add_api_candidate(sym)
        if not candidates_by_key and words_query.lower() != name.lower():
            for sym in query_api(paths, words_query, limit=30)["symbols"]:
                _add_api_candidate(sym)

        # 2. Substring search in `api_symbols` so prefixed M3E composables (e.g. WideNavigationRail, DockedSearchBar) match
        like_patterns: list[str] = []
        for pat in (comp_key_low, slug_key_low, slug_stem):
            if pat and len(pat) >= 3 and pat not in like_patterns:
                like_patterns.append(pat)

        for pat in like_patterns:
            rows = conn.execute(
                """
                SELECT * FROM api_symbols
                WHERE lower(name) LIKE ?
                LIMIT 60
                """,
                (f"%{pat}%",),
            ).fetchall()
            has_kt_col = bool(rows and "kotlin_defaults_signature" in rows[0].keys())
            for r in rows:
                pub_kt = _lookup_kotlin_signatures_for_symbol(conn, r["name"], r["package"], limit=3, public_only=True)
                manifest_kt = str(r["kotlin_defaults_signature"] or "").strip() if has_kt_col else ""
                if manifest_kt and not pub_kt and not _INTERNAL_DECL_RE.search(manifest_kt):
                    pub_kt = [manifest_kt]
                _add_api_candidate(
                    {
                        "name": r["name"],
                        "package": r["package"],
                        "kind": r["kind"],
                        "signature": r["signature"],
                        "kotlin_signatures": pub_kt,
                        "annotations": json.loads(r["annotations"]),
                        "artifact": r["artifact"],
                        "version": r["version"],
                        "targets": json.loads(r["targets"]),
                        "androidx_signature": r["androidx_signature"],
                        "cmp_signature": r["cmp_signature"],
                        "parity_status": r["parity_status"],
                        "doc": r["doc"],
                        "source_file": r["source_file"],
                    }
                )

        # 3. Direct public `kotlin_sources` lookup (prefers androidx.compose.material3 public composables/classes)
        if _has_table(conn, "kotlin_sources"):
            for pat in like_patterns:
                ks_rows = conn.execute(
                    """
                    SELECT * FROM kotlin_sources
                    WHERE visibility = 'public'
                      AND (is_composable = 1 OR kind IN ('composable', 'class', 'object'))
                      AND (lower(name) LIKE ? OR lower(qualified_name) LIKE ?)
                    ORDER BY
                        (fq_package LIKE 'androidx.compose.material3%') DESC,
                        is_composable DESC,
                        has_defaults DESC,
                        length(name) ASC
                    LIMIT 40
                    """,
                    (f"%{pat}%", f"%{pat}%"),
                ).fetchall()
                for r in ks_rows:
                    sig = str(r["kotlin_signature"] or "").strip()
                    if _INTERNAL_DECL_RE.search(sig):
                        continue
                    qname = str(r["qualified_name"] or r["name"])
                    _add_api_candidate(
                        {
                            "name": qname,
                            "package": r["fq_package"],
                            "kind": r["kind"],
                            "signature": sig,
                            "kotlin_signatures": [sig] if sig else [],
                            "annotations": json.loads(r["annotations"]),
                            "artifact": r["coordinate"] or r["artifact_key"],
                            "version": r["version"],
                            "targets": [r["platform"] or "common"],
                            "androidx_signature": "",
                            "cmp_signature": "",
                            "parity_status": "",
                            "doc": r["kdoc"][:200] if r["kdoc"] else "",
                            "source_file": f".corpus/compose-maven-api/sources/{r['jar_name']}!{r['entry_path']}:{r['start_line']}",
                        }
                    )
    finally:
        conn.close()

    def _api_sort_key(sym: dict[str, Any]) -> tuple[int, int, int, int, int, int, str]:
        sname = str(sym.get("name") or "")
        spkg = str(sym.get("package") or "").lower()
        s_norm = _normalize_component_key(sname)
        is_m3 = 0 if spkg.startswith("androidx.compose.material3") else 1
        is_comp = 0 if str(sym.get("kind") or "").lower() == "composable" else 1
        is_helper = 1 if (sname[:1].islower() or sname.startswith("remember")) else 0
        kt_sigs = sym.get("kotlin_signatures") or []
        has_defaults = 0 if any("=" in s for s in kt_sigs) else 1
        exact_or_contains = 0 if (s_norm == comp_key_low or comp_key_low in s_norm or slug_stem in s_norm) else 1
        # Boost flagship M3 Expressive variants (WideNavigationRail, ShortNavigationBar, DockedSearchBar, HorizontalMultiBrowseCarousel)
        is_expressive_flagship = (
            0
            if (
                s_norm == comp_key_low
                or sname.startswith(("Wide", "ModalWide", "Short", "HorizontalMultiBrowse", "HorizontalUncontained", "Docked", "Expanded", "Primary", "Secondary"))
            )
            else 1
        )
        return (is_m3, is_comp, is_helper, exact_or_contains, has_defaults, is_expressive_flagship, sname)

    compose_apis = sorted(candidates_by_key.values(), key=_api_sort_key)[:12]

    # Tokens (fallback to kebab/spaced component slug when camelCase has 0 hits)
    tok_res = query_tokens(paths, name, limit=12)
    tokens = list(tok_res["tokens"])
    if not tokens and resolved_m3:
        slug_q = resolved_m3[0][0].replace("-", " ")
        tokens = list(query_tokens(paths, slug_q, limit=12)["tokens"])
    if not tokens and words_query.lower() != name.lower():
        tokens = list(query_tokens(paths, words_query, limit=12)["tokens"])

    # Curated knowledge notes (deduplicated)
    knowledge_hits = [h.to_dict() for h in search_corpus(paths, name, layer="knowledge", limit=6)]
    if not knowledge_hits and words_query.lower() != name.lower():
        knowledge_hits = [h.to_dict() for h in search_corpus(paths, words_query, layer="knowledge", limit=6)]

    # Backward-compatible summary fields populated cleanly (zero raw firebasestorage image URLs!)
    m3_hits = [
        {
            "layer": "mirror",
            "source_id": "m3-expressive",
            "path": d["path"],
            "line": 1,
            "end_line": 1,
            "title": d["title"],
            "heading": "Official Component Dossier",
            "url": d["url"],
            "score": -10.0,
            "snippet": _make_snippet(d["overview_and_variants"] or d["usage"], [name]),
        }
        for d in m3_dossiers
    ]
    if not m3_hits:
        raw_m3 = search_corpus(paths, words_query, source="m3-expressive", layer="mirror", limit=6)
        m3_hits = [
            h.to_dict()
            for h in raw_m3
            if not _is_excluded_path(h.path, include_excluded_platforms=include_excluded)
            and not _is_skip_heading(h.heading, include_excluded_platforms=include_excluded)
        ][:4]

    compose_hits = [
        h.to_dict()
        for h in (
            search_corpus(paths, name, source="compose-android", layer="mirror", limit=3)
            + search_corpus(paths, name, source="compose-multiplatform", layer="mirror", limit=2)
        )
    ]

    platform_hig = [
        {
            "layer": "mirror",
            "source_id": item["source_id"],
            "path": item["path"],
            "line": 1,
            "end_line": 1,
            "title": item["title"],
            "heading": item["title"],
            "url": item["url"],
            "score": -5.0,
            "snippet": _make_snippet(item["summary"], [name]),
        }
        for item in hig_counterparts
    ]

    return {
        "component": name,
        "m3_dossier": m3_dossiers,
        "hig_counterparts": hig_counterparts,
        "compose_apis": compose_apis,
        "tokens": tokens,
        "knowledge": knowledge_hits,
        "m3_expressive": m3_hits,
        "compose_docs": compose_hits,
        "platform_hig": platform_hig,
    }


# ---------------------------------------------------------------------------
# Upstream Design Direction & Pattern Reader (`rtx spec`)
# ---------------------------------------------------------------------------


def _read_coherent_section(
    paths: RepoPaths,
    rel_path: str,
    target_line: int,
    *,
    include_excluded_platforms: bool = False,
    max_chars: int = 1600,
) -> tuple[str, int, int, str]:
    """Read the full coherent H2 section containing `target_line` from disk and strip noise."""
    full_path = paths.root / rel_path
    if not full_path.is_file():
        return ("", target_line, target_line, "")
    text = full_path.read_text(encoding="utf-8", errors="replace")
    sections = _parse_page_h2_sections(text, include_excluded_platforms=include_excluded_platforms)
    chosen = None
    for sec in sections:
        if sec["start_line"] <= target_line <= sec["end_line"]:
            chosen = sec
            break
    if chosen is None and sections:
        chosen = min(sections, key=lambda s: abs(s["start_line"] - target_line))
    if chosen is None:
        return ("", target_line, target_line, "")

    cleaned = _truncate_clean(chosen["clean"], max_chars)
    return (chosen["heading"], chosen["start_line"], chosen["end_line"], cleaned)


def _topic_boosted_paths(query_tokens: set[str]) -> tuple[str, ...]:
    boosted: list[str] = []
    for triggers, fragments in _SPEC_TOPIC_HINTS:
        if query_tokens & triggers:
            boosted.extend(fragments)
    return tuple(dict.fromkeys(boosted))


def query_spec(
    paths: RepoPaths,
    query: str,
    *,
    source: str | None = None,
    limit: int = 5,
    max_chars: int = 1600,
) -> dict[str, Any]:
    """Return complete, noise-stripped official upstream design sections for architecture/pattern decisions."""
    db_path = ensure_index(paths)
    include_excluded = _query_wants_excluded_platform(query)
    raw_terms = _TOKEN_RE.findall(query)
    terms = [t.lower() for t in raw_terms if t.lower() not in _STOPWORDS] or [t.lower() for t in raw_terms]
    term_set = set(terms)
    boosted_fragments = _topic_boosted_paths(term_set)

    fts_and = _fts_query(query, use_or=False, drop_stopwords=True)
    fts_or = _fts_query(query, use_or=True, drop_stopwords=True)

    allowed_sources = (source,) if source else _SPEC_SOURCES
    placeholders = ",".join("?" for _ in allowed_sources)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    candidates: dict[int, sqlite3.Row] = {}
    try:
        for expr, cap in ((fts_and, max(40, limit * 8)), (fts_or, max(80, limit * 16))):
            if not expr:
                continue
            try:
                rows = conn.execute(
                    f"""
                    SELECT
                        m.id, m.layer, m.source_id, m.path, m.title, m.heading, m.url,
                        m.start_line, m.end_line, m.content,
                        bm25(docs_fts, 5.0, 6.0, 2.0, 1.0, 0.5, 0.5) AS rank
                    FROM docs_fts
                    JOIN docs_meta m ON docs_fts.rowid = m.id
                    WHERE docs_fts MATCH ? AND m.source_id IN ({placeholders})
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (expr, *allowed_sources, cap),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            for r in rows:
                candidates.setdefault(int(r["id"]), r)
            if len(candidates) >= limit * 6:
                break

        # Also pull sections from directly topic-boosted upstream files if FTS missed a synonym
        if boosted_fragments and len(candidates) < limit * 6:
            for frag in boosted_fragments[:6]:
                like_path = f"%{frag}%"
                extra_rows = conn.execute(
                    f"""
                    SELECT
                        id, layer, source_id, path, title, heading, url,
                        start_line, end_line, content, -0.5 AS rank
                    FROM docs_meta
                    WHERE path LIKE ? AND source_id IN ({placeholders})
                    LIMIT 8
                    """,
                    (like_path, *allowed_sources),
                ).fetchall()
                for r in extra_rows:
                    candidates.setdefault(int(r["id"]), r)
    finally:
        conn.close()

    good_headings = (
        "usage",
        "guidelines",
        "overview",
        "best practices",
        "adaptive design",
        "placement",
        "behavior",
        "choosing",
        "hierarchy",
        "similar components",
        "variants",
        "modality",
        "resizing",
        "canonical",
        "focused search",
        "different ways to search",
        "layout",
        "selection",
        "feedback",
    )

    scored: list[tuple[float, sqlite3.Row]] = []
    for row in candidates.values():
        rel_path = str(row["path"]).replace("\\", "/")
        src_id = str(row["source_id"])
        heading = str(row["heading"])
        title = str(row["title"])

        # Exclude Dokka / non-design compose-android pages unless user explicitly filters to compose-android
        if src_id == "compose-android" and "/pages/design/" not in rel_path and source != "compose-android":
            continue
        if rel_path.endswith("/INDEX.md") or rel_path == "INDEX.md":
            continue
        if _is_excluded_path(rel_path, include_excluded_platforms=include_excluded):
            continue
        if _is_skip_heading(heading, include_excluded_platforms=include_excluded):
            continue

        cleaned_preview = clean_spec_markdown(str(row["content"]), include_excluded_platforms=include_excluded)
        if len(cleaned_preview.strip()) < 40:
            continue

        haystack = f"{title} {heading} {cleaned_preview}".lower()
        title_head_low = f"{title} {heading}".lower()
        matched_terms = sum(1 for t in term_set if t in haystack)
        title_term_hits = sum(1 for t in term_set if t in title_head_low)
        if matched_terms == 0 and not any(frag in rel_path.lower() for frag in boosted_fragments):
            continue

        # Lower score is better (matching SQLite BM25 sign convention)
        score = float(row["rank"])
        score -= matched_terms * 2.2
        score -= title_term_hits * 1.5
        if any(frag in rel_path.lower() for frag in boosted_fragments):
            score -= 4.5
        if src_id == "m3-expressive":
            score -= 1.0
        if "/widgets/" in rel_path.lower() and "widget" not in term_set and "widgets" not in term_set:
            score += 4.0
        h_low = heading.lower()
        if h_low == "overview":
            score -= 0.5
        elif any(gh in h_low for gh in good_headings):
            score -= 3.5
        if len(cleaned_preview.strip()) < 140:
            score += 2.0
        if "accessibility" in h_low and not (term_set & {"accessibility", "a11y", "screen", "reader", "keyboard", "focus", "contrast"}):
            score += 2.5
        if h_low in ("measurements", "color", "states", "anatomy"):
            score += 1.5

        scored.append((score, row))

    scored.sort(key=lambda pair: (pair[0], int(pair[1]["start_line"])))

    sections_out: list[dict[str, Any]] = []
    seen_h2: set[tuple[str, str]] = set()
    per_file_count: dict[str, int] = {}

    for score, row in scored:
        rel_path = str(row["path"])
        if per_file_count.get(rel_path, 0) >= 2:
            continue

        h2_heading, s_line, e_line, coherent_body = _read_coherent_section(
            paths,
            rel_path,
            int(row["start_line"]),
            include_excluded_platforms=include_excluded,
            max_chars=max_chars,
        )
        if not coherent_body:
            coherent_body = _truncate_clean(
                clean_spec_markdown(str(row["content"]), include_excluded_platforms=include_excluded),
                max_chars,
            )
            h2_heading = str(row["heading"])
            s_line = int(row["start_line"])
            e_line = int(row["end_line"])

        if not coherent_body.strip():
            continue
        if _is_skip_heading(h2_heading, include_excluded_platforms=include_excluded):
            continue

        dedup_key = (rel_path, h2_heading.lower())
        if dedup_key in seen_h2:
            continue
        seen_h2.add(dedup_key)
        per_file_count[rel_path] = per_file_count.get(rel_path, 0) + 1

        sections_out.append(
            {
                "source_id": str(row["source_id"]),
                "path": rel_path,
                "start_line": s_line,
                "end_line": e_line,
                "title": str(row["title"]),
                "heading": h2_heading,
                "matched_subheading": str(row["heading"]),
                "url": str(row["url"]),
                "score": round(score, 3),
                "content": coherent_body,
            }
        )
        if len(sections_out) >= limit:
            break

    return {
        "query": query,
        "source": source,
        "count": len(sections_out),
        "sections": sections_out,
    }


def query_spec_batch(
    paths: RepoPaths,
    queries: list[str],
    *,
    source: str | None = None,
    limit: int = 5,
    max_chars: int = 1600,
) -> dict[str, Any]:
    """Run `query_spec` over multiple design pattern queries."""
    results = [query_spec(paths, q, source=source, limit=limit, max_chars=max_chars) for q in queries]
    return {"queries": queries, "source": source, "results": results}


# ---------------------------------------------------------------------------
# Upstream Kotlin Source Inspector (`rtx source`)
# ---------------------------------------------------------------------------


def _find_kotlin_source_rows(
    conn: sqlite3.Connection,
    symbol: str,
    *,
    artifact: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    if not _has_table(conn, "kotlin_sources"):
        return []
    sym = symbol.strip()
    if not sym:
        return []
    low = sym.lower()

    art_clause = ""
    art_params: list[Any] = []
    if artifact:
        art_like = f"%{artifact.strip().lower()}%"
        art_clause = " AND (lower(artifact_key) LIKE ? OR lower(coordinate) LIKE ? OR lower(jar_name) LIKE ? OR lower(platform) LIKE ?)"
        art_params = [art_like, art_like, art_like, art_like]

    order_sql = """
        ORDER BY
            (visibility = 'public') DESC,
            is_composable DESC,
            has_defaults DESC,
            CASE kind
                WHEN 'composable' THEN 0
                WHEN 'class' THEN 1
                WHEN 'interface' THEN 2
                WHEN 'object' THEN 3
                WHEN 'fun' THEN 4
                ELSE 5
            END,
            (artifact_key LIKE 'cmp-%') DESC,
            start_line ASC
    """

    # Tier 1: exact qualified_name or name match
    rows = conn.execute(
        f"""
        SELECT * FROM kotlin_sources
        WHERE (lower(qualified_name) = ? OR lower(name) = ?){art_clause}
        {order_sql}
        LIMIT ?
        """,
        (low, low, *art_params, limit * 3),
    ).fetchall()

    # Tier 2: suffix match on qualified_name (e.g. `PrimaryIndicator` -> `TabRowDefaults.PrimaryIndicator`)
    if not rows:
        suffix = f"%.{low}"
        rows = conn.execute(
            f"""
            SELECT * FROM kotlin_sources
            WHERE lower(qualified_name) LIKE ?{art_clause}
            {order_sql}
            LIMIT ?
            """,
            (suffix, *art_params, limit * 3),
        ).fetchall()

    # Tier 3: FTS5 search
    if not rows and _has_table(conn, "kotlin_sources_fts"):
        fts_expr = _fts_query(sym, use_or=False)
        if fts_expr:
            try:
                rows = conn.execute(
                    f"""
                    SELECT k.* FROM kotlin_sources_fts
                    JOIN kotlin_sources k ON kotlin_sources_fts.rowid = k.id
                    WHERE kotlin_sources_fts MATCH ?{art_clause.replace('artifact_key', 'k.artifact_key').replace('coordinate', 'k.coordinate').replace('jar_name', 'k.jar_name').replace('platform', 'k.platform')}
                    ORDER BY bm25(kotlin_sources_fts, 8.0, 4.0, 8.0, 2.0, 3.0, 1.0, 1.0, 0.5)
                    LIMIT ?
                    """,
                    (fts_expr, *art_params, limit * 3),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

    # Tier 4: substring LIKE fallback
    if not rows:
        like = f"%{low}%"
        rows = conn.execute(
            f"""
            SELECT * FROM kotlin_sources
            WHERE (lower(qualified_name) LIKE ? OR lower(name) LIKE ? OR lower(kotlin_signature) LIKE ?){art_clause}
            {order_sql}
            LIMIT ?
            """,
            (like, like, like, *art_params, limit * 3),
        ).fetchall()

    return rows


def query_source(
    paths: RepoPaths,
    symbol: str,
    *,
    artifact: str | None = None,
    context_lines: int = 0,
    limit: int = 5,
    max_lines: int = 140,
) -> dict[str, Any]:
    """Inspect upstream Kotlin/Java KDoc + exact source implementation directly from cached Maven `*-sources.jar`."""
    db_path = ensure_index(paths)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = _find_kotlin_source_rows(conn, symbol, artifact=artifact, limit=max(limit, 8))
    finally:
        conn.close()

    sources_dir = paths.corpus_dir / "compose-maven-api" / "sources"
    zip_cache: dict[str, zipfile.ZipFile] = {}

    # Deduplicate identical symbols across AndroidX & CMP jars (preserving distinct overloads)
    deduped: list[dict[str, Any]] = []
    by_sig_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    try:
        for r in rows:
            qname = str(r["qualified_name"] or r["name"])
            fq_pkg = str(r["fq_package"])
            sig_norm = re.sub(r"\s+", " ", str(r["kotlin_signature"] or "").strip())
            dedup_key = (fq_pkg, qname, sig_norm)
            jar_name = str(r["jar_name"])
            entry_path = str(r["entry_path"])

            if dedup_key in by_sig_key and not artifact:
                existing = by_sig_key[dedup_key]
                alt = f"{jar_name}!{entry_path}:{r['start_line']}"
                if alt not in existing["also_in"]:
                    existing["also_in"].append(alt)
                continue

            if len(deduped) >= limit:
                continue

            kdoc_start = int(r["kdoc_start_line"] or 0)
            start_line = int(r["start_line"] or 1)
            end_line = int(r["end_line"] or start_line)

            source_code = ""
            actual_start = kdoc_start if (kdoc_start > 0 and kdoc_start < start_line) else start_line
            actual_end = end_line
            truncated_lines = 0

            jar_path = sources_dir / jar_name
            if jar_name and jar_path.is_file():
                zf = zip_cache.get(jar_name)
                if zf is None:
                    try:
                        zf = zipfile.ZipFile(jar_path, "r")
                        zip_cache[jar_name] = zf
                    except zipfile.BadZipFile:
                        zf = None
                if zf is not None:
                    try:
                        raw_bytes = zf.read(entry_path)
                        file_lines = raw_bytes.decode("utf-8", errors="replace").splitlines()
                        s_idx = max(1, actual_start - max(0, context_lines))
                        e_idx = min(len(file_lines), end_line + max(0, context_lines))
                        if max_lines > 0 and (e_idx - s_idx + 1) > max_lines:
                            truncated_lines = (e_idx - s_idx + 1) - max_lines
                            e_idx = s_idx + max_lines - 1
                        actual_start = s_idx
                        actual_end = e_idx
                        width = len(str(e_idx))
                        source_code = "\n".join(
                            f"{ln_no:>{width}} | {file_lines[ln_no - 1]}"
                            for ln_no in range(s_idx, e_idx + 1)
                        )
                    except KeyError:
                        source_code = ""

            record = {
                "name": str(r["name"]),
                "owner": str(r["owner"]),
                "qualified_name": qname,
                "fq_package": fq_pkg,
                "kind": str(r["kind"]),
                "visibility": str(r["visibility"]),
                "is_composable": bool(r["is_composable"]),
                "annotations": json.loads(r["annotations"]),
                "jar_name": jar_name,
                "artifact_key": str(r["artifact_key"]),
                "coordinate": str(r["coordinate"]),
                "version": str(r["version"]),
                "platform": str(r["platform"]),
                "entry_path": entry_path,
                "kdoc_start_line": kdoc_start,
                "start_line": start_line,
                "end_line": end_line,
                "display_start_line": actual_start,
                "display_end_line": actual_end,
                "truncated_lines": truncated_lines,
                "has_defaults": bool(r["has_defaults"]),
                "kotlin_signature": str(r["kotlin_signature"]),
                "kdoc": str(r["kdoc"]),
                "source_code": source_code,
                "also_in": [],
            }
            deduped.append(record)
            by_sig_key[dedup_key] = record
    finally:
        for zf in zip_cache.values():
            zf.close()

    return {
        "symbol": symbol,
        "artifact": artifact,
        "count": len(deduped),
        "matches": deduped,
    }


def query_source_batch(
    paths: RepoPaths,
    symbols: list[str],
    *,
    artifact: str | None = None,
    context_lines: int = 0,
    limit: int = 5,
    max_lines: int = 140,
) -> dict[str, Any]:
    """Run `query_source` over multiple symbol names."""
    results = [
        query_source(paths, s, artifact=artifact, context_lines=context_lines, limit=limit, max_lines=max_lines)
        for s in symbols
    ]
    return {"symbols": symbols, "artifact": artifact, "results": results}


# ---------------------------------------------------------------------------
# Batch Wrappers & Copy / Status / Doctor
# ---------------------------------------------------------------------------


def query_api_batch(
    paths: RepoPaths,
    queries: list[str],
    *,
    target: str | None = None,
    diff_only: bool = False,
    limit: int = 30,
) -> dict[str, Any]:
    """Run `query_api` over multiple symbol/artifact queries in one batch."""
    results = [query_api(paths, q, target=target, diff_only=diff_only, limit=limit) for q in queries]
    return {"queries": queries, "target": target, "diff_only": diff_only, "results": results}


def query_component_batch(paths: RepoPaths, names: list[str]) -> dict[str, Any]:
    """Run `query_component` over multiple component names in one batch."""
    results = [query_component(paths, n) for n in names]
    return {"queries": names, "results": results}


def query_tokens_batch(
    paths: RepoPaths,
    queries: list[str],
    *,
    category: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Run `query_tokens` over multiple token queries in one batch."""
    results = [query_tokens(paths, q, category=category, limit=limit) for q in queries]
    return {"queries": queries, "category": category, "results": results}


def query_copy(paths: RepoPaths, topic: str, *, limit: int = 15) -> dict[str, Any]:
    """Query UI copywriting & microcopy rules across UX writing and platform style guides."""
    db_path = ensure_index(paths)
    terms = _TOKEN_RE.findall(topic)
    fts_and = _fts_query(topic, use_or=False)
    fts_or = _fts_query(topic, use_or=True)

    copy_sources = ("knowledge", "writing-style", "m3-expressive", "apple-hig", "windows-fluent", "linux-hig")
    hits: list[SearchHit] = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for expr in (fts_and, fts_or):
            if not expr:
                continue
            placeholders = ",".join("?" for _ in copy_sources)
            try:
                rows = conn.execute(
                    f"""
                    SELECT
                        m.layer, m.source_id, m.path, m.title, m.heading, m.url,
                        m.start_line, m.end_line, m.content,
                        bm25(docs_fts, 4.0, 6.0, 2.0, 1.0, 0.5, 0.5) AS rank
                    FROM docs_fts
                    JOIN docs_meta m ON docs_fts.rowid = m.id
                    WHERE docs_fts MATCH ? AND m.source_id IN ({placeholders})
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (expr, *copy_sources, limit * 2),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []

            for r in rows:
                if r["layer"] == "knowledge" and "05-ux-writing" not in r["path"] and "writing" not in r["path"].lower():
                    score = float(r["rank"]) + 1.0
                elif r["layer"] == "knowledge":
                    score = float(r["rank"]) - 1.5
                else:
                    score = float(r["rank"])
                hits.append(
                    SearchHit(
                        layer=r["layer"],
                        source_id=r["source_id"],
                        path=r["path"],
                        line=_find_best_line(r["content"], int(r["start_line"]), terms),
                        end_line=int(r["end_line"]),
                        title=r["title"],
                        heading=r["heading"],
                        url=r["url"],
                        score=score,
                        snippet=_make_snippet(r["content"], terms),
                    )
                )
            if hits:
                break
    finally:
        conn.close()

    hits.sort(key=lambda h: (h.score, h.line))
    return {
        "topic": topic,
        "results": [h.to_dict() for h in hits[:limit]],
    }


def _count_md_files(root: Path) -> int:
    """Fast recursive `.md` file counter using `os.scandir` (avoids per-file stat overhead on Windows)."""
    if not root.is_dir():
        return 0
    total = 0
    stack = [str(root)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.name.endswith(".md"):
                        total += 1
        except OSError:
            continue
    return total


def get_status(paths: RepoPaths) -> dict[str, Any]:
    """Collect status of all sources, knowledge files, API manifests, tokens, and index DB."""
    sources_info: list[dict[str, Any]] = []
    for adapter in discover_sources(paths):
        committed = SourceManifest.from_json(adapter.committed_manifest) if adapter.committed_manifest.is_file() else None
        corpus = SourceManifest.from_json(adapter.corpus_manifest) if adapter.corpus_manifest.is_file() else None
        active = corpus or committed
        live_pages = _count_md_files(adapter.pages_dir)
        sources_info.append(
            {
                "source_id": adapter.source_id,
                "has_adapter": adapter.has_adapter,
                "synced_locally": adapter.pages_dir.is_dir() and live_pages > 0,
                "live_pages": live_pages,
                "manifest_pages": active.page_count if active else 0,
                "status": active.status if active else ("ready" if adapter.has_adapter else "missing"),
                "fetched_at": active.fetched_at if active else "",
                "upstream_version": active.upstream_version if active else "",
                "has_committed_manifest": committed is not None,
            }
        )

    knowledge_files = (
        sorted(p.relative_to(paths.root).as_posix() for p in paths.knowledge_dir.rglob("*.md"))
        if paths.knowledge_dir.is_dir()
        else []
    )

    api_files = (
        sorted(p.relative_to(paths.root).as_posix() for p in paths.api_manifests_dir.glob("*.json"))
        if paths.api_manifests_dir.is_dir()
        else []
    )

    token_files = (
        sorted(p.relative_to(paths.root).as_posix() for p in paths.token_manifests_dir.glob("*.json"))
        if paths.token_manifests_dir.is_dir()
        else []
    )

    index_meta: dict[str, str] = {}
    if paths.index_db.is_file():
        conn = sqlite3.connect(paths.index_db)
        try:
            for k, v in conn.execute("SELECT key, value FROM index_meta").fetchall():
                index_meta[str(k)] = str(v)
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    return {
        "root": str(paths.root),
        "sources": sources_info,
        "knowledge_count": len(knowledge_files),
        "knowledge_files": knowledge_files,
        "api_manifests": api_files,
        "token_manifests": token_files,
        "index_exists": paths.index_db.is_file(),
        "index_meta": index_meta,
    }


def run_doctor(paths: RepoPaths) -> dict[str, Any]:
    """Verify corpus integrity, line lengths <= 4000, internal links, frontmatter, and FTS5 health."""
    errors: list[str] = []
    warnings: list[str] = []
    checked_files = 0
    broken_links: list[dict[str, Any]] = []
    long_lines: list[dict[str, Any]] = []

    gi = paths.root / ".gitignore"
    if not gi.is_file() or ".corpus/" not in gi.read_text(encoding="utf-8", errors="replace"):
        errors.append(".gitignore missing or does not exclude .corpus/")

    skill_md = paths.skills_dir / "expressive-ui" / "SKILL.md"
    if not skill_md.is_file():
        warnings.append("skills/expressive-ui/SKILL.md does not exist yet")
    else:
        skill_text = skill_md.read_text(encoding="utf-8", errors="replace")
        if not skill_text.startswith("---"):
            errors.append("skills/expressive-ui/SKILL.md missing YAML frontmatter")
        else:
            fm_end = skill_text.find("\n---", 3)
            fm_block = skill_text[3:fm_end] if fm_end != -1 else ""
            if "name:" not in fm_block or "description:" not in fm_block:
                errors.append("skills/expressive-ui/SKILL.md frontmatter missing 'name' or 'description'")

    md_targets: list[tuple[str, Path]] = []
    if paths.knowledge_dir.is_dir():
        for p in sorted(paths.knowledge_dir.rglob("*.md")):
            md_targets.append(("knowledge", p))
    if paths.corpus_dir.is_dir():
        for sdir in sorted(paths.corpus_dir.iterdir()):
            if sdir.is_dir() and not sdir.name.startswith((".", "_")):
                pdir = sdir / "pages"
                if not pdir.is_dir():
                    errors.append(f".corpus/{sdir.name} is missing pages/ directory (empty mirror)")
                    continue
                md_pages = sorted(pdir.rglob("*.md"))
                non_index_pages = [p for p in md_pages if p.name != "INDEX.md"]
                if not non_index_pages:
                    errors.append(f".corpus/{sdir.name}/pages/ has 0 mirrored pages (empty mirror)")
                if not (pdir / "INDEX.md").is_file():
                    warnings.append(f".corpus/{sdir.name}/pages/INDEX.md is missing")
                for p in md_pages:
                    md_targets.append(("mirror", p))

    for kind, md_path in md_targets:
        checked_files += 1
        rel = md_path.relative_to(paths.root).as_posix()
        text = md_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        if kind == "mirror" and md_path.name != "INDEX.md":
            meta, _ = parse_page_frontmatter(text)
            if meta is None or (not meta.url and not meta.title):
                warnings.append(f"{rel}: missing standard frontmatter metadata")

        in_fence = False
        fence_char = ""
        for idx, line in enumerate(lines, start=1):
            if len(line) > MAX_LINE_LENGTH:
                long_lines.append({"path": rel, "line": idx, "length": len(line)})
            fm = _FENCE_RE.match(line)
            if fm:
                marker = fm.group(1)
                if not in_fence:
                    in_fence = True
                    fence_char = marker[0]
                elif marker[0] == fence_char:
                    in_fence = False
                    fence_char = ""
                continue
            if kind == "knowledge" and not in_fence:
                for m in _MD_LINK_RE.finditer(line):
                    target = m.group(1).strip()
                    if not target or target.startswith(("http://", "https://", "mailto:", "#", "file://")):
                        continue
                    target_no_anchor = target.split("#", 1)[0].strip()
                    if not target_no_anchor:
                        continue
                    resolved = (md_path.parent / target_no_anchor).resolve()
                    if not resolved.exists():
                        broken_links.append({"path": rel, "line": idx, "target": target})

    if long_lines:
        errors.append(f"{len(long_lines)} line(s) exceed {MAX_LINE_LENGTH} chars")
    if broken_links:
        errors.append(f"{len(broken_links)} broken relative link(s) in knowledge/")

    from rtx.diff import analyze_impact

    audit = analyze_impact(paths)
    for adv in audit.live_advisories[:30]:
        warnings.append(f"{adv['knowledge_file']}:{adv['line']} [{adv['type']}] {adv['detail']}")

    fts_ok = False
    if not paths.index_db.is_file():
        build_index(paths)
    try:
        conn = sqlite3.connect(paths.index_db)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                errors.append(f"SQLite integrity_check failed: {integrity}")
            else:
                conn.execute("SELECT count(*) FROM docs_fts").fetchone()
                conn.execute("SELECT count(*) FROM api_fts").fetchone()
                conn.execute("SELECT count(*) FROM tokens_fts").fetchone()
                if _has_table(conn, "kotlin_sources_fts"):
                    conn.execute("SELECT count(*) FROM kotlin_sources_fts").fetchone()
                fts_ok = True
        finally:
            conn.close()
    except sqlite3.Error as exc:
        errors.append(f"SQLite FTS5 error: {exc}")

    return {
        "ok": len(errors) == 0,
        "checked_files": checked_files,
        "fts_ok": fts_ok,
        "errors": errors,
        "warnings": warnings,
        "long_lines": long_lines[:20],
        "broken_links": broken_links[:20],
        "citation_counts": audit.citation_counts,
        "live_advisories": audit.live_advisories[:30],
    }
