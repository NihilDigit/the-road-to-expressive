# Motion Physics, Screen Transitions & Reduced Motion Plumbing

> **Scope:** Authoritative specification of Material 3 Expressive's spring-based `MotionScheme`, its separation from easing-and-duration screen transitions, cross-platform timing differences across Android / iOS / Windows / macOS / Linux, and end-to-end `MotionDurationScale` / Reduced Motion plumbing in Compose Multiplatform.

---

## 1. Two-System Architecture: Physics Springs vs. Screen Transitions

A common error in M3 Expressive migrations is replacing *everything* with `MotionScheme` springs or keeping *everything* on `tween()`. M3 Expressive explicitly separates motion into **two distinct systems** (`.corpus/m3-expressive/pages/styles/motion/overview.md:31`, `easing-and-duration.md:25`, `transitions.md:25`):

1. **Component & In-Place Interactions → `MotionScheme` (Physics Springs):**
   - Controls position, size, corner morphing, expansion/collapse, color, and opacity on components (21 built-in Material Compose components consume `MaterialTheme.motionScheme` automatically).
   - Springs preserve velocity when interrupted or gesture-retargeted, and adapt naturally across screen sizes without hardcoding milliseconds (`.corpus/m3-expressive/pages/m3-expressive-motion-theming.md:128-142`).
2. **Full-Screen Navigation Transitions → Legacy Easing + Duration (`tween`):**
   - M3's `transitions.md` explicitly states: *"M3 transitions use the legacy easing and duration system."* Screen transitions must express directional asymmetry (exit faster than enter, or sequential fade-out then fade-in), which requires deterministic duration budgets (`ms`) rather than unbounded spring settling (`.corpus/m3-expressive/pages/styles/motion/transitions.md:25`).

---

## 2. `MotionScheme.expressive()` vs. `MotionScheme.standard()`

In AndroidX `material3` `1.5.0-rc01` and JetBrains CMP `1.13.0-beta02`, `MotionScheme` is **graduated (stable)** with identical APIs (`.corpus/compose-maven-api/pages/expressive-api-reference.md:43-57`):

```kotlin
// Top-level theme injection (MaterialExpressiveTheme defaults to expressive)
MaterialExpressiveTheme(
    motionScheme = MotionScheme.expressive(), // or MotionScheme.standard()
) { ... }

// Reading specs inside components
val spatialSpec = MaterialTheme.motionScheme.fastSpatialSpec<Float>()
val effectsSpec = MaterialTheme.motionScheme.defaultEffectsSpec<Color>()
```

### 2.1 Exact Spring Token Table (`manifests/tokens/m3-expressive-tokens.json`)

Every `MotionScheme` exposes **2 axes** (`spatial` vs. `effects`) × **3 speeds** (`fast`, `default`, `slow`):

