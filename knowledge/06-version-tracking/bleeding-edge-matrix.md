# Bleeding-Edge Compose & Material 3 Expressive Version Matrix

> **Snapshot Timestamp:** `2026-11-18T12:21:52Z`  
> **Authoritative Sources:** `manifests/api/compose-versions.json`, `manifests/api/material3-expressive-surface.json`, `.corpus/compose-maven-api/pages/versions-and-boms.md`, `.corpus/compose-maven-api/pages/parity-diff.md`.  
> **CLI Queries:** Run `uv run rtx status` and `uv run rtx api <Symbol> --diff` to inspect live pinned bytecode signatures.

---

## 1. How AndroidX BOMs Map to JetBrains Compose Multiplatform

Compose Multiplatform (CMP) projects compile `commonMain` against **two distinct artifact trees** that advance on staggered release trains:

1. **Android (`androidMain` / `:app`):** Resolves Google Maven (`dl.google.com/dl/android/maven2`) via `androidx.compose:compose-bom` (stable) or `compose-bom-alpha` / `compose-bom-beta`.
2. **Desktop JVM / iOS / Web (`desktopMain` / `iosMain`):** Resolves Maven Central (`repo1.maven.org/maven2`) and JetBrains Space (`maven.pkg.jetbrains.space/public/p/compose/dev`) via JetBrains `org.jetbrains.compose.*` artifacts.

### Crucial Decoupling & Redirection Mechanics
- **JetBrains `.module` Redirection on Android:** On Android targets, Gradle `.module` metadata inside `org.jetbrains.compose.material3:material3`, `org.jetbrains.compose.material3.adaptive:*`, and `org.jetbrains.androidx.navigation3:navigation3-ui` **redirects to the corresponding `androidx.*` coordinate**. If your `:app` or `androidMain` declares an AndroidX BOM (`compose-bom-alpha`), Android resolves `max(redirectVersion, bomVersion)` via Gradle max-version conflict resolution—causing Android and Desktop to skew whenever `compose-bom-alpha` exceeds `cmp-material3`'s redirect!
  - **How to Lock Android + Desktop to Identical Material 3 APIs:** Pair `cmp-material3` (`1.12.0-alpha03` -> `1.5.0-alpha22`, or `1.13.0-rc01` -> `1.5.0-rc01`) with the **stable** Android BOM (`compose-bom:2026.09.00`, `material3:1.4.0`). Because `1.5.0-* > 1.4.0`, `cmp-material3`'s `.module` redirect wins on Android, giving both targets the exact same Material 3 build with zero `M3Compat` shims. (See [dual-target-unification-and-skiko-interop.md](dual-target-unification-and-skiko-interop.md) for a full Gradle & bytecode walkthrough.)
  - Verified redirects (`.corpus/compose-maven-api/pages/versions-and-boms.md#L530-L538`):
    - `org.jetbrains.compose.material3:material3:1.13.0-rc01` -> `androidx.compose.material3:material3:1.5.0-rc01`
    - `org.jetbrains.compose.material3:material3-adaptive-navigation-suite:1.13.0-rc01` -> `androidx.compose.material3:material3-adaptive-navigation-suite:1.5.0-rc01`
    - `org.jetbrains.compose.material3.adaptive:adaptive*:1.4.0-alpha01` -> `androidx.compose.material3.adaptive:adaptive*:1.4.0-alpha03`
    - `org.jetbrains.androidx.navigation3:navigation3-ui:1.2.0` -> `androidx.navigation3:navigation3-runtime:1.2.0` + `navigation3-ui:1.2.0` + `androidx.savedstate:savedstate-compose:1.4.0`
