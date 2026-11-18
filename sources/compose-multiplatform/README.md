# Compose Multiplatform & KMP Documentation Mirror

Mirrors the official Kotlin Multiplatform and Compose Multiplatform guide pages (`kotlinlang.org/docs/multiplatform/`) and Dokka package/type indexes (`/api/compose-multiplatform/`) into `.corpus/compose-multiplatform/pages/`.

## Scope

- **KMP Guide**: Architecture, project structure, code sharing, iOS UIKit/SwiftUI integration, Desktop JVM window/tray/menu/keyboard/mouse/AOT, testing, compatibility.
- **Compose Multiplatform**: Layouts, adaptive design, navigation, lifecycle/ViewModel, resources, platform specifics (Android, iOS, Desktop, Web).
- **Dokka API Reference**: Package and type index pages from `/api/compose-multiplatform/sitemap.xml`, deduplicating repeated source-set blocks (`common` preserved first).

## Usage

```powershell
# Mirror guides + Dokka package/type indexes (fast, no images)
uv run python sources/compose-multiplatform/refresh.py --no-assets --workers 10

# Check upstream changes via conditional ETag/Last-Modified requests
uv run python sources/compose-multiplatform/refresh.py --check

# Verify fidelity & line lengths <= 4000 chars
uv run python sources/compose-multiplatform/refresh.py --verify
```
