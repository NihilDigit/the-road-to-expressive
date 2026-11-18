# Navigation, Tabs, Adaptive Toolbars & Desktop Island Shells

> **Scope:** Architectural rules for top-level navigation switching (`ShortNavigationBar` / `WideNavigationRail` / persistent Sidebar), `PrimaryTabRow` vs. `SecondaryTabRow`, overflow-safe horizontal toolbars (`AppBarRow` vs. custom `Layout`), and desktop island framing vs. mobile edge-to-edge system bars.

---

## 1. Top-Level Navigation Continuum (By Window Width & Height)

Navigation chrome must map deterministically from **window net width and height (`dp`)** while preserving the **exact same destination vocabulary and selection state** across breakpoints (`.corpus/m3-expressive/pages/foundations/layout/scaffold.md`, `components/navigation-rail.md`).

| Window Geometry | Recommended Shell Chrome | Key Metrics & Behavioral Rules |
| --- | --- | --- |
| **Compact Width (`< 600dp`) & Normal Height (`>= 480dp`)** | **`ShortNavigationBar`** (bottom) + compact `TopAppBar` (`64dp`) | `64dp` bar height (`md.comp.nav-bar.container.height`), 3–5 destinations. Top-level switches use sequential clean cross-fade (`150ms` out -> `250ms` in), never horizontal slide. |
| **Compact Height (`< 480dp`)** *(Landscape Phone)* | **`WideNavigationRail` (explicitly collapsed)** on start edge | **Never** auto-fallback to a bottom bar on `< 480dp` height—a `64dp` bottom bar + `64dp` top bar consumes > 30% of vertical space. Explicitly pass collapsed rail. |
| **Medium Width (`600dp .. 839dp`)** | **`WideNavigationRail` (collapsed `96dp` or `80dp`)** | Start-edge rail frees vertical viewport. If expandable, open expanded drawer (`220–360dp`) as a **modal scrim overlay** so list content is not crushed. |
| **Expanded (`840dp .. 999dp`)** | **`WideNavigationRail` (collapsed)** + modal drawer expansion OR 2-pane scaffold | Keep expanded `240dp` sidebar modal below `1000dp` width when paired with 2-pane content. |
| **Large / Desktop (`>= 1000dp`–`1200dp+`)** | **Persistent / Push `WideNavigationRail` (expanded `220–360dp`)** or `MainSidebar` | Push/dock content beside the sidebar; support `Mod+B` collapse toggle (`LocalSidebarCollapsed`). |

### Navigation Highlight Uniqueness & Icon Rules
- **Single Active Indicator Rule:** Highlight **exactly one** navigation destination at a time. If a sidebar contains both a top-level destination (*Files*) and pinned quick-access shortcuts (*Projects Folder*), navigating into a pinned shortcut must highlight **only** that shortcut—never both simultaneously (`.corpus/m3-expressive/pages/components/navigation-rail.md`).
- **Outlined vs. Filled Icon Pairings:** Use `Outlined` icons for inactive states and `Filled` icons for active/selected states. Avoid icons whose outlined and filled variants have identical silhouettes (e.g., `History`, `Share`, `SyncAlt`) or badges that resemble warnings (e.g., `NewReleases` exclamation starburst for "Recently Added").
- **Collapsed Rail Accessibility & Tooltips:** Every collapsed rail icon must provide a visible hover tooltip (`TooltipIconButton`) and explicit `contentDescription`.

---

## 2. Tabs Hierarchy (`PrimaryTabRow` vs. `SecondaryTabRow`)

M3 distinguishes two tab tiers with distinct visual weight and token specs (`.corpus/m3-expressive/pages/components/tabs.md`, `manifests/tokens/m3-expressive-tokens.json`):

| Variant | Compose API | Active Indicator | Height | Semantic Role & Rules |
| --- | --- | --- | --- | --- |
| **Primary Tabs** | `PrimaryTabRow` (or `PrimaryScrollableTabRow`) | `3dp` height, rounded top corners (`3dp`), matches label width | `48dp` (`64dp` w/ icon+label) | Top-level view switches directly beneath a page's top app bar (e.g., *Videos / Posts / Collections* on a profile page). Set `divider = {}` in zero-divider containment layouts. |
| **Secondary Tabs** | `SecondaryTabRow` (or `SecondaryScrollableTabRow`) | `2dp` height, spans full tab width | `48dp` | Sub-region pagination inside a pane or detail screen (e.g., *Description / Comments* inside a detail pane). Sync indicator smoothly with `HorizontalPager` (`currentPage + currentPageOffsetFraction`). |

**Strict Layer Separation:** Never mix **Workspace Instance Tabs** (closable/reorderable user document or folder tabs like browser tabs, `Ctrl+T` / `Ctrl+W` / `Ctrl+Tab`) with **Functional Section Tabs** (`PrimaryTabRow`) or **Filter Chips**.

---

## 3. Adaptive Toolbars & Priority-Based Overflow

### 3.1 Why Naive `TopAppBar(actions = { Row { ... } })` Fails on Desktop
Material's `TopAppBar` measures its `actions` slot **before** allocating remaining horizontal width to `title` and `navigationIcon`. On a narrow `600dp`–`800dp` desktop window—especially when a custom window caption (`— □ ×` = `~138dp`) shares the top row—a `Row` of 5–7 toolbar buttons **crushes the title and back arrow to zero width**.