- **Independent Versioning Beyond the Core Plugin:** `org.jetbrains.compose:compose-gradle-plugin` no longer dictates `material3`, `adaptive`, `navigation3`, or `lifecycle` versions—all four publish on independent version lines.
- **Gradle Plugin vs. Runtime Library Decoupling:** You can upgrade `org.jetbrains.compose` (the Gradle plugin) independently (e.g., to `1.13.0-rc01` for `buildTypes.release.aot` JDK 25 AOT DSL) while pinning runtime libraries (`org.jetbrains.compose.ui:ui`, `foundation`, `runtime`) to an earlier version (`1.12.0` / `1.12.2`) if native Skiko interop (e.g., MediaMP `0.5.0`–`0.5.3` D3D11) requires Skiko `0.150.x`.
  - **Rule:** When decoupling plugin and runtime versions, **never** use `compose.desktop.currentOs` or `compose.material3` Gradle DSL accessors—those follow the *plugin* version! Declare explicit Maven coordinates (`org.jetbrains.compose.desktop:desktop-jvm-<os>-<arch>:<runtimeVersion>`, `org.jetbrains.compose.material3:material3:<m3Version>`) and disable the plugin library-version compatibility check.

---

## 2. Live Maven Version Matrix (`2026-11-18`)

### 2.1 AndroidX (Google Maven) vs. JetBrains CMP (Maven Central)

| Component Family | AndroidX Coordinate (`dl.google.com`) | AndroidX Stable | AndroidX Latest Pre-Release | JetBrains CMP Coordinate (`repo1.maven.org`) | CMP Stable | CMP Latest Pre-Release |
| --- | --- | --- | --- | --- | --- | --- |
| **Compose BOM (Stable)** | `androidx.compose:compose-bom` | `2026.09.00` | `-` | *(N/A — explicit coordinates)* | `-` | `-` |
| **Compose BOM (Alpha / Beta)** | `androidx.compose:compose-bom-alpha` / `-beta` | `2026.11.00` | `-` (tracks latest pre-release train) | *(N/A)* | `-` | `-` |
| **Compose Plugin / Core (`runtime`, `ui`, `ui-graphics`, `foundation`, `animation`)** | `androidx.compose.ui:ui` (etc.) | `1.12.1` | `1.13.0-rc01` (`alpha03`, `beta02`) | `org.jetbrains.compose:compose-gradle-plugin` & core modules | `1.12.2` | **`1.13.0-rc01`** (`beta02`, `alpha02`) |
| **Skiko AWT (Desktop Rendering)** | *(Android HWUI)* | `-` | `-` | `org.jetbrains.skiko:skiko-awt` | **`0.156.1`** | `0.152.0-alpha02` |
| **Material 3 (incl. Expressive)** | `androidx.compose.material3:material3` | `1.4.0` | **`1.5.0-rc01`** (`beta02`, `alpha29`) | `org.jetbrains.compose.material3:material3` | `1.9.0` | **`1.13.0-rc01`** (`beta02`, `alpha02`) |
| **Adaptive Navigation Suite** | `androidx.compose.material3:material3-adaptive-navigation-suite` | `1.4.0` | **`1.5.0-rc01`** (`beta02`, `alpha29`) | `org.jetbrains.compose.material3:material3-adaptive-navigation-suite` | `1.9.0` | **`1.13.0-rc01`** (`beta02`, `alpha02`) |
| **Material 3 Adaptive (`adaptive`, `adaptive-layout`, `adaptive-navigation`, `adaptive-navigation3`)** | `androidx.compose.material3.adaptive:adaptive*` | `1.3.0` | **`1.4.0-alpha03`** (`1.3.0-rc01`, `beta02`) | `org.jetbrains.compose.material3.adaptive:adaptive*` | `1.3.0` | **`1.4.0-alpha01`** (`1.3.0-rc01`, `beta02`) |
| **Navigation 3 (`runtime`, `ui`)** | `androidx.navigation3:navigation3-runtime` / `navigation3-ui` | `1.2.1` | **`1.3.0-alpha04`** (`1.2.0-rc01`) | `org.jetbrains.androidx.navigation3:navigation3-ui` | **`1.2.0`** | `1.2.0-alpha02` / `beta01` / `rc01` |
| **Lifecycle ViewModel Compose / Nav3** | `androidx.lifecycle:lifecycle-viewmodel-compose` / `-navigation3` | `2.11.0` | `2.12.0-alpha05` (`2.11.0-rc01`) | `org.jetbrains.androidx.lifecycle:lifecycle-viewmodel-compose` / `-navigation3` | **`2.11.0`** | `2.11.0-alpha03` / `beta02` / `rc01` |

