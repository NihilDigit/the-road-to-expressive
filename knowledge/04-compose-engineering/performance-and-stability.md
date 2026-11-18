# Compose Multiplatform Performance, Stability, and Rendering Pitfalls

> **Scope:** Compiler stability, strong skipping, lazy container optimization, Desktop `SubcomposeLayout` popup disposal crashes, IME inset isolation, image/tile memory budgeting, Baseline Profiles, and Skia/Skiko rendering performance.  
> **Sources:** Verified against `.corpus/compose-android/pages/develop/ui/compose/performance/stability.md`, `stability/strongskipping.md`, `modifier-phases.md`, `baseline-profiles.md`, and `system/keyboard-animations.md`.

---

## 1. Compiler Stability & Strong Skipping

With Kotlin 2.0+ Compose Compiler (`org.jetbrains.kotlin.plugin.compose`), **Strong Skipping Mode** is enabled by default:
- `@Composable` functions with **unstable** parameters can now be skipped if those parameters are instance-equal (`===`) to the previous composition.
- Lambdas capturing unstable variables are auto-remembered via `remember(...)`.

### Why Stability Still Matters
1. **Unstable Mutable Collections Still Defeat Skipping:** Strong skipping compares unstable types with referential equality (`===`). Creating a fresh `List` or `MutableList` on every parent emission (`items.filter { ... }` or `mutableStateListOf` mutated in-place and wrapped in a new holder) breaks `===` and forces recomposition of all child rows.
   - Annotate pure immutable UI projection models with `@Immutable` (or `@Stable` when holding snapshot `State<T>` properties).
   - Lift expensive list filtering/sorting out of Composable bodies into `remember(items, query)` or presentation `StateFlow`s.
2. **Avoid Reading Unstable Properties in Outer Scopes:** Even with strong skipping, passing a changing `State<T>` *value* (`val progress: Float`) into a high-level screen wrapper recomposes the wrapper every frame. Pass `() -> Float` or a `@Stable` state holder down to the leaf progress bar.
3. **Verify Compiler Output:** Enable Compose compiler reports (`reportsDestination` / `metricsDestination` in `composeCompiler { ... }`) when auditing hot lazy items or animation wrappers to ensure zero accidental `@NonSkippableComposable` hot spots.

---

## 2. `LazyColumn`, `LazyVerticalGrid`, and `LazyVerticalStaggeredGrid`

### 2.1 Mandatory `key` and `contentType`
- **Always supply unique, stable `key`s:** Without `key`, inserting, sorting, or filtering items shifts positional slots, destroys item `remember` state, and cancels active item animations.
  - **Row-Instance Key vs. Domain ID Trap:** If a single domain entity can appear **more than once** in the same lazy container (e.g., duplicate-file groups showing two rows with the same file ID, or mixed-section headers), using the raw domain ID as `key` crashes with `IllegalArgumentException: Key "..." was already used`. Use a composite row-instance key (`item.rowKey` or `"${group.id}:${item.id}"`).
  - **Scroll/Selection Identity Consistency:** `visibleItemsInfo` returns the lazy `key`. Keep selection and hit-testing keyed on the exact same row-instance key rather than casting back to a domain ID prematurely.
- **Supply `contentType` on Heterogeneous Lists:** Assigning `contentType = { it::class }` (or section enum) lets Compose reuse slot compositions across headers, separators, media rows, and footers instead of tearing down and recreating subtrees during fast flings.
- **No `IntrinsicSize.Min` Inside Lazy Rows:** Measuring `IntrinsicSize` doubles child measurement passes per row. Replace `Row(Modifier.height(IntrinsicSize.Min))` with a single-pass custom `Layout` (measure fixed thumbnail first, then measure text column with `minHeight = thumb.height`).

### 2.2 Near-End Pagination (`PrefetchNearEnd` + Error Latch)
Naive `LaunchedEffect(lastVisibleIndex)` pagination loops without an error latch fire dozens of duplicate requests per second when a page fails (e.g., HTTP `-412` rate limit or offline timeout), because `lastVisibleIndex` stays near the end while `items` does not grow.
- **Mandatory Guard:** Route all infinite-scroll pagination through a single helper (`PrefetchNearEnd` / `QueuePagination`) that latches `hasError` (or `errorBefore` / `errorAfter` for bidirectional queues) and **halts automatic fetches** until the user explicitly taps `"Retry"` or triggers a manual refresh.

---

## 3. Desktop `SubcomposeLayout` Popup Disposal Crash (`RootNodeOwner is already disposed`)

This is one of the most severe Compose Desktop runtime crashes (reproducible in CMP `1.12.x`):

