# Agent UI Information Architecture: Why Mirrors Fail and How `rtx` Solves It

> Design rationale for `the-road-to-expressive`: empirical failure modes observed when AI coding agents rely on raw documentation crawls or short summary files for Material 3 Expressive and Compose Multiplatform development, and the 3-layer architecture that eliminates those bottlenecks.

---

## 1. Empirical Failure Modes of Raw Mirrors & Shallow Summaries

When coding agents build cross-platform Compose UI (Android + Desktop JVM + iOS) against fast-moving Material 3 Expressive (`1.5.0-*` / `1.13.0-*`) and Adaptive Navigation 3 releases, naive documentation strategies fail in five repeatable ways:

### 1.1 Raw Markdown Crawls Cause Context Bloat and Still Miss Implementation Truth
- **Context exhaustion:** Enumerating raw mirror directories and reading 300–1,050-line scraped web pages (`typography.md`, `app-bars.md`, `toolbars.md`, `cards.md`) consumes tens of thousands of tokens before a single line of Kotlin is edited, triggering premature context compaction.
- **Abandonment during implementation:** In multi-agent UI sprints, design scouts may browse conceptual mirror pages upfront, but implementation, polish, and verification agents abandon raw documentation crawls almost completely once coding starts—falling back to ad-hoc `javap` decompilation of local Gradle cache `.jar`/`.aar` archives to answer basic API, parameter-name, and token-value questions.
- **Broken navigation & missing provenance:** Naive crawlers frequently capture marketing landing pages as `INDEX.md`, leave empty index stubs, strip canonical `source:` URLs, or omit dynamic sub-tabs (such as M3's design-token `DSDB` tables and component spec tables).

### 1.2 Conceptual Docs Omit Compose API Signatures, Token Constants, and `@OptIn` State
Design websites explain *conceptual anatomy* but do not reliably expose the exact Kotlin surface compiled into a pinned artifact:
- **Missing Compose symbol coverage:** Scraped design sites and Dokka package-index stubs regularly omit new M3 Expressive / Adaptive APIs (`SegmentedListItem`, `ThreePaneScaffoldScene`, `ListDetailSceneStrategy`, `MaterialExpressiveTheme`, `ButtonDefaults.shapes`, `largeIncreased`, `titleLargeEmphasized`) or omit function parameter lists and defaults.
- **Silent behavior shifts discovered only in bytecode:** For example, `PullToRefreshDefaults.LoadingIndicator` switching from the legacy spinner to M3 Expressive's `LoadingIndicator`, or `NavigationRailCollapsedTokens` resolving to `96.0.dp` instead of legacy `80.dp`, can only be verified reliably from compiled `classes.jar` bytecode unless pre-extracted into structured manifests.
- **`@ExperimentalMaterial3ExpressiveApi` graduation drift:** Between alpha, beta, and RC trains, symbols graduate at different times (`MaterialExpressiveTheme`, `MotionScheme`, `SegmentedListItem`, `SplitButtonLayout`, `WideNavigationRail`, `ToggleButton`, `ButtonGroup`). Without live bytecode annotation checks, agents either scatter unnecessary opt-ins or fail compilation on strict targets.

### 1.3 Dual-Target Compose Multiplatform Skew Is Invisible in Single-Ecosystem Docs
Android (`androidx.compose.*` via Google Maven BOMs) and Desktop/iOS (`org.jetbrains.compose.*` via Maven Central) advance on staggered schedules:
- AndroidX `compose-bom-alpha` can silently pull a newer `material3` (e.g., `1.5.0-alpha25`) than JetBrains CMP's redirected version (`1.5.0-alpha22`), creating subtle overload/naming splits (`ListItem` trailing `content` lambda vs. `headlineContent`, `SplitButton` vs. `SplitButtonLayout`, missing static `SegmentedListItem` overloads, or `@OptIn` differences on `AlertDialog` / `MediumFlexibleTopAppBar`).
- Single-platform documentation never warns about cross-target deltas.

### 1.4 Ad-Hoc Local Bytecode Inspection (`javap`) Is Slow and Error-Prone
When agents manually glob local Gradle caches to run `javap`:
- **Stale cache traps:** Directory globs (`Select-Object -First 1`) routinely pick up older cached versions (e.g., `1.10.0-alpha05` instead of `1.12.0-alpha03`, or `alpha22` instead of `alpha25`).
- **Facade class guessing:** Kotlin top-level composables live in generated `*Kt` facade classes whose names are non-obvious (`AppBarKt`, `MaterialExpressiveThemeKt` vs. `MaterialThemeKt`), causing repeated `Class not found` misses.
- **AAR extraction overhead:** Inspecting Android `.aar` libraries requires unzipping `classes.jar` to temporary directories before running `javap`.

### 1.5 Cross-Platform Desktop, Adaptive Layout, and Copyability Gaps
Web-centric or mobile-only mirrors leave critical engineering blind spots for multiplatform apps:
- **Desktop HIG & native ergonomics:** Mirrors biased toward Web React components fail to capture native Windows (WinUI / Fluent 2 windowing, Mica/Acrylic, Snap Layouts), macOS (AppKit/SwiftUI menu bar, window chrome), and Linux (GNOME/KDE) conventions.
- **Multi-window & input coexistence:** Agents repeatedly need verified patterns for `BottomSheetDefaults.windowInsets` + `imePadding()` double-inset avoidance, `skipPartiallyExpanded` vs. sticky footers, `ListDetailSceneStrategy` independent islands (`TopAppBarDefaults` container color matching), `PointerEventPass.Final` passive hover without stealing clicks, `SelectionContainer` safety around clickable cards / `LazyColumn`, and inline desktop composers vs. mobile IME sheets.

---

## 2. Information Architecture Requirements Satisfied by `the-road-to-expressive`

To eliminate raw-mirror abandonment and ad-hoc bytecode hunting, the corpus enforces a strict **three-layer architecture**:

| Layer | Artifact | Problem Solved |
|---|---|---|
| **Layer 1: Verified Mirrors & Extractors** | `sources/*/refresh.py`, `.corpus/<source>/pages/`, `manifests/api/*.json`, `manifests/tokens/*.json` | Guarantees every mirrored page carries canonical `source:` URLs, real `INDEX.md` topic maps, `<= 4000`-char lines, extracted M3E `DSDB` token tables, and OpenJDK `javap` signatures + `androidx.compose.material3.tokens.*` constants across both AndroidX and CMP. |
| **Layer 2: Compact Agent CLI & Index** | `src/rtx/` (`uv run rtx ...`), `.corpus/index.db` (SQLite FTS5 + BM25) | Replaces 1,000-line raw reads and `.gradle/caches` globs with snippet-first queries (`rtx component`, `rtx api --diff`, `rtx token`, `rtx copy`, `rtx search`) that work across workspaces (`--project <repo-path>`). |
| **Layer 3: Cross-Synthesized Handbooks & Skills** | `knowledge/01-*` .. `06-*`, `skills/expressive-ui/`, `skills/expressive-sync/` | Synthesizes M3E + cross-platform HIGs + Compose engineering + UX writing into actionable matrices, and keeps `knowledge/` synchronized via `rtx sync --diff-report` → `rtx changelog` → `rtx impact` → `rtx doctor`. |

### Concrete Lookup Discipline for Coding Agents
1. **Unified Component Lookup First:** Run `uv run rtx component <Name>` to inspect M3E anatomy/tokens, Compose signature + opt-ins, adaptive behavior, and Apple/Windows/GNOME/KDE HIG rules in one response.
2. **Cross-Target Parity Check Before Writing `commonMain`:** Run `uv run rtx api <Symbol> --diff` to verify AndroidX vs. CMP Desktop/iOS signatures and `@OptIn` requirements.
3. **Exact Token Lookup:** Run `uv run rtx token <query>` instead of guessing `dp` constants, typography `*Emphasized` roles, 10-step `Shapes`, or `MotionScheme` springs.
4. **Synthesized Engineering Guides & Copy Rules:** Read targeted sections of `knowledge/` (and `rtx copy <topic>`) for non-obvious layout, input, sheet, and copywriting contracts.
5. **Fallback to `javap` Only for Unindexed Third-Party Artifacts:** Reserve manual `javap` for non-Compose libraries (e.g., native media or HTTP clients) using exact pinned coordinates, never guessing from `.gradle/caches` globs.
