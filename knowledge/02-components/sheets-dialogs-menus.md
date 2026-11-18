# Unified Secondary Surfaces: Sheets, Floating Panels, Context Menus & Dialogs

> **Scope:** Engineering handbook for transient and secondary UI surfaces across touch and desktop form factors—covering **Bottom Sheets vs. Modal Side Sheets vs. Inline Panes vs. Floating Panels**, **Pointer Context Menus vs. Touch Action Sheets** (including M3E menu shape parity), and **Dialog Sizing, Semantics & Layout Stability**.

---

## 1. Secondary Surface Selection Matrix (`PaneSheet` & `DetailHost` Architecture)

Never call `ModalBottomSheet` directly inside feature screens. Feature code should target a single semantic wrapper (`PaneSheet` or `DetailHost`) that selects the surface container from **layout context** and **task persistence**:

| Context / Task Type | Selected Surface | Container Spec (M3E / Production) | Dismissal & Interaction Rules |
| --- | --- | --- | --- |
| **Compact / Medium Window (`< 840dp`)**, transient secondary task | **Modal Bottom Sheet** | `surfaceContainerLow`, `shapes.extraLarge` (`28dp` top corners), max width `640dp` (`56dp` side/top margins when window > `640dp`), drag handle `32dp × 4dp` (`.corpus/m3-expressive/pages/components/bottom-sheets.md:69-83`) | `skipPartiallyExpanded = true` by default when inputs, footers, or mouse wheel exist; cap max height (e.g., `0.88f`) so background context peeks at top. |
| **Expanded Window (`>= 840dp`) OR Compact-Height (`< 480dp`) Medium**, no inline host column | **Modal Side Sheet** *(Detached)* | `surfaceContainerLow`, `shapes.large` (`16dp` corners), `widthIn(max = 400dp)`, `16dp` detached outer margin (`md.comp.sheet.side.detached.container.shape`), `0.32f` black scrim, single `56dp` header (`[title] [trailing] [Close]`) (`.corpus/m3-expressive/pages/components/side-sheets.md:75-120`) | Respect `WindowInsets.barsAndCutout.union(WindowInsets.ime)`. Click scrim, `Close` button, or `Esc` animates out before `onDismissRequest`. Inside sheet, use `FlowRow` instead of horizontal scrollbars. |
| **Active 2-Pane Workspace** (e.g., Video/Live player with right info column) | **Inline Hosted Side Pane** (`SidePaneLayer`) | Slides over the right column (`surface`, full column height), leaving the left media pane **un-dimmed and visible**, with an invisible `SidePaneDismissLayer` over the left pane so tapping returns focus without pausing video | Top bar integrates `[Back] [title] [trailing]` + desktop window drag/caption slot; `BackHandler` / `Esc` pops the pane. Support `persistent = true` (no dismiss layer) for side-by-side tools. |
| **Inspectable / Multi-Window Desktop Properties or Live Task Detail** | **Draggable Floating Panel** (`FloatingPanel`) | Plain `Layout` overlay (`shapes.large` `16dp`, `1dp` outline border) anchored beside clicked item (`Beside(rect)`), at cursor (`AtPoint`), or top-end (`Centered`); resizable edges/corners; avoids overlapping additional open panels | Use plain **`Layout`** (not `Popup`, which breaks keyboard focus; not `BoxWithConstraints`/`SubcomposeLayout`, which crashes desktop on tooltip disposal). On `< 840dp` windows, `DetailHost` swaps seamlessly to a bottom sheet while preserving inspected ID. |

---

## 2. Critical Sheet Engineering Pitfalls & Fixes

### 2.1 Why `skipPartiallyExpanded = false` Breaks Actions & Mouse Wheels
1. **Clipped Footers & Inputs:** Opening a sheet with a sticky confirm button or text input at the 50% `PartiallyExpanded` detent pushes the primary action off the bottom of the screen. Always default `skipPartiallyExpanded = true` when `footer != null` or interactive forms exist.
2. **Mouse Wheel Deadlock:** `ModalBottomSheet` attaches nested-scroll sheet dragging. When a mouse wheel scrolls a `PartiallyExpanded` sheet or hits the top of an inner `LazyColumn`, unconsumed wheel delta drags the sheet mid-way—and because a mouse wheel emits no touch-release fling, **the sheet freezes half-open and the list refuses to scroll**.
   - **Fix:** Attach a `NestedScrollConnection` (`WheelStopsAtSheet`) consuming leftover `onPostScroll` deltas when `source == NestedScrollSource.UserInput && !pointers.isTouchLike`, and force `skipPartiallyExpanded = true` whenever pointer input is non-touch.

