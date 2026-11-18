# Window Size Classes, Adaptive Geometry, and Canonical Layouts

> **Scope:** Cross-platform adaptive layout engineering for Compose Multiplatform (Android, Desktop JVM, iOS) using Material 3 Expressive (`material3-adaptive`, `adaptive-navigation3`, `navigation3`).  
> **Sources:** Verified against `.corpus/compose-android/pages/develop/ui/compose/layouts/adaptive/use-window-size-classes.md`, `canonical-layouts.md`, `list-detail.md`, `build-a-supporting-pane-layout.md`, `mediaquery.md`, `.corpus/compose-multiplatform/pages/docs/multiplatform/compose-adaptive-layouts.md`, `.corpus/m3-expressive/pages/foundations/layout/canonical-examples.md`, `.corpus/apple-hig/pages/layout.md`, `.corpus/linux-hig/pages/gnome/guidelines/adaptive.md`, and `manifests/api/material3-expressive-surface.json`.

---

## 1. The Four Orthogonal Axes of Adaptive UI

A recurring failure mode in multiplatform Compose apps is collapsing distinct dimensions into a single `isDesktop` or `isTablet` boolean. Every adaptive decision must evaluate **four strictly orthogonal axes** independently:

| Axis | Question Answered | Canonical Source | Never Confuse With |
| --- | --- | --- | --- |
| **1. Workspace & Object Identity** | *What* user data, tab, draft, or session exists? | Account-scoped state holders / ViewModels (`WorkspaceViewModel`, `DriveWorkspace`) | Navigation destination stack or window size |
| **2. Capability** | *What* actions are legal for this object & host? | Domain model + platform capability flags (`supports*` on `AppPlatform` / `SystemActions`) | Narrow vs. wide screen layout (never hide features just because the window is `< 600dp`) |
| **3. Window Geometry** | *How much* net width and height (`dp`) is available right now? | `currentWindowAdaptiveInfo().windowSizeClass` / `LocalWindowInfo.current.containerSize` | Device form factor (`Phone`, `Tablet`, `Desktop`) or OS (`Android` vs `JVM`) |
| **4. Input Modality** | *How* is the user interacting with *this* event? | Per-event `PointerType` (`Touch`, `Mouse`, `Stylus`) + keyboard modifiers | Window width (a `1200dp` Surface Pro uses touch; an `800dp` Android tablet uses a mouse) |

### Anti-Pattern: Feature Gating by Viewport Size
- **Rule:** Window width only rearranges *where* controls live (bottom sheet vs. side pane vs. floating panel, inline toolbar button vs. overflow menu, bottom bar vs. navigation rail). It must **never** drop capabilities (batch operations, rename, filter, tree navigation, properties).
- **Example:** In an adaptive file workspace, compact windows expose directory trees, path entry, duplicate finder, and multi-select item actions through bottom sheets (`AdaptiveSheet`) and header overflow menus (`AdaptiveBar`), while wide windows render floating panels (`FloatingPanel`) and right-click menus (`ContextMenuArea`) backed by the exact same `DriveActions` / `itemCommands` definitions.

---

## 2. `WindowSizeClass` Width and Height Breakpoints

Material 3 Adaptive evaluates **both** width and height independently via `WindowSizeClass` (`androidx.window.core.layout.WindowSizeClass`):

### 2.1 Width Breakpoints

| Width Class | Breakpoint Lower Bound | Typical Context | Navigation & Content Structure |
| --- | --- | --- | --- |
| **Compact** | `< 600dp` | Portrait phone, narrow split-screen pane, compact desktop utility window | Bottom bar (`ShortNavigationBar`), single-column lists, modal bottom sheets, 1-pane `NavDisplay` |
| **Medium** | `600dp .. 839dp` | Landscape phone, portrait tablet, half-screen desktop window | `WideNavigationRail` (collapsed), multi-column media grids, side sheets in compact-height |
| **Expanded** | `840dp .. 1199dp` (plus **`Large` `>= 1200dp`**, **`ExtraLarge` `>= 1600dp`** via `supportLargeAndXLargeWidth = true`) | Landscape tablet, desktop window, foldable unfolded | Persistent/push sidebar (`>= 1000dp` push threshold when needed), 2-pane `ListDetailSceneStrategy`, modal/docked side sheets, persistent tab bars |

