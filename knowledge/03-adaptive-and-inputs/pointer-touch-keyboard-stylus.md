# Multi-Input Engineering: Pointer, Touch, Keyboard, and Stylus

> **Scope:** Unified cross-platform input architecture for Compose Multiplatform (Android, Desktop JVM Windows/macOS/Linux, iOS) covering simultaneous Touch, Mouse, Trackpad, Keyboard, and Stylus.  
> **Sources:** Verified against `.corpus/compose-android/pages/develop/ui/compose/touch-input/pointer-input.md`, `stylus-input.md`, `user-interactions/drag-and-drop.md`, `.corpus/compose-multiplatform/pages/docs/multiplatform/compose-desktop-mouse-events.md`, `compose-desktop-keyboard.md`, `compose-desktop-context-menus.md`, `.corpus/apple-hig/pages/pointing-devices.md`, `keyboards.md`, `apple-pencil-and-scribble.md`, `focus-and-selection.md`, `.corpus/windows-fluent/pages/windows/develop/input/handle-pointer-input.md`, `keyboard-accelerators.md`, `touch-interactions.md`, and `.corpus/linux-hig/pages/gnome/guidelines/pointer-touch.md`, `keyboard.md`.

---

## 1. Per-Event `PointerType` Dispatch (Never Global Mode Flags)

Modern devices switch input modalities mid-session without warning: 2-in-1 Windows laptops alternate between mouse, touchscreen, and pen; iPads mix touch, Apple Pencil, and trackpad; Android tablets attach Bluetooth mice and keyboards.

- **Anti-Pattern:** Caching `isDesktop` at startup or querying `hasTouchscreen` to disable hover, hide context menus, or turn off pull-to-refresh.
- **Correct Pattern (`PointerSource` / `LocalPointerSource`):** Observe every pointer event at the root window (and inside every `ModalBottomSheet` / `Dialog`, which use separate popup windows and bypass the root modifier!) using `PointerEventPass.Initial` without consuming:

```kotlin
// Per-event PointerSource tracker in commonMain
class PointerSource(initialTouchLike: Boolean = true) {
    var isTouchLike: Boolean by mutableStateOf(initialTouchLike)
        private set

    internal fun observe(type: PointerType) {
        val touchLike = type == PointerType.Touch || type == PointerType.Stylus || type == PointerType.Unknown
        if (touchLike != isTouchLike) isTouchLike = touchLike // Mutate ONLY on transition!
    }
}

fun Modifier.trackPointerSource(source: PointerSource): Modifier = pointerInput(source) {
    awaitPointerEventScope {
        while (true) {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            // CRITICAL: Skip synthetic Enter/Exit — on touch interactions they can arrive tagged as PointerType.Mouse
            if (event.type == PointerEventType.Enter || event.type == PointerEventType.Exit) continue
            event.changes.firstOrNull()?.let { source.observe(it.type) }
        }
    }
}
```

**Three Critical Rules:**
1. **Only write snapshot state when `touchLike != isTouchLike`:** Writing on every `Move` event triggers a recomposition on every frame of cursor movement.
2. **Ignore `PointerEventType.Enter` and `Exit`:** Synthetic hover enter/exit events generated during touch taps frequently carry `PointerType.Mouse`, corrupting modality tracking.
3. **Never drop gesture recognizers conditionally on `isTouchLike`:** If an item swaps `combinedClickable(onLongClick = null)` to `onLongClick = { ... }` *during* the first touch `Press` after using a mouse, Compose restarts the `pointerInput` coroutine and **cancels the active long-press gesture**. Keep `onLongClick` registered at all times and inspect `LocalPointerSource.current.isTouchLike` (or the pointer type) *when the gesture fires*.

### 1.1 Separating Touch Gestures from Mouse Dragging (`NestedScrollConnection`)
- **Pull-to-Refresh:** Gate `PullToRefreshBox` enablement on `LocalPointerSource.current.isTouchLike` so mouse wheel overscroll at list top does not trigger pull-to-refresh.
- **Horizontal Pagers (`touchOnlyPaging`):** On Desktop, dragging inside a `HorizontalPager` with a mouse often happens accidentally while trying to select text or scrub a slider. Attach a `NestedScrollConnection` directly on the pager that consumes `available.x` in `onPreScroll` when `source == NestedScrollSource.UserInput && !pointers.isTouchLike` (leaving raw pointer events untouched so child sliders/scrollbars work).
- **Modal Bottom Sheets (`wheelStaysInSheet`):** In `ModalBottomSheet`, residual mouse wheel `onPostScroll` deltas bubble up to the sheet's drag state. Because mouse wheels have no "finger lift / fling release" event, scrolling past the top of a list inside a bottom sheet drags the sheet down one notch per wheel tick and leaves it stranded mid-screen. Consume residual `UserInput` scroll in `onPostScroll` whenever `!pointers.isTouchLike`.

