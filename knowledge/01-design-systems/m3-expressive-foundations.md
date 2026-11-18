# Material 3 Expressive Foundations: Tokens, Color Science, Shapes, Typography & Containment

> **Scope:** Authoritative specification of Material 3 Expressive (`M3E`) design foundations, exact system tokens (`manifests/tokens/m3-expressive-tokens.json`), verified Compose API entry points (`manifests/api/material3-expressive-surface.json`), and practical multiplatform CJK, pure-black OLED, and containment patterns.

---

## 1. Research Rationale & Scope of M3 Expressive

Material 3 Expressive is not a breaking "Material 4"; it is an additive evolution of Material 3 introduced in May 2025 (and expanded with Expressive layout, spacing, lists, and menus at Google I/O 2026) grounded in **46 user research studies with 18,000+ participants** using eye-tracking, usability testing, and sentiment experiments (`.corpus/m3-expressive/pages/building-with-m3-expressive.md:33-42`, `.corpus/google-design/pages/articles/expressive-material-design-google-research.md:31-97`).

### Verified Quantitative Research Findings
- **Visual Fixation Speed:** Eye-tracking across 10 apps showed users located key UI actions **up to 4x faster** in M3 Expressive screens when size, color contrast, and containment emphasized the primary action (e.g., an enlarged, secondary-colored **Send** button positioned above the keyboard rather than buried in a small top-bar icon row) (`.corpus/google-design/pages/articles/expressive-material-design-google-research.md:79-90`).
- **Age Equity:** M3 Expressive erased typical age-related visual search latency gaps, bringing **45+ age cohorts to parity** with younger users in locating primary targets (`.corpus/google-design/pages/articles/expressive-material-design-google-research.md:91-96`).
- **Preference & Brand Perception:** Expressive screens achieved up to **87% preference** among 18–24-year-olds (net-positive across all age groups) and measurable gains in perceived **modernity (+34%)**, **subculture relevance (+32%)**, and **rebelliousness (+30%)** (`.corpus/google-design/pages/articles/expressive-material-design-google-research.md:53-70`).
- **Usability Guardrail:** Breaking familiar interaction paradigms (such as replacing a structured playlist list with unlabeled scattered album art, or removing text labels from email actions) reduced usability scores despite higher aesthetic novelty. Expressive tactics must reinforce—never obscure—canonical affordances (`.corpus/google-design/pages/articles/expressive-material-design-google-research.md:101-111`).

### The Five Expressive Design Tactics
1. **Use a variety of shapes** (mix round and square silhouettes for visual tension; reserve abstract shapes for decorative/hero moments).
2. **Apply rich and nuanced colors** (use tonal hierarchy and primary/secondary/tertiary contrast to prioritize actions).
3. **Guide attention with typography** (pair `*Emphasized` heavier weights with baseline weights while keeping size/line-height stable).
4. **Contain content for emphasis** (group related elements using surface tone shifts and spacing rather than divider lines).
5. **Add fluid and natural motion** (physics-based spatial and effects springs).
*(Source: `.corpus/m3-expressive/pages/building-with-m3-expressive.md:132-185`)*

---

## 2. `MaterialExpressiveTheme` vs. `MaterialTheme` (Compose Runtime Behavior)

In AndroidX `material3` `1.5.0-rc01` and JetBrains CMP `1.13.0-rc01`, `MaterialExpressiveTheme` is **graduated (no `@OptIn` required)** and shares an identical signature across both targets (`manifests/api/material3-expressive-surface.json`, `.corpus/compose-maven-api/pages/expressive-api-reference.md:14-23`):

```kotlin
@Composable
fun MaterialExpressiveTheme(
    colorScheme: ColorScheme = ...,
    motionScheme: MotionScheme = MotionScheme.expressive(),
    shapes: Shapes = ...,
    typography: Typography = ...,
    content: @Composable () -> Unit,
)
```

