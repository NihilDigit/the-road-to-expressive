# Linux Desktop Human Interface Guidelines Mirror (`linux-hig`)

Mirrors BOTH:
1. [GNOME Human Interface Guidelines](https://developer.gnome.org/hig/) (patterns, adaptive scaling, header bars, navigation, pointer & touch, keyboard shortcuts, writing style)
2. [KDE Human Interface Guidelines](https://develop.kde.org/hig/) (Kirigami convergence/adaptive patterns, desktop vs mobile controls, navigation, text & labels)

## Usage

```bash
uv run python sources/linux-hig/refresh.py --no-assets --workers 10 --verify
uv run python sources/linux-hig/refresh.py --check
uv run python sources/linux-hig/refresh.py --verify
```
