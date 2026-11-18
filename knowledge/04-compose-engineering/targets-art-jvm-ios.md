# Target Runtime Engineering: Android ART, Desktop JVM, and iOS Native

> **Scope:** Target-specific runtime semantics, native interop, packaging, rendering backends, OS integration, and failure modes across **Android ART**, **Desktop JVM** (Windows / macOS / Linux), and **iOS Native** (Kotlin/Native).  
> **Sources:** Verified against `.corpus/compose-multiplatform/pages/docs/multiplatform/multiplatform-ios-integration-overview.md`, `compose-ios-touch.md`, `compose-desktop-top-level-windows-management.md`, `compose-desktop-tray.md`, `.corpus/apple-hig/pages/designing-for-ios.md`, `designing-for-macos.md`, `.corpus/windows-fluent/pages/windows/develop/ui/controls/title-bar.md`, and `.corpus/linux-hig/pages/gnome/patterns/containers/windows.md`.

---

## 1. Cross-Target Parity Summary

| Dimension | Android ART | Desktop JVM (Win / Mac / Linux) | iOS Native (Kotlin/Native) |
| --- | --- | --- | --- |
| **Runtime & Stdlib** | ART + Android ICU + Android SDK | Azul Zulu JDK 25 (`jvmToolchain` + FFM + Swing/AWT) | Kotlin/Native (`iosArm64`, `iosSimulatorArm64`), Foundation / UIKit |
| **Rendering Backend** | Skia via Android HWUI / Canvas | Skiko: **D3D12/D3D11** (Win), **Metal** (macOS), **OpenGL/GLX** (Linux) | Skiko **Metal** inside `UIViewController` / SwiftUI |
| **Regex Engine** | **Android ICU** (diverges from JDK!) | HotSpot `java.util.regex` | Kotlin/Native regex (ICU/stdlib) |
| **SQLite Engine** | Framework `SQLiteDatabase` (WAL) | `sqlite-jdbc` or `sqlite-bundled` (custom MSVC build for `windows_arm64`!) | System `libsqlite3` via cinterop / `sqlite-bundled` |
| **Networking / Coil 3** | Ktor OkHttp + `coil-network-okhttp` | Ktor OkHttp + `coil-network-okhttp` | Ktor Darwin + `coil-network-ktor3` (**explicitly wired**, no `ServiceLoader`) |
| **Locking Primitive** | `ReentrantLock` (`jvmSharedMain`) | `ReentrantLock` (`jvmSharedMain`) | `NSRecursiveLock` (`iosMain`—never suspend while holding!) |
| **Window & System Bars** | Edge-to-edge `enableEdgeToEdge`, `SHORT_EDGES` per fullscreen window | FFM Win32 caption (Win), `disableTitleBar` (Mac), native X11/Wayland (Linux) | UIKit `UIViewController` safe areas (`WindowInsets.safeDrawing`) |
| **Packaging & Shrinking** | AGP 9 + **R8** + Baseline Profiles | `jpackage` + `jlink` + **ProGuard** (shrink-only) + **JDK 25 AOT** + `VerifyClasses` | Static `.framework` (`SharedUIKit`) linked by Xcode / SwiftUI host (`iOS 15.0+`) |

---

## 2. Android ART

### 2.1 The Fatal ICU vs. HotSpot Regex Traps
Code in `commonMain` or `jvmSharedMain` compiled and tested on Desktop JVM runs on **HotSpot's `java.util.regex`**, whereas Android executes **`java.util.regex` backed by ICU**. Two silent differences crash production Android apps while passing all JVM unit tests:

1. **`\p{Is...}` / `\p{In...}` Throws `PatternSyntaxException` on Older Android:**
   - Java-specific Unicode prefixes (`\p{IsHan}`, `\p{InCJK_Unified_Ideographs}`) fail compilation in ICU on Android 8 (API 26), crashing class initialization if declared in a top-level `val`.
   - **Rule:** Always write POSIX/ICU-portable syntax: `\p{script=Han}` and `\p{block=CJKUnifiedIdeographs}`.
2. **`\d` Matches All Unicode Decimal Digits (`\p{Nd}`):**
   - HotSpot `\d` matches `[0-9]`; Android ICU `\d` matches *every* Unicode decimal digit (full-width `０-９`, mathematical bold `𝟐`, Arabic-Indic digits). Calling `.toInt()` on a captured `\d+` group throws `NumberFormatException` on files containing stylized Unicode digits.
   - **Rule:** Always write `[0-9]` instead of `\d` (and `[^0-9]` instead of `\D`) in all Android-reachable source sets.
