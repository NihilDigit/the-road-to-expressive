# Cross-HIG Reconciliation: One M3 Expressive UI Across Five Operating Systems

> **Scope:** Engineering contract for shipping **one unified Compose Multiplatform Material 3 Expressive UI** across **Android, iOS/iPadOS, Windows, macOS, and Linux** that feels genuinely native on every host—explicitly separating what remains unified M3E from what **must** adapt to each OS's Human Interface Guidelines.

---

## 1. The Core Reconciliation Principle: Unify Visual Grammar, Adapt Shell & Input Contracts

Users do not expect a Windows, macOS, or Linux desktop app—or an iOS app—to impersonate every pixel of system widgets if the app has a strong, coherent design language (this is the explicit model of Fluent 2 cross-platform apps and Material 3 multiplatform apps). However, users **immediately perceive an app as broken or foreign** when it violates OS-level **shell geometry**, **window management**, **input & shortcut grammar**, **system back/navigation**, or **OS notification/tray integration** (`.corpus/apple-hig/pages/windows.md:34`, `.corpus/windows-fluent/pages/windows/design/basics/titlebar-design.md:32-70`, `.corpus/linux-hig/pages/gnome/guidelines/keyboard.md:23-87`).

### Decision Boundary Matrix

| Layer | Unified M3 Expressive (`commonMain`) | Platform-Adapted per OS HIG (`platform` / `expect-actual`) |
| --- | --- | --- |
| **Color & Surface Hierarchy** | `ColorScheme`, HCT roles, 5-tier `surfaceContainer*`, Oklab pure-black, zero dividers | Dynamic wallpaper color source (Android 12+); Windows high-contrast `SystemColors` fallback; optional Mica/Vibrancy backdrop when using native window chrome |
| **Typography & Shapes** | 30-step `*Emphasized` scale, CJK line heights, `.tabular` `tnum`, 10-step `Shapes` | Native system CJK fallback font families (Android Roboto/Noto, Windows Segoe UI / Microsoft YaHei, macOS SF / PingFang, Linux Noto Sans CJK) |
| **Component Semantics** | `ButtonGroup`, `SplitButtonLayout`, `SegmentedListItem`, `WideNavigationRail`, `ShortNavigationBar`, `PaneSheet` | **Input modality adaptations** (pointer hover & right-click `ContextMenuArea` vs. touch long-press) and **host-appropriate sheet/dialog containers** |
| **Motion** | `MaterialTheme.motionScheme` + `MotionDurationScale` | Mobile (`expressive()`, 150–400ms) vs. Desktop (`standard()`, 83–250ms); iOS parallax vs. Android predictive back; OS Reduced Motion hooks |
| **Window Chrome, Menus & OS Integration** | Content island framing inside the client area | **100% OS-Native Rules:** Title bar / traffic lights / Snap Layouts, global macOS menu bar, `Ctrl` vs. `⌘`, system back/Esc, scrollbars & wheel, native notifications & tray |

---

## 2. Five-Platform Shell & OS Contract Matrix

