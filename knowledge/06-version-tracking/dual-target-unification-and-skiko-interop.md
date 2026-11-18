# Dual-Target Version Unification & Skiko 0.156+ Native GPU Interop Guide

> Authoritative engineering diagnosis for Compose Multiplatform (Android + Desktop JVM) projects facing Material 3 API skew between AndroidX BOMs and JetBrains CMP artifacts, or migrating Desktop Skiko native interop (zero-copy D3D11/D3D12 video surfaces, TDR device-loss watches, ProGuard rules, and `WM_POINTER` touch bridges) from CMP `1.12.x` (`Skiko 0.150.x`) to CMP `1.13.x` (`Skiko 0.156.1+`).
>
> Cross-reference: [bleeding-edge-matrix.md](bleeding-edge-matrix.md) and `manifests/api/compose-versions.json`.

---

## 1. Root Cause of Android vs. Desktop Material 3 Version Skew

Compose Multiplatform projects frequently hit an unexpected API split in `commonMain` where Android compiles against a newer `androidx.compose.material3` release (for example, `1.5.0-alpha25`) while Desktop JVM compiles against an older JetBrains CMP release (`1.5.0-alpha22` inside `org.jetbrains.compose.material3:material3:1.12.0-alpha03`), forcing `expect/actual` compatibility shims (`StaticListItem`, `SplitButton` vs. `SplitButtonLayout`).

### How Gradle `.module` Redirection + BOM Resolution Creates the Split
1. **CMP `.module` Android redirection:** `org.jetbrains.compose.material3:material3` does not ship a separate implementation on Android; its Gradle `.module` metadata (`material3-android-<ver>.module`) declares a dependency on `androidx.compose.material3:material3:<mapped-ver>`.
   - `1.12.0-alpha03` redirects Android → `androidx.compose.material3:material3:1.5.0-alpha22`
   - `1.13.0-beta02` redirects Android → `androidx.compose.material3:material3:1.5.0-beta02`
2. **Pre-release BOM override trap:** If `androidMain` or `:app` applies `androidx.compose:compose-bom-alpha` (or `compose-bom-beta`) whose pinned `material3` version exceeds CMP's redirected version (e.g., `1.5.0-alpha25 > 1.5.0-alpha22`, or `1.5.0-rc01 > 1.5.0-beta02`), Gradle max-version resolution upgrades **only Android** to the BOM's newer `material3`. Desktop stays pinned to the CMP artifact's version.
3. **Stable BOM unification pattern:** If Android uses the **stable** BOM (`androidx.compose:compose-bom:2026.09.00`, which pins `material3 = 1.4.0` and `ui/foundation = 1.12.1`) while `commonMain` declares `org.jetbrains.compose.material3:material3:<cmp-m3-ver>`, Gradle resolves `max(1.4.0, <mapped-ver>) = <mapped-ver>` on Android—locking **both Android and Desktop onto the exact same `material3` API surface** with zero shims.

---

## 2. Why `cmp-material3` Cannot Jump Independently Past `1.12.0-alpha03`

Maven Central resolution & `.module` metadata verify why `cmp-material3` cannot be upgraded on top of a CMP `1.12.x` desktop runtime:

| `org.jetbrains.compose.material3:material3` | `material3-android` Redirects To | Requires `cmp.ui` / `foundation` | Pulls Desktop Skiko |
|---|---|---|---|
| `1.12.0-alpha03` *(last `1.12.x` release)* | `androidx.compose.material3:material3:1.5.0-alpha22` | `1.12.0-beta01` | `0.150.x` (with `1.12.2` runtime) |
| `1.13.0-alpha01` | `androidx.compose.material3:material3:1.5.0-alpha27` | `1.13.0-alpha01` | `0.152+` |
| `1.13.0-alpha02` | `androidx.compose.material3:material3:1.5.0-alpha28` | `1.13.0-alpha02` | `0.152+` |
| `1.13.0-beta01` | `androidx.compose.material3:material3:1.5.0-beta01` | `1.13.0-beta01` | `0.156+` |
| `1.13.0-beta02` | `androidx.compose.material3:material3:1.5.0-beta02` | `1.13.0-beta02` | **`0.156.1`** (`ui-skiko:1.13.0-beta02`) |

- There is **no** `1.12.0` / `1.12.1` / `1.12.2` release of `org.jetbrains.compose.material3:material3` newer than `1.12.0-alpha03`.
- Adopting `cmp-material3:1.13.0-beta02` pulls `org.jetbrains.compose.ui:ui-desktop:1.13.0-beta02` → `ui-skiko-desktop:1.13.0-beta02` → **`org.jetbrains.skiko:skiko:0.156.1`**.

