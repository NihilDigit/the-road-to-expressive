# State Architecture, Compose Phases, and Navigation 3

> **Scope:** Unidirectional data flow (UDF), Compose rendering phases, state holders vs. ViewModels, reactive primitives (`derivedStateOf` vs `remember` vs `snapshotFlow`), optimistic mutations, Navigation 3 backstack invariants, and multiplatform abstraction strategies.  
> **Sources:** Verified against `.corpus/compose-android/pages/develop/ui/compose/state.md`, `phases.md`, `state-callbacks.md`, `.corpus/compose-android/pages/guide/navigation/navigation-3/basics.md`, `custom-layouts.md`, `save-state.md`, `.corpus/compose-multiplatform/pages/docs/multiplatform/compose-navigation-3.md`, and `manifests/api/material3-expressive-surface.json`.

---

## 1. Unidirectional Data Flow (UDF) & Ownership Boundaries

Every cross-platform screen obeys strict **State Down, Events Up** layering:

```
Domain / Repository (shared)
   │  exposes read-only StateFlow<T>
   ▼
Presentation State Holder / ViewModel (account or screen scoped)
   │  projects read-only Compose State<T> or immutable UI snapshots
   ▼
Stateless / Skippable Composable UI (ui / commonMain)
   │  dispatches typed user intents / callbacks upward
   ▼
Presentation / Mutation Coordinator  ──▶  Repository / Optimistic Overlay
```

### Non-Negotiable State Contracts
1. **Never pass `MutableState` or `MutableStateFlow` to UI Composables.**
   - Expose read-only `State<T>` (for snapshot-backed presentation state) or `StateFlow<T>` collected via `collectAsStateWithLifecycle()`.
2. **Transient Events vs. Durable Outcomes:**
   - Ephemeral UI toasts/snackbars use bounded, non-suspending `SharedFlow` / `Channel(Channel.BUFFERED)` or drop-oldest queues so background workers never block waiting for UI collection.
   - **Critical failure states, pending confirmations, and undo/retry entry points must live in queryable durable state**—never solely in a fire-and-forget `SharedFlow`. If a Snackbar fires while the user is in a detached player window or navigating, a pure `SharedFlow` event is lost forever.
   - Distinguish "stale data banner" (`loadError != null` while cached list remains visible) from "empty state" (`items.isEmpty() && loadError == null`).
3. **Network Timeouts Are Unknown Outcomes, Not Rollback Proof:**
   - When a mutation request times out or loses connection, do **not** treat it as guaranteed unexecuted on the server. Surface an explicit `Unknown` / `"Verify"` state and query authoritative server state before retrying or declaring failure.

---

## 2. The Three Compose Phases (Composition -> Layout -> Drawing)

Every Compose frame executes three ordered phases:

| Phase | Question Answered | Cost if Triggered Repeatedly | How to Defer State Reads Here |
| --- | --- | --- | --- |
| **1. Composition** | *What* UI tree exists? | Highest: executes `@Composable` functions, diffs slots, allocates nodes | Keep composition pure; read rapidly changing values *below* this phase |
| **2. Layout** | *Where* and *how big* is each node? | Medium: runs `measure` and `place` passes | Read scroll/drag offsets inside `Modifier.offset { IntOffset(x, y) }` instead of `Modifier.offset(x.dp, y.dp)` |
| **3. Drawing** | *What pixels* render? | Lowest: executes GPU/Skia draw commands | Read animated scale, alpha, rotation, translation, and color tints inside `Modifier.graphicsLayer { ... }` or `Modifier.drawBehind { ... }` / `drawWithContent { ... }` |

### High-Impact Phase Optimizations
- **Scroll-Linked Animations & Parallax:** Never read `scrollState.value` or `lazyListState.firstVisibleItemScrollOffset` directly inside a `@Composable` body to pass `Dp` parameters to modifiers. Pass a lambda `() -> Int` or read inside `graphicsLayer { translationY = ... }` / `offset { ... }` so scrolling skips Composition completely.
- **Color & Alpha Animations:** When animating background/hover/fade state (`animateFloatAsState` / `animateColorAsState`), read `alphaState.value` inside `graphicsLayer { alpha = ... }` or `drawBehind { drawRect(colorState.value) }` rather than `Modifier.alpha(alpha)` or `Modifier.background(color)`.
- **Single-Pass `Layout` Over `IntrinsicSize` / `BoxWithConstraints`:** Computing sibling dimensions in one custom `Layout` measure block (measuring child A first, passing its measured height as `minHeight` to child B) eliminates subcomposition and double-measurement passes on every list item.

---

## 3. Plain State Holders vs. ViewModels & Scope Separation