---

## 2. Non-Consuming Hover, Press Feedback, and Multi-Select

### 2.1 `PointerEventPass.Final` Passive Observation (`Modifier.interactiveCard`)
When building clickable cards that also contain nested buttons, links (`LinkAnnotation`), and an outer `ContextMenuBox`, putting `hoverable` or `pointerInput(Main)` on the card often breaks either hover or child clicks.

**Solution (`Modifier.interactiveCard` via `PointerEventPass.Final`):**
- Observe pointer state in **`PointerEventPass.Final`** and **never call `change.consume()`**:
  - `Enter` (if `!isTouch`) -> `hovered = true`
  - `Exit` -> `hovered = false; pressed = false`
  - `Move`: if `isTouch`, force `hovered = false`; if `pressed` and any change became `!pressed || isConsumed` (e.g., child button or scroll took over), reset `pressed = false`.
  - Primary press (excluding secondary mouse button `event.buttons.isSecondaryPressed`): animate scale (`0.985f` via `MaterialTheme.motionScheme.fastSpatialSpec()`, disabled when Reduced Motion is active) on `graphicsLayer`.
- **Transparent Color Interpolation Fix:** When interpolating from `Color.Transparent` (`0x00000000`, transparent black) to a light `hoverColor` (e.g., `surfaceContainerLow`), Compose interpolates RGB through black, creating an ugly gray flash. Set resting color to `hoverColor.copy(alpha = 0f)`.

### 2.2 Desktop Hover Quirks & Zero-Shift Checkboxes
- **Compose Desktop `previousPosition == position` Bug:** On Skiko/AWT hover `Move` events, `change.previousPosition` equals `change.position`. For dwell detection or cursor-movement intent (e.g., auto-hiding floating panels or showing player HUD), record the previous frame's `Offset` manually in local state rather than computing `position - previousPosition`.
- **Hover-Reveal Selection Checkboxes:** On desktop lists/tables, show the selection checkbox on row hover or when `isSelectionMode == true` **by swapping inside a fixed-width leading slot** (replacing the file/type icon in place). Never insert a new column or shift item titles horizontally on hover.

---

## 3. Context Menus, Long-Press Divergence, and Tooltips

### 3.1 Input Matrix for Item Context Menus & Multi-Select

| Interaction | Mobile Touch | Desktop Touch / Stylus | Desktop Mouse | Keyboard |
| --- | --- | --- | --- | --- |
| **Primary Activate** | Single tap | Single tap | Double-click (file manager) or single click (web/feed) | `Enter` (Win/Linux) or `⌘↓` (macOS) |
| **Secondary / Context Menu** | Overflow `⋮` button (or long-press if no multi-select mode) | **Long-press release** at touch point (Windows touch convention; includes `"Select"` item) | **Right-click press** (`isSecondaryPressed`) at pointer position | `Key.Menu` or `Shift+F10` at item center |
| **Enter Multi-Select** | **Long-press** enters multi-select directly | Context menu `"Select"` (or multi-select toolbar toggle) | `Ctrl/⌘ + Click` toggle, `Shift + Click` range, or **marquee box drag** | `Ctrl/⌘ + A` or `Space` in selection mode |

### 3.2 `ContextMenuArea` & `PointerMenuPositionProvider`
- **Innermost Wins on Nested Menus:** Register `pointerInput` at `PointerEventPass.Initial` (or `Main`, bubbling inner-to-outer). When an item's `ContextMenuArea` sees `event.type == PointerEventType.Press && event.buttons.isSecondaryPressed && !change.isConsumed`, record `change.position` and call `change.consume()`. An outer grid background `ContextMenuArea` checks `!change.isConsumed` and stays closed when right-clicking an item.
- **Anchor at Cursor, Not Row Bounds:** Material `DropdownMenu` defaults to `MenuAnchorPosition.Below`—which anchors to the *entire row/grid item* and flips the whole menu above the row when near the bottom of the window, jumping far away from the cursor. Implement a custom `DropdownMenuPopupPositionProvider` (`PointerMenuPositionProvider`) that positions the menu's top-left corner at the recorded pointer `Offset` and flips **per-axis** (left if overflowing right edge, up if overflowing bottom edge).
- **No Scale-Spring Menu Entrance (`DesktopMenuMotionScheme`):** Standard M3 `DropdownMenu` animates scale `0.8 -> 1.0`. On fast right-click -> immediate click workflows, scaling shifts item hitboxes under the cursor. Override `MotionScheme` locally on desktop context menus with `snap()` for spatial specs and `tween(80)` fade-in for effects specs.
- **Initial Keyboard Focus Inside Menus:** When a mixed context menu has a top row of quick-action icons followed by grouped text rows, move initial keyboard focus to the **first list row**, not the first quick-action icon (otherwise a tooltip immediately pops over the first row). Grab `LocalFocusManager.current` *inside* the popup content scope so `FocusDirection.Down` / `Up` navigates within the menu popup.

