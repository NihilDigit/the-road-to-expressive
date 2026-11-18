# Material 3 Expressive Component Catalog (Compose `1.5.0-rc01` / CMP `1.13.0-rc01`)

> **Scope:** Component-by-component engineering reference for the 14 new and updated **Material 3 Expressive (`M3E`)** components—covering anatomy, exact tokens (`dp`), when-to-use vs. avoid rules, verified Compose signatures, and `@OptIn` / cross-target parity status from `manifests/api/material3-expressive-surface.json`.

---

## 1. Graduation & Opt-In Quick Matrix (`1.5.0-rc01` vs. `1.13.0-rc01`)

| Component | Compose Entry Point(s) | Opt-In Status (AndroidX `1.5.0-rc01` & CMP `1.13.0-rc01`) | Cross-Target Parity |
| --- | --- | --- | --- |
| **Button Group** | `ButtonGroup`, `ButtonGroupDefaults`, `ButtonGroupScope` | Graduated (Stable) | `identical` |
| **Split Button** | `SplitButtonLayout`, `SplitButtonDefaults` | Graduated (Stable) | `identical` |
| **Toggle Button** | `ToggleButton`, `FilledTonalToggleButton`, `IconToggleButton`, `FilledIconToggleButton`, `OutlinedIconToggleButton` | Graduated (Stable) | `identical` |
| **FAB Menu** | `FloatingActionButtonMenu`, `FloatingActionButtonMenuItem`, `ToggleFloatingActionButton` | Graduated (Stable) | `identical` |
| **Floating Toolbar** | `HorizontalFloatingToolbar`, `VerticalFloatingToolbar`, `FloatingToolbarDefaults` | Graduated (Stable) | `identical` |
| **Loading Indicator** | `LoadingIndicator`, `ContainedLoadingIndicator`, `LoadingIndicatorDefaults` | **`@ExperimentalMaterial3ExpressiveApi`** | `identical` (`Defaults`: `overload_delta`) |
| **Wavy Progress** | `LinearWavyProgressIndicator`, `CircularWavyProgressIndicator`, `WavyProgressIndicatorDefaults` | Graduated (Stable) | `identical` |
| **Flexible Top App Bars** | `MediumFlexibleTopAppBar`, `LargeFlexibleTopAppBar`, `AppBarRow`, `AppBarColumn` | Graduated (Stable) *(note: `alpha22` needed `@OptIn`)* | `identical` |
| **Wide Navigation Rail** | `WideNavigationRail`, `WideNavigationRailItem`, `WideNavigationRailState` | Graduated (Stable) | `identical` |
| **Short Navigation Bar** | `ShortNavigationBar`, `ShortNavigationBarItem`, `ShortNavigationBarDefaults` | Graduated (Stable) | `identical` |
| **Segmented List Item** | `SegmentedListItem`, `ListItemShapes`, `ListItemDefaults` | Graduated (Stable) *(note: `alpha22` lacked non-clickable overload)* | `identical` (`ListItemShapes`/`Defaults`: `overload_delta`) |
| **Carousel** | `HorizontalMultiBrowseCarousel`, `HorizontalUncontainedCarousel`, `HorizontalCenteredHeroCarousel` | Graduated (Stable) (`carouselParallaxScrollEffect` is `@ExperimentalMaterial3Api`) | `identical` |
| **Search** | `SearchBar`, `ExpandedFullScreenSearchBar`, `ExpandedDockedSearchBar` | `SearchBar` is **`@ExperimentalMaterial3Api`**; `Expanded*` are **Stable** | `identical` |

---

## 2. Expressive Buttons & Action Clusters

### 2.1 `ButtonGroup` (Connected & Standard)
- **Purpose:** Organizes 2–5 related actions or mutually exclusive / multi-select mode toggles (`ButtonGroupDefaults.connected*` replaces legacy M2/early-M3 `SegmentedButton`) (`.corpus/m3-expressive/pages/components/button-groups.md`).
- **Tokens & Geometry:**
  - **5 Size Tiers** (`xsmall` `32dp`, `small` `40dp`, `medium` `56dp`, `large` `96dp`, `xlarge` `136dp`).
  - **Connected:** `between-space = 2dp` (`md.sys.measurement.space25`), outer corners `full` (`CircleShape`), inner corners `small`/`extraSmall` morphing on press/check (`ButtonGroupDefaults.connectedLeadingButtonShapes()`, `connectedMiddleButtonShapes()`, `connectedTrailingButtonShapes()`).
  - **Standard:** `between-space = 8dp` (`large`/`medium`/`xlarge`), `12dp` (`small`), `18dp` (`xsmall`); pressed items dynamically widen via `ButtonGroupScope.animateWidth(interactionSource)` while squeezing neighbors (`expandedRatio`).
