# Microsoft Fluent 2 & Windows App Design Guidelines Mirror (`windows-fluent`)

Mirrors BOTH:
1. [Fluent 2 Design System](https://fluent2.microsoft.design/) (via `sitemap-index.xml`)
2. [Windows App Design Guidelines](https://learn.microsoft.com/en-us/windows/apps/design/) and Windows HIG UI / Input / Accessibility / Notifications guides (`learn.microsoft.com/en-us/windows/apps/develop/toc.json`)

## Usage

```bash
uv run python sources/windows-fluent/refresh.py --no-assets --workers 10 --verify
uv run python sources/windows-fluent/refresh.py --check
uv run python sources/windows-fluent/refresh.py --verify
```