### 2.2 BOM Pin Breakdown (`compose-bom` `2026.09.00` vs. `compose-bom-alpha` `2026.11.00`)

| Artifact | `compose-bom` `2026.09.00` | `compose-bom-alpha` `2026.11.00` |
| --- | --- | --- |
| `ui` / `foundation` / `animation` / `runtime` | `1.12.1` | `1.13.0-rc01` |
| `material3` / `material3-window-size-class` / `material3-adaptive-navigation-suite` | `1.4.0` | `1.5.0-rc01` |
| `adaptive` / `adaptive-layout` / `adaptive-navigation` / `adaptive-navigation3` | `1.3.0` | `1.4.0-alpha03` |
| `material3-common` / `material3-adaptive` | *(absent)* | `1.0.0-alpha01` / `1.0.0-alpha06` |
| `foundation-text` / `adaptive-render-strategy` / `runtime-dispatch` | *(absent)* | `1.0.0-alpha07` / `1.1.0-alpha04` / `1.0.0-alpha12` |

*Note on `androidx.compose.*-desktop` stubs inside Google's BOM:* Google's BOM still lists legacy `-desktop` pins (e.g., `ui-desktop:1.7.0`, `material3-desktop:1.3.2`). Multiplatform Desktop builds must resolve `org.jetbrains.compose.*` coordinates—never `androidx.compose.*` desktop stubs.

---

## 3. Bytecode-Verified Parity Diff (`javap` Audit)

Inspected across 15 JARs/AARs (`1,628` symbols) via OpenJDK 21 `javap` in `manifests/api/material3-expressive-surface.json` and `.corpus/compose-maven-api/pages/parity-diff.md`:

| Module Pair | AndroidX Inspected | CMP Desktop Inspected | Identical | Opt-In Delta | Overload Delta | Android Only | CMP Only |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `material3` | `1.5.0-rc01` | `1.13.0-rc01` | 849 | **4** | 98 | 67 | 141 |
| `material3-adaptive-navigation-suite` | `1.5.0-rc01` | `1.13.0-rc01` | 26 | 0 | 0 | 7 | 7 |
| `adaptive` | `1.4.0-alpha03` | `1.4.0-alpha01` | 16 | 0 | 1 | 1 | 0 |
| `adaptive-layout` | `1.4.0-alpha03` | `1.4.0-alpha01` | 136 | 0 | 26 | 1 | 86 |
| `adaptive-navigation` | `1.4.0-alpha03` | `1.4.0-alpha01` | 9 | 0 | 0 | 3 | 0 |
| `adaptive-navigation3` | `1.4.0-alpha03` | `1.4.0-alpha01` | 29 | 0 | 0 | 5 | 5 |
| `navigation3-ui` | `1.3.0-alpha04` | `1.2.0` | 35 | 0 | 2 | 4 | 1 |

*(Most `android_only` / `cmp_only` entries in `adaptive-navigation3`, `material3-adaptive-navigation-suite`, and `material3` are synthetic compiler `getLambda$...` methods or CMP bundled locale string functions `translationFor`, `af`, `ar`, etc.)*

### 3.1 Material 3 Expressive Graduation & Opt-In Status (`1.5.0-rc01` vs. `1.13.0-rc01`)