| Concern | Owner Type | Lifetime | Examples |
| --- | --- | --- | --- |
| **Business Session & Account Workspaces** | Account-scoped `ViewModel` (`AccountPresentationStores`) or Repository | Survives navigation, layout breakpoint swaps, and narrow/wide resize; destroyed only on account switch / logout | `WorkspaceViewModel` (tabs, duplicate finder scans, import drafts, detail panel store) |
| **Screen / Destination Data** | `ViewModel` bound to `NavEntry` (`ViewModelStoreNavEntryDecorator`) | Lives while its `NavKey` remains on the Navigation 3 backstack | `SpaceViewModel`, `ArticleViewModel`, `CommentViewModel` |
| **UI Element & Gesture Coordination** | Plain State Holder (`@Stable class` via `remember` or `rememberSaveable`) | Bound to UI element lifecycle (or hoisted in ViewModel if shared across adaptive panes) | `LazyListState`, `PaneSheet` / `SidePaneState`, `SettledKeyboardHeightTracker`, `FolderMapState` |

### Scoped Execution Separation
- **Read/UI Subscriptions:** Cancel when the browsing tab, sheet, or screen leaves scope (browsing child `CoroutineScope`).
- **Accepted Write Executions:** Launch on an account-level execution scope (`AccountExecutionScopes`) so closing a bottom sheet or switching tabs mid-save does **not** cancel an accepted upload, move, or archive commit.
- **Snapshot Target Binding:** When opening a composer/import draft, capture the default target directory/context *at creation time* (`SaveTargetContext`). Subsequent browsing in other tabs must never silently mutate an open draft's save destination.

---

## 4. `derivedStateOf` vs. `remember(keys)` vs. `snapshotFlow`

Choosing the wrong reactive primitive causes either **frame-by-frame recomposition storms** or **stale UI bugs**:

| Primitive | Use When... | Anti-Pattern / Trap | Verified Example |
| --- | --- | --- | --- |
| **`derivedStateOf { ... }`** | Inputs (Snapshot `State`) change **far more frequently** than the computed result (e.g., scroll offset -> boolean, collection -> count) | Wrapping non-Snapshot inputs (`val` params) without `rememberUpdatedState`, or wrapping 1:1 transforms where output changes every time input changes (adds snapshot observer overhead for zero gain) | `val scrolled by remember { derivedStateOf { scrollState.value > 0 } }`<br>`val activeCount by remember(state) { derivedStateOf { state.activity.active.size } }` |
| **`remember(k1, k2) { ... }`** | Performing a synchronous calculation or creating a helper/filter list keyed on discrete parameters that change infrequently | Reading Snapshot `State` *inside* `remember(Unit) { state.x }` (captures initial value forever and ignores updates!) | `val results = remember(items, query) { filterAndScore(items, query) }` |
| **`snapshotFlow { ... }`** | Bridging Compose Snapshot `State` reads into a cold `Flow` inside `LaunchedEffect` / coroutines (to debounce, `distinctUntilChanged`, `collectLatest`, `first { ... }`, or combine with backend flows) | Calling `snapshotFlow` directly during Composition without `LaunchedEffect`; reading non-Snapshot mutable properties inside it | `LaunchedEffect(pagerState) { snapshotFlow { pagerState.currentPage }.collect(session::moveTo) }`<br>`snapshotFlow { if (caption.isSizing) null else live.containerSize }` |

---

## 5. Optimistic UI Updates Without Double-Refetch Flicker

Two complementary rules keep interactive feeds and file managers responsive without visual jumping:

### 5.1 Local Counter Adjustments (No Post-Write Refetch)
For idempotent toggle/counter mutations (like, bookmark, favorite, coin):
- Update the local state and counter **immediately** upon user tap; rollback only if the mutation fails.
- **Never** immediately trigger a full detail/item refetch after a successful toggle: CDN/cache lag on high-traffic items frequently returns the pre-mutation count for 1–2 seconds, causing the counter to flicker `100 -> 101 -> 100 -> 101`.

### 5.2 Overlay Projection for Structural Mutations (`OptimisticWrites`)
For list/tree mutations (rename, move, trash, delete, restore) across shared caches:
1. **Immutable Base + Pending Overlay:** Store pending mutations in `MutableStateFlow<List<Write>>` (`OptimisticWrites`), each carrying its `before: Map<String, FileStat>`, `change`, and `done: CompletableDeferred<Unit>`.
2. **Per-ID Ordering:** When queuing a new write affecting `ids`, collect `predecessors = all.filter { it.ids.any(ids::contains) }.map { it.done }`. The network worker calls `write.awaitTurn()` so sequential operations on the same file execute in exact user-accepted order without locking unrelated files.
3. **Pure Projection Layer:** Lists, folder trees, search, and libraries apply `optimisticWrites.project(...)` over the confirmed base cache.
4. **Targeted Settle:**
   - **On success:** Commit the canonical delta to the repository (`applyChange`) *and* remove only that `Write` from `pending` (completing `write.done`).
   - **On failure:** Remove *only* that rejected `Write` from `pending`; surviving optimistic writes for other items continue projecting cleanly without resetting the whole list.

---

## 6. Navigation 3 (`SnapshotStateList<NavKey>`) & Backstack Deduplication