---

## 3. Skiko `0.150.x` vs. `0.156.1` Native Interop Breaking Changes (`javap -p -s`)

Inspecting `skiko-awt-0.156.1.jar` vs. `skiko-awt-0.150.1` reveals the exact internal class/field refactoring that breaks Skiko `0.150.x` D3D11/D3D12 video-surface interop (e.g., `org.openani.mediamp:mediamp-mpv-desktop:0.5.0`–`0.5.3`) and TDR device-loss watches:

| Interop Role | Skiko `0.150.x` (CMP `1.12.x`) | Skiko `0.156.1` (CMP `1.13.0-beta02`) Exact `javap -p -s` Signature | Impact |
|---|---|---|---|
| Layer → Driver / Redrawer | `SkiaLayer.getRedrawer$skiko()` | **Removed**; replaced by:<br>`SkiaLayer.getFrameDriver$org_jetbrains_skiko_skiko()Lorg/jetbrains/skiko/renderer/FrameDriver;`<br>and `private final RenderApiFallbackManager<FrameDriver> frameDriverManager` (`RenderApiFallbackManager.getCurrent()Ljava/lang/Object;`) | Breaks `SkiaLayer.class.getMethod("getRedrawer$skiko")` in `mediamp` `SkiaLayerRedrawer` (`0.5.0`–`0.5.3`) and legacy TDR watches |
| Driver → Renderer | *(Redrawer returned directly)* | `org.jetbrains.skiko.renderer.FrameDriver` → `private final FrameProducer producer` (`getRenderer(): AwtRenderer` / `access$getRenderer(FrameDriver): AwtRenderer`) and `FrameProducer.getRenderer$org_jetbrains_skiko_skiko()Lorg/jetbrains/skiko/renderer/AwtRenderer;` (`private final AwtRenderer renderer`) | New hop required to obtain the active `AwtRenderer` |
| Direct3D Backend Class | `org.jetbrains.skiko.redrawer.Direct3DRedrawer` (`device: J`, `contextHandler`) | **Removed**; replaced by `org.jetbrains.skiko.renderer.Direct3DRenderer extends AwtRenderer` (`private long device` descriptor `J`, `private long adapter` descriptor `J`, `private final long getDevice()J`) | Breaks `Class.forName("org.jetbrains.skiko.redrawer.Direct3DRedrawer")` and class-name assertions in `mediamp` `SkiaDirectXInterop` (`0.5.0`–`0.5.3`) |
| Skia `DirectContext` | `org.jetbrains.skiko.context.ContextHandler` (`private DirectContext context`) | **`ContextHandler` removed**; `private org.jetbrains.skia.DirectContext context` (descriptor `Lorg/jetbrains/skia/DirectContext;`) now lives **directly on `Direct3DRenderer`** (`ensureContext()` calls `DirectContext.Companion.makeDirect3D(adapter, getDirectXDevice(device), getDirectXCommandQueue(device))`) | Breaks `SkiaDirectXInterop$RedrawerAccess` (`getDeclaredField("contextHandler")` / `ContextHandler.context`) |
| `WM_POINTER` Touch Bridge Targets | `ComposeWindow.composePanel` → `ComposePanel._composeContainer` → `mediator` → `ComposeScene.sendPointerEvent-UGFwazM` | **All intact** in `ui-desktop-1.13.0-beta02.jar`: `ComposeWindow.composePanel` (`ComposeWindowPanel`), `ComposeWindowPanel._composeContainer`, `ComposeContainer.mediator`, `ComposeSceneMediator.getSceneBoundsInPx()` & `access$getScene` / `scene$delegate`, 10-arg `ComposeScene.sendPointerEvent-UGFwazM` | Desktop `WM_POINTER` touch injection remains compatible without changes |

