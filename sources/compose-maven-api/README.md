# Compose Maven API & Material 3 Expressive Bytecode Inspector

Live Maven version tracker, AAR/JAR bytecode surface extractor (`javap` via OpenJDK 21), cross-platform parity differ (AndroidX Compose vs JetBrains Compose Multiplatform), and AndroidX release notes mirror.

## What It Produces

- `manifests/api/compose-versions.json` — Live latest `stable`, `rc`, `beta`, `alpha`, and `dev` versions across Google Maven (`dl.google.com/dl/android/maven2`), Maven Central (`repo1.maven.org/maven2`), and JetBrains Compose Dev (`maven.pkg.jetbrains.space/public/p/compose/dev`), including `org.jetbrains.skiko:skiko-awt`, `compose-bom` / `compose-bom-alpha` pin tables, and JetBrains CMP `.module` AndroidX redirects.
- `manifests/api/material3-expressive-surface.json` — Bytecode-verified public & `@Composable` signatures, `@ExperimentalMaterial3ExpressiveApi` / `@ExperimentalMaterial3Api` / `@ExperimentalMaterial3AdaptiveApi` opt-in status, compiled numeric constants from `androidx.compose.material3.tokens.*` (`token_constants`), historical CMP alpha graduation deltas (`1.12.0-alpha03` -> latest), and exact parity diff across:
  - `material3` (AndroidX `-android` vs CMP `-desktop`)
  - `material3-adaptive-navigation-suite`
  - `adaptive`, `adaptive-layout`, `adaptive-navigation`, `adaptive-navigation3`
  - `navigation3-ui`, `navigation3-runtime`
- `.corpus/compose-maven-api/jars/` — Cached JARs and extracted `classes.jar` files from AndroidX AARs.
- `.corpus/compose-maven-api/pages/` — Markdown API reference pages, parity diff reports, and mirrored AndroidX Jetpack release notes (`compose-material3`, `compose-material3-adaptive`, `compose-ui`, `compose-foundation`, `navigation3`).
- `manifests/sources/compose-maven-api.json` — Committed source manifest summary.

## Usage

```powershell
# Full sync + bytecode inspection
uv run python sources/compose-maven-api/refresh.py --no-assets --workers 10

# Check if upstream Maven latest versions changed
uv run python sources/compose-maven-api/refresh.py --check

# Verify generated JSON & Markdown fidelity (line length <= 4000)
uv run python sources/compose-maven-api/refresh.py --verify
```