### 2.2 Sticky `footer` Slot & `BottomSheetDefaults.windowInsets` Double-Inset Trap
- **Do NOT put bottom action buttons inside the scrollable body**—they scroll off-screen on short viewports. Provide a dedicated `footer` slot rendered in a `surfaceContainer` slab pinned below `Modifier.weight(1f, fill = false)`.
- **Avoid Double Bottom Insets:** Material 3's `ModalBottomSheet` already applies `BottomSheetDefaults.windowInsets` (`safeDrawing.only(Top + Bottom)`). Check whether your `ModalBottomSheet` call passes `contentWindowInsets` before adding `navigationBarsPadding()` inside `SheetFooterSlot`; doubling both adds a ~48dp empty bar beneath footer buttons.
- **Immediate `hideThen` Execution:** When an action item inside a sheet navigates away or flips a parent toggle, invoke `onDismissRequest()` synchronously *before* running `action()` rather than waiting 300ms for a slide-down animation—preventing stale close callbacks from clobbering newly opened state.

### 2.3 Consistent Sheet Header Anatomy
Every mode of a unified sheet (bottom, modal side, inline pane) must render the **same title, subtitle/subheader, and trailing close/action slots** with identical leading padding. Never show a title on tablet while hiding it on phone.

---

## 3. Context Menus vs. Touch Action Sheets (`SheetAction` & M3E Menu Shapes)

### 3.1 Single Action Definition Driving Pointer & Touch Surfaces
Define item commands once as data (`SheetAction(icon, label, shortLabel, onClick, destructive, group, tier, onPrepare)`), then feed that single list into both **desktop right-click menus** (`ContextMenuArea`) and **mobile bottom action sheets** (`layoutActions`):