### 3.3 Desktop Tooltip Crash Avoidance (`AdaptiveTooltip`)
Compose Desktop's `BasicTooltipBox` / `TooltipBox` (in CMP `1.12.x`) can synchronously dispose its `Popup` during `doMeasureAndLayout` via an `UNDISPATCHED` coroutine when pointer state changes mid-frame, throwing `RootNodeOwner is already disposed`.
- **Workaround:** On touch (`isTouchLike`), delegate to M3 `TooltipBox` (long-press, never include keyboard shortcut text). On mouse (`!isTouchLike`), build a lightweight hover `Popup` driven by `MutableInteractionSource.collectIsHoveredAsState()` where `visible` is mutated **exclusively inside `LaunchedEffect`** (delayed `500ms`), and pointer-down/wheel dismissals signal through a conflated `Channel<Unit>` rather than writing snapshot state mid-pointer-pass. Hide immediately when `LocalWindowResizing.current` is true.

---

## 4. Bimodal Text Selection & Structured Copy

Wrapping `LazyColumn` rows or clickable cards in `SelectionContainer` causes two severe bugs:
1. `SelectionContainer` steals long-press and drag gestures from `combinedClickable` and vertical/horizontal scrolling.
2. Scrolling selected items out of a `LazyColumn` / `LazyVerticalGrid` viewport disposes `Text` `Selectable` nodes while `SelectionRegistrar` still holds references, risking crashes or stuck selection handles.

**Unified Bimodal Copy Architecture:**
1. **Non-Clickable Prose Blocks** (expanded descriptions, article paragraphs, rich assistant answers):
   - Wrap in `SelectionContainer` **only when `!LocalPointerSource.current.isTouchLike`** (giving desktop mouse users native I-beam drag selection while keeping `LinkAnnotation` spans clickable).
   - Wrap *outside* in `ContextMenuBox` offering one-tap `"Copy ..."` plus `"Select text"` (which opens a bounded-height `SelectableTextDialog` containing a clean `SelectionContainer` over plain selectable text for touch users).
2. **Clickable List Items, Comments, Bubbles & Cards:**
   - **Never** wrap inline in `SelectionContainer`. Provide structured copy actions (Copy Title, Copy ID, Copy Body, Copy Link) + `"Select text"` (`SelectableTextDialog`) inside `ContextMenuBox` / bottom action sheet.
3. **Inline ID Pills & Code Blocks:**
   - Render copyable IDs (`UID`, record IDs, hashes) as standalone `CopyableIdPill`s that consume their own click so tapping them never toggles parent expand/collapse rows.
   - Code blocks carry a top `surfaceContainerHigh` bar with language label + one-click Copy icon, and a horizontally scrollable `SelectionContainer` body.
4. **Copy Feedback Deduplication:** Android 13 (API 33+) shows a built-in system clipboard preview overlay. Only display an in-app `"Copied"` Snackbar on Desktop and Android <= 12L (`NeedsCopyNotice`).

### 4.1 Inline Pointer Composers vs. Mobile IME Sheets
- On touch devices, popping a dedicated `Dialog` / `ModalBottomSheet` composer isolates the soft keyboard (`WindowInsets.ime`) from heavy list scrolling (`CommentComposerDialog`).
- On desktop / pointer environments (`!isTouchLike` inside a 2-pane player/inspector), popping a centered white modal dialog obscures content unnecessarily—dock an inline composer card (`InlineCommentComposer`) directly at the bottom of the right pane instead.

---

## 5. Keyboard Navigation, Shortcuts, Focus, and Command Palettes