*(Source: `.corpus/compose-android/pages/develop/ui/compose/layouts/adaptive/use-window-size-classes.md#L26-L48` — pass `currentWindowAdaptiveInfo(supportLargeAndXLargeWidth = true)` to opt into `Large` `1200dp` and `ExtraLarge` `1600dp` desktop/large-tablet breakpoints.)*

```kotlin
// Cross-platform width class helper in commonMain
enum class WidthClass { Compact, Medium, Expanded }

@Composable
fun currentWidthClass(): WidthClass {
    val sizeClass = currentWindowAdaptiveInfo().windowSizeClass
    return when {
        sizeClass.isWidthAtLeastBreakpoint(WindowSizeClass.WIDTH_DP_EXPANDED_LOWER_BOUND) -> WidthClass.Expanded
        sizeClass.isWidthAtLeastBreakpoint(WindowSizeClass.WIDTH_DP_MEDIUM_LOWER_BOUND) -> WidthClass.Medium
        else -> WidthClass.Compact
    }
}
```

### 2.2 Height Breakpoints & The Landscape Phone Trap (`< 480dp`)

Using width alone breaks on **landscape phones** (typically `640–900dp` wide, `360–420dp` tall). Their width resolves to `Medium` (or even `Expanded`), yet vertical chrome + dual headers + bottom bars leave almost zero content viewport.

- **Height Breakpoint:** `WindowSizeClass.HEIGHT_DP_MEDIUM_LOWER_BOUND = 480` (`dp`). Any window with height `< 480dp` is **Compact Height** (`isHeightCompact()`):

```kotlin
// Compact-height landscape detection
@Composable
fun isHeightCompact(): Boolean =
    !currentWindowAdaptiveInfo().windowSizeClass.isHeightAtLeastBreakpoint(
        WindowSizeClass.HEIGHT_DP_MEDIUM_LOWER_BOUND
    )
```

**Mandatory Layout Adaptations When `isHeightCompact()` Is True:**
1. **Navigation Chrome:** Explicitly select a collapsed rail (`WideNavigationRailCollapsed`) on the start edge rather than letting `NavigationSuiteScaffold` auto-pick a bottom bar, which steals `64–80dp` of scarce vertical height.
2. **Workspace Chrome Gate:** Do not mount persistent multi-row desktop chrome (e.g., permanent tab strips + command bars + island margins) unless **both** `widthDp >= 600f` and `heightDp >= 480f` (or `840f × 480f` for heavy multi-tab workspaces).
3. **Dialogs & Pickers:** Folder pickers, batch rename forms, and multi-input forms switch from centered modal dialogs (which clip vertically) to full-screen destinations or full-height sheets.
4. **Immersive Media:** Video/clip feeds auto-hide system status and navigation bars without locking screen orientation.
5. **Secondary Panels:** Medium-width + compact-height modals prefer side drawers/sheets over vertical bottom sheets that collide with soft keyboards.

### 2.3 Net Content Width vs. Window Width

When a persistent navigation rail (`80dp`) or expanded sidebar (`240dp`) is active, child components (grids, toolbars, reading columns) must budget against **actual available net width** (`BoxWithConstraints` avoided—use `Layout` or `onSizeChanged` / pane constraints) rather than raw `LocalWindowInfo.current.containerSize`.

- **Sidebar Push vs. Modal Overlay Threshold:** On windows `< 1000dp` wide, expanding a `240dp` sidebar alongside a `400dp+` detail pane squeezes list content into unusably narrow strips. Keep a collapsed rail persistent and open the expanded drawer as a **modal scrim overlay** below `1000dp`; switch to **push/docked sidebar** at `>= 1000dp`.

---

## 3. Canonical Layouts & Navigation 3 Scene Strategies

### 3.1 List-Detail with `ListDetailSceneStrategy` + Navigation 3 `NavDisplay`

In Navigation 3 (`androidx.navigation3:navigation3-ui`), multi-pane adaptive layouts are modeled as a **Scene Strategy** over a flat `SnapshotStateList<NavKey>` back stack—not as separate nested graphs or manual `if (isWide)` split containers inside a single screen.

**Recommended Navigation 3 + `ListDetailSceneStrategy` Configuration:**