- **Compose Signature:**
  ```kotlin
  @Composable fun ButtonGroup(
      overflowIndicator: @Composable (ButtonGroupMenuState) -> Unit,
      modifier: Modifier = Modifier,
      expandedRatio: Float = ButtonGroupDefaults.ExpandedRatio,
      horizontalArrangement: Arrangement.Horizontal = ButtonGroupDefaults.HorizontalArrangement,
      verticalAlignment: Alignment.Vertical = Alignment.CenterVertically,
      content: ButtonGroupScope.() -> Unit,
  )
  ```
- **When to Use vs. Avoid:** Use connected `ButtonGroup` for compact 2–5 option view/mode switches (`List | Grid`, `All | Unread`); use standard `ButtonGroup` for adjacent peer action bars where items flex on press. Avoid > 5 items in a horizontal group—let `overflowIndicator` collapse excess actions rather than wrapping into jagged rows.

### 2.2 `SplitButtonLayout`
- **Purpose:** Pairs a primary default action (`leadingButton`, e.g., *Save*, *Reply*, *Share*) with an adjacent dropdown menu trigger (`trailingButton`, e.g., chevron revealing *Save as…*, *Reply all*) (`.corpus/m3-expressive/pages/components/split-button.md`).
- **Tokens & Geometry:**
  - **5 Size Tiers:** `xsmall` (`32dp` height, `22dp` trailing icon), `small` (`40dp` height, `22dp` icon), `medium` (`56dp` height, `26dp` icon), `large` (`96dp` height, `38dp` icon), `xlarge` (`136dp` height, `50dp` icon).
  - **Gap & Inner Corner Morph:** `between-space = 2dp` (`space25`) across all sizes; inner corners start at `extraSmall` (`4dp`) on `xsmall`/`small`/`medium` (`8dp` on `large`, `12dp` on `xlarge`) and expand (`small` -> `medium` -> `largeIncreased`) on hover/press.
- **Compose Signature:**
  ```kotlin
  @Composable fun SplitButtonLayout(
      leadingButton: @Composable () -> Unit,
      trailingButton: @Composable () -> Unit,
      modifier: Modifier = Modifier,
      spacing: Dp = SplitButtonDefaults.Spacing,
  )
  ```
- **Historical Rename Trap:** Earlier alpha pins (`1.5.0-alpha25`) experimented with `SplitButton`; in both `1.5.0-rc01` and CMP `1.13.0-rc01`, the canonical layout composable is **`SplitButtonLayout`** (`.corpus/compose-maven-api/pages/expressive-api-reference.md:174-183`).
- **When to Use vs. Avoid:** Use when one action represents 80%+ of invocations and 2–5 secondary variants exist. Avoid when all options are equally likely (use a menu or `ButtonGroup` instead).

### 2.3 `ToggleButton`, `FilledTonalToggleButton` & `IconToggleButton`
- **Purpose:** Stateful binary switches presented as buttons (mute, bookmark, sort-ascending, filter toggles) where selected vs. unselected state morphs **both container color and shape** (e.g., pill ↔ rounded-rectangle via `ToggleButtonShapes` / `IconToggleButtonShapes`) (`.corpus/compose-maven-api/pages/expressive-api-reference.md:205-271`).
- **Compose Pattern:** Prefer `ToggleButton` / `FilledTonalToggleButton` with `ToggleButtonDefaults.tonalToggleButtonColors()` over manually branching `IconButton` tints—the component manages contrast, checked shape morphs, and accessibility `Role.Checkbox` / `toggleable` semantics automatically.