### 5.1 Platform Shortcut Abstraction
Never hardcode `event.isCtrlPressed` for cross-platform app shortcuts. Define a platform abstraction:
- **Windows / Linux / Android:** Primary modifier = `Ctrl` (`event.isCtrlPressed && !event.isAltPressed && !event.isMetaPressed`).
- **macOS:** Primary modifier = `⌘` (`event.isMetaPressed && !event.isAltPressed && !event.isCtrlPressed`).

**Platform-Specific Keymap Divergences (File / List Workspaces):**

| Action | Windows / Linux | macOS | Notes |
| --- | --- | --- | --- |
| Primary Command Modifier | `Ctrl` | `⌘` (`Meta`) | Abstract via `AppPlatform.shortcutModifier` |
| Open / Activate Item | `Enter` | `⌘ + ↓` | Intercept in item `onPreviewKeyEvent` |
| Rename Item | `F2` | `Enter` | On macOS Finder convention, `Enter` renames! |
| Properties / Inspector | `Alt + Enter` or `Ctrl + I` | `⌘ + I` | Show shortcut in `TooltipIconButton` |
| Back / Forward / Up | `Backspace` / `Alt+←` / `Alt+→` / `Alt+↑` | `⌘[` / `⌘]` / `⌘↑` | Also bind mouse XButton1/XButton2 (`Back`/`Forward`) |
| Context Menu | `Menu` or `Shift + F10` | `Menu` or `Shift + F10` | Opens at focused item center |
| Command Palette | `Ctrl + K` | `⌘ + K` | Fuzzy search across routes, recents, page actions |
| Shortcuts Cheat Sheet | `F1` or `Ctrl + /` | `F1` or `⌘ + /` | Keep synced with all registered shortcuts |

### 5.2 Focus Management & Editable Guards
- **Root Key Listener + `EditableFocusTracker`:** Register global single-key or `Ctrl`-less shortcuts (`Space`, `Delete`, `Backspace`, `Esc`, `/`) at the root `onPreviewKeyEvent`, but **yield immediately** whenever a text input holds focus (`LocalEditableFocusTracker`). Never swallow `Backspace`, `Enter`, or `Ctrl+A/C/V/X` when typing inside a `TextField`.
- **Distinct Keyboard vs. Mouse Focus Indication:** Differentiate keyboard traversal focus (high-contrast `outline` ring) from mouse-click selection (`secondaryContainer` / `surfaceContainerHigh` fill), and clear or redirect item focus via a `FocusFallback` root when clicking empty grid background so `Backspace`/navigation shortcuts do not misfire on stale list items.
- **Scope Tab Shortcuts to Active Surface:** Shell-level tab shortcuts (`Ctrl/⌘+T`, `Ctrl/⌘+W`, `Ctrl/⌘+Tab`, `Ctrl+Shift+PageUp/PageDown`) must check that the active surface is the workspace (not Settings, Task queue, or detached Video Player) before mutating background tabs.

### 5.3 Dynamic Command Palette (`CommandPalette` + `ContributePaletteItems`)
Pages contribute context-sensitive commands while composed using `DisposableEffect(registry, key)` + `rememberUpdatedState(items)`:
- Commands resolve lazily only when the palette opens (reading current screen state without recomposing on every change).
- Disabled commands remain visible with `disabledReason` displayed on the trailing edge (matching toolbar/menu parity: disable with explanation rather than hiding).
- Match query against `title` (fuzzy subsequence score) and contiguous substrings in `keywords` / `group` (do *not* fuzzy-subsequence match long keyword strings, or `"sp"` falsely matches `"details inspector"`).

---

## 6. Scrollbars, Wheel Translation, Marquee, and Drag-and-Drop

### 6.1 Horizontal Rows with Vertical Mouse Wheel (`verticalWheelScrollsRow`)
Standard mice only have a vertical scroll wheel; Compose `horizontalScroll` and `LazyRow` ignore vertical wheel deltas unless `Shift` is held.
- Attach a `pointerInput` at **`PointerEventPass.Initial`** listening for `PointerEventType.Scroll`:
  1. Check `abs(delta.y) > abs(delta.x)`.
  2. Compute `px = delta.y * stepPx` (e.g., `96.dp.toPx()` per notch).
  3. **Boundary Yield:** Check `state.canScrollForward` / `state.canScrollBackward`. If the row cannot move further in that direction (or fits completely without scrolling), **do not consume** so the outer vertical page scrolls normally.
  4. **Use `state.dispatchRawDelta(px)` directly (no `animateScrollBy`):** Rapid wheel ticks cancel prior animations if animated, causing the row to travel far less than the notches scrolled.

