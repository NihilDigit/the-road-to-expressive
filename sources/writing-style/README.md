# UI Copywriting, UX Writing & AP Style Mirror (`writing-style`)

Mirrors authoritative public UX writing, microcopy, and AP-style reference guides (respecting `robots.txt` and TLS; no paywalled sources):

1. [Google Developer Documentation Style Guide](https://developers.google.com/style/) — sentence case, numbers, dates/times, commas/Oxford comma, active voice, UI elements, error messages, and explicit AP/Chicago comparisons
2. [Microsoft Writing Style Guide](https://learn.microsoft.com/en-us/style-guide/welcome/) — brand voice, UI text, buttons, menus, error messages, punctuation, capitalization, numbers, global/localization readiness
3. [18F Content Guide](https://github.com/18F/content-guide) — public-domain AP-based web & UI style guide (numbers, percentages, punctuation, capitalization, technical & interface writing)
4. [AP Stylebook Overview](https://en.wikipedia.org/wiki/AP_Stylebook) — AP Stylebook mechanics & historical rules overview
5. [Mailchimp Content Style Guide](https://styleguide.mailchimp.com/) — voice & tone, grammar & mechanics, web/UI elements
6. [Digital.gov Plain Language Guidelines](https://digital.gov/guides/plain-language/)

Cross-links to platform UX writing pages in sibling corpora:
- `.corpus/apple-hig/pages/writing.md`
- `.corpus/linux-hig/pages/gnome/guidelines/writing-style.md`
- `.corpus/linux-hig/pages/kde/text_and_labels.md`
- `.corpus/m3-expressive/pages/` (Content design)

## Usage

```bash
uv run python sources/writing-style/refresh.py --no-assets --workers 10 --verify
uv run python sources/writing-style/refresh.py --check
uv run python sources/writing-style/refresh.py --verify
```
