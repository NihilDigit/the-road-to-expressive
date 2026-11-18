# The Road to Expressive

**A curated local research corpus, bytecode-verified Maven API parity tracker, SQLite FTS5 search engine, and cross-platform UI engineering knowledge base for AI coding agents.**

Built for teams shipping **Material 3 Expressive** and **Compose Multiplatform** across **Android (ART)**, **Desktop JVM (Windows / macOS / Linux)**, and **iOS (Kotlin/Native)** while honoring native **Human Interface Guidelines** (Apple HIG, Microsoft Windows Design / Fluent 2, GNOME HIG, KDE HIG) and **AP-aligned UX copywriting**.

---

## Why This Repository Exists

AI coding agents routinely hit two failure modes when building modern multiplatform UI:

1. **Raw documentation dumps** bloat agent context windows, omit dynamically rendered design tokens, and lag behind bleeding-edge Compose alpha/beta releases.
2. **Thin high-level summaries** lack exact `@OptIn(...)` annotations, Kotlin Multiplatform vs. AndroidX parameter deltas, spring stiffness/damping values, and target-specific runtime constraints (Skiko D3D11/Metal interop, Win32 custom captions, iOS safe areas).

`the-road-to-expressive` solves both with a **three-layer architecture**:

| Layer | Location | Committed | Purpose |
| --- | --- | --- | --- |
| **Layer 1: Upstream Mirrors & Bytecode/Token Extractors** | `sources/*/refresh.py`, `manifests/`, `.corpus/` | Adapters + `manifests/` yes; `.corpus/` gitignored | Incremental conditional HTTP mirrors (`ETag`/`Last-Modified`, `robots.txt`) + OpenJDK `javap` bytecode surface extraction + M3 Expressive token tables |
| **Layer 2: SQLite FTS5 & Parity Query Engine (`rtx`)** | `src/rtx/`, `.corpus/index.db` | Package yes; DB gitignored | Fast BM25 section-level search, Maven API parity diffing (`--diff`), unified component views, token/copy lookups, and citation impact analysis |
| **Layer 3: Cross-Synthesized Handbooks & Agent Skills** | `knowledge/`, `skills/` | Yes | Structured engineering guides reconciling M3 Expressive, Compose APIs, adaptive layouts, multi-input patterns, platform HIGs, and UX writing rules |

---

## Upstream Sources & Coverage Matrix

All nine source adapters under `sources/<id>/refresh.py` run standalone or via `uv run rtx sync` using conditional HTTP requests and `robots.txt` compliance.

| Source ID | Coverage | Tracked Items | Incremental Mechanism |
| --- | --- | --- | --- |
| [`m3-expressive`](sources/m3-expressive/README.md) | `m3.material.io` foundations, styles, expressive components, develop guides, and DSDB token tables | 95 pages + `manifests/tokens/m3-expressive-tokens.json` | Carbon JSON route/version check + `ETag`/`Last-Modified` |
| [`google-design`](sources/google-design/README.md) | `design.google/library/*` articles + Material Color Utilities HCT / `DynamicScheme` specs | 97 pages | Sitemap + Next.js `__NEXT_DATA__` + `ETag`/`Last-Modified` |
| [`compose-android`](sources/compose-android/README.md) | Jetpack Compose, Navigation 3, Android Mobile & Large-Screen UI design guidelines | 443 pages | Sitemap / URL discovery + `ETag`/`Last-Modified` |
| [`compose-multiplatform`](sources/compose-multiplatform/README.md) | Compose Multiplatform guides (adaptive, navigation, lifecycle, iOS, Desktop JVM, AOT) + Dokka indexes | 399 pages | TOC / sitemap + `ETag`/`Last-Modified` |
| [`compose-maven-api`](sources/compose-maven-api/README.md) | Google Maven & JetBrains Compose Maven version tracking + OpenJDK `javap` bytecode inspection | 11 pages, 31 Maven coordinates, 1,628 API symbols (`manifests/api/`) | `maven-metadata.xml` + `.module` + cached JAR/AAR `javap` diff |
| [`apple-hig`](sources/apple-hig/README.md) | Apple Human Interface Guidelines across iOS, iPadOS, macOS, visionOS, watchOS, tvOS | 173 pages | DocC JSON index + `ETag`/`Last-Modified` |
| [`windows-fluent`](sources/windows-fluent/README.md) | Microsoft Learn Windows App Design Guidelines + Fluent 2 design system | 370 manifest entries | TOC JSON + `ETag`/`Last-Modified` |
| [`linux-hig`](sources/linux-hig/README.md) | GNOME Human Interface Guidelines (`developer.gnome.org/hig`) + KDE HIG (`develop.kde.org/hig`) | 78 pages | Crawl/index + `ETag`/`Last-Modified` |
| [`writing-style`](sources/writing-style/README.md) | Google Developer Style Guide, Microsoft Writing Style Guide, 18F Content Guide (AP-based), AP Stylebook overview, Mailchimp Content Style Guide, and Digital.gov Plain Language | 206 pages | TOC / sitemap + `ETag`/`Last-Modified` |

---

## Knowledge Base Map