### MediaMP `0.5.3` Interop Chain (`mediamp-mpv-desktop-0.5.3.jar` `javap -p -s`)
1. `MpvMediampPlayerSurfaceProvider.Surface(MpvMediampPlayer, Modifier, Composer, Int)` delegates to `MpvMediampPlayerSurface_desktopKt.MpvMediampPlayerSurface(player, modifier)`.
2. `MpvMediampPlayerSurfaceRing` invokes `D3D11SurfaceRingBackend.createSkiaInterop(SkiaLayerRedrawer)` → `SkiaDirectXInterop(SkiaLayerRedrawer)`:
   - `SkiaLayerRedrawer(layer: SkiaLayer)` caches `SkiaLayer.class.getMethod("getRedrawer$skiko")` in `<clinit>`, exposing `getRedrawerOrNull(): Object`, `getRedrawer(): Object`, and `getRendererChanges(): StateFlow<Long>` (via `SkiaLayer.onStateChanged(SkiaLayer$PropertyKind.Renderer, ...)`).
   - `SkiaDirectXInterop` implements `SkiaRenderDeviceInterop` (`getRenderDevicePtr(): Long`, `getDirectContext(): DirectContext?`), asserting `redrawer.javaClass.name == "org.jetbrains.skiko.redrawer.Direct3DRedrawer"` and reading `device` (`J`), `contextHandler`, and `ContextHandler.context`.
3. `MpvSurfaceRing(handlePtr: Long, backend: MpvSurfaceRingBackend)` consumes `interop.getRenderDevicePtr()` (`DirectXDevice*`, passed to `MPVHandleDesktop.nSetConsumerDeviceHintD3D11` / `nSetSurfaceConfigD3D11`) and `interop.getDirectContext()`, wrapping D3D11→D3D12 textures via `D3D11SurfaceRingBackend.makeConsumerRenderTarget` (`BackendRenderTarget.Companion.makeDirect3D`).
4. Note: `mediamp 0.5.3` includes `D3D11ReadbackSurfaceBackend` (`SkiaReadbackInterop` — zero Skiko reflection), but `MpvBackendSelection.fallbackWhenUnavailable` only falls back to it from `WindowsOpenGLSurfaceBackend`, not from `D3D11SurfaceRingBackend`.

---

## 4. Two Clean Dual-Target Unification Paths

### Path A — Immediate Zero-Risk Unification (`material3 1.5.0-alpha22` + CMP `1.12.2`)
Use when hardware zero-copy D3D11→D3D12 video via unmodified upstream `mediamp` (`0.5.0`–`0.5.3`) is required immediately:
1. **Switch Android BOM from `compose-bom-alpha` to stable `androidx.compose:compose-bom:2026.09.00`** (`ui/foundation 1.12.1`, `material3 1.4.0`). `cmp-material3:1.12.0-alpha03`'s Android `.module` redirect (`1.5.0-alpha22 > 1.4.0`) pins **both Android and Desktop to `1.5.0-alpha22`**.
2. **Align stable `1.12.x` patch versions:** `composeMultiplatform = "1.12.2"` (Skiko `0.150.2`), `cmp-material3 = "1.12.0-alpha03"`, `cmp-adaptive = "1.3.0"`, `cmp-navigation3-ui = "1.2.0"`, `mediamp = "0.5.3"`. Keep `compose-gradle-plugin` decoupled at `1.13.0-beta02` (or `1.13.0-alpha01`) if JDK 25 `buildTypes.release.aot` packaging is needed.
3. **Remove `M3Compat` `expect/actual` splits:** Both targets share `ListItem(headlineContent = ...)` and `SplitButtonLayout(...)` directly in `commonMain`.

### Path B — Bleeding-Edge Unification (`CMP 1.13.0-beta02` + `material3 1.5.0-beta02`)
Use to adopt the graduated M3 Expressive API surface (where `MaterialExpressiveTheme`, `MotionScheme`, all 4 `SegmentedListItem` overloads, `SplitButtonLayout`, and `WideNavigationRail` are stable without opt-ins; see [bleeding-edge-matrix.md §3.1](bleeding-edge-matrix.md)):

1. **Adapt Desktop MediaMP D3D11/D3D12 Interop for Skiko `0.156.1` (`Direct3DRenderer`):**
   - **Option B1 (Local surface wrapper — no classpath shadowing):** Replace `MpvMediampPlayerSurface(...)` in `desktopMain` with a local composable wrapping `MpvSurfaceRing(mpvHandlePtr, D3D11SurfaceRingBackend)`, resolving Skia's D3D12 device and `DirectContext` via:
     1) `val frameDriver = SkiaLayer::class.java.getMethod("getFrameDriver\$org_jetbrains_skiko_skiko").invoke(layer)` (or `frameDriverManager.getCurrent()`),
     2) `val producer = frameDriver.javaClass.getDeclaredField("producer").apply { isAccessible = true }.get(frameDriver)`,
     3) `val renderer = producer.javaClass.getMethod("getRenderer\$org_jetbrains_skiko_skiko").invoke(producer)` (verify class `org.jetbrains.skiko.renderer.Direct3DRenderer`),
     4) `val devicePtr = renderer.javaClass.getDeclaredField("device").apply { isAccessible = true }.getLong(renderer)` (`DirectXDevice*`),
     5) `val directContext = renderer.javaClass.getDeclaredField("context").apply { isAccessible = true }.get(renderer) as DirectContext`.
   - **Option B2 (Composite/forked `mediamp`):** Patch `SkiaLayerRedrawer` (falling back from `getRedrawer$skiko` to `getFrameDriver$org_jetbrains_skiko_skiko` → `producer.getRenderer$org_jetbrains_skiko_skiko()`) and `SkiaDirectXInterop` (supporting `org.jetbrains.skiko.renderer.Direct3DRenderer` reading `device` + `context` directly without `ContextHandler`).
