# Apple Human Interface Guidelines Mirror (`apple-hig`)

Mirrors the official [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines) via Apple's structured DocC JSON endpoints (`developer.apple.com/tutorials/data/index/design--human-interface-guidelines` and per-topic `.json` payloads).

## Coverage

- Foundations: Layout, Color, Typography, Motion, Accessibility, Writing, Icons, Dark Mode, Materials
- Platforms: iOS, iPadOS, macOS, tvOS, visionOS, watchOS
- Patterns, Inputs (Touch, Pointing devices, Keyboards, Apple Pencil, Gestures), and Components

## Usage

```bash
uv run python sources/apple-hig/refresh.py --no-assets --workers 10 --verify
uv run python sources/apple-hig/refresh.py --check
uv run python sources/apple-hig/refresh.py --verify
```