| Dimension | Android (ART) | iOS / iPadOS | Windows 11 (Desktop JVM) | macOS (Desktop JVM) | Linux GNOME / KDE (Desktop JVM) |
| --- | --- | --- | --- | --- | --- |
| **Window Chrome & Controls** | Edge-to-edge behind transparent status & gesture nav bars (`enableEdgeToEdge()`); cutout insets (`SHORT_EDGES` only in fullscreen media) | Safe areas (`safeDrawing`); Home indicator clearance; iPadOS windowed mode leaves leading clearance for traffic lights (`.corpus/apple-hig/pages/windows.md:57`) | Custom Win32 caption via `WM_NCCALCSIZE` + `WM_NCHITTEST` (`HTCAPTION`, min/max/close) **never** `undecorated`—preserves **Snap Layouts**, `Win+Arrows`, shadow, and resize borders | Native **traffic lights** on leading edge (`disableTitleBar` + `NSWindow` full-size content view); auto-hide custom top bar in `WindowPlacement.Fullscreen`; distinct active/key vs. inactive appearance (`.corpus/apple-hig/pages/windows.md:76-92`) | System/GTK/KWin header bar or client-side window controls matching WM; set `WM_CLASS` & `.desktop` ID (`dev.example.App`) so Dock/Taskbar groups icons |
| **Primary Shortcut Modifier** | `Ctrl` (external physical keyboard) | `⌘` (`Command`) on iPadOS external keyboards (`.corpus/apple-hig/pages/the-menu-bar.md:21`) | `Ctrl` (`Alt` reserved for mnemonics/access keys; `Win` reserved by OS) | **`⌘` (`Command`)** (`Ctrl` used for system/Emacs/secondary chords; never hardcode `Ctrl` in `commonMain`!) | `Ctrl` (`Super` reserved by GNOME/KDE for WM shortcuts; `Alt` reserved for access keys, `.corpus/linux-hig/pages/gnome/guidelines/keyboard.md:35-38`) |
| **Global App Menu & Settings Shortcut** | In-app top bar / overflow / navigation destination | In-app + iPadOS global menu bar (`Settings…` `⌘,`, `Quit` `⌘Q`) | In-app command bar / overflow / header (`F1` help, `Ctrl+,` optional) | **Mandatory macOS menu bar** (`AppName > About`, `Settings… ⌘,`, `Hide ⌘H`, `Quit ⌘Q`, `File`, `Edit`, `View`, `Window`, `Help`) (`.corpus/apple-hig/pages/the-menu-bar.md:29-71`) | Header bar primary menu (`F10`), shortcuts dialog (`Ctrl+?`), `Ctrl+Q` quit |
| **Back Navigation & Dismiss** | System **Back** + **Predictive Back** (`SeekableTransitionState`, edge swipe insets reserved!) | Leading **edge-swipe back**; sheet pull-down; `Esc` on hardware keyboard | In-app back button + `Alt+Left` / mouse Back (`XButton1`) + **`Esc`** for transient popups/sheets/dialogs | In-app back + **`⌘[` / `⌘Left`** + **`Esc`** (`.corpus/apple-hig/pages/keyboards.md:49`) | In-app back + `Alt+Left` / mouse Back + **`Esc`** for popovers/dialogs (`.corpus/linux-hig/pages/gnome/guidelines/keyboard.md:87`) |
| **Transient Menus & Secondary Surfaces** | Touch long-press → `ModalBottomSheet` or multi-select; no hover dependency | Touch long-press context menu or Action Sheet; iPadOS popover anchored to source | Pointer **right-click** (`ContextMenuArea`) anchored at cursor (`PointerMenuPositionProvider`, `80ms` fade-in, no scale-in); `ModalSideSheet` or `FloatingPanel` | Right-click / `Ctrl+Click` context menu at pointer; inspectors/sheets on trailing edge; non-modal utility panels | Right-click / `Shift+F10` / `Menu` key popover at pointer; GNOME `AdwUtilityPane` / KDE inline drawers |
| **Scrollbars, Wheel & Trackpad** | Touch inertia; hidden transient scroll indicator | Elastic bounce; hidden transient scroll indicator; scroll edge effects behind floating bars (`.corpus/apple-hig/pages/scroll-views.md:17-48`) | **Visible draggable vertical scrollbar** on dense desktop lists; mouse wheel converts to horizontal scroll on horizontal rows (`verticalWheelScrollsRow`); wheel must **not** drag bottom sheets (`WheelStopsAtSheet`) | Overlay or persistent scrollbars per system pref; smooth high-precision trackpad inertia; wheel horizontal routing | Visible scrollbar on scrollable views; wheel + keyboard `PageUp`/`PageDown`/`Home`/`End` |
| **Notifications & System Tray** | Notification channels + Foreground Service progress notification **only when backgrounded** (`ProcessLifecycleOwner`) | `UNUserNotificationCenter` permission + grouped banners; badges strictly for unread count (`.corpus/apple-hig/pages/notifications.md:71-79`) | Windows Toast via COM/FFM (`AppUserModelId`); **wide-char Win32 `CreatePopupMenu` + `AppendMenuW`** tray menu (AWT `Tray` corrupts UTF-8/CJK!) | `UNUserNotificationCenter` / `osascript`; Dock icon menu & badge; `⌘Q` hides or quits per window policy | D-Bus `org.freedesktop.Notifications` via `gdbus`; **GNOME has no default system tray** (never rely on tray to reopen hidden window—use single-instance activation via UDS!) |