- **Enforcement:** Add a static source-scanner test (`AndroidRegexGuardTest`) checking `commonMain`, `jvmSharedMain`, `androidMain` for `\\p{(?:Is|In)[A-Z]` and `\\[dD]`, paired with an Android instrumentation smoke test feeding mathematical-bold and full-width digits into parsers.

### 2.2 AGP 9, R8, Insets, and Process Lifecycle
- **AGP 9 Built-In Kotlin:** AGP 9 (`9.3+`) includes Kotlin Android support natively; applying `org.jetbrains.kotlin.android` is a hard build error.
- **Test APK Transitive Alignment:** Because Android `androidTest` runs in-process with the app APK, AGP forces test dependencies to match app runtime versions (keep `androidx.test.*` aligned with runtime `concurrent-futures` / `lifecycle` pins).
- **System Bars & Cutouts:** Keep `usesCleartextTraffic="false"` (normalize `http://` -> `https://` in media mappers). Apply `LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES` only on fullscreen player/viewer windows/dialogs—never globally in the app theme.
- **Foreground Services & Notifications:** Gate foreground service notifications strictly via `ProcessLifecycleOwner` (`AppVisibility`) so progress notifications appear only when backgrounded with active transfers and retract automatically on resume.
- **Motion Scale Sync:** Attach `AppMotionScale` to the activity `DecorView`'s `WindowRecomposer` and mirror `Settings.Global.ANIMATOR_DURATION_SCALE` (`followSystemAnimatorScale`).

---

## 3. Desktop JVM (Windows, macOS, Linux)

