# AGENTS.md

Instructions for AI coding agents working inside or querying `the-road-to-expressive`.

## Environment & Tooling

- Use `uv` exclusively for all Python commands:
  - `uv sync`
  - `uv tool install --editable . --force` (installs bare `rtx` globally on `PATH`)
  - `rtx ...` (or `uv run rtx ...` inside this repo; `uv run --project <path-to-the-road-to-expressive> rtx ...` from external workspaces if not globally installed)
  - `uv run pytest`
  - `uv run python ...`
- Do not modify `.corpus/` manually; it is gitignored runtime output managed by `sources/*/refresh.py` and `rtx index`.
- Keep all Markdown lines in `knowledge/` and `.corpus/*/pages/` at `<= 4000` characters so grep and indexers stay fast.
- Do not add static derived design-opinion docs; upstream design guidance is served dynamically from `.corpus/` via `rtx spec` and `rtx component`.

## Querying Before Implementing UI (3-Step Design-First Funnel)

When using this repository as a reference for building Compose Multiplatform or Material 3 Expressive interfaces:

1. **Step 1 — Screen Skeleton & Canonical Layouts (`rtx spec`)**:
   ```bash
   rtx spec "canonical layouts"
   rtx spec "desktop scaffold breakpoints"
   ```
2. **Step 2 — Cross-Component Emphasis & Task Patterns (`rtx spec`)**:
   ```bash
   rtx spec "button emphasis"
   rtx spec "selection filtering"
   rtx spec "transient feedback snackbar dialog"
   rtx spec "navigation bar rail toolbar duplicate"
   rtx spec "search bar docked fullscreen"
   ```
3. **Step 3 — Lossless Official Component Dossier (`rtx component`)**:
   ```bash
   rtx component SearchBar Carousel Tabs Snackbar NavigationRail
   ```
4. **Verify Maven Parity, Kotlin Defaults & Upstream Source (`rtx api` + `rtx source`)** — zero manual `javap` needed:
   ```bash
   rtx api material3 --diff
   rtx api HorizontalMultiBrowseCarousel --target common
   rtx source HorizontalMultiBrowseCarousel
   rtx source TabRowDefaults.PrimaryIndicator
   rtx source SkiaLayer --artifact skiko
   ```
5. **Verify Tokens, Copy & Engineering Handbooks (`rtx token`, `rtx copy`, `rtx search`)**:
   ```bash
   rtx token MotionScheme largeIncreased displayLargeEmphasized
   rtx copy "sentence case title case"
   rtx search "Direct3DRenderer FrameDriver" --layer knowledge
   ```

> **Swarm / Subagent Propagation**: Whenever spawning a worker or subagent that touches UI, layouts, navigation, settings, or Compose/Skiko code, include in its `brief`: `Load the expressive-ui skill first and run rtx spec / rtx component / rtx source before writing UI code.`

## Incremental Corpus Updates

When updating upstream mirrors, Maven API / `*-sources.jar` indexes, or M3E tokens (see `skills/expressive-sync/SKILL.md`):

```bash
rtx sync --all --no-assets --workers 10 --diff-report
rtx changelog
rtx impact
```

Update only the `knowledge/` sections flagged by `rtx impact` and `rtx doctor`, then re-run the Integrity Gate.

## Integrity Gate

Before finishing changes to `knowledge/`, `manifests/`, `sources/`, or `src/rtx/`:

```bash
rtx index
rtx doctor
uv run pytest
```