| Scheme | Category | Speed | Damping Ratio ($\zeta$) | Stiffness ($k$) | Web Curve Equivalent (Duration) | Compose Accessor |
| --- | --- | --- | --- | --- | --- | --- |
| **Expressive** | **Spatial** *(overshoot bounce)* | `fast` | `0.6` | `800.0` | `(0.42, 1.67, 0.21, 0.90)` (`350ms`) | `fastSpatialSpec()` |
| **Expressive** | **Spatial** *(overshoot bounce)* | `default` | `0.8` | `380.0` | `(0.38, 1.21, 0.22, 1.00)` (`500ms`) | `defaultSpatialSpec()` |
| **Expressive** | **Spatial** *(overshoot bounce)* | `slow` | `0.8` | `200.0` | `(0.39, 1.29, 0.35, 0.98)` (`650ms`) | `slowSpatialSpec()` |
| **Expressive** | **Effects** *(critically damped, zero bounce)* | `fast` | `1.0` | `3800.0` | `(0.31, 0.94, 0.34, 1.00)` (`150ms`) | `fastEffectsSpec()` |
| **Expressive** | **Effects** *(critically damped, zero bounce)* | `default` | `1.0` | `1600.0` | `(0.34, 0.80, 0.34, 1.00)` (`200ms`) | `defaultEffectsSpec()` |
| **Expressive** | **Effects** *(critically damped, zero bounce)* | `slow` | `1.0` | `800.0` | `(0.34, 0.88, 0.34, 1.00)` (`300ms`) | `slowEffectsSpec()` |
| **Standard** | **Spatial** *(minimal/no bounce)* | `fast` | `0.9` | `1400.0` | `(0.27, 1.06, 0.18, 1.00)` (`350ms`) | `fastSpatialSpec()` |
| **Standard** | **Spatial** *(minimal/no bounce)* | `default` | `0.9` | `700.0` | `(0.27, 1.06, 0.18, 1.00)` (`500ms`) | `defaultSpatialSpec()` |
| **Standard** | **Spatial** *(minimal/no bounce)* | `slow` | `0.9` | `300.0` | `(0.27, 1.06, 0.18, 1.00)` (`750ms`) | `slowSpatialSpec()` |
| **Standard** | **Effects** *(critically damped, zero bounce)* | `fast` | `1.0` | `3800.0` | `(0.31, 0.94, 0.34, 1.00)` (`150ms`) | `fastEffectsSpec()` |
| **Standard** | **Effects** *(critically damped, zero bounce)* | `default` | `1.0` | `1600.0` | `(0.34, 0.80, 0.34, 1.00)` (`200ms`) | `defaultEffectsSpec()` |
| **Standard** | **Effects** *(critically damped, zero bounce)* | `slow` | `1.0` | `800.0` | `(0.34, 0.88, 0.34, 1.00)` (`300ms`) | `slowEffectsSpec()` |

*(Values verified from `manifests/tokens/m3-expressive-tokens.json` and `.corpus/m3-expressive/pages/styles/motion/overview.md:190-200`.)*

### 2.2 Strict Spatial vs. Effects Separation Rule
- **Spatial (`fastSpatialSpec`, `defaultSpatialSpec`, `slowSpatialSpec`):** Use **only** for `x`/`y` translation, rotation, scale, bounds/size, and `CornerSize` shape morphing.
  - `fast`: switches, checkboxes, buttons, card press micro-scale (`0.985f`).
  - `default`: bottom sheets, side sheets, expanded navigation rails, inline accordions.
  - `slow`: full-screen container expansions.
- **Effects (`fastEffectsSpec`, `defaultEffectsSpec`, `slowEffectsSpec`):** Use **only** for color, elevation tint, and alpha opacity. Because $\zeta = 1.0$ (critically damped), colors and opacities never overshoot into invalid alpha (`> 1f` / `< 0f`) or inverted hues (`.corpus/m3-expressive/pages/styles/motion/overview.md:90-118`).

### 2.3 Scoped Scheme Swapping (Subtree Overrides)
M3 explicitly encourages overriding `motionScheme` at subtree boundaries (`.corpus/m3-expressive/pages/styles/motion/overview.md:168-171`):
- **Media Player / Video HUD Rule:** Even if the outer app uses `MotionScheme.expressive()`, wrap video/live player overlays in a `PlayerTheme` with `MotionScheme.standard()`. Play/pause morphs, scrubbers, and HUD buttons overlaid directly on video must settle cleanly without bouncy overshoot that distracts from playback.
- **Desktop Context Menu Hit-Target Rule:** Never apply `0.8f -> 1.0f` spatial scale-up on desktop right-click/command menus. Because Compose's `graphicsLayer` scale transforms pointer hit-testing during animation, fast mouse clicks during a 200ms scale-in can mis-hit menu items. On desktop, override menu `MotionScheme` so spatial specs resolve to `snap()` and effects specs perform a crisp `80ms` fade-in.

---

## 3. Screen Transitions & Cross-Platform Motion Expectations

### 3.1 M3 Easing & Duration Transition Baseline
From `.corpus/m3-expressive/pages/styles/motion/easing-and-duration.md:31-38, 84-141` and `transitions.md:81-140`:

