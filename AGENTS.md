# AGENTS.md

Instructions for AI coding agents working inside or querying `the-road-to-expressive`.

## Environment & Tooling

- Use `uv` exclusively for all Python commands:
  - `uv sync`
  - `uv run rtx ...`
  - `uv run pytest`
  - `uv run python ...`
- Do not modify `.corpus/` manually; it is gitignored runtime output managed by `sources/*/refresh.py` and `rtx index`.
- Keep all Markdown lines in `knowledge/` and `.corpus/*/pages/` at `<= 4000` characters so grep and indexers stay fast.

## Querying Before Implementing UI

When using this repository as a reference for building Compose Multiplatform or Material 3 Expressive interfaces (from inside this repo with `uv run rtx ...`, or from another workspace with `uv run --project <path-to-the-road-to-expressive> rtx ...` / `uv run --directory <path-to-the-road-to-expressive> rtx ...`):

1. Check current status and tracked bleeding-edge versions:
   ```bash
   uv run rtx status
   uv run rtx api material3 --diff
   ```
2. Query unified component guidance (M3E tokens + Compose API + Adaptive + Platform HIG):
   ```bash
   uv run rtx component <ComponentName>
   ```
3. Verify exact tokens (`MotionScheme`, 10-step `Shapes`, `*Emphasized` typography, color roles):
   ```bash
   uv run rtx token <query>
   ```
4. Check UX writing / microcopy rules (Material Content Design + AP Style + platform guides):
   ```bash
   uv run rtx copy <topic>
   ```
5. Run full-text BM25 search for deep links into `knowledge/` and mirrored docs:
   ```bash
   uv run rtx search "<query>" --layer knowledge
   uv run rtx search "<query>" --layer mirror --source apple-hig
   ```

## Incremental Corpus Updates

When updating upstream mirrors, Maven API surfaces, or M3E tokens (see `skills/expressive-sync/SKILL.md`):

```bash
uv run rtx sync --all --no-assets --workers 10 --diff-report
uv run rtx changelog
uv run rtx impact
```

Update only the `knowledge/` sections flagged by `rtx impact` and `rtx doctor`, then re-run the Integrity Gate.

## Integrity Gate

Before finishing changes to `knowledge/`, `manifests/`, `sources/`, or `src/rtx/`:

```bash
uv run rtx index
uv run rtx doctor
uv run pytest
```