Navigation 3 (`androidx.navigation3:navigation3-runtime` / `navigation3-ui`) eliminates graph DSLs: your backstack is literally a `SnapshotStateList<NavKey>` passed to `NavDisplay`.

### 6.1 Mandatory `NavBackStack` Setup
- Define `@Serializable` routes implementing `NavKey`, registered in a `SavedStateConfiguration` `SerializersModule` (`polymorphic(NavKey::class)`) so `rememberNavBackStack` persists across Android process death **and compiles on non-JVM targets (iOS/Web)** where reflection-based serialization is unavailable (`.corpus/compose-multiplatform/pages/docs/multiplatform/compose-navigation-3.md#L80-L105`).
- Always attach both decorators on `NavDisplay`:
  - `rememberSaveableStateHolderNavEntryDecorator()` (preserves `rememberSaveable` scroll/tab state per `NavKey`)
  - `rememberViewModelStoreNavEntryDecorator()` (scopes `viewModel(...)` per `NavKey`)

### 6.2 The Three-Layer Duplicate `NavKey` Hazard (`pushUnique`)
`NavBackStack` forwards `add()` straight to the underlying list **with zero deduplication**. Pushing a `NavKey` already present in the stack (e.g., tapping `@author` on an author's own space/profile page, or deep-linking to an already-open folder) triggers three severe bugs verified against `navigation3-runtime 1.1.5` & `runtime-saveable 1.10.2`:

1. **Shared ViewModel & Saveable Slot:** Both entry decorators index by `NavKey` equality. Two identical keys share the *exact same* `ViewModelStore` and `SaveableStateHolder` slot.
2. **Popping One Wipes Both:** Popping the top duplicate runs `clearKey(contentKey)`, destroying the lower entry's `ViewModel` while leaving stale `rememberSaveable` state behind.
3. **Simultaneous Composition Crash:** During animated transitions or predictive back, both the top and underlying entries compose simultaneously, tripping `SaveableStateHolder.SaveableStateProvider`'s `require(key !in registries) { "Key $key was used multiple times" }`!

**Mandatory Policy (`NavBackStackPolicy.kt`):**

```kotlin
/** Reorders existing key to top in the same frame (REORDER_TO_FRONT semantics). */
fun MutableList<NavKey>.pushUnique(key: NavKey): Boolean {
    if (lastOrNull() == key) return false // Already on top; caller can scroll-to-top or show notice
    remove(key)
    add(key)
    return true
}

/** Replaces top entry while guaranteeing stack-wide uniqueness. */
fun MutableList<NavKey>.replaceTopUnique(key: NavKey) {
    for (i in lastIndex - 1 downTo 0) {
        if (this[i] == key) removeAt(i)
    }
    if (isEmpty()) add(key) else this[lastIndex] = key
}
```
- Because `remove(key)` and `add(key)` execute in the **same snapshot/frame**, Navigation 3 sees `key` present in both the previous and next backstack snapshots—so it preserves the entry's `ViewModel` and `SaveableState` intact while moving it to the top!
- **Root Floor Invariant:** Never call `backStack.clear()` when switching top-level sections or resetting home. Pop down to `backStack.size > 1` (`while (backStack.size > 1) backStack.removeLastOrNull()`) so the root `Home` key always stays anchored.

---

## 7. Multiplatform Abstraction: `commonMain` Interfaces vs. `expect`/`actual`

| Mechanism | Best Used For | Avoid When |
| --- | --- | --- |
| **`commonMain` Interface + Platform Impl (`AppPlatform`, `SystemActions`, `PlaybackHost`)** | Complex platform services (file pickers, window caption, media playback, credential keychains, capability flags `supports*`) | Tiny value helpers or leaf composables that need no lifecycle or DI |
| **`CompositionLocalProvider` (`LocalAppPlatform`, `LocalAppServices`)** | Injecting process-wide services and platform handles into `commonMain` UI cleanly without singletons (`Application.instance` banned!) | Rapidly mutating per-frame values without `State` wrapping |
| **Intermediate Source Set (`jvmSharedMain`)** | Pure-JDK logic shared identically by `androidMain` and `desktopMain` (e.g., `OkHttp` `ProxySelector`, `java.io.File` caches, `ReentrantLock`) without touching `iosMain` | Anything importing `java.awt.*`, `android.*`, or `androidx.*` |
| **`expect` / `actual`** | Small, zero-dependency leaf primitives with distinct native APIs (`AppLock` -> `ReentrantLock` / `NSRecursiveLock`; `ListScrollbar` -> `VerticalScrollbar` / no-op) | Large feature subsystems (creates rigid constructor contracts and awkward test faking) |

- **Capability Flags Over OS Checks:** Never write `if (isDesktop)` or `if (isAndroid)` inside `commonMain` UI to toggle features. Expose explicit capability booleans/nullables on the platform interface (e.g., `shareFile: ((...) -> Unit)? = null`, `ExternalVideoPlayer.requiresDirectUrl: Boolean`) and omit/hide UI entries when `null`/`false`.