Start at [`knowledge/INDEX.md`](knowledge/INDEX.md) or jump directly to any topic handbook:

- **00 — Agent Needs & Corpus Architecture**
  - [`knowledge/00-agent-needs/agent-ui-information-architecture.md`](knowledge/00-agent-needs/agent-ui-information-architecture.md) — Why raw mirrors and thin summaries fail coding agents, and how bytecode + token + cross-HIG synthesis closes the gaps.
- **01 — Design Systems & Expressive Foundations**
  - [`knowledge/01-design-systems/why-hig-taxonomy.md`](knowledge/01-design-systems/why-hig-taxonomy.md) — Why Human Interface Guidelines are organized into Foundations, Patterns, Components, and Inputs.
  - [`knowledge/01-design-systems/m3-expressive-foundations.md`](knowledge/01-design-systems/m3-expressive-foundations.md) — HCT 2025/2026 color roles, 10-tier `Shapes` scale, 15 baseline + 15 `*Emphasized` typography tokens, and `surfaceContainer*` containment.
  - [`knowledge/01-design-systems/motion-and-physics.md`](knowledge/01-design-systems/motion-and-physics.md) — `MotionScheme` expressive/standard spatial and effects springs, Reduced Motion policies, and desktop menu snap behavior.
  - [`knowledge/01-design-systems/cross-hig-reconciliation.md`](knowledge/01-design-systems/cross-hig-reconciliation.md) — Reconciling Material 3 Expressive with Apple HIG, Microsoft Fluent 2 / Windows Design, GNOME HIG, and KDE HIG.
- **02 — Components & Shells**
  - [`knowledge/02-components/expressive-catalog.md`](knowledge/02-components/expressive-catalog.md) — `SplitButtonLayout`, `ButtonGroup`, `FloatingToolbar`, `LoadingIndicator`, wavy progress, `SegmentedListItem`, carousels, and search bars.
  - [`knowledge/02-components/navigation-and-shells.md`](knowledge/02-components/navigation-and-shells.md) — `ShortNavigationBar`, `WideNavigationRail`, `NavigationSuiteScaffold`, `MediumFlexibleTopAppBar`, `LargeFlexibleTopAppBar`, and desktop window captions.
  - [`knowledge/02-components/sheets-dialogs-menus.md`](knowledge/02-components/sheets-dialogs-menus.md) — Bottom sheets, side sheets, dialogs, popovers, and context menus across touch and pointer targets.
- **03 — Adaptive Layouts & Multi-Input**
  - [`knowledge/03-adaptive-and-inputs/window-size-and-canonical-layouts.md`](knowledge/03-adaptive-and-inputs/window-size-and-canonical-layouts.md) — `WindowSizeClass` width/height breakpoints, List-Detail / Supporting Pane / Feed, `ListDetailSceneStrategy`, and live-resize state preservation.
  - [`knowledge/03-adaptive-and-inputs/pointer-touch-keyboard-stylus.md`](knowledge/03-adaptive-and-inputs/pointer-touch-keyboard-stylus.md) — Per-event `PointerType` dispatch, `PointerEventPass.Final` hover, `ContextMenuArea` vs. long-press, `SelectionContainer`, and keyboard shortcuts.
- **04 — Compose Engineering & Targets**
  - [`knowledge/04-compose-engineering/state-architecture-and-navigation3.md`](knowledge/04-compose-engineering/state-architecture-and-navigation3.md) — UDF, Compose phases, `derivedStateOf` vs. `snapshotFlow`, Navigation 3 `SnapshotStateList<NavKey>`, and KMP DI/state boundaries.
  - [`knowledge/04-compose-engineering/performance-and-stability.md`](knowledge/04-compose-engineering/performance-and-stability.md) — Strong skipping, `LazyColumn`/`LazyVerticalGrid` keys, `SubcomposeLayout` desktop popup safety, IME inset isolation, and baseline profiles.
  - [`knowledge/04-compose-engineering/targets-art-jvm-ios.md`](knowledge/04-compose-engineering/targets-art-jvm-ios.md) — Android ART, Desktop JVM (Win32/D3D11/D3D12, macOS AppKit/Metal, Linux X11/Wayland), and iOS Kotlin/Native runtime guides.
- **05 — UX Writing & Copy Mechanics**
  - [`knowledge/05-ux-writing/ui-copy-and-ap-style.md`](knowledge/05-ux-writing/ui-copy-and-ap-style.md) — Material Content Design, AP Style mechanics vs. tabular UI numerals, sentence vs. title case, confirmations, error recovery, and CJK rules.
- **06 — Version Tracking & Interop**
  - [`knowledge/06-version-tracking/bleeding-edge-matrix.md`](knowledge/06-version-tracking/bleeding-edge-matrix.md) — AndroidX BOM / alpha train vs. JetBrains Compose Multiplatform artifact coordinates, graduated `@ExperimentalMaterial3ExpressiveApi` status, and parity deltas.
  - [`knowledge/06-version-tracking/dual-target-unification-and-skiko-interop.md`](knowledge/06-version-tracking/dual-target-unification-and-skiko-interop.md) — Gradle `.module` redirect mechanics, stable BOM unification, and Skiko `0.156+` `Direct3DRenderer` / `FrameDriver` GPU interop.