### 2.4 `FloatingActionButtonMenu` & `ToggleFloatingActionButton`
- **Purpose:** Replaces the M2 "speed dial" FAB pattern with a first-class animated menu: tapping `ToggleFloatingActionButton` morphs the FAB (`56dp` container, `20dp` close icon) and fans out `FloatingActionButtonMenuItem` rows (`56dp` height, `24dp` icon) (`.corpus/m3-expressive/pages/components/fab-menu.md:160-164`).
- **Compose Signature:**
  ```kotlin
  @Composable fun FloatingActionButtonMenu(
      expanded: Boolean,
      button: @Composable () -> Unit, // host ToggleFloatingActionButton here
      modifier: Modifier = Modifier,
      horizontalAlignment: Alignment.Horizontal = Alignment.End,
      content: @Composable FloatingActionButtonMenuScope.() -> Unit,
  )
  ```
- **When to Use vs. Avoid:** Use for 2–6 creation/launch sub-actions tied to a single primary FAB concept (*New Note*, *Scan Document*, *Voice Memo*). Avoid when actions operate on selected list items (use `HorizontalFloatingToolbar` or contextual app bar) or when > 6 items are needed (use a modal sheet).

### 2.5 `HorizontalFloatingToolbar` & `VerticalFloatingToolbar`
- **Purpose:** Replaces the M3 baseline `BottomAppBar` for floating in-context action bars (`64dp` height horizontal / `64dp` width vertical, `16dp` screen edge clearance, optional adjacent `56dp` or medium `80dp` FAB) (`.corpus/m3-expressive/pages/components/toolbars.md:200-210`).
- **Compose Signature:**
  ```kotlin
  @Composable fun HorizontalFloatingToolbar(
      expanded: Boolean,
      floatingActionButton: @Composable () -> Unit,
      modifier: Modifier = Modifier,
      colors: FloatingToolbarColors = FloatingToolbarDefaults.standardFloatingToolbarColors(),
      contentPadding: PaddingValues = FloatingToolbarDefaults.ContentPadding,
      scrollBehavior: FloatingToolbarScrollBehavior? = null,
      shape: Shape = FloatingToolbarDefaults.ContainerShape,
      floatingActionButtonPosition: FloatingToolbarHorizontalFabPosition = ...,
      animationSpec: FiniteAnimationSpec<Float> = FloatingToolbarDefaults.animationSpec(),
      expandedShadowElevation: Dp = FloatingToolbarDefaults.ContainerExpandedElevationWithFab,
      collapsedShadowElevation: Dp = FloatingToolbarDefaults.ContainerCollapsedElevationWithFab,
      content: @Composable RowScope.() -> Unit,
  )
  ```