- **Graduated to Stable (No `@OptIn` Required on Either Platform):**
  - **Theme & Motion:** `MaterialExpressiveTheme`, `MaterialTheme`, `MotionScheme`, `Shapes`, `Typography`, `ColorScheme`
  - **Buttons & Toolbars:** `ButtonGroup`, `ButtonGroupDefaults`, `ButtonGroupScope`, `ButtonDefaults`, `SplitButtonLayout`, `SplitButtonDefaults`, `ToggleButton`, `ToggleButtonDefaults`, `IconToggleButton`, `FilledIconToggleButton`, `OutlinedIconToggleButton`, `FloatingActionButtonMenu`, `FloatingActionButtonMenuItem`, `ToggleFloatingActionButton`, `ToggleFloatingActionButtonDefaults`, `HorizontalFloatingToolbar`, `VerticalFloatingToolbar`, `FloatingToolbarDefaults`, `FloatingToolbarColors`, `FloatingToolbarScrollBehavior`
  - **Progress & Lists & Bars:** `LinearWavyProgressIndicator`, `CircularWavyProgressIndicator`, `WavyProgressIndicatorDefaults`, `PullToRefreshDefaults`, `MediumFlexibleTopAppBar`, `LargeFlexibleTopAppBar`, `TopAppBarDefaults`, `AppBarRow`, `AppBarColumn`, `WideNavigationRail`, `WideNavigationRailItem`, `WideNavigationRailDefaults`, `WideNavigationRailState`, `ShortNavigationBar`, `ShortNavigationBarItem`, `ShortNavigationBarDefaults`, `SegmentedListItem` (all 4 overloads including static non-clickable + `onClick` + `selected` + `checked`), `HorizontalMultiBrowseCarousel`, `HorizontalUncontainedCarousel`, `HorizontalCenteredHeroCarousel`, `ExpandedFullScreenSearchBar`, `ExpandedDockedSearchBar`
- **Still Requires `@ExperimentalMaterial3ExpressiveApi` on Both:**
  - `LoadingIndicator`, `ContainedLoadingIndicator`, `LoadingIndicatorDefaults`, `MaterialShapes`
- **Still Requires `@ExperimentalMaterial3Api` on Both:**
  - `SearchBar`
- **Still Requires `@ExperimentalMaterial3AdaptiveApi` on Both:**
  - `ListDetailPaneScaffold`, `SupportingPaneScaffold`, `ListDetailSceneStrategy`, `SupportingPaneSceneStrategy`, `ThreePaneScaffoldNavigator`
  - *(Note: `PaneScaffoldDirective`, `WindowAdaptiveInfo`, `currentWindowAdaptiveInfo`, `NavigationSuiteScaffold`, `NavigationSuite`, `NavDisplay`, `NavEntry`, `NavBackStack`, `rememberNavBackStack` are all stable.)*

### 3.2 Exact `opt_in_delta` & `android_only` Platform Deltas

