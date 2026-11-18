# Why Ecosystems Name Standards Differently: Cross-Platform HIG & Design System Taxonomy

> **Scope:** Objective structural mapping of how Apple, GNOME, KDE, Microsoft, and Google organize and name their user interface standards—separating **design language/tokens**, **platform human interface & interaction conventions**, and **toolkit/quality compliance gates**.

---

## 1. Why There Is No Single "Google HIG"

Engineers moving from Apple, GNOME, or KDE to Google or Microsoft ecosystems often search in vain for a single document titled "Android HIG" or "Windows HIG." Each platform vendor splits the same conceptual responsibilities—visual grammar, component anatomy, windowing/input conventions, and app store quality bars—across different architectural layers:

- **Single-brand / single-shell ecosystems (Apple, GNOME, KDE):** One vendor controls both the desktop/mobile shell and the primary UI toolkit (SwiftUI/UIKit/AppKit, GTK 4/Libadwaita, QtQuick/Kirigami). Consequently, visual aesthetics, interaction physics, window chrome, and writing style live together in one unified **Human Interface Guidelines (HIG)** document tree.
- **Multi-product / multi-OEM ecosystems (Google, Microsoft):** Visual design languages (**Material Design 3** and **Fluent 2**) are deliberately decoupled from OS-level shell, windowing, and OEM/hardware compliance rules (**Android UI Design & App Quality Guidelines** and **Windows App Design / WinUI 3 Guidelines**). Material Design targets Android, Web, and multiplatform apps; Fluent 2 targets Windows, Web, iOS, and Android Microsoft apps. OS-specific rules (system bars, predictive back, Snap Layouts, Mica, tray/notifications) live in separate OS developer portals.

---

## 2. Five-Ecosystem 1:1 Taxonomy Mapping

| Conceptual Layer | Apple (`developer.apple.com`) | Google (Material + Android) | Microsoft (Fluent 2 + Windows) | GNOME (`developer.gnome.org`) | KDE (`develop.kde.org`) |
| --- | --- | --- | --- | --- | --- |
| **Umbrella Standard Name** | **Human Interface Guidelines (HIG)** | **Material Design 3 (M3 / M3 Expressive)** + **Android Design & Quality Guidelines** | **Fluent 2 Design System** + **Windows App Design Guidelines** | **GNOME Human Interface Guidelines** | **KDE Human Interface Guidelines** |
| **Visual Grammar & Tokens** | HIG *Foundations* (Color, Typography, Layout, Materials / Liquid Glass, Motion, SF Symbols) | **Material 3 Styles** (`m3.material.io/styles/`: HCT Color, 10-step Shapes, 30-step Typography, `MotionScheme`, Elevation, Spacing) | **Fluent 2** (`fluent2.microsoft.design`: Alias Color Tokens, Type Ramp, Shapes, Elevation, Motion) + Windows *Signature Experiences* (Mica, Acrylic, Smoke, Geometry) | HIG *Guidelines* (UI Styling, Typography, UI Icons, Palette, Adwaita CSS classes) | Breeze Visual Style + HIG *Displaying Content* / *Icons* (Colorful vs. Monochromatic) |
| **Component Specs & Anatomy** | HIG *Components* (Bars, Menus, Presentation, Selection, Status, System Experiences) | **Material 3 Components** (`m3.material.io/components/`) + Compose `material3` API | **Fluent 2 Components** (React / Windows / iOS / Android) + WinUI 3 Controls | HIG *Patterns* (Containers, Navigation, Feedback, Controls) backed by `Adw*` / `Gtk*` | HIG *Getting Input* / *Layout and Navigation* backed by **Kirigami** & QtQuick Controls |
| **OS Shell, Windowing & Input Rules** | HIG *Platforms* (`Designing for iOS`, `iPadOS`, `macOS`, `visionOS`, `watchOS`) + *Inputs* (`Keyboards`, `Pointing devices`, `Gestures`) | **Android UI Design** (`developer.android.com/design/ui/mobile`, `large-screens`, `desktop`: System Bars, Edge-to-Edge, Predictive Back, Multi-Window) | **Windows App Design & Develop** (`learn.microsoft.com/en-us/windows/apps/`: Title Bar, Snap Layouts, Pointer/Touch/Pen/Keyboard Accelerators) | HIG *Patterns / Containers / Windows*, *Header Bars*, *Pointer & Touch*, *Keyboard* | HIG *Simple by default*, *Powerful when needed*, *Layout and Navigation* |
| **App Store / Platform Quality Bar** | App Review Guidelines + HIG Best Practices | **Android Core App Quality** & **Large Screen App Quality** (`Tier 3: Differentiated`, `Tier 2: Optimized`, `Tier 1: Large screen ready`) | Microsoft Store Policies & Windows App Accessibility Checklist | GNOME Circle Criteria & Libadwaita App Naming / Icon conventions | KDE Gear / AppStream & Kirigami Convergence Criteria |
| **UX Copy & Microcopy** | HIG *Foundations → Writing* + Apple Style Guide | **Material Content Design** (`foundations/content-design/*`, `foundations/writing`) + Google Developer Documentation Style Guide | **Fluent 2 Content Design** + **Microsoft Writing Style Guide** (`learn.microsoft.com/en-us/style-guide/`) | HIG *Guidelines → Writing Style* (`writing-style.md`) | HIG *Text and Labels* (`text_and_labels.md`) |