---

## 3. High-Friction Cross-Platform Reconciliation Rules

### 3.1 Window Chrome & Custom Title Bars (Why `undecorated` Fails on Windows)
- **Windows:** Creating a Compose Desktop `Window(undecorated = true)` strips native **Snap Layouts** (hovering Maximize button), `Win+Left/Right` snapping, DWM rounded corners/drop shadows, and smooth resize hit-testing.
  - **Correct Pattern (`WindowsCaption`):** Keep a standard decorated `Window`, subclass `WndProc` via JDK FFM, handle `WM_NCCALCSIZE` to extend client area into the top title bar while preserving resize borders, and respond to `WM_NCHITTEST` with `HTCAPTION` (draggable header spaces), `HTMINBUTTON`, `HTMAXBUTTON`, and `HTCLOSE`. Let Win32 drive caption button hover/press states so Snap Layouts work identically to native WinUI 3 apps (`.corpus/windows-fluent/pages/windows/design/basics/titlebar-design.md`).
  - **Coordinate Stability (`DesktopIslandFrame`):** Keep the top-right `— □ ×` caption cluster at an invariant coordinate across every pushed route by wrapping content in a `surfaceContainer` frame with an `8.dp` inset `shapes.large` (`16.dp`) island, suspending the island frame only on full-bleed immersive video players.
- **macOS:** Do not render Windows-style `— □ ×` buttons on the right! Use `apple.awt.fullWindowContent` / Skiko `disableTitleBar`, reserve leading inset clearance for the system traffic lights, and hide the custom header pad automatically when `WindowPlacement.Fullscreen` moves the window into its own macOS Space (`.corpus/apple-hig/pages/windows.md:76-92`).
- **Linux:** On Wayland/X11, respect system decorations or standard WM `WM_CLASS` registration (`XToolkit`), and avoid `java.awt.Desktop` which pulls system GTK/`glib` into the JVM process and conflicts with bundled native media/FFmpeg SONAMEs.

### 3.2 Shortcut Modifiers & Key Reservation (`Ctrl` vs. `⌘` vs. `Alt`)
Never hardcode `isCtrlPressed` in `commonMain` or display literal `"Ctrl+K"` strings in tooltips/palettes:
- Define `Platform.shortcutModifier`: `Key.Meta` (`⌘`) on macOS/iPadOS; `Key.Ctrl` (`Ctrl`) on Windows, Linux, and Android hardware keyboards.
- **Avoid OS-Reserved Combos:**
  - macOS reserves `⌘Space` (Spotlight), `⌘Tab`, `⌘H` (Hide), `⌘Q` (Quit), `⌘,` (Settings), `⌘W` (Close Window/Tab) (`.corpus/apple-hig/pages/keyboards.md:40-100`).
  - GNOME reserves `Super` for shell overview/tiling and `Alt+<letter>` for localized mnemonics (`.corpus/linux-hig/pages/gnome/guidelines/keyboard.md:35-45`).
  - Windows reserves `Win+*` and `Alt+F4`.
- **Single-Key / Navigation Shortcuts Guard:** Never intercept `Delete`, `Backspace`, `Space`, `Enter`, `Ctrl+A`, or `Esc` at the window root when focus is inside a `TextField`—text inputs must own editing, IME composition confirmation, and selection first.
- **Tooltip & Palette Parity:** Every keyboard shortcut shown in `TooltipIconButton` or a `ShortcutsDialog` (`F1` / `Mod+/`) must filter by host capability so mobile users do not see `"Ctrl+B toggle sidebar"` when no sidebar exists.

