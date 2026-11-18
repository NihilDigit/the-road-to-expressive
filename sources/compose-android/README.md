# Android Jetpack Compose, Navigation 3 & UI Design Mirror

Mirrors the official Android Developer documentation from `developer.android.com` into `.corpus/compose-android/pages/`, respecting `robots.txt`.

## Scope

- `/develop/ui/compose/**` — Complete Jetpack Compose guide (architecture, state, lifecycle, phases, performance, stability, baseline profiles, layouts, adaptive/window size classes, canonical layouts, modifiers, pointer/keyboard/stylus input, animations, graphics, text, theming/M3, accessibility, testing, interop).
- `/guide/navigation/navigation-3/**` — Navigation 3 (`NavDisplay`, `NavEntry`, `SnapshotStateList`, `SceneStrategy`).
- `/design/ui/mobile/**` — Android Mobile UI Design & Quality Guidelines (Android's official HIG equivalent).
- `/design/ui/large-screens/**` & `/design/ui/desktop/**` — Android Large-Screen, Desktop & Adaptive Design Guidelines (pointer interactions, windowing/multi-task, system bars).

## Usage

```powershell
# Full mirror (no images, 10 workers)
uv run python sources/compose-android/refresh.py --no-assets --workers 10

# Check upstream changes via conditional requests & article SHA-256
uv run python sources/compose-android/refresh.py --check

# Verify HTML->Markdown fidelity and max line length <= 4000
uv run python sources/compose-android/refresh.py --verify
```