---

## 3. Layer-by-Layer Structural Comparison

### 3.1 Apple HIG: Platform-Segmented Convergence
Apple divides its HIG into four top-level axes (`.corpus/apple-hig/pages/components.md`, `designing-for-ios.md`, `designing-for-macos.md`):
1. **Foundations:** Cross-platform visual primitives (Color, Dark Mode, Typography, Layout, Motion, Accessibility, Writing, Materials/Liquid Glass).
2. **Platforms:** Explicit behavioral contracts per OS (`iOS`, `iPadOS`, `macOS`, `visionOS`, `watchOS`, `tvOS`). Notably, macOS HIG explicitly warns *"Avoid creating custom window UI"* (`.corpus/apple-hig/pages/windows.md:34`) and mandates global menu bar integration (`.corpus/apple-hig/pages/the-menu-bar.md:17`), whereas iOS prioritizes reachability in the lower/middle display and swipe-back gestures (`.corpus/apple-hig/pages/designing-for-ios.md:41`).
3. **Patterns & Inputs:** Task-level interactions (Modality, Multitasking, Drag and Drop) and physical input hardware (`Keyboards`, `Pointing devices`, `Apple Pencil`, `Gestures`).
4. **Components:** System widgets grouped by functional intent (*Presentation*, *Menus and actions*, *Navigation and search*, *Selection and input*, *Status*).

### 3.2 Google Material Design 3 + Android Quality Guidelines: Toolkit-First + Adaptive Tiers
Google splits design standards across two companion sites:
- **`m3.material.io` (Design System & Cross-Device Grammar):** Defines the token architecture (`md.sys.*`, `md.comp.*`), HCT color science, Material 3 Expressive (`M3E`, introduced May 2025 with 46 studies and 18,000+ participants, followed by Compose-first and spacing/layout updates at I/O 2026), and 39 component specifications (`.corpus/m3-expressive/pages/building-with-m3-expressive.md`, `whats-new-at-io26.md`, `material-is-compose-first.md`). Material explicitly notes that Material Android is **Compose-first**, with Android Views (`MDC-Android 1.14.0`) entering maintenance mode as Compose `material3` `1.5.0` graduates Expressive APIs to stable (`.corpus/m3-expressive/pages/material-is-compose-first.md:23-52`).
- **`developer.android.com/design/ui/` (Android OS & Form-Factor Contracts):** Defines OS-specific mechanics absent from pure Material specs—edge-to-edge transparency, system gesture insets, predictive back animations (`.corpus/compose-android/pages/design/ui/mobile/guides/foundations/system-bars.md`, `predictive-back.md`), desktop multi-windowing (`design/ui/desktop.md`), and the **Android Core & Large Screen App Quality Guidelines** (referenced in `design/ui/mobile/guides/layout-and-content/adapt-layout.md:117`).