2. **Update TDR Device-Loss Watch & ProGuard Keep Rules:**
   - Update `GpuDeviceWatch` reflection from `getRedrawer$skiko` / `Direct3DRedrawer` to `getFrameDriver$org_jetbrains_skiko_skiko` → `FrameProducer.getRenderer$org_jetbrains_skiko_skiko` → `Direct3DRenderer.device` (`DirectXDevice*` → slot `6` `ID3D12Device` → vtable slot `37` `GetDeviceRemovedReason`, verified in `Direct3DRenderer.ensureContext()` passing `device` to `getDirectXDevice(J)J`).
   - Update desktop `proguard-rules.pro` to `-keepclassmembers` for:
     ```proguard
     -keepclassmembers class org.jetbrains.skiko.SkiaLayer {
         *** getFrameDriver$org_jetbrains_skiko_skiko();
     }
     -keepclassmembers class org.jetbrains.skiko.renderer.FrameDriver {
         *** producer;
     }
     -keepclassmembers class org.jetbrains.skiko.renderer.FrameProducer {
         *** getRenderer$org_jetbrains_skiko_skiko();
     }
     -keepclassmembers class org.jetbrains.skiko.renderer.Direct3DRenderer {
         *** device;
         *** context;
     }
     ```
   - Retain existing `ComposeWindow` / `ComposeWindowPanel` / `ComposeContainer` / `ComposeSceneMediator` / `ComposeScene` keep rules for `compose-windows-touch:0.1.0`.
3. **Verify Fractional DPI Scaling:** Test 125% and 150% Windows display scaling on `Direct3DRenderer` (`Skiko 0.156.1`) to confirm whether pixel-aligned content layout workarounds remain necessary.
4. **Pin Parity Versions Across Targets:**
   - `composeMultiplatform = "1.13.0-beta02"`, `composeMultiplatformMaterial3 = "1.13.0-beta02"`, `composeMultiplatformAdaptive = "1.3.0"` (or `1.4.0-alpha01`), `navigation3Multiplatform = "1.2.0"`, paired with stable `androidx.compose:compose-bom:2026.09.00` so `cmp-material3:1.13.0-beta02` locks Android and Desktop to identical **`material3 1.5.0-beta02`** parity (or upgrade both once `1.13.0-rc01` / `1.5.0-rc01` ships).

---

## 5. Decision Matrix

| Criterion | Skewed Baseline (`bom-alpha` + `CMP 1.12.1`) | **Path A (Zero-Risk Now):** `compose-bom 2026.09.00` + `CMP 1.12.2` + `cmp-m3 1.12.0-alpha03` | **Path B (After Skiko `0.156` Interop Adaptation):** `CMP 1.13.0-beta02` + `cmp-m3 1.13.0-beta02` |
|---|---|---|---|
| Android vs. Desktop M3 Parity | `alpha25` vs. `alpha22` (skewed) | **`1.5.0-alpha22` vs. `1.5.0-alpha22`** (identical) | **`1.5.0-beta02` vs. `1.5.0-beta02`** (identical) |
| `M3Compat` `expect/actual` Needed? | Yes | **No** | **No** (plus static `SegmentedListItem` & graduated M3E APIs) |
| MediaMP D3D11 Zero-Copy | Works (`0.5.0`) | **Works (`0.5.3`)** | Works once adapted to `Direct3DRenderer` |
| `compose-windows-touch 0.1.0` | Works | **Works** | **Works** (`javap` verified on `1.13.0-beta02`) |
| TDR `GpuDeviceWatch` | Works | **Works** | Requires `Direct3DRedrawer` → `Direct3DRenderer` update |