### Why `MaterialExpressiveTheme` Matters Beyond Aesthetics
1. **Activates Expressive Component Defaults:** `MaterialExpressiveTheme` populates `LocalUsingExpressiveTheme`, causing Material 3 components (buttons, navigation items, menus, toolbars) to automatically select expressive shapes and behaviors without passing manual `shapes = ...` at every call site.
2. **Enforces a Unified `MotionScheme`:** Provides `MaterialTheme.motionScheme` (`MotionScheme.expressive()` or `MotionScheme.standard()`) into `CompositionLocal`, replacing ad-hoc `tween()` / `spring()` literals. Note that `MaterialTheme` in 1.5.0-rc01 / 1.13.0-rc01 also exposes a 5-parameter overload accepting `motionScheme` (`.corpus/compose-maven-api/pages/expressive-api-reference.md:40`), while `MaterialExpressiveTheme` defaults to expressive semantics.
3. **Content Color Caveat:** Neither `MaterialTheme` nor `MaterialExpressiveTheme` sets `LocalContentColor` (whose default is `Color.Black`). Always wrap root content in `Surface(color = MaterialTheme.colorScheme.background)` (or `Scaffold`) so dark themes set `LocalContentColor = onSurface`.

---

## 3. Color System, HCT Science & Surface Container Hierarchy

### 3.1 HCT Color Space & Spec Versions (`2021` vs. `2025` vs. `2026`)
Material Color Utilities (MCU) computes tonal palettes in **HCT (Hue, Chroma, Tone)**, combining **CAM16-JCH** perceptual hue/chroma with **CIE L\*a\*b\*** luminance (`Tone` 0–100) so any two tones with a delta >= 40–50 guarantee accessible contrast regardless of hue (`.corpus/google-design/pages/material-color-utilities/concepts__color_spaces.md:80-90`, `concepts__contrast_for_accessibility.md`).

- **Spec 2021 (`ColorSpec2021`):** Original Material You static tone pairings (`neutral98` light / `neutral6` dark surface, `primary40` / `primary80`).
- **Spec 2025 (`ColorSpec2025`):** M3 Expressive color specification refining `SchemeExpressive`, `SchemeTonalSpot`, `Platform` awareness (`PHONE` vs. `WATCH`), higher-contrast surface containers (`surface = tone 4.0` in dark phone mode, vibrant chroma multipliers), and three contrast curves: **Standard**, **Medium**, and **High** (`.corpus/google-design/pages/material-color-utilities/kotlin__dynamiccolor__ColorSpec2025.kt.md:46-120`, `.corpus/m3-expressive/pages/styles/color/system.md:76-90`).
- **Spec 2026 (`ColorSpec2026`):** Extends `ColorSpec2025` with `findBestToneForChroma` (`tMaxC`/`tMinC`) and expanded `ContrastCurve` ladders (`1.5`..`11.0` -> `21.0`) (`.corpus/google-design/pages/material-color-utilities/kotlin__dynamiccolor__ColorSpec2026.kt.md:38-90`).

> **Multiplatform Alignment Warning:** If your app embeds a static fallback palette alongside Android 12+ `dynamicLightColorScheme()` / `dynamicDarkColorScheme()` and an Android XML splash background (`res/values/colors.xml`), generate the fallback palette with the **exact same MCU spec version** (`spec_version="2021"` when targeting OS/Compose `dynamic*ColorScheme()` built on 2021 tones) so the splash screen and dynamic fallback do not shift hue/tone on launch.

### 3.2 Complete Color Role & Surface Container Hierarchy
M3 defines **26 standard roles** plus **add-on fixed & bright/dim surface roles** (50 role tokens in `manifests/tokens/m3-expressive-tokens.json`, `.corpus/m3-expressive/pages/styles/color/roles.md:15, 156-425`):