### 3.3 Microsoft Fluent 2 + Windows App Design: Cross-App Brand vs. Win32/WinUI Shell
Microsoft similarly operates two complementary layers:
- **`fluent2.microsoft.design` (Cross-Platform Brand Language):** Built around four principles—*Natural on every platform*, *Built for focus*, *One for all, all for one*, *Unmistakably Microsoft*—specifically noting *"reuse native platform components and patterns 80% of the time, focusing our energy on signature experiences instead"* (`.corpus/windows-fluent/pages/fluent2/design-principles.md:19-78`). It publishes Web/React, Windows, iOS, and Android component specs plus Content Design / Content Engineering guidance.
- **`learn.microsoft.com/en-us/windows/apps/design/` (Windows OS HIG):** Defines Windows 11 native desktop ergonomics: *Effortless*, *Calm*, *Personal*, *Familiar*, *Complete + Coherent* (`.corpus/windows-fluent/pages/windows/design/design-principles.md:19-37`), 32px/48px title bar anatomy and `AppWindowTitleBar` customization, **Mica** (opaque wallpaper-tinted base layer showing active/inactive focus), **Acrylic** (translucent frost for transient light-dismiss flyouts/context menus), **Smoke** (translucent black modal scrim), and strict 3-tier corner geometry (`8px` overlay/window, `4px` in-page controls, `0px` snapped/abutting edges) (`.corpus/windows-fluent/pages/windows/design/signature-experiences/materials.md`, `geometry.md`, `basics/titlebar-design.md`).

### 3.4 GNOME HIG & KDE HIG: Convergent Open-Desktop Standards
Linux desktop environments publish distinct HIGs reflecting contrasting UX philosophies:
- **GNOME HIG (`GTK 4` + `Libadwaita`):** Opinionated, distraction-free simplicity centered on **Header Bars** (`AdwHeaderBar`, combining window title, primary actions, drag region, and window controls into one 3-slot bar), **Boxed Lists**, **Utility Panes**, **Popovers**, and adaptive clamping/flattening across mobile/desktop Linux form factors (`.corpus/linux-hig/pages/gnome/index.md`, `gnome/patterns/containers/header-bars.md`).
- **KDE HIG (`QtQuick` + `Kirigami`):** Guided by **"Simple by default, powerful when needed"** (`.corpus/linux-hig/pages/kde/kde_app_design.md:19`), targeting convergent Plasma desktop and mobile apps while accommodating power users—emphasizing explicit `Switch` (instant-apply) vs. `CheckBox` (explicit OK/Apply) semantics, `Slider` + `SpinBox` pairing for gross/fine control, and inline messages over modal interruption (`.corpus/linux-hig/pages/kde/getting_input.md:27-97`).

---

## 4. Practical Implications for Compose Multiplatform Architecture

When building a single Compose Multiplatform codebase targeting Android, iOS, Windows, macOS, and Linux:
1. **Material 3 Expressive supplies the shared visual & component layer** (colors, 10-step shapes, 30-step typography, `MotionScheme`, and Compose widgets) because M3E is a cross-platform token and component system rather than an Android-only shell.
2. **OS HIG layers supply the non-negotiable shell & input invariants** (`cross-hig-reconciliation.md`): window frames/title bars, modifier keys (`Ctrl` vs. `⌘`), back/escape dispatch, transient vs. modal surfaces, pointer vs. touch selection, and native notification/tray integration.
3. **Never confuse a visual style guide with a platform capability contract:** Adopting Material 3 Expressive components on Windows or macOS does **not** excuse ignoring Windows Snap Layouts (`WM_NCHITTEST`), macOS `⌘` shortcuts, or GNOME/Linux XDG portal conventions.

---

## Sources & Cross-References
- `.corpus/m3-expressive/pages/building-with-m3-expressive.md`, `whats-new-at-io26.md`, `material-is-compose-first.md`
- `.corpus/compose-android/pages/design/ui/mobile.md`, `large-screens.md`, `desktop.md`, `mobile/guides/layout-and-content/adapt-layout.md`
- `.corpus/apple-hig/pages/components.md`, `designing-for-ios.md`, `designing-for-macos.md`, `windows.md`, `the-menu-bar.md`
- `.corpus/windows-fluent/pages/fluent2/design-principles.md`, `windows/design/guidelines-overview.md`, `windows/design/design-principles.md`, `windows/design/signature-experiences/materials.md`, `geometry.md`
- `.corpus/linux-hig/pages/gnome/index.md`, `gnome/patterns/containers/header-bars.md`, `kde/index.md`, `kde/kde_app_design.md`, `kde/getting_input.md`