### 3.2 Canonical Solutions: `AppBarRow` vs. Custom `Layout` (`AdaptiveBar`)
1. **Material `AppBarRow` / `AppBarColumn` (Stable in `1.5.0-rc01` / `1.13.0-beta02`):**
   - `AppBarRow(maxItemCount = ..., overflowIndicator = { state -> ... })` automatically moves trailing `clickableItem` / `toggleableItem` entries into an overflow menu once `maxItemCount` or width constraints are exceeded (`.corpus/compose-maven-api/pages/expressive-api-reference.md:516-538`).
2. **Priority-Driven Custom `Layout` (`AdaptiveBar` Pattern for Desktop + Mobile):**
   - When title bars, window caption controls, drag regions, and priority-ordered actions must coexist in one row without `SubcomposeLayout` crashes:
     - Assign each `BarItem` an integer `priority` (`PinnedPriority` for critical view switches/back/title/caption) and an `overflow: List<SheetAction>` fallback.
     - Measure all items inside a plain **`Layout`** (never `SubcomposeLayout`—see `performance-and-stability.md` for Desktop `RootNodeOwner is already disposed` popup crash!).
     - Evict items deterministically from **lowest priority -> rightmost first**, guaranteeing stateless eviction (dragging a window edge wider/narrower never flickers hysterically) and preserving `middleMinWidth` for titles and `windowDragArea` for blank header space.
   - **Touch vs. Desktop Discovery:** Actions that live behind hover or secondary right-click menus on desktop (e.g., Refresh, Select All, Sort, View Mode) must remain reachable via visible icons or the `⋮` overflow menu on touch windows.

---

## 4. Custom Desktop Island Frames vs. Edge-to-Edge Mobile System Bars

### 4.1 Mobile (`Android` / `iOS`): Full-Bleed Edge-to-Edge
- **Android:** Call `enableEdgeToEdge()` (mandatory on Android 15+) so lists and top/bottom bars draw behind transparent status and gesture navigation bars, using `WindowInsets` (`statusBars`, `navigationBars`, `displayCutout`, `systemGestures`) strictly as content padding on scrollable interiors rather than opaque boxes (`.corpus/compose-android/pages/design/ui/mobile/guides/foundations/system-bars.md:26-69`).
- **Notch/Cutout Rule:** Keep global themes at standard cutout insets; only switch window attributes to `SHORT_EDGES` inside dedicated fullscreen video or image-viewer `Effect`s.
- **Scroll-Triggered Bar Tint:** Top bars sit flush with `surface` (`0dp` elevation) at scroll offset 0 and shift to `surfaceContainer` (`3dp` `level2` tonal elevation) when scrolled (`md.comp.app-bar.on-scroll.container.*`). Use `canScrollBackward` (`rememberListScrollTint`) rather than cumulative `pinnedScrollBehavior` nested-scroll offsets so switching folders or filtering to a short list immediately resets the bar back to `surface`.

### 4.2 Desktop (`Windows` / `macOS` / `Linux`): Island Framing (`DesktopIslandFrame`)
On multi-window desktops with custom integrated title bars, flat full-bleed mobile panes leave no clear boundary between the window chrome/sidebar and pushed subpages, and risk shifting the top-right `— □ ×` caption buttons whenever a detail screen pushes onto the back stack.

- **Island Architecture (`DesktopIslandFrame`):**
  1. **Outer Window Frame (`frame`):** Fill the outer window shell with **`surfaceContainer`** (or `surfaceContainerHigh` when pairing with `surfaceContainerLow` island headers) so the sidebar, top row (`56dp` `FrameTopRowHeight`), and caption controls sit stably on one continuous backdrop.
  2. **Inset Content Islands (`shapes.large` `16dp`):** Clip each active content pane (and each pane in `ListDetailSceneStrategy`) into an independent `shapes.large` (`16.dp`) rounded island (`surfaceContainerLowest` in light mode, `surface` in dark mode) separated by an **`8.dp` `IslandGap`** (`Spacing.Tight`).
  3. **Lighter-on-Darker Overlapping Rule (`IslandInnerCorner`):** Where a darker island header (`islandHeader = surfaceContainerLow`) meets the lighter content list (`surface`) inside the same island, round the top corners of the lighter content surface (`IslandInnerCorner = 12.dp`) over the header background—creating crisp hierarchy with **zero horizontal dividers**.
  4. **Immersive Escape Hatch:** Automatically suspend the island margin when entering fullscreen video/live players so media fills 100% of the window.
  5. **Title-Bar Drag Safety:** Register `windowDragArea` **only** on blank regions of top-row headers attached to the window's top edge—never on mid-page list headers.

---

## Sources & Cross-References
- `.corpus/m3-expressive/pages/foundations/layout/scaffold.md`, `components/navigation-bar.md`, `components/navigation-rail.md`, `components/tabs.md`, `components/app-bars.md`
- `.corpus/compose-maven-api/pages/material3-token-constants.md`, `expressive-api-reference.md`
- `.corpus/compose-android/pages/design/ui/mobile/guides/foundations/system-bars.md`
