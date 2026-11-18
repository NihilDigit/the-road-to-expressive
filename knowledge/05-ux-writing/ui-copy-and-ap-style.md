# UI Copy, UX Writing, and AP Style Reference

> **Purpose:** Authoritative microcopy, editorial mechanics, localization, and accessibility-copy handbook for cross-platform Compose Multiplatform interfaces.
> **Primary Upstream Sources:** [M3 Content Design Overview](../../.corpus/m3-expressive/pages/foundations/content-design/overview.md), [M3 Style Guide](../../.corpus/m3-expressive/pages/foundations/content-design/style-guide.md), [M3 Global Writing](../../.corpus/m3-expressive/pages/foundations/content-design/global-writing.md), [M3 Alt Text](../../.corpus/m3-expressive/pages/foundations/content-design/alt-text.md), [M3 Notifications](../../.corpus/m3-expressive/pages/foundations/content-design/notifications.md), [M3 Writing & Text](../../.corpus/m3-expressive/pages/foundations/writing.md), [AP Stylebook Overview](../../.corpus/writing-style/pages/ap-style/ap-stylebook-overview.md), [Google Style Guide](../../.corpus/writing-style/pages/google-style/capitalization.md), [Microsoft Style Guide](../../.corpus/writing-style/pages/microsoft-style/capitalization.md), [Fluent 2 Content Design](../../.corpus/windows-fluent/pages/fluent2/content-design.md), [18F Content Guide](../../.corpus/writing-style/pages/18f-content-guide/our-style/technical-and-interface-writing.md), [Apple HIG Writing](../../.corpus/apple-hig/pages/writing.md), [GNOME HIG Writing Style](../../.corpus/linux-hig/pages/gnome/guidelines/writing-style.md), and [KDE HIG Text & Labels](../../.corpus/linux-hig/pages/kde/text_and_labels.md).

---

## 1. Cross-Ecosystem Editorial Matrix

Material 3 Content Design explicitly defaults to the **Associated Press (AP) Stylebook** unless noted otherwise (`overview.md:22`, `style-guide.md:121`). Where platform Human Interface Guidelines (Apple, GNOME, KDE, Fluent 2) diverge—such as menu capitalization or ellipsis triggers—native desktop chrome adapts to host conventions while shared in-app UI stays consistent.

| Rule / Element | Material 3 + Google Style | AP Stylebook / 18F Baseline | Microsoft / Fluent 2 | Apple HIG (iOS / macOS) | GNOME HIG / KDE HIG |
| --- | --- | --- | --- | --- | --- |
| **Capitalization** | **Sentence case** everywhere (`style-guide.md`) | Sentence case headings in 18F; AP headlines traditionally vary, web UI uses sentence case | **Sentence case** on Windows, Android, web; **title case** when targeting iOS/macOS (`fluent2/content-design.md`) | Title case on macOS menu items & alert/notification titles; sentence case in body (`the-menu-bar.md`, `writing.md`) | GNOME: **Header** case (headings, tabs, buttons, menus) vs **Sentence** case (checkboxes, dialogs, tooltips); KDE: Title case on standalone buttons/tabs, sentence case on labels/subtitles |
| **Serial (Oxford) Comma** | **Required** (`A, B, and C`), except before `&` (`style-guide.md:164`) | AP: usually omitted in simple series unless needed for clarity; 18F/Google require it | **Required** (`commas.md:15`) | Standard clear punctuation | Follow target locale; avoid dense 3-clause UI lists |
| **Periods in UI** | **Omit** on labels, tooltips, bullets, single-sentence dialogs/snackbars; use on multi-sentence blocks | Omit on UI headings & short fragments | **Omit** on titles, UI text, simple lists (<= 3 words); use after all full multi-word prose sentences (`periods.md`) | Omit on buttons, labels, menu items; use on multi-sentence alerts | Omit trailing periods on labels, headers, tooltips, single-sentence check items |
| **Ellipsis (`…` vs `...`)** | **Omit** on buttons/menus that open dialogs (`style-guide.md:218`); use **only** for in-progress states (`Saving…`) or truncation; docs write `...` spaced in prose (`ellipses.md`) | Use sparingly (`...` in quoted omission) | Use Unicode `…` (`ellipses.md:13`); no ellipsis in docs referencing UI labels (`Select Safety`); `...` fallback only if font lacks glyph | Unicode **`…` (U+2026)** on menu items requiring further user input (`Print…`, `Save As…`) (`the-menu-bar.md`) | GNOME: **`…`** (never `...`) strictly on actions opening a dialog/prompt (`writing-style.md`); KDE: consistent follow-up cue |
| **Contractions** | **Recommended** (`don't`, `can't`) for scannability (`contractions.md`); spell out `do not` only for high-stakes caution | Conversational plain-language contractions encouraged | **Recommended** (`use-contractions.md`) | Natural contractions welcome in friendly alerts | GNOME/KDE: clear natural tone; avoid stiff phrasing |
| **Voice & Person** | Active voice, **second person** (`you`), present tense; avoid `we`/`I` unless necessary | Active voice, imperative verbs, direct `you` | Active voice, **second person** (`you`), present tense; avoid `we`/`Microsoft` (`fluent2/content-design.md`) | Clear, direct, person-centric (`writing.md`) | GNOME: imperative/active; KDE: **never** use `you` in terse error blame |