### 3.1 JDK 25 Toolchain, FFM, ProGuard, and AOT Cache
- **Why Azul Zulu JDK 25:**
  - JDK 22+ is required for non-preview Foreign Function & Memory API (`java.lang.foreign.*`, used for Win32/COM/FFmpeg/libzstd interop without JNI C compilation).
  - **Azul Zulu 25** is required for `jlink` / `jpackage` / ProGuard packaging: Eclipse Temurin 25 omits `jmods` (breaking `jlink` & ProGuard's `java.lang.Object` lookup) and lacks Windows ARM64 JDK 25 builds; JetBrains Runtime (JBR) drifts faster and breaks binary patch consistency.
- **ProGuard Pitfalls (Shrink-Only, Never Obfuscate):**
  - Configure `-dontobfuscate` on Desktop. ProGuard's preverifier (`7.8.0` / `7.10.0`) can emit invalid `StackMapTable` frames (e.g., recording an unset `long` local as `long` instead of `top`, throwing `VerifyError` at runtime): either pass `-dontpreverify` or copy your app's own jars back over ProGuard's output (shrinking only dependencies).
  - **Mandatory `-keep` Rules ProGuard Misses (Unlike R8):**
    1. **`MethodHandles.findVirtual` FFM Upcalls:** Window procedures (`WindowsCaption.frameProc`, `childProc`) and FFmpeg `AVIO` callbacks (`AvioReader.read`, `seek`) have zero direct bytecode callers—ProGuard deletes them silently, causing Release builds to fall back to default OS titlebars or fail all remuxes.
    2. **Reflection-Invoked Compose Internals:** `compose-windows-touch` multi-pointer methods (`ComposeWindow.composePanel`, `ComposeWindowPanel._composeContainer`, `ComposeContainer.mediator`, `ComposeSceneMediator.scene$delegate`, `ComposeScene.sendPointerEvent-*`).
    3. **`META-INF/services` (`ServiceLoader`) Providers:** ProGuard does **not** automatically keep `ServiceLoader` implementations like R8 does! Explicitly keep `OkHttpNetworkFetcherServiceLoaderTarget`, `OkHttpEngineContainer`, `KotlinxSerializationJsonExtensionProvider`, `SimpleServiceProvider`, and `mediamp` / `sqlite` drivers.
    4. **Bytecode Gate:** Run `java -Xverify:all VerifyClasses.java <app-dir>` in CI to load and verify every packaged class before shipping.
- **JDK 25 AOT Cache (`app.aot`) & Timestamp Trap:**
  - Compose Gradle plugin `1.13.0-alpha01+` adds `buildTypes.release.aot` (a ~12s `-Dcompose.aot.training-run=true` launch).
  - **Isolate Training Home:** Inject a temporary `build/aot-training-home` directory during training so the build machine never logs into or mutates real user data in `~/.app`.
  - **Disable CPU-Specific Stubs:** Always pass `-XX:-AOTAdapterCaching -XX:-AOTStubCaching` during both training and runtime; CI runners with AVX-512 bake AVX-512 `AdapterBlob`s into `app.aot` that crash user CPUs without AVX-512.
  - **Strict `mtime` Validation (`aotClassLocation.cpp`):** JDK 25 invalidates the entire AOT cache if *any* classpath jar differs in byte size or second-precision `mtime`:
    - *Windows MSI:* CAB archives store local timestamps rounded to **even seconds** without timezone—installing a UTC-built MSI in UTC+8 shifts jar `mtime` by 8 hours! Align all jars to a uniform even-second epoch before training, embed `-Dapp.classpath-mtime=<epoch>`, and restore jar `mtime` on first launch so launch #2+ hits AOT cache (verify via `-Xlog:class+path`, not `"Opened AOT cache"` which prints before validation).
    - *Portable Archives:* Use `.7z` (stores UTC timestamps), never `.zip` (Windows Explorer / `Expand-Archive` ignore UTC extra fields and shift local time).
    - *Linux AppImage:* SquashFS preserves timestamps—**never set `SOURCE_DATE_EPOCH`**, or `mksquashfs` overwrites all jar timestamps and breaks AOT cache validation.

### 3.2 AWT Event Dispatch Thread (EDT) Modal Dialog Deadlock
Calling `java.awt.FileDialog` (`isVisible = true`) or `javax.swing.JFileChooser` (`showOpenDialog`) synchronously on Compose Desktop's EDT **starts a nested AWT event pump** (`WaitDispatchSupport`) while holding the active Compose coroutine frame:
- The nested pump renders a new frame and flushes Compose's non-reentrant `FlushCoroutineDispatcher`, **resuming the already-executing coroutine continuation twice** and crashing the entire window (trivially reproduced on macOS while video playback ticks frames).
- **Solution (`AwtDialogs`):** Expose *only* `suspend` functions backed by a dedicated single-thread `Executors.newSingleThreadExecutor` dispatcher (`"App-AwtDialog"`). Capture the owner `Window` at click time on the UI thread, then `withContext(dialogDispatcher)` to show the modal dialog off-EDT while the UI thread keeps rendering smoothly. Enforce via a source-scanning `AwtDialogsGuardTest`.

### 3.3 Windows Runtime Specifics (Win32 / D3D12 / Natives)
- **Custom Caption Without `undecorated` (`WindowsCaption`):**
  - Never use `WindowDecoration.Undecorated` (loses Snap Layouts, DWM shadow, Aero Shake, `Win+Arrows`, and invisible resize borders) and never return `0` unconditionally from `WM_NCCALCSIZE` (forces manual edge resize math and maximized screen inset clamping).
  - Subclass the AWT frame HWND and Skiko child canvas HWND via FFM `SetWindowLongPtrW`:
    - `WM_NCCALCSIZE`: Let `DefWindowProc` compute the standard frame, then restore `rgrc[0].top` to the window's top edge (removing *only* the top titlebar while keeping left/right/bottom resize borders and DWM 1px border/shadow).
    - `WM_NCHITTEST`: Return `HTTOP` on the top resize strip (when not maximized), `HTCAPTION` on empty drag regions, and `HTMINBUTTON` / `HTMAXBUTTON` / `HTCLOSE` on the three caption buttons (**`HTMAXBUTTON` is mandatory to trigger Windows 11 Snap Layouts on hover!**). Child canvas returns `HTTRANSPARENT` over caption regions so Windows routes hit-tests to the parent frame.
    - Drive button hover/press visuals from `WM_NCMOUSEMOVE` / `WM_NCMOUSELEAVE` / `WM_NCLBUTTONDOWN` / `WM_NCLBUTTONUP` (do not forward button clicks to `DefWindowProc`, which draws classic Win95-style buttons).
    - Render glyphs via Skia `FontMgr.default.matchFamilyStyle("Segoe Fluent Icons", ...)` -> `"Segoe MDL2 Assets"` fallback.
- **D3D12 / D3D11 Device Reset Recovery (`GpuDeviceWatch`):**
  - On GPU driver reset/upgrade (NVIDIA Event 153 / Windows TDR), Skiko `0.150` `Direct3DRedrawer` ignores `HRESULT` failures: frames freeze, and the next window resize crashes the JVM with `EXCEPTION_ACCESS_VIOLATION` in `makeDirectXSurface`.
  - Inspect `SkiaLayer.getRedrawer$skiko` -> `Direct3DRedrawer.device` (`ID3D12Device` at native pointer slot `6`) and invoke `GetDeviceRemovedReason` (vtable slot `37`) via FFM before resize and on a 1Hz heartbeat; on non-zero `HRESULT`, bump `generation++` to recreate Compose windows cleanly.
  - **Skiko Version Lock Warning (`0.150.x` vs. `0.152`–`0.156.1`):** Starting in Skiko `0.152` through `0.156.1` (CMP `1.13.0-alpha01`–`1.13.0-beta02`), `SkiaLayer.getRedrawer$skiko()`, `org.jetbrains.skiko.redrawer.Direct3DRedrawer`, and `ContextHandler` were **removed** and replaced by `SkiaLayer.frameDriverManager` and `org.jetbrains.skiko.renderer.Direct3DRenderer` (owning `device` and `DirectContext context` directly). This breaks `mediamp 0.5.0`–`0.5.3` D3D11 zero-copy video surfaces into black screens or `IllegalStateException`, and requires updating `GpuDeviceWatch` when upgrading to CMP `1.13+`. (Note: `compose-windows-touch:0.1.0` reflection targets remain intact in `ui-desktop:1.13.0-beta02`.) See [dual-target-unification-and-skiko-interop.md](../06-version-tracking/dual-target-unification-and-skiko-interop.md).
- **UTF-8 System Tray (`WindowsSystemTray`) & Non-Focus-Stealing Toasts:**
  - Compose Desktop's `Tray` uses `java.awt.PopupMenu`, whose `WMenuItemPeer` passes UTF-8 bytes from JDK 18+ straight into ANSI `AppendMenuA`—garbling CJK/Unicode menu items on CP936/non-UTF-8 Windows locales.
  - Use `java.awt.TrayIcon` (for icon + wide tooltip only) and intercept right-click to show an FFM `user32.dll` Unicode menu (`CreatePopupMenu` + `AppendMenuW` + `TrackPopupMenu`) styled with `uxtheme.dll` dark-mode ordinals (`135` / `136`).
  - For lightweight in-app notifications on Desktop, prefer a non-focus-stealing pass-through capsule overlay (`DesktopToastOverlay`) over `TrayIcon.displayMessage` (which forces noisy OS notification center banners).
- **Windows Test & Storage Gotchas:**
  - **Robolectric on Windows ARM64:** Robolectric's native runtime is unsupported on Windows 11 `aarch64`—gate Robolectric `androidHostTest` runs on Linux/x64 CI or macOS.
  - **`DataStore` `File.renameTo` on Windows:** Atomic `DataStore` file replacement fails intermittently on Windows when another reader/antivirus holds a file handle; serialize preference writes cleanly and avoid parallel file-backed `DataStore` races in Windows unit tests.
- **Windows ARM64 & Bundled Natives:**
  - Never extract bundled DLLs (`mpv`, `jnidispatch.dll`, `sqlitejdbc.dll`) into `%TEMP%` at runtime (locked DLLs fail `deleteOnExit` and bloat `%TEMP%`). Extract at build time into app resources (`mpv/`, `jna/`, `sqlite/`) and point loaders on line 1 of `main()`.
  - `androidx.sqlite:sqlite-bundled` lacks a `windows_arm64` native through `2.8.0-alpha01` (requires compiling SQLite amalgamation + `sqlite_bindings.cpp` on ARM64 MSVC); `zstd-jni` `win_aarch64` exports C symbols without JNI methods (invoke `libzstd` via JDK 25 FFM instead).

### 3.4 macOS Specifics (`arm64` / Metal)
- **Titlebar & Traffic Lights:** Set root pane properties (`apple.awt.fullWindowContent`, `apple.awt.transparentTitleBar`, `apple.awt.windowTitleVisible=false`), wait until `window.isShowing`, then call `SkiaLayer.disableTitleBar(heightDp)` **exactly once** (each call attaches another drag view & fullscreen observer). Pad custom top headers by `~76.dp` start margin for traffic lights and hide custom top chrome in `WindowPlacement.Fullscreen`.
- **AOT & Signing Conflict:** Do not generate `app.aot` after ad-hoc/developer `codesign` on `.app` bundles—mutating bundle contents post-signing breaks the code signature seal.
- **Bundle Metadata & Updates:** Ensure `CFBundleVersion` major segment `> 0` (`jpackage` rejects `0.x`); for in-app bundle replacement, validate `codesign --verify` and strip `com.apple.quarantine` before atomic directory swap.
- **System Integration:** Handle `⌘Q`, Dock click, and deep links via Apple Events; read `accessibilityDisplayShouldReduceMotion`; never block the AppKit/UI thread with `.torrent`/file hashing.

### 3.5 Linux Specifics (`x64` / X11 / Wayland / OpenGL)
- **`java.awt.Desktop` Forbidden:** Calling `java.awt.Desktop` on Linux loads system GTK & `glib`, which can collide on SONAMEs with bundled native libraries (`mpv`). Replace with `xdg-open` for URLs/files, `gdbus` (`org.freedesktop.Notifications`, `org.freedesktop.FileManager1.ShowItems`), and `systemd-inhibit`.
- **X11 `WM_CLASS` & Dock Icon Matching:** AWT defaults `WM_CLASS` to the main class name (`MainKt`), breaking `.desktop` icon matching in GNOME/KDE docks. Reflectively set `XToolkit.awtAppClassName` (requiring `--add-opens java.desktop/sun.awt.X11=ALL-UNNAMED` on Linux only) to your reverse-DNS App ID before creating windows. Omit `SingleMainWindow` from `.desktop` if targeting Ubuntu 22.04 `desktop-file-validate`.
- **Hardware OpenGL & `llvmpipe`:** Media GLX texture sharing requires `LinuxOpenGLRedrawer` on hardware drivers (`glibc 2.38+`). Detect `llvmpipe` software fallback in VMs/WSLg (`GALLIUM_DRIVER=d3d12` unset) and warn users before presenting black video surfaces.
- **AppImage Self-Relaunch Hazard:** `jpackage` injects `_JPACKAGE_LAUNCHER` into the process environment. Any child process spawning the updated AppImage **must scrub `_JPACKAGE_LAUNCHER`** from its environment (`setsid sh`), or the new launcher skips reading `.cfg` and prints `java` CLI help and exits! Never kill the outer FUSE mount runtime while an AppImage JVM process is running (`SIGBUS`).

---

## 4. iOS Native (Kotlin/Native + UIKit/SwiftUI + Skiko Metal)

- **Deployment Target Parity:** Align Kotlin/Native `-Xoverride-konan-properties=minVersion.ios=15.0` with the Xcode/SwiftUI host `MinimumOSVersion` (`15.0`). Guard any newer iOS 16+/17+ Foundation/UIKit calls behind availability checks.
- **Static Framework Export & Host:** Export `ui` + `shared` as a single static framework (`binaries.framework { isStatic = true }`) embedded in a SwiftUI `ComposeUIViewController` host (managing Xcode project cleanly via XcodeGen `project.yml`).
- **No JVM Assumptions in `commonMain`:**
  - `String.format`, `java.util.Locale`, `java.io.File`, `java.util.concurrent.locks`, `OkHttp`, and `ServiceLoader` do **not** exist in `commonMain` when `iosArm64` / `iosSimulatorArm64` targets are enabled!
  - Wire Coil 3 with `coil-network-ktor3` + `ktor-client-darwin` in `iosMain`.
  - Provide `NSRecursiveLock` (`@OptIn(ExperimentalForeignApi::class)`) for `AppLock` short critical sections (**strictly non-suspending**—never hold a recursive lock across a `suspend` call).
- **SQLite WAL Parity:** Implement the exact same WAL connection lifecycle, transaction boundaries, explicit cursor closure, and account-ownership assertions on native SQLite as on Android/Desktop—do not fall back to loading entire datasets as JSON into memory.
- **Safe Areas, Back Gestures & Build Gates:**
  - Respect `WindowInsets.safeDrawing` / `systemBars` for Dynamic Island, notch, and home indicator.
  - Hook `org.jetbrains.compose.ui:ui-backhandler` so iOS edge swipe-back integrates cleanly with Navigation 3's `BackHandler`.
  - **Verification Boundary:** Passing `compileCommonMainKotlinMetadata`, `:app:compileDebugKotlin`, and `:desktopApp:compileKotlinDesktop` on Windows/Linux does **not** verify iOS cinterop, framework linking, or native SQLite bindings. Always gate iOS changes with macOS CI (`:shared:iosSimulatorArm64Test`, `:ui:iosSimulatorArm64Test`, `MinimumOSVersion` artifact inspection, and simulator launch).