| Transition Pattern | Enter Spec | Exit Spec | Spatial Geometry / Notes |
| --- | --- | --- | --- |
| **Forward / Backward** *(Android default)* | `400ms` (`medium4`), `EmphasizedDecelerate` `(0.05, 0.7, 0.1, 1.0)` | `200ms` fade / `400ms` slide (`EmphasizedAccelerate` `(0.3, 0.0, 0.8, 0.15)`) | **1/5 screen width** slide + cross-fade (`SLIDE_FRACTION = 5`). Never slide full-screen width for hierarchical push/pop (full-width slides are reserved for peer *Lateral* swipes). |
| **Forward / Backward** *(iOS default)* | Parallax push (`100%` foreground, slower `~30%` background shift) | Interactive edge-swipe parallax | Matches iOS `UINavigationController` mental model; M3 `transitions.md:89-92` explicitly notes *"Both Android and iOS should use platform defaults for forward and backward navigation."* |
| **Top-Level Destination Switch** *(Bottom Bar / Rail)* | `250ms` (`medium1`, `delay = 150ms`), `StandardDecelerate` `(0, 0, 0, 1)` | `150ms` (`short3`), `StandardAccelerate` `(0.3, 0, 1, 1)` | **Sequential clean fade:** exit screen fades out completely before entering screen fades in, preventing ghost overlap across unrelated sections and avoiding horizontal slides that clash with swipeable rows. |
| **Predictive Back** *(Android 14+)* | `SeekableTransitionState` driven by finger progress | Scale `100% -> 90%`, fade-through at `35%` threshold | Map `SeekableTransitionState` with `tween(Medium4, StandardDecelerate)`—**never `snap()`**, which jumps to 100% on the first gesture pixel (`.corpus/compose-android/pages/design/ui/mobile/guides/patterns/predictive-back.md:64-73`). |

### 3.2 Cross-Platform Motion Reconciliation Table

| Platform | HIG / System Motion Ethos | Recommended Multiplatform Compose Strategy |
| --- | --- | --- |
| **Android** | Expressive physics (`MotionScheme.expressive()`), 150–400ms transitions, gesture-driven predictive back | Default to `MotionScheme.expressive()`; use M3 `400ms`/`200ms` transitions; honor `Settings.Global.ANIMATOR_DURATION_SCALE` (including developer-options `0.5x`–`10x` scales). |
| **iOS / iPadOS** | Fluid, gesture-cancellable spring physics; avoid gratuitous motion on high-frequency UI (`apple-hig/pages/motion.md:29-35`) | `MotionScheme.expressive()` works well for touch physics; use parallax or crisp directional push for hierarchical navigation; honor `UIAccessibility.isReduceMotionEnabled`. |
| **Windows 11** | Fast, purposeful, zero-lag productivity: WinUI 3 defines `ControlFasterAnimationDuration = 83ms`, `ControlFastAnimationDuration = 167ms`, `ControlNormalAnimationDuration = 250ms`, Fast-Out-Slow-In `cubic-bezier(0, 0, 0, 1)` enter, Slow-Out-Fast-In `cubic-bezier(1, 0, 1, 1)` exit (`.corpus/windows-fluent/pages/windows/design/motion/timing-and-easing.md:30-72`) | Switch desktop `MotionScheme` to **`MotionScheme.standard()`** (settles in ~160–220ms vs. 340–400ms for expressive) and shorten desktop page transitions to WinUI's `83ms / 167ms / 250ms`. Honor `SPI_GETCLIENTAREAANIMATION` + `WM_SETTINGCHANGE`. |
| **macOS** | Subtle, crisp, non-bouncy desktop responsiveness; Liquid Glass tones down touch emphasis when using a trackpad (`.corpus/apple-hig/pages/motion.md:17`) | Use `MotionScheme.standard()` with WinUI/macOS-paced short transitions (`<= 250ms`); disable menu scale-in; honor `NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion`. |
| **Linux (GNOME / KDE)** | Functional, unobtrusive desktop transitions; Adwaita/Kirigami honor desktop animation toggle | Use `MotionScheme.standard()` and `<= 250ms` transitions; read GNOME `org.gnome.desktop.interface enable-animations` (or KDE global animation speed) on focus/resume. |