---

## Installation & Bootstrap (`uv`)

Requires **Python >= 3.12** and [`uv`](https://docs.astral.sh/uv/). OpenJDK 21 (`javap`) on `PATH` is required if re-running `compose-maven-api` bytecode extraction.

```bash
git clone https://github.com/NihilDigit/the-road-to-expressive.git
cd the-road-to-expressive

# 1. Create .venv and install `rtx`
uv sync

# 2. Populate .corpus/ mirrors and build .corpus/index.db (skip binary images for speed)
uv run rtx sync --all --no-assets --workers 10

# 3. Inspect corpus status, tracked Maven versions, and index stats
uv run rtx status
```

`.corpus/` is gitignored; fresh clones can run `uv run rtx index` to index committed `knowledge/` and `manifests/` immediately, or run `uv run rtx sync --all --no-assets --workers 10` to populate all local mirror pages.

---

## Agent Skill Integration

Two turnkey Agent Skills are included under `skills/`:

- [`skills/expressive-ui/SKILL.md`](skills/expressive-ui/SKILL.md) — Teaches coding agents to query `rtx` for M3 Expressive tokens, Compose API parity, adaptive layouts, multi-input rules, HIG reconciliation, and UX writing before writing UI code.
- [`skills/expressive-sync/SKILL.md`](skills/expressive-sync/SKILL.md) — Teaches maintenance agents how to run incremental syncs, inspect section-level changelogs and citation impacts, and update `knowledge/` with zero drift.

To mount them in Antigravity, Claude Code, or Codex, symlink or copy `skills/expressive-ui` and `skills/expressive-sync` into your agent skills directory (e.g., `~/.gemini/config/skills/` or `.agents/skills/`).

### Cross-Workspace Usage

When an agent is working inside **another repository**, invoke `rtx` without changing your workspace using `--project` or `--directory`:

```bash
uv run --project <path-to-the-road-to-expressive> rtx component SplitButton
uv run --directory <path-to-the-road-to-expressive> rtx api SegmentedListItem --diff
```

`rtx` resolves the corpus root from its installed editable package location rather than the caller's working directory.

---

## CLI Reference (`rtx`)

Add `--json` to query and status commands for structured machine-readable output.

### Querying Components, APIs, Tokens & Copy

| Command | Purpose |
| --- | --- |
| `uv run rtx component <name>` | Unified view combining M3E tokens, Compose API signatures & opt-ins, adaptive notes, and Apple/Windows/Linux HIG guidance |
| `uv run rtx api <query> [--target common\|android\|desktop\|ios] [--diff]` | Query bytecode-verified AndroidX vs. JetBrains CMP signatures, `@Experimental*` opt-ins, and Maven versions (`--diff` highlights deltas) |
| `uv run rtx token <query> [--category <cat>]` | Query M3 Expressive color roles, 10-step `Shapes`, `*Emphasized` typography, and `MotionScheme` spring constants |
| `uv run rtx copy <topic>` | Query Material UX writing, AP Style mechanics, platform writing guides, and CJK UI copy rules |
| `uv run rtx search "<query>" [--layer knowledge\|mirror\|api\|tokens] [--source <id>] [--limit N]` | Fast BM25 FTS5 search returning exact file paths, line numbers, source URLs, and snippets |

### Maintenance, Diffing & Integrity

| Command | Purpose |
| --- | --- |
| `uv run rtx status` | Show sync status, page counts, upstream version pins, and `.corpus/index.db` metrics |
| `uv run rtx sync [source...] [--all] [--check] [--refresh] [--no-assets] [--workers 10] [--verify] [--diff-report]` | Run `sources/*/refresh.py` adapters, rebuild `.corpus/index.db`, and record `.corpus/sync-diff.json` |
| `uv run rtx index` | Rebuild `.corpus/index.db` from `knowledge/`, `.corpus/*/pages/`, `manifests/api/`, and `manifests/tokens/` |
| `uv run rtx changelog [--since-last]` | Show added/modified/removed mirror sections, Maven version bumps, graduated opt-ins, signature diffs, and token changes |
| `uv run rtx impact` | Map `.corpus/sync-diff.json` changes and live manifest drift to exact `knowledge/*.md` sections |
| `uv run rtx doctor` | Verify `<= 4000`-char line lengths, zero broken relative links, empty-mirror detection, live citation audit, and SQLite FTS5 integrity |

---

## Incremental Update & Zero-Drift Workflow

Whenever upstream docs, Maven alpha/beta artifacts, or M3 Expressive tokens change:

```bash
# 1. Incremental conditional sync + diff report
uv run rtx sync --all --no-assets --workers 10 --diff-report

# 2. Inspect targeted diffs and affected knowledge/ citations
uv run rtx changelog
uv run rtx impact

# 3. Update only the flagged knowledge/*.md sections, then run the Integrity Gate
uv run rtx index
uv run rtx doctor
uv run pytest
```

---

## Development

```bash
uv sync
uv run pytest -v
```
