---
name: expressive-ui
description: Query the local Road to Expressive corpus via bare `rtx` commands (`rtx spec`, `rtx component`, `rtx api`, `rtx source`, `rtx token`, `rtx copy`, `rtx search`) for Material 3 Expressive official design specs & tokens, upstream Compose Multiplatform / AndroidX / Skiko Kotlin source & default parameters, Gradle Compose BOM / CMP dual-target version unification, Skiko native GPU surface interop (`Direct3DRenderer`, `FrameDriver`, D3D11/Metal), ProGuard / JDK AOT rules, adaptive layouts, multi-input patterns, cross-platform HIG (Apple/Windows/GNOME/KDE), and UX writing / AP Style rules. Use whenever designing, reviewing, upgrading, or implementing Compose UI, Gradle Compose dependencies, desktop/iOS runtime interop, adaptive layouts, design tokens, or UI copy.
---

# Expressive UI Corpus Skill (`rtx`)

Use this skill to ground every UI design decision, Material 3 Expressive component choice, Compose Multiplatform API call, Skiko/desktop interop detail, platform HIG tradeoff, and UI string in live local upstream mirrors, cached Maven `*-sources.jar` Kotlin implementations, bytecode parity manifests, and verified design tokens.

> **CLI Invocation**: `rtx` is installed globally on `PATH` (via `uv tool install --editable . --force`) and resolves the corpus automatically from any workspace directory. Run bare `rtx ...` commands directly!
> *(Fallback if `rtx` is not globally installed on `PATH`: `uv run --project <path-to-the-road-to-expressive> rtx ...`)*

---

## Mandatory Design-First Gate (3-Step Top-Down Pre-Design Reading Funnel)

**Before proposing a UI plan, choosing a widget, or custom-drawing ANY UI component**, you MUST walk this 3-step funnel using live upstream specs from `.corpus/`:

### Step 1 — Screen Skeleton & Canonical Layouts (`rtx spec`)

Before picking any component, read the official layout, breakpoint, scaffold, and canonical multi-pane structure:

```bash
rtx spec "canonical layouts"
rtx spec "desktop scaffold breakpoints"
```

This pulls noise-stripped upstream sections directly from `m3-expressive` (`foundations/layout/canonical-examples.md` [List-Detail, Supporting Pane, Feed], `scaffold.md`, `breakpoints.md`, `desktop.md`), `compose-android` (`across-form-factors.md`), and `apple-hig` (`layout.md`).

### Step 2 — Cross-Component Emphasis & Task Patterns (`rtx spec`)

Before committing to a component class, read the **cross-component comparison & pattern pages** so you pick the right visual weight, modality, and single canonical entry point:

```bash
# Action emphasis ladder (FAB vs Filled vs Tonal vs Outlined vs lightweight Text/IconButton):
rtx spec "button emphasis"

# Selection & filtering (Checkbox vs Switch vs Radio vs Chip vs ToggleButton vs Menu):
rtx spec "selection filtering"

# Modality & transient feedback (Snackbar vs Sheet vs Dialog — NEVER custom-draw fake Toasts!):
rtx spec "transient feedback snackbar dialog"

# Mutually exclusive navigation chrome & single canonical entry point:
rtx spec "navigation bar rail toolbar duplicate"

# Search entry points & docked vs full-screen focused search:
rtx spec "search bar docked fullscreen"

# Domain patterns (Media / Settings / Inputs & Drag-and-Drop / Loading):
rtx spec "video player fullscreen immersive"
rtx spec "settings page organization"
rtx spec "inputs gestures drag drop"
rtx spec "loading progress"
```

Key design guardrails verified from upstream specs:
- **Never custom-draw a fake Toast overlay** when standard `Snackbar` / `SnackbarHost` exists.
- **Check emphasis weight** before using heavy `ButtonGroup` / filled pills where lightweight text/icon/chip controls fit better.
- **Verify single canonical entry points**: never show `NavigationRail` and `ShortNavigationBar` simultaneously or paint duplicate visible buttons for the same action on one screen.

### Step 3 — Specific Component Variants & Official Do/Don'ts (`rtx component`)

Once you have candidate components, read their **lossless official M3 Expressive dossier** (`Overview & Variants`, `Usage`, `Official Do & Don't Rules`, `Adaptive Design & Placement`, `Behavior`), **Desktop & Mobile HIG counterparts**, **key tokens**, and **Kotlin signatures with default parameters** in one batch call:

```bash
rtx component SearchBar Carousel Tabs Snackbar NavigationRail
rtx component FloatingToolbar ButtonGroup SplitButtonLayout
```

---

## CRITICAL: Swarm & Subagent Propagation Rule

> **Subagents and Swarm workers start with a blank context and will NOT load `expressive-ui` on their own when handed a concrete file list.**
>
> Whenever you (as a Coordinator or Parent Agent) spawn **ANY** worker or subagent that designs, audits, or implements UI, layouts, navigation, player controls, settings, design tokens, or Skiko/Compose code, you **MUST** include this exact instruction in its `brief`:
>
> ```text
> Load the expressive-ui skill first and run rtx spec / rtx component / rtx source before writing UI code.
> ```

---

## Zero `javap` Needed: Inspect Exact Kotlin Defaults & Upstream Source (`rtx api` + `rtx source`)

Never manually glob `.gradle/caches` with `javap` or guess experimental annotations, default parameter values, or internal Compose/Skiko behavior from memory!

### 1. Check Parity, Opt-Ins & Kotlin Default Parameters (`rtx api`)

```bash
# Check latest alpha/beta/rc/stable Maven versions and AndroidX vs CMP parity deltas
rtx api material3 --diff

# Batch-query symbols with Kotlin default parameter expressions + @OptIn status
rtx api HorizontalMultiBrowseCarousel WideNavigationRail ButtonGroup --target common
rtx api ListDetailSceneStrategy --target desktop
```

Key checks before writing Kotlin/Compose code:
- Inspect the `kotlin:` declaration lines for exact **default parameter expressions** (e.g., `flingBehavior = CarouselDefaults.singleAdvanceFlingBehavior(state = state)`).
- Confirm whether the symbol requires `@OptIn(ExperimentalMaterial3ExpressiveApi::class)` or `@OptIn(ExperimentalMaterial3Api::class)`.
- Compare `androidx:` vs `cmp:` signatures to prevent desktop/iOS compilation failures.

### 2. Read Exact Upstream Kotlin KDoc & Implementation (`rtx source`)

`rtx source` opens the locally cached Maven `*-sources.jar` archives (`material3`, `foundation`, `ui`, `adaptive`, `navigation3`, `skiko`) directly and prints exact line-numbered KDoc + Kotlin/Java implementation:

```bash
rtx source HorizontalMultiBrowseCarousel
rtx source TabRowDefaults.PrimaryIndicator
rtx source WideNavigationRailItem
rtx source SkiaLayer --artifact skiko
rtx source SearchBar DockedSearchBar --limit 3 --context-lines 2
```

Use `--artifact <filter>` (e.g., `cmp-material3`, `androidx-material3`, `foundation`, `ui`, `navigation3`, `skiko`), `--max-lines N`, or `--json` when needed.

---

## Tokens, Knowledge Handbooks, Runtime Interop & UX Copy

### Query M3 Expressive Design Tokens (`rtx token`)

```bash
rtx token MotionScheme largeIncreased displayLargeEmphasized
rtx token largeIncreased --category shape
rtx token Emphasized --category typography
rtx token surfaceContainer --category color
```

### Search Curated Engineering Handbooks & Mirrors (`rtx search`)

Prefer curated `knowledge/` handbooks for Gradle BOM unification, Skiko `Direct3DRenderer` / `FrameDriver` native GPU interop, ProGuard / JDK AOT rules, and multi-input engineering:

```bash
rtx search "Direct3DRenderer FrameDriver" --layer knowledge
rtx search "compose-bom dual-target ProGuard AOT" --layer knowledge
rtx search "WindowSizeClass compact height landscape" --layer knowledge
rtx search "ContextMenuArea long press" --layer knowledge
rtx search "Navigation 3 NavDisplay backstack" --layer mirror --source compose-android
```

### Query UX Writing & AP Style Rules (`rtx copy`)

```bash
rtx copy "sentence case title case"
rtx copy "error message recovery"
rtx copy "numerals dates tabular"
rtx copy "destructive button confirmation"
```

---

## Corpus Freshness & Verification

Check corpus status and tracked Maven versions at any time:

```bash
rtx status
```

If `.corpus/index.db` or `source-index.json` needs rebuilding or refreshing:

```bash
rtx index
rtx doctor
```

Add `--json` to any query subcommand when structured output is easier to parse.