```kotlin
val listDetailWide = rememberAppWindowSize().isAtLeast(AppWindowSize.Expanded) // >= 840.dp
val listDetailDirective = remember(listDetailWide) {
    PaneScaffoldDirective(
        maxHorizontalPartitions = if (listDetailWide) 2 else 1,
        horizontalPartitionSpacerSize = if (listDetailWide) Spacing.Tight else 0.dp, // 8.dp island gap
        maxVerticalPartitions = 1,
        verticalPartitionSpacerSize = 0.dp,
        defaultPanePreferredWidth = ListPaneWidth,
        excludedBounds = emptyList(),
    )
}
val listDetailStrategy = rememberListDetailSceneStrategy<NavKey>(
    backNavigationBehavior = BackNavigationBehavior.PopLatest,
    directive = listDetailDirective,
)
```

**Critical Production Pitfalls & Fixes:**

1. **`BackNavigationBehavior.PopLatest` vs. Default `PopUntilScaffoldValueChange`:**
   - Default `PopUntilScaffoldValueChange` pops *every* entry that does not change the 2-pane scaffold structure—meaning pressing Back from a level-2 detail subpage in Settings pops the entire Settings flow at once!
   - Use `BackNavigationBehavior.PopLatest` so Back pops one `NavKey` at a time.
2. **Per-Key `inListPane` Flag (Context-Sensitive Pane Tagging):**
   - `ListDetailSceneStrategy` pairs contiguous `listPane` + `detailPane` entries sharing the same `sceneKey` without verifying *which* screen pushed the detail.
   - If a detail route (e.g., `Whisper(talkerId, inListPane)`) can be opened both from `Messages` (a list pane) and from a standalone `Profile` screen, only tag `ListDetailSceneStrategy.detailPane(sceneKey)` when `key.inListPane == true`. Otherwise opening it from `Profile` renders a blank or stale left list pane.
3. **Replacing the Right Pane on Master Click:**
   - In 2-pane mode (`listDetailWide == true`), clicking a second item in the visible left list while a detail is open on the right must **replace** the top `detailPane` entry (or pop back to the `listPane` root first, as in Settings sections + subpages) rather than stacking multiple invisible detail pages behind each other.
4. **Placeholder Sync When Resizing Narrow -> Wide:**
   - If the user enters a list route (e.g. `Settings`) on a `< 840dp` window and drags the window wider than `840dp`, the right pane is empty unless a default detail entry is pushed or a `detailPlaceholder` is supplied. When popping the last `SettingsPage` on wide windows (`listDetailWide && popped is SettingsPage && backStack.lastOrNull() is Settings`), pop `Settings` too—otherwise the placeholder immediately re-fills the right pane and traps the user inside Settings.
5. **Custom `PaneScaffoldDirective` & Island Framing (`DesktopIslandFrame`):**
   - Supply an explicit `PaneScaffoldDirective` driven by your app's unified window-size state so breakpoints match the rest of the app (e.g., `8.dp` `surfaceContainer` island gutter separating independent `shapes.large` `16.dp` clipped left/right islands instead of Material's default `24.dp` gap).
   - **TopAppBar Color Mismatch Fix:** `TopAppBarDefaults.topAppBarColors()` defaults to `surface` rather than `surfaceContainer` / `surfaceContainerLowest`. Explicitly pass the island's container color to `TopAppBar` inside both `listPane` and `detailPane` so two-pane Settings/Messages headers do not produce jagged color notches.
   - **Stable Desktop Window Caption Coordinates:** Wrap non-immersive desktop routes in a single `DesktopIslandFrame` outside `NavDisplay` (keeping the `surfaceContainer` frame + `8.dp` margin constant across single-pane and 2-pane scenes) so custom Win32 caption buttons (`— □ ×`) never shift coordinates on push/pop.

### 3.2 Supporting Pane & Unified Secondary Surfaces (`PaneSheet`)

For screens with a primary canvas (video player, live stream, import workspace, media inspector) and an auxiliary pane (comments, episode queue, source file tree, item properties):

- **Never call `ModalBottomSheet` directly from feature screens.** Route all secondary surfaces through a single adaptive host (`PaneSheet` / `DetailHost`):

