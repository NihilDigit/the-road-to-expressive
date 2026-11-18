# Material Design 3 Expressive Mirror (`m3-expressive`)

Mirrors the official [Material Design 3](https://m3.material.io/) site and DSDB design token database into `.corpus/m3-expressive/` and exports structured M3 Expressive tokens to `manifests/tokens/m3-expressive-tokens.json`.

## What It Captures

1. **All 95 Carbon Routes** from `m3.material.io`'s Angular bundle (`main.*.js`), including:
   - **Blog & Expressive Features**: `blog`, `building-with-m3-expressive`, `m3-expressive-motion-theming`, `material-is-compose-first`, `enhance-your-component-designs-with-parametric-prototyping`, `whats-new-at-io26`.
   - **Foundations**: Adaptive design, layouts, canonical examples, desktop, XR, watches, interaction/inputs/gestures/states, accessibility, and Content Design / UX writing (`foundations/content-design/*`, `foundations/writing`).
   - **Styles**: Color (system, roles, dynamic, static, choosing a scheme, advanced), Motion (`MotionScheme` overview, easing & duration, transitions), Shape (10-tier scale & morphing), Typography (15 baseline + 15 `*Emphasized` + variable font axes), Elevation, Spacing, Icons.
   - **Components**: All 39 component pages including Expressive components (`button-groups`, `split-button`, `fab-menu`, `toolbars`, `loading-indicator`, `progress-indicators`, `navigation-bar`, `navigation-rail`, `carousel`, `search`, `lists`, `bottom-sheets`, `side-sheets`, `dialogs`, etc.).
   - **Develop**: Jetpack Compose, MDC-Android, Flutter, Web.
2. **DSDB System & Component Token Tables** (`_dsm/data/dsdb-m3/<carbonVersion>/`):
   - `COLOR`, `TYPOGRAPHY`, `TOKEN_TYPE_UNSPECIFIED` (Shape, Motion, State opacities), `ELEVATION`, `MEASUREMENT`, `STATUS_TABLE`, and all 37 component `TOKEN_TABLE` files.
   - Rendered as Markdown tables inside `.corpus/m3-expressive/pages/**/*.md` AND exported in structured form to `manifests/tokens/m3-expressive-tokens.json`.

## Usage

```bash
uv run python sources/m3-expressive/refresh.py --no-assets --workers 10 --verify
uv run python sources/m3-expressive/refresh.py --check
uv run python sources/m3-expressive/refresh.py --verify
```
