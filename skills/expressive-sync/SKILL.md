---
name: expressive-sync
description: Incrementally sync upstream documentation mirrors, Maven bytecode + Kotlin `*-sources.jar` manifests, and M3 Expressive token tables via `rtx sync`, inspect targeted diffs (`rtx changelog`), map affected citations (`rtx impact`), and update only the impacted `knowledge/` guides without drift. Use whenever updating the corpus or checking for upstream Material 3, Compose, Skiko, or HIG changes.
---

# Expressive Corpus Incremental Sync & Maintenance (`rtx sync`)

Use this workflow whenever updating upstream mirrors, Maven alpha/beta/rc API & `*-sources.jar` manifests, or M3 Expressive tokens, and keeping `knowledge/` aligned with zero drift.

## Turnkey 4-Step Update Workflow

Run commands directly via global `rtx` on `PATH` (or `uv run rtx` from the repository root).

### Step 1: Run Incremental Upstream Sync

```bash
rtx sync --all --no-assets --workers 10 --diff-report
```

What this does automatically:
- Uses conditional HTTP (`ETag`, `Last-Modified`, `304 Not Modified`) across all `sources/*/refresh.py` adapters.
- Refreshes Maven alpha/beta/rc/stable versions, `javap` bytecode signatures (`manifests/api/`), cached `*-sources.jar` archives (`.corpus/compose-maven-api/sources/`), and `.corpus/compose-maven-api/source-index.json` (Kotlin signatures with default parameter values + KDoc line spans).
- Rebuilds `.corpus/index.db` SQLite FTS5 tables (`docs_fts`, `api_fts`, `tokens_fts`, `kotlin_sources_fts`).
- Diffs the new state against `.corpus/snapshot.json.gz` and writes `.corpus/sync-diff.json`.

To sync a single source:

```bash
rtx sync compose-maven-api --diff-report
```

### Step 2: Inspect Targeted Changelogs & Impacted Knowledge Citations

Never re-read the whole corpus. Inspect only what changed and which `knowledge/` sections cite it:

```bash
rtx changelog
rtx impact
```

Pass `--json` to either command when you need machine-readable diffs (`pages.modified[].changed_sections`, `api.graduated_opt_ins`, `api.signature_changes`, `tokens.changed`, `impacted_sections`, `live_advisories`).

### Step 3: Update Only Impacted `knowledge/` & `manifests/`

For each entry listed in `rtx impact`:
1. Inspect the exact `changed_sections`, `graduated_opt_ins`, or `tokens.changed` entry in `rtx changelog`.
2. Open the cited `knowledge/*.md` file at the reported line/heading and update only the affected rules, version pins, `@OptIn(...)` annotations, signatures, or token values.
3. Keep every Markdown line `<= 4000` characters and preserve valid relative links.
4. Do not add static derived design-opinion docs; upstream design guidance is served live from `.corpus/` via `rtx spec` and `rtx component`.

### Step 4: Verify Zero Drift

```bash
rtx index
rtx doctor
uv run pytest
```

Confirm:
- `rtx doctor` exits `0` with `FTS5 index health: OK`, zero broken links, and zero lines `> 4000` chars.
- `uv run pytest` passes all checks.
- `git status` shows `.corpus/` remains gitignored while updated `manifests/` and `knowledge/` files are clean for commit.