| Host Condition | Presentation Mode | Dismissal & Chrome |
| --- | --- | --- |
| Inside an active 2-pane host (`SidePaneLayer`, `inPane == true`) | Slides inline into the right column (`slideInHorizontally`), preserving left canvas visibility without dimming | Transparent click-outside scrim on left pane (unless `persistent = true`) + back arrow in header |
| No inline host & `Expanded` (`>= 840dp`) | Floating modal side sheet (`ModalSideSheet`: `400.dp` max width, `16.dp` outer float margin, `shapes.large`, `surfaceContainerLow`) OR draggable `FloatingPanel` (`DetailHost` for properties/tasks) | `0.32f` scrim + close button + `Esc` |
| `Compact` / `Medium` (`< 840dp`) | Modal bottom sheet (`ModalBottomSheet`: `shapes.extraLarge` top corners, `maxHeightFraction = 0.88f`, `skipPartiallyExpanded = true`) | Drag handle + swipe down + `wheelStaysInSheet()` mouse guard |

- **Sticky Footer & Partial-Expand Rule:** Any sheet with confirm/save actions, input fields, or short content **must** default to `skipPartiallyExpanded = true` and place actions in a dedicated `footer` slot (`surfaceContainer` + `navigationBarsPadding()` + `imePadding()`). Stopping at a 50% detent clips primary CTAs off-screen.
- **No Unrequested Third Columns:** Reject 3-column persistent layouts (e.g. Sidebar + File Grid + Permanent Inspector) on normal desktop widths (`1000–1440dp`). Use an on-demand floating/dockable panel (`FolderMap`) or `PropertiesPane` anchored near the target item (`280–440dp` adaptive width).

### 3.3 Feed, Multi-Column Grids, and Readable Width Caps

Separate **long-form / structured reading** from **dense visual feeds**:

| Content Type | Strategy | Rule |
| --- | --- | --- |
| **Prose, Articles, Comments, Settings, Forms, Task Lists** | **Readable Width Cap** | Cap line length at `840.dp` (forms/settings/tasks) to `1040.dp` (rich articles/threads). For `LazyColumn`, apply `contentPadding = PaddingValues(horizontal = ((containerWidth - ReadableContentMaxWidth) / 2).coerceAtLeast(0.dp))` so the list still spans full width and **mouse wheel scrolling works in the side margins**! Always write `Modifier.widthIn(max = ...)` *before* `Modifier.fillMaxWidth()`, or `.fillMaxWidth().wrapContentWidth(Alignment.CenterHorizontally).widthIn(max = ...)`. |
| **Media / Video / File Poster Grids** | **Adaptive Multi-Column Grid (`LazyVerticalGrid`)** | Avoid naive `GridCells.Adaptive(240.dp)` on multi-column media walls (half-screen desktop windows squeeze cards awkwardly). Either use bounded-width `maxWidthGridCells` (ceiling column count so cards never exceed `maxCellWidth`) or **display-anchored scaling** (`rememberVideoGridCells()`): read the physical monitor's full width (`WindowManager.maximumWindowMetrics` on Android, AWT `GraphicsConfiguration.bounds` on Desktop), combine with the user's full-screen `"items per row"` preference (e.g. `3–7`, default `5`), and scale columns proportionally to the current net window width. Keep row-aligned `LazyVerticalGrid` so card baselines align and keyboard arrow traversal stays predictable. |
| **Heterogeneous Social / Mixed Feeds** | **Staggered Grid (`LazyVerticalStaggeredGrid`)** | Use `minColumnWidth = 400.dp` for wide-screen multi-column feeds with variable card heights; reserve single-column `< 600dp`. Provide a custom `ScrollbarAdapter` on Desktop since Foundation lacks a built-in staggered scrollbar adapter. |

### 3.4 Adaptive Toolbars (`AdaptiveBar`)

Material 3 `TopAppBar` measures its `actions` `Row` *first* and gives the leftover space to the `title`. On narrow desktop windows (especially with custom window caption buttons on the top-right), 4+ action icons crush the title and navigation icon to zero width.