1. **Deterministic Ordering (`layoutActions`):**
   - Partition **`destructive`** actions into a standalone bottom group colored `error`.
   - Place **`ActionGroup.Properties`** in its own group immediately above destructive actions.
   - If non-destructive items total `<= FlatLimit` (`6`), render a flat grouped list (don't force users to hunt a top icon row for 4 items).
   - Otherwise, promote up to `4` (`QuickLimit` on mobile sheets with `shortLabel`, or `5` icon-only quick actions matching Windows 11 Explorer on desktop context menus) into a top quick-action row, and group remaining items by `ActionGroup`.
2. **Never Truncate or Nest "More" Pages:** Both menus and sheets scroll vertically if taller than the viewport—never hide capabilities in cascading submenus or paginated "more" tabs.
3. **Initial Keyboard Focus Rule:** When a context menu opens with a top quick-icon row, place initial focus on the **first list row** (not the first quick icon) so an auto-shown icon tooltip does not cover the first menu item.

### 3.2 Pointer Context Menu Positioning & Motion (`PointerMenuPositionProvider`)
- **Do NOT use Material's default `DropdownMenu` anchor logic for row/grid right-clicks:** `DropdownMenu` anchors below the entire composable bounds (`anchorBounds`), flipping above the entire row/grid when near the bottom of the window—causing the menu to jump far away from the mouse cursor!
- **Canonical Fix (`PointerMenuPositionProvider`):** Anchor at the exact window pointer coordinate `(anchorBounds.left + pointer.x, anchorBounds.top + pointer.y)`, expanding down-right and flipping per-axis only when constrained by `windowSize`.
- **Desktop Menu Motion:** Override `MotionScheme` locally inside desktop context menus to **`snap()` spatial + `80ms` fade-in effects**—suppressing `0.8f -> 1.0f` scale-up so fast muscle-memory clicks never miss moving `graphicsLayer` bounds.
- **Coexisting Touch & Pointer Triggers:** Touch long-press on items enters multi-select (mobile) or opens the action sheet at release (desktop touchscreen/stylus per Windows guidelines); mouse left-press never triggers long-press multi-select.

### 3.3 M3 Expressive Menu Shapes & `totalCount` Parity
M3 Expressive menus replace the uniform `4dp` M3 baseline menu container with segmented expressive item geometry (`.corpus/m3-expressive/pages/components/menus.md`, `manifests/tokens/m3-expressive-tokens.json`):
- **Container:** `shapes.large` (`16dp`), gap between items `2dp` (`md.comp.menus.gap`), item height `44dp` (expressive) / `48dp` (baseline), leading/trailing icon `20dp`.
- **Segmented Item Corner Parity (`totalCount` trap):** First child and last child receive `medium` (`12dp`) outer corners and `extraSmall` (`4dp`) inner corners; middle items receive `4dp` corners (morphing to `12dp` on hover/selection/focus). Any helper building segmented menus dynamically (e.g., `MediaCommonMenuItems`) **must receive an accurate `totalCount`** reflecting conditional items (like *Play Next* or *Unpin*), or the last visible item renders with sharp `4dp` bottom corners.

---

## 4. Dialog Sizing, Semantics & Stability Rules

### 4.1 M3 Baseline vs. Desktop-Calibrated Dialogs
- **M3 Mobile Spec:** `28dp` (`extraLarge`) corners, `minWidth = 280dp`, `maxWidth = 560dp`, `24dp` outer padding, `16dp` title-to-body gap, `surfaceContainerHigh`, headline `headlineSmall` (`24sp`), text-only confirm/dismiss buttons (`.corpus/m3-expressive/pages/components/dialogs.md:83-98`).
- **Desktop-Calibrated Shared Dialog (`AppDialog` Pattern):** On `1440px` desktop screens, `28dp` corners and text-only confirm buttons look oversized and ambiguous. Standardize shared dialogs on `shapes.large` (`16dp`) with `titleLarge` (`22sp`), pairing a **filled `Button`** for executable confirmations (switched to `colorScheme.error` / `onError` **only** for irreversible destructive actions) with a **`TextButton`** for cancel, and plain `TextButton` for informational acknowledgements (`"Close"` / `"OK"`).
- **CMP Opt-In Note:** In `material3` `1.5.0-rc01` (Android) vs. `1.13.0-beta02` (CMP Desktop), `AlertDialog` and `BasicAlertDialog` are stable on Android but still carry `@ExperimentalMaterial3Api` on CMP Desktop (`opt_in_delta` in `manifests/api/material3-expressive-surface.json`). Declare module-level `@OptIn(ExperimentalMaterial3Api::class)` or opt-in in Gradle.

### 4.2 Five Non-Negotiable Dialog Rules
1. **Zero Internal Height Jumps (Android Window Resize Bug):** On Android, `Dialog` sizes its native window dynamically to its composable bounds. Animating validation error lines in/out (`AnimatedVisibility`) makes the entire centered window bounce vertically under the user's finger. **Always reserve a fixed-height supporting/validation slot and switch only text color/content.**
2. **Never Nest Dialogs Over Dialogs:** M3 and Fluent both forbid stacking a modal dialog on top of another modal dialog (`.corpus/m3-expressive/pages/components/dialogs.md:478`). Replace secondary prompts (e.g., *New Folder* inside a *Folder Picker* dialog) with an inline input row at the top of the picker list.
3. **Scrollable Content Keeps Header & Actions Pinned:** When dialog lists/forms exceed viewport height, scroll **only** the middle body while keeping title and action buttons fixed—and show visual scroll affordances/fade so clipped controls aren't hidden.
4. **Match Commitment Model to Action Labels:**
   - *Instant-apply radio/choice dialog:* Selection applies immediately; provide a single **`Close`** button (never **`Cancel`**, which falsely implies rollback!).
   - *Editable form / multi-field dialog:* Changes apply only on submit; provide **`Cancel`** + specific verb (**`Save`**, **`Rename`**, **`Delete`**—never vague `OK` or `Done`).
5. **Icon & Alignment Consistency:** When a dialog has a top icon (`24dp`), center-align the headline; without a top icon, start-align the headline (`.corpus/m3-expressive/pages/components/dialogs.md:92-93`). Establish one app-wide rule for which dialogs carry icons rather than mixing centered and start-aligned confirmation alerts arbitrarily.

---

## Sources & Cross-References
- `.corpus/m3-expressive/pages/components/{bottom-sheets,side-sheets,dialogs,menus}.md`
- `manifests/tokens/m3-expressive-tokens.json` & `manifests/api/material3-expressive-surface.json`