| Role Group | Compose `ColorScheme` Properties | Tone (Light / Dark) | Semantic Usage & Pairing Rules |
| --- | --- | --- | --- |
| **Primary** | `primary`, `onPrimary`, `primaryContainer`, `onPrimaryContainer` | `40`/`100`, `90`/`30` (L)<br>`80`/`20`, `30`/`90` (D) | Highest-emphasis actions (Filled Button, FAB, active switches/badges). Always pair `X` with `onX`. |
| **Secondary** | `secondary`, `onSecondary`, `secondaryContainer`, `onSecondaryContainer` | `40`/`100`, `90`/`30` (L)<br>`80`/`20`, `30`/`90` (D) | Medium-emphasis & recessive fills (Tonal Button, Filter Chips, Nav Bar/Rail active pill). |
| **Tertiary** | `tertiary`, `onTertiary`, `tertiaryContainer`, `onTertiaryContainer` | `40`/`100`, `90`/`30` (L)<br>`80`/`20`, `30`/`90` (D) | Contrasting accents, secondary highlights, input emphasis, notification badges. |
| **Error (Static)** | `error`, `onError`, `errorContainer`, `onErrorContainer` | `40`/`100`, `90`/`30` (L)<br>`80`/`20`, `30`/`90` (D) | Urgent error states & destructive actions (never dynamically re-hued by wallpaper). |
| **Surface Base** | `surface`, `onSurface`, `onSurfaceVariant`, `surfaceDim`, `surfaceBright` | `N98`/`N10`/`NV30`/`N87`/`N98` (L)<br>`N6`/`N90`/`NV80`/`N6`/`N24` (D) | Base canvas (`surface`). `surfaceDim`/`surfaceBright` preserve relative brightness across themes. |
| **Surface Containers (5-tier)** | `surfaceContainerLowest`<br>`surfaceContainerLow`<br>`surfaceContainer`<br>`surfaceContainerHigh`<br>`surfaceContainerHighest` | `N100` / `N4`<br>`N96` / `N10`<br>`N94` / `N12`<br>`N92` / `N17`<br>`N90` / `N22` | **Canonical containment ladder** replacing M2 elevation overlays and `1.dp` dividers. `Low` = elevated cards/sheets; `Container` = nav bars/toolbars; `High` = FAB/dialogs; `Highest` = switches/chips/nested blocks. |
| **Surface Variant (Restricted!)** | `surfaceVariant` | `NV90` (L) / `NV30` (D) | **Legacy/low-emphasis pairing token for `onSurfaceVariant`.** Do **not** use `surfaceVariant` as a general container fill—in dark theme (`NV30`, `#45464F`) it jumps abruptly brighter than `surfaceContainerHighest` (`N22`). |
| **Outline & Inverse** | `outline`, `outlineVariant`, `inverseSurface`, `inverseOnSurface`, `inversePrimary` | `NV50`/`NV80` (L)<br>`NV60`/`NV30` (D) | `outline` (3:1 boundary: text fields); `outlineVariant` (decorative/hairlines). `inverse*` for Snackbars. |
| **Fixed Accents** | `{primary,secondary,tertiary}Fixed`, `*FixedDim`, `on*Fixed`, `on*FixedVariant` | Same tone in Light & Dark | Elements that must keep identical tone regardless of dark/light mode (use cautiously to avoid contrast loss). |

### 3.3 Applied Color Extensions: Pure-Black Oklab Ladder & Fixed Media Colors
*(Composable multiplatform patterns layered cleanly onto M3E tokens)*
1. **Oklab Pure-Black Surface Interpolation (`ColorScheme.toPureBlack()`):**
   - Naively shifting M3's 5 surface container slots down by one slot collapses `surfaceContainerLow` (`N10`) into `#000000` and compresses `High` (`N17`) and `Highest` (`N22`) into near-identical dark grays.
   - Instead, pin `background`, `surface`, `surfaceDim`, and `surfaceContainerLowest` to `Color.Black` (`#000000`), and re-space the remaining 4 tiers using Compose's `lerp()` (Oklab color-space interpolation) to preserve palette hue while maintaining crisp luminance separation:
     - `surfaceContainerLow = lerp(surface, surfaceContainerLow, 0.2f)`
     - `surfaceContainer = lerp(surfaceContainerLow, surfaceContainer, 0.35f)`
     - `surfaceContainerHigh = lerp(surfaceContainer, surfaceContainerHigh, 0.65f)`
     - `surfaceContainerHighest = lerp(surfaceContainerHigh, surfaceContainerHighest, 0.75f)`