### 6.2 Desktop Scrollbars (`ListScrollbar` `expect`/`actual`)
- Android / iOS: `ListScrollbar` is a no-op (`actual fun ListScrollbar(...) {}`); touch uses fling + edge glow.
- Desktop: Overlay `VerticalScrollbar(rememberScrollbarAdapter(state))` with `CircleShape` thumb, theme-aware colors (`onSurface` alpha), and auto-fade via `Modifier.alpha` **without** removing the composable from composition when idle (keeping the hit target active so moving the mouse to the right edge reveals and grabs the thumb).
- For `LazyStaggeredGridState` (which has no built-in Foundation adapter), implement `ScrollbarAdapter` estimating `averageRowHeight` from `visibleItemsInfo` and `rowCount = ceil(totalItemsCount / lanes)`.

### 6.3 Marquee Selection & Internal Drag-and-Drop
- **Marquee Selection (`Modifier.marqueeSelection`):** Attached to `LazyGridState` at `PointerEventPass.Initial`:
  - Only activates on `PointerType.Mouse` primary press over empty background or unselected items (if pressed over an already selected/movable item, yield to `fileDragSource`). Touch drags scroll the grid; touch background taps clear selection.
  - Supports `Ctrl/⌘` and `Shift` additive merging, auto-scrolls when pointer nears viewport top/bottom edges (adjusting `start.y - scrolled` origin), and retains off-screen boxed item IDs until the marquee shrinks back.
  - **Key Identity Rule:** Pass unique row keys (`item.key`) rather than raw domain IDs when a list (e.g., duplicate finder) can show two rows for the same underlying file.
- **Internal Drag-and-Drop:** Track `FileDragState` at root scope (`LocalFileDrag`) with drop targets (`fileDropTarget`) on folder cards, breadcrumb path segments, workspace tab pills, and sidebar quick-access pins (`Ctrl` / macOS `⌥` switches Move -> Copy). Disable drag-out on read-only/virtual namespaces (trash, archive inner entries, pending uploads, import projections).

---

## 7. Windows Touch & Stylus Bridging (`WM_POINTER*`)

On Desktop JVM (Windows), AWT's legacy window procedure **does not handle `WM_POINTER*`**. Windows translates unhandled `WM_POINTER` messages into single-point synthetic mouse events, breaking multi-touch pinch/scroll, touch slop, and `PointerType.Touch` / `PointerType.Stylus` identification in Compose Desktop.

**Production Bridge Architecture (`WM_POINTER*` -> Compose Desktop `ComposeScene`):**
1. **Window Procedure Interception:** Subclass both the outer AWT frame HWND and the inner Skiko canvas child HWND via JDK FFM (`SetWindowLongPtrW`).
2. **Client-Area Only:** Intercept client-area `WM_POINTERDOWN` / `WM_POINTERUPDATE` / `WM_POINTERUP` / `WM_POINTERCAPTURECHANGED` / `WM_POINTERWHEEL`. **Never** intercept `WM_NCPOINTER*` so Windows continues synthesizing non-client mouse interactions for titlebar dragging, Snap Layouts, and window borders.
3. **Coalescing & Velocity Preservation:** Batch accumulated pointer history via `GetPointerFrameInfoHistory` into Compose `HistoricalChange`s and populate **`originalEventPosition`** explicitly—omitting `originalEventPosition` causes Compose's `VelocityTracker` to calculate fling velocity from `(0, 0)`, resulting in runaway scroll flings.
4. **Touch Slop Override (`ProvideTouchViewConfiguration`):** Compose Desktop hardcodes `touchSlop = 18.dp`. Override `LocalViewConfiguration` for touch/pen pointers to Android's `8.dp` standard while preserving sub-pixel mouse click stability.
5. **Injection & ProGuard Hazard:** Dispatch multi-pointer frames via reflection into Compose Desktop's internal chain (`ComposeWindow.composePanel` -> `ComposeWindowPanel._composeContainer` -> `ComposeContainer.mediator` -> `ComposeSceneMediator.scene` -> `ComposeScene.sendPointerEvent-*` 10-arg `List<PointerInputEventData>` overload).
   - Because Compose Desktop's own AWT path only calls the single-pointer overload, **ProGuard strips the 10-arg overload in Release builds unless explicitly kept**.
   - Inline value-class name mangling (e.g. `sendPointerEvent-UGFwazM`) changes across Compose versions; re-verify with `javap` on `ui-desktop-*.jar` on every CMP upgrade and test with native Windows `InjectTouchInput` smoke tests (`:desktopApp:desktopTest`).