| Symbol | Module | Android (`1.5.0-rc01` / `1.4.0-alpha03` / `1.3.0-alpha04`) | CMP Desktop (`1.13.0-rc01` / `1.4.0-alpha01` / `1.2.0`) | Impact in `commonMain` |
| --- | --- | --- | --- | --- |
| `AlertDialog` | `material3` | Stable (no opt-in) | `@ExperimentalMaterial3Api` | Module-level `optIn` or `@OptIn(ExperimentalMaterial3Api::class)` needed for Desktop compilation! |
| `BasicAlertDialog` | `material3` | Stable (no opt-in) | `@ExperimentalMaterial3Api` | Same as above |
| `DatePickerDialog` | `material3` | Stable (no opt-in) | `@ExperimentalMaterial3Api` | Same as above |
| `DropdownMenuPopupImpl` | `material3` | Stable (no opt-in) | `@ExperimentalMaterial3ExpressiveApi` | Internal/popup wrapper; use `@OptIn` if referenced |
| `dynamicDarkColorScheme*` / `dynamicLightColorScheme*` / `dynamicTonalPalette` | `material3` | Present (`android_only`) | Absent | Call only from `androidMain` behind Android 12+ (`SDK_INT >= 31`) |
| `collectFoldingFeaturesAsState` | `adaptive` | Present (`android_only`) | Absent | Hinge/fold sensor collection lives in `androidMain` (`WindowAdaptiveInfo` falls back cleanly in `commonMain`) |
| `NavigableListDetailPaneScaffold` / `NavigableSupportingPaneScaffold` / `ThreePaneScaffoldPredictiveBackHandler` | `adaptive-navigation` | Present (`android_only`) | Absent | Prefer `ListDetailSceneStrategy` + `SupportingPaneSceneStrategy` in `commonMain` (identical across targets!) |
| `TitleMetadataKey` / `UrlMetadataKey` / `toMutableTransform` | `navigation3-ui` | Present (`1.3.0-alpha04`) | Absent (`1.2.0`) | Do not use `1.3.0-alpha04` Navigation 3 metadata keys in `commonMain` until CMP `navigation3-ui` reaches `1.3.0` |

### 3.3 CMP `1.13` UI-Graphics / Skiko Breaking & Deprecation Notes
- **`Canvas.skiaCanvas` replaces `Canvas.nativeCanvas` (`ui-skiko:1.13.0-rc01`):** In `androidx.compose.ui.graphics.SkiaBackedCanvas_skikoKt` (`ui-skiko`), `val Canvas.nativeCanvas: org.jetbrains.skia.Canvas` is now `@Deprecated` in favor of `val Canvas.skiaCanvas: org.jetbrains.skia.Canvas` (`import androidx.compose.ui.graphics.skiaCanvas`). Additionally, `androidx.compose.ui.graphics.NativeCanvas` (`Canvas_skikoKt` in `ui-graphics`) carries `@Deprecated(level = DeprecationLevel.ERROR)`—reference `org.jetbrains.skia.Canvas` directly.
- **Skiko `0.156.1` GPU Interop:** `SkiaLayer.getRedrawer$skiko()`, `Direct3DRedrawer`, and `ContextHandler` are removed in Skiko `0.156.1`, replaced by `SkiaLayer.frameDriverManager` (`FrameDriver` -> `FrameProducer`) and `org.jetbrains.skiko.renderer.Direct3DRenderer`. See [dual-target-unification-and-skiko-interop.md](dual-target-unification-and-skiko-interop.md).

### 3.4 Historical Pin Caveats (When Pinned Below `1.5.0-rc01` / `1.13.0-rc01`)
If an app must pin CMP below `1.13.x` (e.g., CMP `1.12.0` / `1.12.2` + `org.jetbrains.compose.material3:material3:1.12.0-alpha03` -> Material3 `1.5.0-alpha22` due to Skiko `0.152+` removing `ContextHandler` and breaking `mediamp 0.5.0`–`0.5.3`):
- **`ListItem` overload drift:** `1.5.0-alpha25+` shifted `ListItem` to a trailing `content` lambda and deprecated `headlineContent`, whereas `alpha22` lacks the trailing-`content` overload—bridge via an `expect/actual` `M3Compat` wrapper.
- **`SplitButtonLayout` vs. `SplitButton`:** Verify exact symbol name via `uv run rtx api SplitButton` (in `1.5.0-rc01` / `1.13.0-rc01`, the composable is `SplitButtonLayout`).
- **Non-clickable `SegmentedListItem`:** Absent in `alpha22` (only `onClick` / `selected` / `checked` overloads existed); present in `1.5.0-rc01` / `1.13.0-rc01` (all 4 overloads verified).
- **Opt-in drift:** `MediumFlexibleTopAppBar` required `@OptIn(ExperimentalMaterial3ExpressiveApi::class)` in `alpha22`, but graduated in `alpha25+` / `1.5.0-rc01`. Add module-wide opt-ins in `ui/build.gradle.kts` (`languageSettings.optIn(...)`) so `commonMain` compiles cleanly across skewed Android/Desktop Material3 versions.