2. **Fixed Non-Inverting Colors (`FixedColors`):**
   - **Rule:** Never invert colors that are either **machine-readable** (e.g., QR code `#FFFFFF` quiet-zone substrate; dark-mode inversion breaks scanners) or **composited over uncontrolled media** (video HUD icons `#FFFFFF`, `ScrimOnMedia = 0x8C000000` 55% black for > 4.5:1 text over bright thumbnails, `ScrimOnLyrics = 0xB8000000` 72% black).
   - **Semantic Fixed Accents:** For inline `@mentions` or timestamps that have no M3 `ColorScheme` slot, derive light/dark HCT pairs (e.g., HCT Tone `45` on light surfaces, Tone `65` on dark surfaces) and expose via a `CompositionLocal` (`LocalMentionColor`), never `color.copy(alpha = 0.15f)` on arbitrary backgrounds.

---

## 4. 10-Step `Shapes` Scale, Optical Roundness & 35 Expressive Shapes

M3 Expressive replaced M2's 3-level container-size scale with a **10-step roundedness scale** (`manifests/tokens/m3-expressive-tokens.json`, `.corpus/m3-expressive/pages/styles/shape.md:145-196`). In `material3` `1.5.0-rc01` / CMP `1.13.0-rc01`, all 8 `CornerBasedShape` properties on `Shapes` are graduated (stable), while `MaterialShapes` (the 35-shape morph library) still requires `@ExperimentalMaterial3ExpressiveApi` (`manifests/api/material3-expressive-surface.json`).

### 4.1 10-Step Shape Scale Table

| Scale Step | Design Token (`md.sys.shape.*`) | Compose API (`MaterialTheme.shapes.*`) | Radius Value | Canonical M3E / Production Usage |
| --- | --- | --- | --- | --- |
| 1 | `corner-value.none` | `RectangleShape` / `0.dp` | `0dp` | Full-bleed edge-to-edge panes, snapped/abutting inner edges |
| 2 | `corner-value.extra-small` | `shapes.extraSmall` | `4dp` | Menus, snackbars, badges, ID pills, inner corners of segmented items |
| 3 | `corner-value.small` | `shapes.small` | `8dp` | Chips, compact list thumbnails, nested attachment sub-blocks |
| 4 | `corner-value.medium` | `shapes.medium` | `12dp` | Cards, text fields, dialogs (desktop compact), code/quote blocks |
| 5 | `corner-value.large` | `shapes.large` | `16dp` | Navigation drawers, modal side sheets, desktop island frames, floating panels |
| 6 | `corner-value.large-increased` *(New)* | `shapes.largeIncreased` | `20dp` | Expressive feed/social cards, pill multiline composers, assistant cards |
| 7 | `corner-value.extra-large` | `shapes.extraLarge` | `28dp` | Bottom sheets (`top` corners), M3 standard dialogs, hero identity cards |
| 8 | `corner-value.extra-large-increased` *(New)* | `shapes.extraLargeIncreased` | `32dp` | Large hero containers, wide showcase cards |
| 9 | `corner-value.extra-extra-large` *(New)* | `shapes.extraExtraLarge` | `48dp` | Full-focus hero media artwork (e.g., audio/listen-mode album cover) |
| 10 | `corner.full` | `CircleShape` | `50%` (pill/circle) | Buttons, FABs, toggle buttons, search pills, filter tags |

### 4.2 Shape Rules: Density, Asymmetry & Optical Nested Roundness
- **Density Drives Radius, Not Just Physical Size:** In high-density multi-column feeds and lists, prefer `small` (`8dp`) to `large` (`16dp`); reserve `extraLarge` (`28dp`) and `extraExtraLarge` (`48dp`) for focal hero containers.
- **Asymmetric Inner Corners:** Connected groups (button groups, split buttons, segmented lists, menus) pair large outer corners (`large` / `full`) with tight inner corners (`extraSmall` `4dp` or `small` `8dp`) to visually bind related actions (`.corpus/m3-expressive/pages/styles/shape.md:188-196`).
- **Optical Nested Roundness Formula:** When nesting a rounded child container inside a padded parent container, avoid mismatched concentric arcs by applying:
  $$\text{innerRadius} = \max(4\,\text{dp},\; \text{outerRadius} - \text{padding})$$
  For example, a `16.dp` (`shapes.large`) island card with `8.dp` inner padding uses `8.dp` (`shapes.small`) for nested sub-cards; a `20.dp` card with `8.dp` padding uses `12.dp` (`shapes.medium`).
