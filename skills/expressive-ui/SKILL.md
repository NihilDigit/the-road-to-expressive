---
name: expressive-ui
description: Query the local Road to Expressive corpus via `uv run rtx` for Material 3 Expressive tokens, Compose Multiplatform vs AndroidX alpha/beta API parity, Gradle Compose BOM / CMP dual-target version unification, Skiko / native GPU surface interop (`Direct3DRenderer`, `FrameDriver`, D3D11/Metal), ProGuard / JDK AOT rules, adaptive layouts, multi-input patterns, cross-platform HIG (Apple/Windows/GNOME/KDE), and UX writing / AP Style rules. Use whenever designing, reviewing, upgrading, or implementing Compose UI, Gradle Compose dependencies, desktop/iOS runtime interop, adaptive layouts, design tokens, or UI copy.
---

# Expressive UI Corpus Skill (`rtx`)

Use this skill to ground UI architecture, Material 3 Expressive tokens, Compose Multiplatform APIs, platform HIG decisions, and UI copywriting in verified local manifests, bytecode signatures, and mirrored official documentation.

## When to Use

- Implementing or updating Material 3 Expressive components (`SplitButton`, `ButtonGroup`, `FloatingToolbar`, `VerticalFloatingToolbar`, `FlexibleTopAppBar`, `WideNavigationRail`, `ShortNavigationBar`, `LoadingIndicator`, `LinearWavyProgressIndicator`, `MotionScheme`).
- Checking whether an experimental M3E or Navigation 3 API exists in JetBrains Compose Multiplatform (`org.jetbrains.compose.material3`) vs AndroidX (`androidx.compose.material3`) before writing code.
- Aligning Gradle Compose BOM / CMP dual-target dependency versions, upgrading Skiko / native GPU surface interop (`Direct3DRenderer`, `FrameDriver`, D3D11/Metal), or updating ProGuard / JDK AOT keep rules.
- Designing adaptive layouts (`WindowSizeClass` width & height, canonical List-Detail / Supporting Pane / Feed, `ListDetailSceneStrategy`) or multi-input support (touch, mouse hover/right-click, keyboard shortcuts, stylus).
- Reconciling Material 3 Expressive with Apple HIG, Microsoft Windows/Fluent 2, GNOME HIG, or KDE HIG.
- Writing or auditing UI microcopy, labels, error states, confirmations, numerals, dates, or CJK text.

## Core Query Workflow

Run commands from the corpus repository root using `uv run rtx`, or from **any external project directory** using `--project` or `--directory`:

```bash
# From inside the-road-to-expressive:
uv run rtx status

# From any other repository (cross-repo invocation):
uv run --project <path-to-the-road-to-expressive> rtx status
# or:
uv run --directory <path-to-the-road-to-expressive> rtx status
```

Add `--json` to any query subcommand when structured output is easier to parse.

### 1. Check Corpus Freshness & Tracked Versions

```bash
uv run rtx status
```

If `.corpus/index.db` is missing or stale after pulling updates, rebuild or sync:

```bash
uv run rtx index
# Optional live refresh from upstream docs & Maven:
uv run rtx sync --all --no-assets --workers 10
```

### 2. Inspect One or Multiple Components in a Batch

Start with `rtx component` for a unified view combining M3E tokens, bytecode-verified Compose APIs, adaptive layout rules, and Apple/Windows/Linux HIG notes (pass multiple names in one call to avoid repeated shell invocations):

```bash
uv run rtx component SplitButton
uv run rtx component FloatingToolbar ButtonGroup SplitButtonLayout
```

### 3. Verify Maven Versions & AndroidX vs CMP API Parity

Never guess Compose experimental annotations or parameter lists from memory — query one or multiple symbols in a single batch:

```bash
# Check latest alpha/beta/rc/stable versions and parity deltas
uv run rtx api material3 --diff
uv run rtx api ButtonGroup FloatingToolbar MaterialShapes --target common
uv run rtx api ListDetailSceneStrategy --target desktop
```

Key checks before writing Kotlin/Compose code:
- Confirm whether the symbol requires `@OptIn(ExperimentalMaterial3ExpressiveApi::class)` or `@OptIn(ExperimentalMaterial3Api::class)`.
- Compare `androidx_signature` vs `cmp_signature` to avoid desktop/iOS compilation failures.

### 4. Query M3 Expressive Tokens

```bash
uv run rtx token MotionScheme largeIncreased
uv run rtx token largeIncreased --category shape
uv run rtx token Emphasized --category typography
uv run rtx token surfaceContainer --category color
```

### 5. Search Knowledge Handbooks, Runtime Interop & Official Mirrors

Prefer curated `knowledge/` handbooks first (including Gradle BOM unification, Skiko `Direct3DRenderer` / `FrameDriver` GPU interop, and ProGuard / JDK AOT rules), then drill into `.corpus/` mirror pages for exact upstream wording:

```bash
uv run rtx search "Direct3DRenderer FrameDriver" --layer knowledge
uv run rtx search "compose-bom dual-target ProGuard AOT" --layer knowledge
uv run rtx search "WindowSizeClass compact height landscape" --layer knowledge
uv run rtx search "ContextMenuArea long press" --layer knowledge
uv run rtx search "Navigation 3 NavDisplay backstack" --layer mirror --source compose-android
uv run rtx search "window title bar snap layouts" --layer mirror --source windows-fluent
```

### 6. Query UX Writing & AP Style Rules

```bash
uv run rtx copy "sentence case title case"
uv run rtx copy "error message recovery"
uv run rtx copy "numerals dates tabular"
uv run rtx copy "destructive button confirmation"
```

## Verification Checklist

After applying guidance or updating corpus knowledge:
1. Run `uv run rtx doctor` to confirm zero broken links, zero lines `> 4000` chars, and healthy FTS5 indexes.
2. Verify all Compose API calls against `manifests/api/material3-expressive-surface.json` and `manifests/api/compose-versions.json`.
3. Verify all token names against `manifests/tokens/m3-expressive-tokens.json`.