### Root Cause
In Compose Desktop (`CanvasLayersComposeSceneImpl.doMeasureAndLayout`), every frame snapshots the list `[mainScene, popupLayer1, popupLayer2, ...]` and measures them sequentially:
1. While measuring the main layer, containers that perform **subcomposition during the measure phase** (`SubcomposeLayout`, `BoxWithConstraints`, Material `Scaffold`, `ExposedDropdownMenuBox`, or lazy grids) run composition *inside layout*.
2. If that subcomposition removes a `Popup`, `DropdownMenu`, `Tooltip`, or `Dialog` from the tree (for example, while dragging a window border triggers a synchronous resize measure pass across a breakpoint, or `BasicTooltipBox` cancels via an `UNDISPATCHED` coroutine), Compose immediately calls `dispose()` on that popup's `RootNodeOwner`.
3. Moments later, `doMeasureAndLayout` reaches that popup in its pre-copied layer list and throws:
   ```text
   java.lang.IllegalArgumentException: RootNodeOwner is already disposed
   ```
   terminating the desktop rendering coroutine and freezing the window forever.

### Four-Layer Defense Strategy
1. **Ban `SubcomposeLayout` / `BoxWithConstraints` Around or Above Popups:** Replace custom responsive bars, toolbars, tab strips, and floating panels with single-pass **`Layout`** (all children stay composed in the slot table; unused items are simply not placed or given zero bounds). Do not use `ExposedDropdownMenuBox` in resize-sensitive toolbars.
2. **Never Mutate Popup Visibility Mid-Pointer-Pass or via `UNDISPATCHED` Coroutines:** Drive custom hover tooltips (`AdaptiveTooltip`) exclusively from `LaunchedEffect` (frame-scheduled) and forward pointer/wheel dismissal signals through a conflated `Channel<Unit>`.
3. **Freeze Breakpoint `WindowInfo` During Live Border Drag (`SettledWindowInfo`):** Delay layout-mode swaps (sidebar collapse, 2-pane collapse, tab bar toggle) until `WM_EXITSIZEMOVE` completes (see `window-size-and-canonical-layouts.md` §4.2).
4. **Window-Level Recovery Fallback (`isDisposedLayerRace`):** In the desktop window's uncaught exception handler, match `IllegalArgumentException` with message `"RootNodeOwner is already disposed"` and increment the window's `key(generation)` to rebuild the window cleanly instead of crashing the JVM. *(Re-verify the exact `require` message string whenever upgrading Compose Multiplatform.)*

---

## 4. IME / Soft-Keyboard Inset Isolation

Attaching `Modifier.imePadding()` or reading `WindowInsets.ime` on a root `Scaffold` that wraps a `LazyColumn` of hundreds of rich-text items (comments, chat messages, search threads) forces Compose to **remeasure the entire `LazyColumn` and every visible item on every single frame (60–120fps) of the keyboard slide animation**, dropping frames on mid-range Android devices.

**Zero-Remeasure Architecture:**
1. **Decouple the Prompt Bar from `WindowInsets.ime`:** Place an inert pill trigger (`CommentPromptBar`) at the bottom of the list that **never reads `WindowInsets.ime`**. The underlying list stays at 100% static viewport height while typing.
2. **Isolate the Active Composer:** Open a dedicated `Dialog` / overlay sheet (`CommentComposerDialog`) to host the live `TextField` + `imePadding()` + emoji/attachment picker.
3. **1:1 Keyboard-to-Panel Height Handoff (`SettledKeyboardHeightTracker`):**
   - Measure net keyboard height per screen orientation (`(WindowInsets.ime.getBottom(density) - WindowInsets.navigationBars.getBottom(density)).coerceAtLeast(0)`).
   - Update `settledDp` **only** when `targetImeDp >= currentImeDp - 0.5f` (rising or settled) and `currentImeDp > 120.dp`, clamped to `[180.dp, 560.dp]` (never cap at a low `360.dp`, as high-DPI IMEs with toolbars routinely reach `380–420.dp`!).
   - Freeze `settledDp` while the keyboard is retracting so switching between IME and an in-app emoji/sticker panel renders `complementPanelDp = (settledDp - currentImeDp).coerceAtLeast(0f)` with **zero vertical jump**.
4. **Avoid Double Bottom Insets in `ModalBottomSheet`:** Material 3 `ModalBottomSheet` already applies `BottomSheetDefaults.windowInsets` (`safeDrawing.only(Bottom + Top)`). Do not blindly stack `navigationBarsPadding()` on inner `footer` slots inside `ModalBottomSheet`; apply `navigationBarsPadding()` conditionally only in inline side-pane or custom dialog hosts.

---

## 5. Image Loading, Prefetching, Tiling, and Memory Budgets

### 5.1 Coil 3 Multiplatform Configuration
- **Explicit Network Fetcher:** Coil 3 silently fails image requests if no network fetcher is installed:
  - Android / Desktop JVM: Register `OkHttpNetworkFetcherFactory` explicitly (and install any `ProxySelector` *before* creating `ImageLoader` / `OkHttpClient`).
  - iOS Native: Add `coil-network-ktor3` + `ktor-client-darwin` (`ktor-client-core` in `commonMain`, `ktor-client-okhttp` on JVM).