- **Solution:** Replace `TopAppBar` action rows and command bars with a single-pass custom `Layout` (`AdaptiveBar`):
  1. Every action item declares a display `priority` and an optional `overflow: List<SheetAction>`.
  2. Measure all action items, the `"More"` overflow button, `end` (window caption buttons), and `middle` (title / path jumper) in a single `Layout` pass (never `SubcomposeLayout`—see `performance-and-stability.md`).
  3. Reserve `middleMinWidth` + `end.width` first, then greedily hide actions from lowest priority to highest (right-to-left within equal priority) into the overflow menu.
  4. Recomputing visible actions purely from current `constraints.maxWidth` guarantees deterministic, flicker-free button ordering during window resize.

---

## 4. Preserving Workspace & Session State Across Live Resizing

### 4.1 Ownership Outside Layout & Navigation Trees
Resizing a window across `600dp` or `840dp` swaps top-level navigation chrome (`ShortNavigationBar` <-> `WideNavigationRail` <-> `MainSidebar`) and multi-pane hosts (`NavDisplay` single pane <-> 2-pane scene).

- **Rule:** Never scope `ViewModel`s, active network scans, multi-selection sets, scroll anchors, or editing drafts inside `if (isWide)` branches.
  - Hold account-wide work collections (`DriveWorkspace`, `WorkspaceContexts`, `DetailPanelStore`) in an account-scoped `ViewModelStoreOwner` (`AccountPresentationStores`) above the adaptive shell.
  - Key `rememberSaveableStateHolder()` by stable context IDs (e.g., tab/draft IDs), cleaning up removed entries via `LaunchedEffect(contextIds)` + `removeState(id)` only when a tab/draft is explicitly closed—never when layout mode switches.
  - Keep non-modal/floating panel geometry (`DetailPanelState`: open target, dragged offset, pinned state) independent of current list selection and layout mode.

### 4.2 Debouncing Live Resize Breakpoints on Desktop (`SettledWindowInfo`)
On Windows and macOS, dragging a window border dispatches synchronous measure/layout passes on every mouse pixel. Crossing a breakpoint mid-drag causes:
1. Visual thrashing as sidebars/tabs flicker open and shut.
2. Full-tree recomposition on every pixel of drag.
3. **Fatal Compose Desktop Crash:** If a breakpoint swap removes a composable hosting an open `Popup` / `DropdownMenu` / `Tooltip` during synchronous resize measurement, Compose Desktop throws `IllegalArgumentException("RootNodeOwner is already disposed")` and kills the rendering coroutine.

**Desktop Live-Resize Debounce Pattern (`SettledWindowInfo`):**
- Track the native Win32 resize loop (`WM_ENTERSIZEMOVE` .. `WM_EXITSIZEMOVE`) via `caption.isSizing`.
- Provide **two** `CompositionLocal`s:
  - `LocalLiveWindowInfo`: the real `LocalWindowInfo.current` (so fluid content, `LazyGrid` widths, and titlebar hit-testing stay pixel-accurate during drag).
  - `LocalWindowInfo`: wrapped in `SettledSizeWindowInfo`, whose `containerSize` freezes at its pre-drag value while `caption.isSizing == true` and updates via `snapshotFlow` the instant `WM_EXITSIZEMOVE` fires (plus `LocalWindowResizing` so tooltips/popups can suppress themselves during drag).
- Note: Maximizing and Windows Snap Layouts bypass `WM_ENTERSIZEMOVE` and update `SettledSizeWindowInfo` immediately.

---

## 5. Checklist for Coding Agents
- [ ] Breakpoints check **both** `width` (`600dp`, `840dp`, `1000dp` sidebar push) and `height` (`480dp` compact-height landscape guard).
- [ ] `ListDetailSceneStrategy` uses `BackNavigationBehavior.PopLatest`, explicit `PaneScaffoldDirective`, and per-key pane guards (`inListPane`).
- [ ] All secondary surfaces route through a unified `PaneSheet` / `DetailHost` with `skipPartiallyExpanded = true` for action/input sheets.
- [ ] Prose/settings cap width at `840–1040dp` via list `contentPadding` (preserving edge wheel scrolling); grids scale columns cleanly; toolbars use single-pass `Layout` overflow (`AdaptiveBar`).
- [ ] Session/workspace state lives above adaptive layout branches; Desktop live-drag resizing freezes breakpoint `WindowInfo` until drag release (`SettledWindowInfo`).
