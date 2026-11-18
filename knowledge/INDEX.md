# The Road to Expressive — Knowledge Index

> **Agent-First Handbook Directory** for building bleeding-edge **Material 3 Expressive**, **Compose Multiplatform** (Android ART, Desktop JVM, iOS Native), **Cross-Platform HIG**, and **AP-Style UX Copy** interfaces.
> All handbooks cite grounded upstream mirrors under `.corpus/<source_id>/pages/`, bytecode-verified Maven signatures in [manifests/api/](../manifests/api/material3-expressive-surface.json), and design tokens in [manifests/tokens/m3-expressive-tokens.json](../manifests/tokens/m3-expressive-tokens.json).

---

## Quick `rtx` Query Workflow (Before Writing UI Code)

| Goal | Command |
| --- | --- |
| Check tracked Maven/CMP versions & mirror status | `uv run rtx status` |
| Inspect AndroidX vs. JetBrains CMP bytecode API & `@Experimental*` parity | `uv run rtx api <SymbolName> --diff` |
| Unified component brief (M3E tokens + Compose signature + Adaptive + HIG) | `uv run rtx component <ComponentName>` |
| Exact M3E color, 10-step shape, `*Emphasized` typography, or `MotionScheme` tokens | `uv run rtx token <query>` |
| UX writing, microcopy, AP Style, CJK, & accessibility string rules | `uv run rtx copy <topic>` |
| Full-text BM25 search across synthesized handbooks or mirrored pages | `uv run rtx search "<query>" --layer knowledge` / `--layer mirror` |
| Inspect recent upstream diffs & impacted handbook citations | `uv run rtx changelog` / `uv run rtx impact` |
| Run full corpus, citation, link, and FTS5 health checks | `uv run rtx doctor` |

---

## Handbook Map (`knowledge/`)

### `00-agent-needs/` — Empirical Agent & Mirroring Diagnostics
- **[Agent UI Information Architecture](00-agent-needs/agent-ui-information-architecture.md)** — Why raw documentation mirrors and shallow summaries both fail coding agents, and how layered upstream mirrors, Maven bytecode extraction, token tables, and cross-HIG handbooks solve UI drift.

### `01-design-systems/` — Design Systems, Tokens, Motion & Cross-OS Reconciliation
- **[Why Ecosystems Name Standards Differently](01-design-systems/why-hig-taxonomy.md)** — 1:1 architectural mapping across Apple HIG, GNOME HIG, KDE HIG, Google Material 3 + Android Quality/Large-Screen Guidelines, and Microsoft Fluent 2 + Windows App Design Guidelines.
- **[Material 3 Expressive Foundations](01-design-systems/m3-expressive-foundations.md)** — Research rationale, `MaterialExpressiveTheme`, HCT ColorSpec (`ColorSpec2021`/`2025`/`2026`), 5-tier `surfaceContainer*`, pure-black Oklab ladder (`toPureBlack()`), 10-step `Shapes` + 35 `MaterialShapes` + optical roundness, 30-step `*Emphasized` typography, CJK metrics, `tnum`, and zero-divider containment.
- **[Motion Physics, Screen Transitions & Reduced Motion](01-design-systems/motion-and-physics.md)** — `MotionScheme.expressive()` vs. `standard()`, spatial vs. effects springs (`fast`/`default`/`slow`), transition tween boundaries, 5-OS motion reconciliation, and `MotionDurationScale` / Reduced Motion plumbing.
- **[Cross-HIG Reconciliation (Android, iOS/iPadOS, Windows, macOS, Linux)](01-design-systems/cross-hig-reconciliation.md)** — Decision matrix for what stays unified M3E vs. what adapts to native OS chrome: Win32 `WM_NCCALCSIZE`/`WM_NCHITTEST` & Snap Layouts, macOS traffic lights & menu bars, Linux `WM_CLASS` & CSD/SSD, `Ctrl` vs. `⌘`, predictive back vs. swipe-back vs. `Esc`, sheets, scrollbars, and notifications.

### `02-components/` — M3 Expressive Components, Shells & Secondary Surfaces
- **[Material 3 Expressive Component Catalog](02-components/expressive-catalog.md)** — Bytecode-verified anatomy, tokens, Compose signatures, `@Experimental*` flags, and do/don't rules for `ButtonGroup`, `SplitButtonLayout`, `ToggleButton`, `FloatingActionButtonMenu`, `HorizontalFloatingToolbar`/`VerticalFloatingToolbar`, `LoadingIndicator`/`ContainedLoadingIndicator`, `LinearWavyProgressIndicator`/`CircularWavyProgressIndicator`, `MediumFlexibleTopAppBar`/`LargeFlexibleTopAppBar`/`AppBarRow`, `WideNavigationRail`, `ShortNavigationBar`, `SegmentedListItem`, `Carousel`, and `SearchBar`.
- **[Navigation, Tabs, Adaptive Toolbars & Desktop Island Shells](02-components/navigation-and-shells.md)** — Navigation bars vs. `WideNavigationRail` vs. permanent desktop sidebars, `PrimaryTabRow` vs. `SecondaryTabRow`, `AppBarRow` vs. single-pass custom `Layout` overflow (`AdaptiveBar`), and custom desktop island framing vs. edge-to-edge mobile system bars.
- **[Unified Secondary Surfaces: Sheets, Floating Panels, Context Menus & Dialogs](02-components/sheets-dialogs-menus.md)** — Unified sheet routing (`SidePaneLayer`, `ModalSideSheet`, `ModalBottomSheet` via `PaneSheet`), sticky footers & IME insets, `WheelStopsAtSheet`, `hideThen`, pointer-anchored context menus & M3E `totalCount` shape parity, and jitter-free dialog sizing.