- **35-Shape Morph Library (`MaterialShapes`):** Exposed via `androidx.compose.material3.MaterialShapes` (`@ExperimentalMaterial3ExpressiveApi`), providing `RoundedPolygon` primitives (`Circle`, `Pill`, `Square`, `Clover4Leaf`, `Clover8Leaf`, `Cookie4Sided`, `Cookie12Sided`, etc.) for `LoadingIndicator` and interactive control morphs (`.corpus/m3-expressive/pages/styles/shape.md:42, 60-87`).

### 4.3 Physical Intuition & Anti-Gimmick Shape Restraint
- **Preserve Physical & Skeuomorphic Metaphors:** Elements anchored in real-world physical metaphors—spinning vinyl discs, analog/mechanical countdown dials, stacked folder sleeves, desktop window islands—**must retain their intuitive geometry** (`CircleShape` for records/dials, stable `shapes.large` corners for window frames). **Never** warp content artwork or physical metaphors into `MaterialShapes` polygons (`Cookie12Sided`, `Clover4Leaf`) purely for novelty; M3's own user studies confirm that breaking familiar visual metaphors degrades usability (`.corpus/google-design/pages/articles/expressive-material-design-google-research.md:101-111`). Deliver expressive life on physical objects through **causal physics** (angular velocity spin-up/damped spin-down inertia on play/pause, subtle `Canvas` specular sheen, or tactile press deflection).
- **Reserve `MaterialShapes` Morphing for Abstract Controls:** Morphing between silhouettes (`Circle` ↔ `Square` / `Pill` / rounded rectangles) belongs strictly on abstract interactive controls responding to discrete state changes (play/pause morph buttons, checked `ToggleButton` / `IconToggleButton` pills, `FloatingActionButtonMenu`, and active `LoadingIndicator` waits)—never on content thumbnails, cover art, or empty-state decorative illustrations. See [motion-and-physics.md](motion-and-physics.md#5-causal-motion-physical-intuition--anti-gimmick-restraint).

---

## 5. 30-Step Typography (`15 Baseline + 15 *Emphasized`) & CJK Engineering

M3 Expressive doubles the Material type scale from 15 to **30 styles**: 15 baseline styles plus 15 `*Emphasized` counterparts (`.corpus/m3-expressive/pages/styles/typography.md:21, 63-90`, `manifests/tokens/m3-expressive-tokens.json`). **All 30 `Typography` properties are graduated (stable)** in `material3` `1.5.0-rc01` and CMP `1.13.0-rc01`.

### 5.1 Complete 30-Step Type Scale Token Table

| Role | Size | Line Height | Baseline Weight (`tracking`) | Emphasized Weight (`tracking`) | Compose Properties (`Typography.*`) |
| --- | --- | --- | --- | --- | --- |
| `display-large` | `57sp` | `64sp` | `400` Normal (`0`) | `500` Medium (`0`) | `displayLarge` / `displayLargeEmphasized` |
| `display-medium` | `45sp` | `52sp` | `400` Normal (`0`) | `500` Medium (`0`) | `displayMedium` / `displayMediumEmphasized` |
| `display-small` | `36sp` | `44sp` | `400` Normal (`0`) | `500` Medium (`0`) | `displaySmall` / `displaySmallEmphasized` |
| `headline-large` | `32sp` | `40sp` | `400` Normal (`0`) | `500` Medium (`0`) | `headlineLarge` / `headlineLargeEmphasized` |
| `headline-medium` | `28sp` | `36sp` | `400` Normal (`0`) | `500` Medium (`0`) | `headlineMedium` / `headlineMediumEmphasized` |
| `headline-small` | `24sp` | `32sp` | `400` Normal (`0`) | `500` Medium (`0`) | `headlineSmall` / `headlineSmallEmphasized` |
| `title-large` | `22sp` | `28sp` | `400` Normal (`0`) | `500` Medium (`0`) | `titleLarge` / `titleLargeEmphasized` |
| `title-medium` | `16sp` | `24sp` | `500` Medium (`0`) | `700` Bold (`0`) | `titleMedium` / `titleMediumEmphasized` |
| `title-small` | `14sp` | `20sp` | `500` Medium (`0`) | `700` Bold (`0`) | `titleSmall` / `titleSmallEmphasized` |
| `body-large` | `16sp` | `24sp` | `400` Normal (`0`) | `500` Medium (`0`) | `bodyLarge` / `bodyLargeEmphasized` |
| `body-medium` | `14sp` | `20sp` | `400` Normal (`0`) | `500` Medium (`0`) | `bodyMedium` / `bodyMediumEmphasized` |
| `body-small` | `12sp` | `16sp` | `400` Normal (`0.1pt`) | `500` Medium (`0`) | `bodySmall` / `bodySmallEmphasized` |
| `label-large` | `14sp` | `20sp` | `500` Medium (`0`) | `700` Bold (`0`) | `labelLarge` / `labelLargeEmphasized` |
| `label-medium` | `12sp` | `16sp` | `500` Medium (`0.1pt`) | `700` Bold (`0.1pt`) | `labelMedium` / `labelMediumEmphasized` |
| `label-small` | `11sp` | `16sp` | `500` Medium (`0.1pt`) | `700` Bold (`0.1pt`) | `labelSmall` / `labelSmallEmphasized` |

*Note: M3 Expressive variable specs use `Google Sans` / `Google Sans Text` / `Google Sans Flex` (`opsz`, `wght`, `ROND=100` for emphasized variable styles); fallback static Android typefaces use Roboto + Noto Sans CJK (`.corpus/m3-expressive/pages/styles/typography.md:125-199`, `manifests/tokens/m3-expressive-tokens.json`).*

### 5.2 Crucial Invariant: Never Change Font Sizes—Change Weight & Line Height Safely
- **Keep M3 Font Sizes Intact:** Material 3 components compute intrinsic button heights, list row heights, and tab minimum widths from `Typography` font sizes. Emphasized styles intentionally keep the **exact same `fontSize` and `lineHeight`** as their baseline peers so switching between `bodyMedium` and `bodyMediumEmphasized` never causes list rows to jump vertically.
- **Language Script Height Support (Aug 2026 M3 Update):** M3's typography spec formally recognizes that non-Latin scripts require taller line-height buckets (*small, medium, large, extra large*) (`.corpus/m3-expressive/pages/styles/typography.md:45-57`).

### 5.3 CJK & Tabular Numerals Playbook
When configuring `Typography` for Chinese/Japanese/Korean + Latin mixed UIs:
1. **Zero Letter Spacing on Prose/Titles:** Baseline Roboto specs add `+0.25sp`..`+0.5sp` tracking for Latin lowercase legibility. Full-width CJK ideographs break apart visually if tracked apart—set `letterSpacing = 0.sp` across `headline*`, `title*`, and `body*`, keeping slight positive tracking (`0.1.sp` / `0.5.sp`) only on `label*` styles that primarily carry short ASCII codes or durations (`1080P`, `12:34`).
2. **CJK Line-Height Compensation on Dense Slots:** Bump `bodyMedium` (`14/22sp`), `bodySmall` (`12/18sp`), and `titleSmall` (`14/22sp`) by `+2sp` line height so dense multi-line ideographs breathe, and apply larger line heights locally to long-form prose (`14/24sp` comments, `16/26sp` feed posts, `16/28sp` articles).
3. **Eliminate Latin Font Padding Offset:** Set `PlatformTextStyle(includeFontPadding = false)` and `LineHeightStyle(alignment = LineHeightStyle.Alignment.Center, trim = LineHeightStyle.Trim.None)` on **all 30 styles** (baseline + `*Emphasized`) so CJK glyphs center cleanly next to leading icons without sitting high in the em-box.
4. **Prevent Synthetic Bold Smear on `*Emphasized`:** Upstream M3 sets `title*Emphasized` and `label*Emphasized` to `700` (Bold). On CJK fonts lacking a native `700` weight or on dense screens, `SemiBold (600)` for `display*`/`headline*`/`title*`/`label*` and `Medium (500)` for `body*` cleanly separate primary titles from `onSurfaceVariant` metadata without filling in dense CJK strokes. **You must override all 15 `*Emphasized` slots in `Typography(...)`**, or emphasized text silently falls back to default Roboto tracking.
5. **Mandatory Tabular Numerals (`tnum`):** Provide a `val TextStyle.tabular: TextStyle get() = copy(fontFeatureSettings = "tnum")` extension and apply it to every live counter, video duration badge, `X / N` queue index, clock (`HH:mm`), battery percentage, transfer rate/ETA, and monospace/ID pill to eliminate horizontal jitter as digits update.

---

## 6. Containment Without Dividers (Elevation & Spacing System)

Material 3 Expressive replaces structural `1.dp` hairline dividers (`HorizontalDivider` / `VerticalDivider`) with **Containment**: combining tonal surface hierarchy, spacing tokens, and scroll-triggered container shifts (`.corpus/m3-expressive/pages/styles/elevation.md:47-149`, `building-with-m3-expressive.md:168-178`).

### 6.1 Elevation Levels & Tonal Separation
M3 restricts elevation to **6 discrete levels** (`manifests/tokens/m3-expressive-tokens.json`):
- `level0` (`0dp`): Flat background/inline surfaces
- `level1` (`1dp`): Elevated cards, navigation rails (resting)
- `level2` (`3dp`): Navigation bars, scrolled app bars (`md.comp.app-bar.on-scroll.container.elevation = level2`, `color = surface-container`)
- `level3` (`6dp`): FABs, dialogs, search bars, menus
- `level4` (`8dp`): Hovered interactive elevated states (`resting + 1`)
- `level5` (`12dp`): Dragged states

### 6.2 Spacing System (`8dp` Grid)
M3's spacing scale (`.corpus/m3-expressive/pages/whats-new-at-io26.md:44-52`, `manifests/tokens/m3-expressive-tokens.json`) defines `space0` (`0dp`), `space25` (`2dp`), `space50` (`4dp`), `space75` (`6dp`), `space100` (`8dp`), `space125` (`10dp`), `space150` (`12dp`), `space200` (`16dp`), `space300` (`24dp`), `space400` (`32dp`), `space600` (`48dp`), `space700` (`56dp`), `space800` (`64dp`), `space900` (`72dp`).

### 6.3 The Zero-Divider Containment Playbook
Visual separation across clean M3 Expressive layouts relies strictly on three mechanisms instead of `HorizontalDivider` / `VerticalDivider`:
1. **Whitespace & Leading Anchors:** Repeated homogeneous rows (videos, comments, messages) separate naturally through consistent vertical padding (`8.dp`–`12.dp`) and leading avatars/thumbnails.
2. **Stepped Surface Containers:** Nesting increments the `surfaceContainer*` tier—for example, `surface` page background → `surfaceContainer` outer card (`shapes.largeIncreased` `20.dp`) → `surfaceContainerHigh` embedded media/quote block (`shapes.medium` `12.dp`) → `surfaceContainerHighest` nested forward block (`shapes.small` `8.dp`).
3. **Scroll-State Tinting:** Top bars sit flush (`surface`) at scroll offset 0 and transition smoothly to `surfaceContainer` once content scrolls beneath them—avoid `pinnedScrollBehavior` accumulating stale offsets across route or directory switches by driving bar tint directly from `listState.canScrollBackward`.
*(Exception: Menu section dividers—like separating destructive actions from properties in context menus—remain appropriate where grouping distinct command categories inside a single floating surface.)*

---

## Sources & Cross-References
- `manifests/tokens/m3-expressive-tokens.json` (`shapes`, `typography`, `motion_scheme`, `elevation`, `spacing`, `color`)
- `manifests/api/material3-expressive-surface.json` & `.corpus/compose-maven-api/pages/expressive-api-reference.md`
- `.corpus/m3-expressive/pages/building-with-m3-expressive.md`, `whats-new-at-io26.md`, `styles/color/roles.md`, `styles/color/system.md`, `styles/shape.md`, `styles/typography.md`, `styles/elevation.md`
- `.corpus/google-design/pages/articles/expressive-material-design-google-research.md`, `material-color-utilities/concepts__color_spaces.md`, `kotlin__dynamiccolor__ColorSpec2025.kt.md`, `kotlin__dynamiccolor__ColorSpec2026.kt.md`