- **When to Use vs. Avoid:** Use `HorizontalFloatingToolbar` for page-scoped contextual actions (media/editor formatting, multi-select actions) that float above scrolling content and optionally collapse via `FloatingToolbarDefaults.exitAlwaysScrollBehavior(...)`. **Never** use a floating toolbar for top-level app navigation (use `ShortNavigationBar` or `WideNavigationRail`), never display a floating toolbar alongside a `ShortNavigationBar`, and never duplicate a FAB or inline bar action across multiple visible anchors on one screen (see [navigation-and-shells.md](navigation-and-shells.md#5-single-canonical-entry-point--anti-duplication-rules-no-duplicate-visual-anchors-on-one-screen)).

---

## 3. Expressive Loading & Progress Indicators

### 3.1 `LoadingIndicator` & `ContainedLoadingIndicator` (`@ExperimentalMaterial3ExpressiveApi`)
- **Purpose:** Morphs continuously through a sequence of `MaterialShapes` `RoundedPolygon` forms (`LoadingIndicatorDefaults.IndeterminateIndicatorPolygons`) for **indeterminate waits** where duration/percentage is unknown (`.corpus/m3-expressive/pages/components/loading-indicator.md`).
- **Tokens & Geometry:** Container `48dp × 48dp`, active morphing polygon `38dp` (`md.comp.loading-indicator.*`), also available in `PullToRefreshDefaults.LoadingIndicator(...)` (`.corpus/m3-expressive/pages/components/loading-indicator.md:233-235`).
- **Critical Usage Guardrail:**
  - **Do NOT use `LoadingIndicator` alongside a determinate progress bar** (e.g., on a download/extraction card that already displays a `LinearProgressIndicator`), and avoid displaying it for sub-`200ms` transitions (wait `200ms` before showing to avoid flicker). When frozen by `MotionDurationScale = 0f` or static screenshots, an intermediate morph frame looks like a broken blob unless replaced by a static icon when `reduced == true`.
  - **Compose Opt-In:** Both `LoadingIndicator` and `ContainedLoadingIndicator` remain `@ExperimentalMaterial3ExpressiveApi` in `1.5.0-rc01` and `1.13.0-rc01`.

### 3.2 `LinearWavyProgressIndicator` & `CircularWavyProgressIndicator`
- **Purpose:** Determinate and indeterminate progress indicators with expressive sinusoidal wave geometry (`amplitude`, `wavelength`, `waveSpeed`) and an explicit `4dp` `stopIndicator` dot on determinate linear tracks (`.corpus/m3-expressive/pages/components/progress-indicators.md:260-269`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:430-472`).
- **Tokens:** Linear height `4dp` (standard) / `8dp` (`thick`) / `10dp` (`with-wave`) / `14dp` (`thick.with-wave`); Circular size `40dp` (standard) / `52dp` (`thick`) / `48dp` (`with-wave`).
- **When to Use vs. Avoid:** Use wavy indicators for media playback progress, active foreground transfers, or expressive onboarding steps; use flat `LinearProgressIndicator` for high-density multi-row tables (e.g., transfer task lists with 20+ concurrent rows) where animated sine waves create visual noise.

---

## 4. Flexible App Bars, Navigation Rails & Bars

### 4.1 `MediumFlexibleTopAppBar` & `LargeFlexibleTopAppBar`
- **Purpose:** Graduated M3E replacements for legacy `MediumTopAppBar` / `LargeTopAppBar`, adding a dedicated `subtitle` slot, `titleHorizontalAlignment`, and tighter expressive heights (`.corpus/compose-maven-api/pages/material3-token-constants.md:14-53`, `expressive-api-reference.md:474-494`):
  - **Small:** `64dp` (`TitleLarge`, subtitle `LabelMedium`).
  - **Medium Flexible:** `112dp` (`136dp` with subtitle; `HeadlineMedium` title, `LabelLarge` subtitle).
  - **Large Flexible:** `120dp` (`152dp` with subtitle; `DisplaySmall` title, `TitleMedium` subtitle).
- **Subtitle Discipline:** Use `subtitle` strictly for passive parent/context info (e.g., item count or breadcrumb)—never cram interactive dropdowns into the subtitle slot where users mistake them for the current path.
- **Action Overflow:** Pair top bars with `AppBarRow(maxItemCount = ...)` / `AppBarColumn(...)` (or custom `Layout`-based `AdaptiveBar`) so trailing actions never crush the title on narrow desktop windows.

### 4.2 `WideNavigationRail` (Collapsed `96dp` / `80dp` ↔ Expanded `220–360dp`)
- **Purpose:** Replaces the baseline `NavigationRail` (`80dp`) with an expandable rail (`WideNavigationRailState.expand()` / `collapse()` / `toggle()`) supporting vertical icon-over-label items when collapsed and horizontal full-width pill rows when expanded (`.corpus/m3-expressive/pages/components/navigation-rail.md:383-402`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:540-598`).
- **Exact Bytecode/Spec Tokens (`NavigationRailCollapsedTokens`):**
  - **Collapsed Width:** **`96dp`** (M3E default, giving longer vertical labels breathing room) or `80dp` (`narrow` variant).
  - **Expanded Width:** `220dp` min .. `360dp` max; item height `64dp` (`56dp` short), horizontal active indicator height `56dp`, vertical active indicator `56dp × 32dp`.
  - **Compact-Height Trap (`< 480dp`):** Explicitly select `WideNavigationRail` (collapsed) on landscape phones (`< 480dp` height) rather than letting `NavigationSuiteScaffold` choose a bottom bar.

### 4.3 `ShortNavigationBar`
- **Purpose:** Expressive compact bottom navigation bar reducing container height from M3 baseline `80dp` down to **`64dp`** (`md.comp.nav-bar.container.height = 64dp`) and supporting horizontal (`40dp` indicator height) as well as vertical (`56dp × 32dp`) item arrangements (`.corpus/m3-expressive/pages/components/navigation-bar.md:441-451`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:600-634`).
- **Limit:** Keep to 3–5 top-level destinations; never mix utility actions into `ShortNavigationBar`.

---

## 5. Segmented Lists, Carousels & Search

### 5.1 `SegmentedListItem` (`ListItemShapes`)
- **Purpose:** Expressive grouped list cards separated by a **`2dp` gap (`md.comp.list.segmented.gap`)** with rounded outer group corners and smaller (`4dp`–`8dp`) inner corners, replacing flat edge-to-edge lists divided by `HorizontalDivider` (`.corpus/m3-expressive/pages/components/lists.md:491-511`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:636-686`).
- **Four Graduated Overloads (`1.5.0-rc01` & `1.13.0-rc01`):**
  1. Static (no `onClick` — *missing in older CMP `1.12.0-alpha03` / `alpha22`!*)
  2. Clickable (`onClick`, `onLongClick`)
  3. Selectable (`selected`, `onClick`, `onLongClick`)
  4. Toggleable (`checked`, `onCheckedChange`, `onLongClick`)
- **Single-Item Group Corner Rule:** When a segmented group contains only **1 item**, that item is simultaneously first and last—apply full outer corner radii (`shapes.large` / `shapes.medium`) to all 4 corners, never `4dp` inner radii.
- **Container Height Tokens:** 1-line `56dp`, 2-line `72dp`, 3-line `88dp`; expressive leading/trailing icon size `20dp` (baseline `24dp`).

### 5.2 Carousel (`MultiBrowse`, `Uncontained`, `CenteredHero`)
- **Purpose:** Tactile horizontal media strips with dynamic item resizing near edges (`28dp` item corner radius, `8dp` item spacing, `16dp` leading/trailing padding, `40–56dp` dynamic small peek items) (`.corpus/m3-expressive/pages/components/carousel.md:524-545`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:688-719`).
- **Variants:** `HorizontalMultiBrowseCarousel` (mixed large/medium/small items), `HorizontalUncontainedCarousel` (uniform `itemWidth` flowing off-screen—best for variable aspect ratios or dense thumbnails), `HorizontalCenteredHeroCarousel` (centered focal card).
- **Accessibility & Desktop Rules:** Disable parallax and item-size morphing when Reduced Motion is active (`.corpus/m3-expressive/pages/components/carousel.md:623`), and wrap desktop horizontal carousels in a vertical-wheel-to-horizontal-scroll modifier (`verticalWheelScrollsRow`).

### 5.3 Expressive Search (`SearchBar`, `ExpandedFullScreenSearchBar`, `ExpandedDockedSearchBar`)
- **Purpose:** Contained `56dp`-tall search pill (`360dp..720dp` width, `30dp` avatar inside `48dp` target) expanding cleanly into either a full-screen overlay (`Compact` / `< 600dp` width) or a docked floating card (`Medium+` / `360..720dp` width, height `240dp .. 2/3 screen`, `2dp` bar-to-results gap) (`.corpus/m3-expressive/pages/components/search.md:100-140`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:721-754`).
- **API Status:** `SearchBar` still carries `@ExperimentalMaterial3Api`, while `ExpandedFullScreenSearchBar` and `ExpandedDockedSearchBar` (taking `SearchBarState`) are graduated stable in `1.5.0-rc01` and `1.13.0-rc01`.
- **Touch Exit Rule:** Always expose an explicit trailing **Clear / Cancel** button inside active search bars so touch-only users without a physical `Esc` key can clear and exit search effortlessly.

---

## Sources & Cross-References
- `manifests/api/material3-expressive-surface.json` & `.corpus/compose-maven-api/pages/expressive-api-reference.md`, `material3-token-constants.md`, `parity-diff.md`
- `manifests/tokens/m3-expressive-tokens.json`
- `.corpus/m3-expressive/pages/components/{button-groups,split-button,buttons,fab-menu,toolbars,loading-indicator,progress-indicators,app-bars,navigation-rail,navigation-bar,lists,carousel,search}.md`