### `03-adaptive-and-inputs/` — Window Geometry, Canonical Layouts & Multi-Input
- **[Window Size Classes, Adaptive Geometry, and Canonical Layouts](03-adaptive-and-inputs/window-size-and-canonical-layouts.md)** — M3 adaptive breakpoints, `ListDetailPaneScaffold` / `SupportingPaneScaffold` / feed layouts, dual-axis width+height adaptation (`< 480.dp` compact rail), `LocalDisplayFeatures` / hinge posture, and safe insets.
- **[Multi-Input Engineering: Pointer, Touch, Keyboard, and Stylus](03-adaptive-and-inputs/pointer-touch-keyboard-stylus.md)** — Per-event `PointerType` dispatch (`PointerSource`), mouse/touchpad/touch/stylus ergonomics, focus traversal (`FocusRequester`, directional/tab order), keyboard shortcuts, drag-and-drop, and `compose-windows-touch` interop.

### `04-compose-engineering/` — State, Performance & Target Runtimes
- **[State Architecture, Compose Phases, and Navigation 3](04-compose-engineering/state-architecture-and-navigation3.md)** — Strict UDF boundaries, durable vs. transient events, optimistic overlay semantics, Compose Composition/Layout/Drawing phase deferral, and Navigation 3 `NavDisplay` / `SceneStrategy` invariants.
- **[Compose Multiplatform Performance, Stability, and Rendering Pitfalls](04-compose-engineering/performance-and-stability.md)** — Strong skipping & collection stability, mandatory `key`/`contentType` & error-latched `PrefetchNearEnd`, Desktop `SubcomposeLayout` popup disposal hazards, IME inset isolation, image memory budgeting, and Baseline Profiles.
- **[Target Runtime Engineering: Android ART, Desktop JVM, and iOS Native](04-compose-engineering/targets-art-jvm-ios.md)** — Target-specific pitfalls: Android ICU vs. HotSpot `\d` / `\p{Is...}` regex hazards, Skiko D3D12/Metal/OpenGL rendering backends, FFM Win32 / macOS / Linux native bridges, SQLite & Coil 3 wiring, R8 / ProGuard / JDK 25 AOT packaging.

### `05-ux-writing/` — Microcopy, AP Style, CJK & Accessibility Copy
- **[UI Copy, UX Writing, and AP Style Reference](05-ux-writing/ui-copy-and-ap-style.md)** — M3 Content Design + AP Stylebook + Google/Microsoft/Fluent 2/18F/Apple/GNOME/KDE synthesis: capitalization matrices, UI vs. prose numerals & `tnum`, punctuation & Unicode `…` rules, avoiding middle-dot separators (`·`), active error/button/notification formulas, 200% scaling & CJK rules, and `contentDescription`/alt-text accessibility copy.

### `06-version-tracking/` — Live Maven Pins, Parity Diffs & Dual-Target Roadmaps
- **[Bleeding-Edge Compose & Material 3 Expressive Version Matrix](06-version-tracking/bleeding-edge-matrix.md)** — Live Maven Central / Google Maven matrix (`compose-bom-alpha`, `material3 1.5.0-rc01`, JetBrains CMP `1.13.0-beta02`), AndroidX-vs-CMP API parity diff, and graduated vs. `@ExperimentalMaterial3ExpressiveApi` symbol tracking.
- **[Dual-Target Version Unification & Skiko 0.156+ Native GPU Interop](06-version-tracking/dual-target-unification-and-skiko-interop.md)** — Gradle `.module` redirect mechanics (`alpha` vs. stable BOM resolution), CMP `1.12.x` (`Skiko 0.150.x`) vs. `1.13.x` (`Skiko 0.156.1` `Direct3DRenderer`/`FrameDriver`), D3D11/D3D12 zero-copy interop, TDR recovery, and ProGuard `-keep` rules.

---

## Supporting Manifests & Agent Skills

- **API & Token Manifests:** [compose-versions.json](../manifests/api/compose-versions.json), [material3-expressive-surface.json](../manifests/api/material3-expressive-surface.json), [m3-expressive-tokens.json](../manifests/tokens/m3-expressive-tokens.json)
- **Mirrored Source Snapshots:** [manifests/sources/](../manifests/sources/) (`m3-expressive`, `compose-maven-api`, `compose-android`, `compose-multiplatform`, `google-design`, `apple-hig`, `windows-fluent`, `linux-hig`, `writing-style`)
- **Agent Skills:** [expressive-ui](../skills/expressive-ui/SKILL.md) (query workflow before coding UI), [expressive-sync](../skills/expressive-sync/SKILL.md) (incremental sync & knowledge maintenance)