### 3.3 System Back vs. Edge Swipe vs. `Esc`
Do **not** equate `Esc` with global Android system Back:
1. **Priority Stack (Top to Bottom, One Layer per Press):**
   `Active IME / Text Selection` → `Topmost Popup / Context Menu / Tooltip` → `Modal Dialog / Sheet / Side Pane` → `Explicit Multi-Select Mode` → `In-Pane / Sub-View Back` → `Top-Level Route / Window Close (if applicable)`.
2. **Android Predictive Back:** Keep interactive controls out of system left/right gesture insets (`WindowInsets.systemGestures`) (`.corpus/compose-android/pages/design/ui/mobile/guides/foundations/system-bars.md:87-88`).
3. **Desktop `Esc` Scope:** `Esc` dismisses transient popups, search overlays, multi-select mode, or pushed detail overlays—it must **not** unexpectedly exit the entire desktop application window (`.corpus/linux-hig/pages/gnome/guidelines/keyboard.md:87`, `.corpus/apple-hig/pages/keyboards.md:49`).

### 3.4 Dialogs, Sheets, and Pointer vs. Touch Selection
- **Dialogs:** M3 standard mobile dialogs use `28.dp` corners, `24.sp` headlines, and text-only buttons—which look like floating phone cards on a 1440px desktop monitor. On multiplatform apps, tighten desktop/shared dialogs to `shapes.large` (`16.dp`) with `titleLarge` (`22.sp`) and a filled primary/destructive confirm button (`Button` / `error` container) paired with a `TextButton` cancel. Always enforce zero internal layout jumps (keep validation helper lines fixed-height!).
- **Sheets vs. Floating Panels vs. Context Menus:**
  - *Touch (`Compact`):* `ModalBottomSheet` (`skipPartiallyExpanded = true` whenever confirm buttons or inputs exist).
  - *Wide / Desktop (`Expanded+` or pointer-driven):* `ModalSideSheet` (trailing edge, `<= 400.dp`, `0.32f` scrim) or draggable `FloatingPanel` (`DetailHost`), plus cursor-anchored `ContextMenuArea` (`PointerMenuPositionProvider`).
  - *Never* open a `ModalBottomSheet` in the middle of a `1440dp` desktop screen or anchor a desktop right-click menu to the entire list row's bottom edge.

### 3.5 Foreground vs. Background Notifications & System Tray
- **Suppress Redundant OS Notifications in Foreground:** Apple HIG explicitly prohibits popping system notifications when the user is already viewing the relevant foreground view (`.corpus/apple-hig/pages/notifications.md:39`). Use in-app `Snackbar` (only for actionable/non-visible outcomes) or live list updates; reserve OS notifications (`ForegroundService`, Windows Toast, `UNUserNotificationCenter`, D-Bus `org.freedesktop.Notifications`) for backgrounded completions or failures.
- **No Unsolicited Red-Dot Anxiety Badges:** Apple HIG restricts app-icon badges strictly to unread notifications (`.corpus/apple-hig/pages/notifications.md:71-73`); avoid decorative red notification dots on settings rows or static navigation tabs.
- **Desktop Tray Fallbacks:** On Windows, bypass AWT `PopupMenu` (ANSI `AppendMenuA` corrupts UTF-8/CJK on Windows) in favor of `AppendMenuW` via FFM; on GNOME Linux, assume no persistent tray exists and rely on single-instance IPC reactivation.

---

## Sources & Cross-References
- `.corpus/apple-hig/pages/windows.md`, `the-menu-bar.md`, `keyboards.md`, `scroll-views.md`, `notifications.md`
- `.corpus/windows-fluent/pages/windows/design/basics/titlebar-design.md`, `signature-experiences/materials.md`, `geometry.md`, `develop/title-bar.md`
- `.corpus/linux-hig/pages/gnome/guidelines/keyboard.md`, `gnome/patterns/containers/header-bars.md`, `kde/getting_input.md`
- `.corpus/compose-android/pages/design/ui/mobile/guides/foundations/system-bars.md`, `patterns/predictive-back.md`, `design/ui/desktop.md`
