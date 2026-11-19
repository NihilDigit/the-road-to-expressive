# Compose Maven API & Material 3 Expressive Bytecode + Source Inspector

Live Maven version tracker, AAR/JAR bytecode surface extractor (`javap` via OpenJDK 21), official Maven `*-sources.jar` Kotlin/Java declaration & default-parameter indexer, cross-platform parity differ (AndroidX Compose vs JetBrains Compose Multiplatform), and AndroidX release notes mirror.

## What It Produces

- `manifests/api/compose-versions.json` — Live latest `stable`, `rc`, `beta`, `alpha`, and `dev` versions across Google Maven (`dl.google.com/dl/android/maven2`), Maven Central (`repo1.maven.org/maven2`), and JetBrains Compose Dev (`maven.pkg.jetbrains.space/public/p/compose/dev`), including `org.jetbrains.skiko:skiko-awt`, `compose-bom` / `compose-bom-alpha` pin tables, and JetBrains CMP `.module` AndroidX redirects.
- `manifests/api/material3-expressive-surface.json` — Bytecode-verified public & `@Composable` signatures enriched with Kotlin source default-parameter expressions (`kotlin_defaults_signatures` / `kotlin_defaults_signature`), `@ExperimentalMaterial3ExpressiveApi` / `@ExperimentalMaterial3Api` / `@ExperimentalMaterial3AdaptiveApi` opt-in status, compiled numeric constants from `androidx.compose.material3.tokens.*` (`token_constants`), historical CMP alpha graduation deltas (`1.12.0-alpha03` -> latest), and exact parity diff across:
  - `material3` (AndroidX `-android` vs CMP `-desktop`)
  - `material3-adaptive-navigation-suite`
  - `adaptive`, `adaptive-layout`, `adaptive-navigation`, `adaptive-navigation3`
  - `navigation3-ui`, `navigation3-runtime`
- `.corpus/compose-maven-api/jars/` — Cached JARs and extracted `classes.jar` files from AndroidX AARs.
- `.corpus/compose-maven-api/sources/` — Cached upstream `*-sources.jar` archives (AndroidX & JetBrains CMP `material3`, `material3-adaptive-navigation-suite`, `adaptive*`, `foundation`, `ui`, `navigation3-ui`, `navigation3-runtime`, and `org.jetbrains.skiko:skiko-awt`).
- `.corpus/compose-maven-api/source-index.json` — Pure-Python Kotlin/Java declaration index mapping `public` and `internal` `@Composable fun`, `fun`, `class`, `interface`, `object`, `enum`, `val`, and `typealias` declarations to their exact `jar_name`, `entry_path`, `kdoc_start_line`/`start_line`/`end_line`, full Kotlin signature (including default parameter expressions), and KDoc.
- `.corpus/compose-maven-api/pages/` — Markdown API reference pages, parity diff reports, and mirrored AndroidX Jetpack release notes (`compose-material3`, `compose-material3-adaptive`, `compose-ui`, `compose-foundation`, `navigation3`).
- `manifests/sources/compose-maven-api.json` — Committed source manifest summary.

## Usage

```powershell
# Full sync + bytecode inspection + *-sources.jar download & Kotlin indexing
uv run python sources/compose-maven-api/refresh.py --no-assets --workers 10

# Check if upstream Maven latest versions changed
uv run python sources/compose-maven-api/refresh.py --check

# Verify generated JSON, *-sources.jar spot-checks & Markdown fidelity (line length <= 4000)
uv run python sources/compose-maven-api/refresh.py --verify
```
