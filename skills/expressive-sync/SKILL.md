---
name: expressive-sync
description: Incrementally sync upstream documentation mirrors, Maven bytecode API manifests, and M3 Expressive token tables via `uv run rtx sync`, inspect targeted diffs (`rtx changelog`), map affected citations (`rtx impact`), and update only the impacted `knowledge/` guides without drift. Use whenever updating the corpus or checking for upstream Material 3, Compose, or HIG changes.
---

# Expressive Corpus Incremental Sync & Maintenance (`rtx sync`)

Use this workflow whenever updating upstream mirrors, Maven alpha/beta API manifests, or M3 Expressive tokens, and keeping `knowledge/` aligned with zero drift.

## Turnkey 4-Step Update Workflow

Run all commands from the repository root using `uv run rtx`.

### Step 1: Run Incremental Upstream Sync

```bash
uv run rtx sync --all --no-assets --workers 10 --diff-report
```

What this does automatically:
- Uses conditional HTTP (`ETag`, `Last-Modified`, `304 Not Modified`) across all `sources/*/refresh.py` adapters.
- Refreshes Maven alpha/beta/rc/stable versions and `javap` bytecode signatures (`manifests/api/`).
- Rebuilds `.corpus/index.db` SQLite FTS5 tables.
- Diffs the new state against `.corpus/snapshot.json.gz` and writes `.corpus/sync-diff.json`.

To sync a single source:
```bash
uv run rtx sync compose-maven-api --diff-report
```

### Step 2: Inspect Targeted Changelogs & Impacted Knowledge Citations

Never re-read the whole corpus. Inspect only what changed and which `knowledge/` sections cite it:

```bash
uv run rtx changelog
uv run rtx impact
```

Pass `--json` to either command when you need machine-readable diffs (`pages.modified[].changed_sections`, `api.graduated_opt_ins`, `api.signature_changes`, `tokens.changed`, `impacted_sections`, `live_advisories`).

### Step 3: Update Only Impacted `knowledge/` & `manifests/`

For each entry listed in `rtx impact`:
1. Inspect the exact `changed_sections`, `graduated_opt_ins`, or `tokens.changed` entry in `rtx changelog`.
2. Open the cited `knowledge/*.md` file at the reported line/heading and update only the affected rules, version pins, `@OptIn(...)` annotations, signatures, or token values.
3. Keep every Markdown line `<= 4000` characters and preserve valid relative links.

### Step 4: Verify Zero Drift

```bash
uv run rtx index
uv run rtx doctor
uv run pytest
```

Confirm:
- `rtx doctor` exits `0` with `FTS5 index health: OK`, zero broken links, and zero lines `> 4000` chars.
- `uv run pytest` passes all checks.
- `git status` shows `.corpus/` remains gitignored while updated `manifests/` and `knowledge/` files are clean for commit.