---

## 2. Capitalization & Casing Rules

### 2.1 Default Sentence Case (Material 3, Google, Fluent 2 Windows/Android/Web)
1. Capitalize **only** the first word of a label, heading, tab, button, menu item, caption, table header, or dialog title, plus proper nouns and standard all-caps acronyms (`PDF`, `USB`, `HDR`) (`style-guide.md`, `capitalization.md`).
2. **After a colon (`:`):** Begin with **lowercase** unless the following word is a proper noun, a full heading, a direct quote, or follows a severity prefix (`Note:`, `Caution:`, `Warning:`) (`capitalization.md:56-64`).
3. **Hyphenated first words:** Capitalize only the first segment (`Case-by-case basis`, `Real-time sync`) unless the second segment is a proper noun (`Non-English`) (`capitalization.md:77`).
4. **Never use ALL CAPS blocks:** Avoid uppercase button labels, overlines, or badges (`ADD TO CART`, `NEW`). Screen readers may spell individual letters (`N-E-W`), uppercase blocks slow word-shape recognition, and unicase scripts lack uppercase forms (`style-guide.md:299-305`, `accessibility.md:45`).
5. **Exact code / literal strings:** Never auto-capitalize identifiers, flags, filenames, or commands at the start of a sentence unless already capitalized in code (`technical-and-interface-writing.md:82`).

### 2.2 When Desktop Native Chrome Overrides Sentence Case
Cross-platform apps adapting their native window menu bar (`MenuBar` on macOS, native Linux headerbars/menus) follow the host OS capitalization rule *inside that native surface* (`fluent2/content-design.md:87-101`):
- **macOS (`NSMenu` / system menu bar):** Title Case (`New Window`, `Save As…`, `Check for Updates…`), keeping short articles (`a`, `an`, `the`), short prepositions, and conjunctions (`and`, `or`, `for`) lowercase unless first or last.
- **GNOME / GTK native dialogs vs header bars:** Header Capitalization on top-level header buttons/tabs/menus (`Open Folder…`); Sentence Capitalization on check buttons, radio labels, and secondary explanatory text (`writing-style.md`).
- **Windows / Android / in-app Compose UI:** Keep **sentence case** everywhere (`Save changes`, `Check for updates`, `Sort by date`).

---

## 3. Numerals, Units, Ranges & Tabular Alignment (`tnum`)