- **HTTPS & Anti-Hotlink Normalization:** Many APIs return `http://` or protocol-relative `//` URLs that Android's default `usesCleartextTraffic = false` blocks. Normalize to `https://` and inject required `Referer` headers inside a single shared `AsyncImage` wrapper (`AppAsyncImage`), never scattered across screens.
- **Desktop Disk Cache Hygiene:** Redirect Coil's `DiskCache` directory to your app's own data/cache directory (`AppHome.root/cache/images`), **not** the default system `%TEMP%/coil3_disk_cache` where private user thumbnails leak across users or survive app uninstall.
- **High-Latency Grid Concurrency:** Desktop OkHttp `Dispatcher` defaults (`maxRequests = 64`, `maxRequestsPerHost = 5`) throttle multi-column thumbnail grids. Raising `maxRequests = 96` and `maxRequestsPerHost = 32` eliminates head-of-line stalls on CDN hosts.

### 5.2 Zero-Decode Prefetching & Tiling Large Images
- **Disk Prefetch Without CPU Bitmap Thrash:** When pre-warming off-screen thumbnails (e.g., `GalleryCanvas` lookahead), issue Coil requests with `BlackholeDecoder` and `CachePolicy.READ_ONLY` (memory cache disabled) so compressed bytes populate disk cache with zero bitmap allocation or main-thread decode overhead.
- **Full-Screen Image Tiling:** Use `zoomimage-compose-coil3` (`ZoomImage`) for full-screen viewers so multi-megapixel images decode sub-sampled viewport tiles from disk. Activate tile decoding **only for the currently settled pager page** (`settledPage`) so adjacent swiped pages don't thrash or evict the shared thumbnail `MemoryCache`.

### 5.3 Memory Governance & Offscreen Snapshots
- **Bounded Snapshot Cache:** If capturing live page thumbnails (e.g., `WorkspacePageSnapshot` for narrow-window tab overviews), cap longest edge at `512px`, throttle capture cadence (`>= 350ms`), pause capture while the overview is open, and evict LRU entries under a strict byte budget (e.g., `8 MiB`).
  - *Known Skiko Caveat:* Repeated `GraphicsLayer.toImageBitmap()` pixel readbacks on Desktop Skia have been observed to trigger rare native `RenderNode` access violations in stress scenarios—gate capture strictly to visible, settled frames (`LocalWorkspaceSnapshotEnabled`).
- **Central Memory Governor (`AppMemoryGovernor`):** Bound heavy streaming/decode caches proportionally (`128–512 MiB`, e.g. 1/8 max JVM heap on Desktop) and trim caches dynamically in response to Android `ComponentCallbacks2.onTrimMemory` / `onLowMemory`.

---

## 6. Baseline Profiles (Android) & Skia/Skiko Rendering

### 6.1 Android Baseline Profiles
- ART interprets/JIT-compiles DEX bytecode on cold launch unless guided by a **Baseline Profile** (`androidx.benchmark:benchmark-macro-junit4` + `androidx.profileinstaller`).
- Always generate and ship `baseline-prof.txt` covering:
  1. Cold start -> Main scaffold -> Initial list composition.
  2. Fast vertical/grid scrolling (`LazyColumn` / `LazyVerticalGrid`).
  3. Opening the primary detail sheet/player route.
- Note: Compose libraries ship their own library baseline profiles merged by AGP, but **your app's theme, navigation routes, and custom list items** still suffer JIT jank on first scroll without an app-level Baseline Profile.

### 6.2 Skia / Skiko Rendering Rules (Desktop & iOS)
- **Avoid Unnecessary Offscreen RenderLayers:** `Modifier.alpha(x)` (when `0 < x < 1`) and `Modifier.shadow(...)` with non-default clipping allocate offscreen layers in Skia. Prefer color alpha (`background(color.copy(alpha = x))`) for flat surfaces, and use `graphicsLayer` when animating opacity/scale so Skia caches the layer across frames.
- **Reduced Motion Compliance (`MotionDurationScale`):** Inject a single process-wide `MotionDurationScale` (e.g., `AppMotionScale`) into the root `Recomposer` coroutine context (`MainActivity` `WindowRecomposer` on Android; `runBlocking(motionScale) { awaitApplication { ... } }` on Desktop so all child windows & popups inherit it).
  - When `scaleFactor == 0f`, Compose `Transition` and `SuspendAnimation` jump straight to target values—**except** infinite loops (`rememberInfiniteTransition`), which freeze at frame 0/end! Read `reducedMotion` explicitly on shimmer skeletons and spinners to render clean static placeholders instead of frozen mid-pulse alpha states.
- **Text Line-Height & Font Fallback Cost:** Disable `includeFontPadding = false` and standardize `LineHeightStyle.Alignment.Center` across typography tokens to eliminate per-line baseline drift without extra layout passes; on Desktop Skia, cache `FontMgr.default.matchFamilyStyle(...)` lookups (`by lazy`) rather than resolving system fonts inside Composition.