> **Design Rule:** Derive `MotionStyle` (`Expressive` vs. `Standard`) from the **host platform family** (Mobile touch-first vs. Desktop productivity-first), **not** dynamically per pointer event—otherwise a hybrid 2-in-1 device (Surface Pro / iPad with mouse) shifts animation personality back and forth between clicks and taps.

---

## 4. Full `MotionDurationScale` & Reduced Motion Plumbing

Simply reading `isReducedMotion()` inside individual components leaves Material's built-in ripples, `ModalBottomSheet`, `DropdownMenu`, `NavDisplay`, and `AnimatedVisibility` animating normally. Compose provides a single authoritative coroutine context hook: **`androidx.compose.ui.MotionDurationScale`**.

### 4.1 Architecture of a Process-Wide `MotionDurationScale`
1. **Single Snapshot-Backed Instance (`AppMotionScale` pattern):**
   ```kotlin
   class AppMotionScale : MotionDurationScale {
       var systemScale by mutableFloatStateOf(1f)
       var appReduced by mutableStateOf(false)
       override val scaleFactor: Float
           get() = if (appReduced) 0f else systemScale
       val reduced: Boolean
           get() = scaleFactor == 0f
   }
   ```
   Because `scaleFactor` reads Compose snapshot state, toggling system Accessibility or an in-app "Reduce animations" setting immediately snaps active and future animations to completion on the next frame.
2. **Root Coroutine Context Injection (Including Sub-Windows & Popups):**
   - **Desktop JVM:** Pass `motionScale` into `runBlocking(motionScale) { awaitApplication { ... } }` so the root `Recomposer`, every secondary `Window`, and every `Dialog`/`Popup` inherit `coroutineContext[MotionDurationScale]`.
   - **Android:** Install a `WindowRecomposer` on the `DecorView` carrying `motionScale`, updating `systemScale` from `Settings.Global.ANIMATOR_DURATION_SCALE` via a `ContentObserver`.
   - **iOS:** Attach `motionScale` to the `ComposeUIViewController` / Skiko coroutine context and observe `UIAccessibilityReduceMotionStatusDidChangeNotification`.
3. **Platform Reduced-Motion Listeners:**
   - **Windows:** Query `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION)` and re-read on `WM_SETTINGCHANGE`.
   - **macOS:** Read `NSWorkspace.shared.accessibilityDisplayShouldReduceMotion` (and refresh on app activation / `NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification`).
   - **Linux:** Read `gsettings get org.gnome.desktop.interface enable-animations` (or XSettings/portal `ReduceMotion` where available) on startup and window focus regain.
4. **Two Things `scaleFactor = 0f` Does NOT Fix Automatically:**
   - **Infinite Decorative Loops:** When `scaleFactor == 0f`, `rememberInfiniteTransition` freezes at an arbitrary initial frame (often looking like broken shimmer or pulse opacity). Pass `reduced: Boolean` via a `CompositionLocal` (`LocalMotion.current.reduced`) and render a **static** placeholder skeleton or non-pulsing indicator when `reduced == true`.
   - **Parallax, Carousel Expansion & Shape Morphing:** M3's Carousel accessibility spec requires removing parallax and dynamic item expansion (rendering uniform item sizes) when Reduced Motion is active (`.corpus/m3-expressive/pages/components/carousel.md:623`, `styles/motion/transitions.md:263-266`), and `interactiveCard` micro-scale (`0.985f`) should be suppressed (`enableScale && !reducedMotion`) while keeping instant color state feedback.

---

## Sources & Cross-References
- `manifests/tokens/m3-expressive-tokens.json` (`motion_scheme`, `motion_easing`, `motion_duration`)
- `manifests/api/material3-expressive-surface.json` & `.corpus/compose-maven-api/pages/expressive-api-reference.md`
- `.corpus/m3-expressive/pages/styles/motion/overview.md`, `easing-and-duration.md`, `transitions.md`, `m3-expressive-motion-theming.md`, `components/carousel.md`
- `.corpus/compose-android/pages/design/ui/mobile/guides/patterns/predictive-back.md`
- `.corpus/apple-hig/pages/motion.md`
- `.corpus/windows-fluent/pages/windows/design/motion/timing-and-easing.md`, `signature-experiences/motion.md`