### 3.1 Prose vs. UI Numerals (AP Style Reconciled with UI Constraints)
- **Running prose / documentation (`google-style/numbers.md`, `microsoft-style/numbers.md`):** Spell out `zero` through `nine` (`four files`, `two steps`); use Arabic numerals for `10` and above (`12 items`, `100 requests`), mixing digits consistently if two numbers in the same category compare items across the boundary (`4 of 12 downloads`). Always spell out a number that starts a sentence (or rewrite so the numeral moves inside).
- **UI microcopy, counters, tables & badges (M3 override):** Always use **numerals (`0`–`9`)** inside chips, counters, durations, percentages, measurements, ratings, versions, ages, dates, and compact labels (`3 unread`, `2 min left`, `4.8 stars`, `v2.4`, `0 errors`).
- **Commas & million-scale abbreviations (`style-guide.md:176-192`):**
  - Insert commas in exact numbers from `1,000` to `999,999` (`1,185 reviews`).
  - Omit commas in identifying numbers (years `2026`, ports `8080`, IDs `#10492`, street addresses).
  - Above `1,000,000`, abbreviate approximate volume counters (`23M views`, `1.4M`) when precision is not required; keep exact `1,240,510` in financial/telemetry views.

### 3.2 Units, Dates, Times & Ranges
- **Spacing (`units-of-measure.md:17-60`):** Put a nonbreaking space (`\u00A0`) between a number and its unit (`64\u00A0GB`, `16\u00A0dp`, `25\u00A0mm`, `300\u00A0K`, `50\u00A0°C`)—**never** attach `64GB`. Exceptions with **no space**: currency (`$10`), percent (`65%`), and angle degrees (`180°`). Distinguish decimal SI units (`kB`, `MB`, `GB`) from binary IEC units (`KiB`, `MiB`, `GiB`) accurately (`units-of-measure.md:23`).
- **Time & date formatting (`dates-times.md`, `style-guide.md:264`, `dashes-hyphens.md:35-37`):**
  - AP / Google time style uses numerals + space + uppercase `AM`/`PM` (`9:00 AM`, `9 AM–Noon`) or 24-hour ISO in technical logs (`2026-11-18T15:10:00Z`).
  - **Ranges:** In prose, write `-40 °C to 85 °C` (repeating the unit and using `to` so hyphens aren't read as subtraction). In compact UI labels, use an **en dash (`–`)** without spaces for numeric/short ranges (`2015–2017`, `9 AM–Noon`), or Microsoft's spaced en dash when full clock/date timestamps appear (`2:15 PM – 4:45 PM`) (`dashes-hyphens.md:19,35-37`).
- **Negative numbers:** Use the true minus sign `−` (`U+2212`) in editorial math/temperatures (`−12°F`, `12 − 3 = 9`) where supported; never substitute an en dash `–` (`dashes-hyphens.md:23,39-41`).

### 3.3 Compose Tabular Numerals (`tnum`) Mandate
Any dynamic numeric UI element—timers, scrubbers, byte-transfer speeds, download percentages, pagination counters, file sizes, or numeric table columns—**must** apply `fontFeatureSettings = "tnum"` (via a shared `TextStyle.tabular` helper; see [m3-expressive-foundations.md](../01-design-systems/m3-expressive-foundations.md#4-typography--multilingual-rules)). Proportional digits (`1` vs `8`) cause horizontal layout jitter on every tick unless tabular figures lock every glyph advance width.

---

## 4. Punctuation, Ellipses & Separator Hygiene

### 4.1 Punctuation Checklist
| Mark | Rule in UI Microcopy | Anti-Pattern |
| --- | --- | --- |
| **Period (`.`)** | Use **only** on multi-sentence blocks or full explanatory paragraphs. Omit on headings, tabs, buttons, chips, list rows, tooltips, and single-sentence snackbars/dialogs (`style-guide.md:125-146`). | `"Item deleted."` on a 2-word snackbar; `"Save changes."` on a button. |
| **Ellipsis (`…`)** | Always use the single Unicode glyph **`…` (`U+2026`)**, never three ASCII dots `...`. In M3 UI, use **only** for active in-progress states (`Connecting…`, `Saving…`) or overflow truncation—**omit** on buttons/menus that open dialogs (`style-guide.md:218`). *Exception:* On native macOS/GNOME desktop menu bars (`Save As…`, `Export…`), retain `…` when a command requires a follow-up dialog (`the-menu-bar.md`, `writing-style.md`). | `"Loading..."` (ASCII dots) or `"Settings…"` on a standard navigation item. |
| **Comma (`,`)** | Include the Oxford/serial comma before `and`/`or` in 3+ item lists (`style-guide.md:164`, `commas.md:15`). | `"Files, folders and tags"` |
| **Colon (`:`)** | Omit on headings above UI lists or form sections (`style-guide.md:194-200`). Use only inside body sentences introducing an inline list. | `"Recent files:"` as a section header. |
| **Em / En Dash (`—` / `–`)** | Avoid em dashes (`—`) in short UI strings; split into two short sentences or a comma (`style-guide.md:262`). En dash (`–`) without spaces for numeric ranges (`10–20`). | Long nested parenthetical clauses broken by `—`. |
| **Hyphen (`-`)** | Hyphenate compound modifiers before a noun (`real-time sync`, `high-contrast mode`) and noun forms (`sign-off`, `check-in`), never verb phrases (`sign in`, `check in to`, `set up`) (`style-guide.md:276-283`). | `"Log-in to your account"` or `"setup your device"` (noun used as verb). |
| **Ampersand (`&`)** | Allowed in space-tight tabs, column headers, and buttons (`Audio & video`). Always spell out `and` in sentences, notifications, error messages, and alt text (`style-guide.md:240-252`, `accessibility.md:47`). | `"Delete files & folders permanently?"` in body prose. |
| **Exclamation (`!`)** | Reserve strictly for celebratory milestones (`Backup complete!`). Never use in errors, confirmations, empty states, or system status (`style-guide.md:202-212`, `fluent2/content-design.md:139`). | `"File not found!"`, `"Welcome!"` on every blank list. |
| **Latin abbr.** | Ban `e.g.`, `i.e.`, `etc.`, `vs.` in user-facing UI (`writing-style.md`). Write `for example`, `that is`, `such as`, or list concrete items. | `"Formats (e.g., MP4, MKV, etc.)"` |

### 4.2 Responsive Separator Rule: Never Use Middle Dots (`·` / `•`) as Metadata Separators
> *Note:* Applied engineering extension layered onto M3 Content Design for multi-width Compose layouts.

Do **not** join metadata tokens with ` · ` or ` • ` (such as `"4.2 MB · 12 min ago · MP4"`). On narrow viewports, rotated phones, or 200% font scale, single-line ellipsizing or multi-line wrapping orphans the dot at the end or start of a line (`"4.2 MB ·"` or `"· MP4"`).
- **Use instead:** Double space (`const val MetaSeparator = "  "`), distinct `Text` slots in a `FlowRow` with `horizontalArrangement = Arrangement.spacedBy(8.dp)`, or stacked typographic hierarchy (`titleMedium` + muted `bodySmall`).

---

## 5. Voice, Actionable Microcopy & Error/Notification Formulas

### 5.1 Tone & Register (Neutral Factuality Over Chatty Filler)
- **Active, direct, present tense, second person (`you`):** `"Choose a folder"` rather than `"A folder should be chosen by the user"`.
- **Written register, zero colloquial filler:** Do not pad UI strings with faux-casual exclamations (`"Oops!"`, `"Uh oh!"`, `"Hold tight!"`, `"Woohoo!"`, `"Something went wrong :("`) or robotic niceties (`"Please kindly wait"`, `"Success!"`). State the fact immediately.
- **Contractions for scan safety:** Prefer `"You can't undo this"` over `"You cannot undo this"` because negation contractions prevent readers from overlooking `not` while scanning (`contractions.md:17`). Spell out `"Do not"` only when deliberate cadence is needed for high-risk warnings (`style-guide.md:152`).
- **Never blame `you` in errors (`kde/text_and_labels.md`):** Avoid `"You entered an invalid URL"`; write `"URL must start with https://"`.

### 5.2 Action Buttons, Confirmations & Destructive Dialogs
Every dialog or sheet button must name the **specific outcome verb (+ object)** so a user scanning only the buttons knows the consequence without re-reading the body (`apple-hig/writing.md`, `writing-style.md`):
- **Avoid:** `OK` / `Cancel`, `Yes` / `No`, `Confirm` / `Back`, `Submit`.
- **Use:**
  - Confirmation of discard: `"Discard changes?"` -> **`Discard`** (destructive/primary) + **`Keep editing`** (dismiss).
  - Confirmation of permanent deletion: `"Delete 3 playlists?"` + `"Items will be removed from this device and synced folders. This can't be undone."` -> **`Delete`** + **`Cancel`**.
  - Wait/cancel safety: Use **`Keep`** / **`Cancel`** + explicit verb (`Remove`, `Replace`, `Overwrite`) rather than pairing `"Cancel"` against `"Cancel sync"` (two `"Cancel"` buttons create ambiguity).

### 5.3 Error Messages (What Happened + Why + How to Recover)
Structure every error message in three compact parts within 1–2 sentences (no stack traces, no raw HTTP codes alone unless paired with actionable context):
1. **Fact:** What failed (`"Sync paused"` or `"Couldn't save recording"`).
2. **Reason (if actionable/known):** Why (`"Drive storage is full"` or `"Connection timed out"`).
3. **Next Step:** Concrete recovery (`"Free up 240 MB or choose another folder."` + action button `Retry` / `Choose folder`).
- **No silent or redundant feedback:** Do **not** trigger a `Snackbar` (`"Saved"`, `"Updated"`) when the surrounding UI already updates visibly in-place (e.g., toggle flipped, item appeared in list). Reserve snackbars for off-screen side effects (`"Copied link"`, `"Moved 4 files to Archive"`, paired with **`Undo`** when reversible).

### 5.4 Notifications & Character Budgets (`notifications.md`)
- Put the **most critical fact first** (F-shape scanning; headlines truncate permanently even inside expandable notifications).
- Never repeat the app name in the notification title (`notifications.md:38`).
- Avoid dynamic interpolation in titles unless guaranteed short (`<= 1` extra word) with a static fallback (`notifications.md:64-76`).
- **Strict character budgets (`notifications.md:78-86`):**
  - Title: **`< 29` chars**
  - Collapsed body: **`< 40` chars**
  - Expanded body: **`< 80` chars** (extend the collapsed body cleanly; don't contradict it)
  - Action buttons: **`1–2` buttons**, **`1–2` words** each (`Reply`, `Mark read`)

### 5.5 Ban Directional Language
Never use spatial/visual references (`"above"`, `"below"`, `"on the left"`, `"top-right corner"`) in copy (`fluent2/content-design.md:155-157`, `accessibility.md`). Adaptive multi-pane layouts reflow panels between mobile portrait and desktop landscape, RTL locales mirror horizontally, and screen-reader users do not experience 2D coordinates. Reference elements by their **visible label** instead (`"Select Filters to refine results"`).

---

## 6. Global Writing, 200% Text Scaling & CJK Multilingual Rules

### 6.1 Translation-Ready English (`global-writing.md`)
1. **Disambiguate noun/verb collisions:** Words such as `filter`, `change`, `traffic`, `home`, `check`, and `match` translate into completely different words depending on part of speech (`global-writing.md:134-138`). Write unambiguous phrases (`Home screen` vs `Home address`; `Apply filter` vs `No filters active`) and supply string-resource context comments for translators.
2. **Preserve 30%–40% horizontal headroom & 200% font scaling (`writing.md:137-219`):**
   - German, Russian, and Spanish strings frequently expand 30%+ beyond English. Never clip single-line buttons or force fixed `dp` widths on text containers.
   - UIs must scale text cleanly to **200%** via OS `FontScale` while keeping inner component padding (`8.dp` vertical, `24.dp` horizontal) and element spacing at **1x** (`writing.md:141-175`).
   - Reflow side-by-side action buttons into a vertical column (or `FlowRow`) when scaled text exceeds container width (`writing.md:212-219`).

### 6.2 CJK & Bilingual Copy Rules
> *References:* Upstream typography/script hygiene from [m3-expressive-foundations.md](../01-design-systems/m3-expressive-foundations.md#4-typography--multilingual-rules) paired with bilingual punctuation consistency practices for Compose Multiplatform UIs.

1. **Full-width vs. half-width punctuation:**
   - In Chinese/Japanese UI prose, use full-width sentence punctuation (`，`, `。`, `：`, `；`)—never mix stray half-width `,` or `:` inside CJK sentences.
   - Keep numeric units, versions, and code tokens in ASCII (`12 MB`, `v1.5`, `HTTPS`) with half-width characters, and standardize question marks/ellipses per locale (avoid mixing `...` with `…`; use consistent locale punctuation across every screen rather than alternating `?`/`？` ad hoc).
2. **Never use full-width digits (`０-９`) in UI counters:** Full-width digits break tabular `tnum` alignment and trigger Android ICU `\d` parsing mismatches if copied/edited by users (see [targets-art-jvm-ios.md](../04-compose-engineering/targets-art-jvm-ios.md)).
3. **Short CJK button & tab density:** CJK characters carry higher semantic density per glyph (`删除`, `保存更改`, `取消`). Keep action button labels to `2–4` characters and set `maxLines = 1` + `softWrap = false` inside compact chips/buttons only when containers are guaranteed to grow with `fontScale`; never wrap a 4-character CJK verb mid-word across two lines.
4. **CJK line height & `LineHeightStyle`:** Chinese/Japanese glyphs fill ~90%+ of their em-box; ensure `TextStyle` maintains >= `1.45x` line height for body copy so dense paragraphs remain scannable (`m3-expressive-foundations.md`).

---

## 7. Accessibility Copy (`contentDescription`, Semantics & Alt Text)

### 7.1 Interactive Controls & Screen-Reader Semantics
1. **Never put component types in `contentDescription`:** Compose `Button`, `Checkbox`, `Switch`, and `IconButton` announce their `Role` automatically. Set `contentDescription = "Delete track"`, **never** `"Delete track button"`.
2. **Decorative vs. functional icons:**
   - Leading decorative icons next to visible text (`Row { Icon(...); Text("Downloads") }`) must pass **`contentDescription = null`** so TalkBack / VoiceOver does not read `"Downloads, Downloads"` twice.
   - Clickable standalone `IconButton`s **must** always have a concise verb-noun `contentDescription` (`"Close panel"`, `"More options"`), ideally matching their desktop hover `TooltipBox` label (`m3-expressive` tooltip + accessibility alignment).
3. **Merge composite list rows:** Use `Modifier.semantics(mergeDescendants = true) {}` on clickable cards/list rows so screen readers read the title, subtitle, and status together in one swipe rather than stepping through 4 separate fragments.

### 7.2 Images, Charts & Motion Alt Text (`alt-text.md`, `accessibility.md`)
- **State meaning in context; never duplicate adjacent captions (`alt-text.md:125-178`):** If the caption says `"Pigeons have a distinct silhouette"`, alt text should reinforce the visual aspect (`"Flying pigeons."`), not repeat the caption verbatim.
- **Omit `"image of"` / `"picture of"` (`alt-text.md:181-198`):** Screen readers already announce `"Image"`. Name the medium **only** when format aids comprehension (`"Map of Denver Rd. Park"`, `"Diagram of M3 token hierarchy"`, `"Screenshot of settings pane"`).
- **Editorial vs. analytical charts (`alt-text.md:201-270`):**
  - *Editorial charts:* State the main takeaway and anchor metric (`"Your step count was 55% higher this week vs last week with 4,106 additional steps on average."`) instead of enumerating raw points.
  - *Analytical charts:* Describe overall structure and axes, avoid forcing a single biased takeaway, and provide an interactive tooltip or link to the underlying data table.
- **Motion & GIFs (`alt-text.md:271-293`):** Summarize the demonstrated behavior in one crisp headline (`"A tooltip labeled 'star' appears when a cursor hovers over a star icon."`) rather than narrating every frame.
- **Keep alt text concise and avoid relying on punctuation alone:** Screen readers may pause or drop punctuation depending on verbosity settings (`accessibility.md:46`); write grammatically complete, unadorned plain phrasing.