```kotlin
// M3Compat.kt (commonMain) — bridge API drift cleanly when Android & Desktop pins skew
@Composable
internal expect fun StaticListItem(
    modifier: Modifier = Modifier,
    leadingContent: (@Composable () -> Unit)? = null,
    trailingContent: (@Composable () -> Unit)? = null,
    supportingContent: (@Composable () -> Unit)? = null,
    colors: ListItemColors = ListItemDefaults.colors(),
    content: @Composable () -> Unit,
)
// androidMain calls ListItem(..., content = content); desktopMain (alpha22) calls ListItem(headlineContent = content, ...)
```

---

## 4. Dual-Target Compilation Gates & Bytecode Verification Workflow

### 4.1 Mandatory Multi-Target Compile Gate
Never rely on a single target compile (especially Android-only) after editing `commonMain` UI code:
```bash
# Fast dual-target Kotlin compilation check (no full packaging)
./gradlew :shared:compileCommonMainKotlinMetadata :ui:compileCommonMainKotlinMetadata \
          :app:compileDebugKotlin :desktopApp:compileKotlinDesktop

# Plus iOS compile/test gate on macOS runners:
./gradlew :shared:iosSimulatorArm64Test :ui:iosSimulatorArm64Test
```
*Note:*
- Serialize Gradle invocations in multi-agent workflows—running two `./gradlew` processes concurrently crashes the shared Kotlin compiler daemon.
- On **AGP 9**, AndroidX Compose `1.13` / Material 3 `1.5.0-rc01` AAR metadata requires Android API `37.1` (`compileSdk { version = release(37) { minorApiLevel = 1 } }`); plain `compileSdk = 37` fails metadata validation.
- On **Windows NTFS**, terminate any running desktop dev JVM instance holding `*-desktop.jar` open before running `:shared:desktopJar` or packaging tasks (`Unable to delete file`).

### 4.2 `M3ApiProbe.kt` Test-Source-Set Gate
Keep a compile-only API probe file (e.g., `shared/src/androidHostTest/.../M3ApiProbe.kt` or `ui/src/commonTest/.../M3ApiProbe.kt`) exercising every M3 Expressive theme, token, and component symbol your app relies on:
- **Never place probes in `main` source sets**—any intermediate alpha breakage blocks all parallel contributors.
- Re-run test compilation immediately after bumping `composeBom`, `composeMultiplatform`, or `cmpMaterial3` to catch removed overloads, renamed symbols, or changed `@OptIn` requirements.

### 4.3 `rtx` + `javap` Bytecode Verification Workflow
Follow this exact lookup precedence (`manifests/api/` > `.corpus/` > memory):
1. **Query the pre-indexed bytecode manifest first** (avoids scanning `.gradle/caches` and guessing `*Kt` facade names):
   ```bash
   uv run rtx api <SymbolName> --diff
   ```
2. **Check AndroidX release notes in `.corpus/compose-maven-api/pages/releases/`** (`compose-material3.md`, `compose-material3-adaptive.md`, `compose-ui.md`, `compose-foundation.md`, `navigation3.md`) for behavioral changes between alpha/beta/rc cuts.
3. **Only when inspecting a locally pinned older/custom version** not tracked in `manifests/api/`, run `javap` on the **exact** pinned artifact:
   - For Desktop: target the exact version path (never `Select-Object -First 1` on a wildcard glob across `.gradle/caches`, which frequently hits stale cached alphas).
   - For Android `.aar`: extract `classes.jar` to a temp directory first, then run `javap -p` / `javap -v` (for `@OptIn` runtime-invisible/class annotations).
   - Refresh the repo's live manifest anytime via `uv run rtx sync compose-maven-api --verify`.
