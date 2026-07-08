---
name: Cinematic Intelligence System
colors:
  surface: '#17130d'
  surface-dim: '#17130d'
  surface-bright: '#3e3831'
  surface-container-lowest: '#110e08'
  surface-container-low: '#1f1b14'
  surface-container: '#231f18'
  surface-container-high: '#2e2922'
  surface-container-highest: '#39342d'
  on-surface: '#ebe1d6'
  on-surface-variant: '#d3c4b1'
  inverse-surface: '#ebe1d6'
  inverse-on-surface: '#353028'
  outline: '#9b8f7d'
  outline-variant: '#4f4537'
  surface-tint: '#f3be60'
  primary: '#ffd185'
  on-primary: '#422c00'
  primary-container: '#e8b457'
  on-primary-container: '#654600'
  inverse-primary: '#7d5700'
  secondary: '#ffb4aa'
  on-secondary: '#680105'
  secondary-container: '#8c1f1a'
  on-secondary-container: '#ff9f93'
  tertiary: '#c3daff'
  on-tertiary: '#00315d'
  tertiary-container: '#94bffc'
  on-tertiary-container: '#1b4d83'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdeaa'
  primary-fixed-dim: '#f3be60'
  on-primary-fixed: '#271900'
  on-primary-fixed-variant: '#5f4100'
  secondary-fixed: '#ffdad5'
  secondary-fixed-dim: '#ffb4aa'
  on-secondary-fixed: '#410002'
  on-secondary-fixed-variant: '#891d18'
  tertiary-fixed: '#d4e3ff'
  tertiary-fixed-dim: '#a4c9ff'
  on-tertiary-fixed: '#001c39'
  on-tertiary-fixed-variant: '#13487d'
  background: '#17130d'
  on-background: '#ebe1d6'
  surface-variant: '#39342d'
typography:
  display-lg:
    fontFamily: Playfair Display
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: 0.02em
  display-md:
    fontFamily: Playfair Display
    fontSize: 36px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: 0.02em
  headline-lg:
    fontFamily: Playfair Display
    fontSize: 28px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: 0.01em
  headline-lg-mobile:
    fontFamily: Playfair Display
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: 0.01em
  title-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.5'
    letterSpacing: 0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: 0.01em
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: 0.01em
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '700'
    lineHeight: '1'
    letterSpacing: 0.1em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
---

## Brand & Style

This design system embodies the atmosphere of a high-end, private screening room. It targets cinephiles and industry professionals who value curation, depth, and a premium aesthetic. The emotional response should be one of "quiet luxury"—sophisticated, authoritative, yet technologically advanced.

The style is a fusion of **Modern Minimalism** and **Glassmorphism**, drawing inspiration from prestige editorial layouts and luxury streaming platforms. The interface prioritizes content (film imagery) through deep blacks and subtle tonal layering. Interaction is characterized by "tasteful micro-details"—1px borders, soft backdrops blurs, and precise typography—ensuring the AI feels like an expert concierge rather than a utility tool.

## Colors

The palette is rooted in a "Noir" foundation to allow movie posters and gold accents to command attention.

- **Backgrounds:** Use the base `#0E0E11` for the main canvas. Use `#16161B` for structural sidebars and navigation containers.
- **Accents:** The **Warm Gold** is reserved for high-priority actions (CTAs), active states, and focus indicators. The **Muted Crimson** serves as a secondary accent for categorization, such as "Critical Acclaim" or specific metadata tags.
- **Interactive States:** Buttons should utilize a subtle glow effect on hover rather than a simple color shift to maintain the cinematic feel.

## Typography

The typography system pairs a high-contrast serif with a neutral, systematic sans-serif to create a "modern classic" hierarchy.

- **Headlines:** Use Playfair Display for movie titles, section headers, and the AI's primary responses. Generous letter-spacing is required on all serif headlines to enhance readability against dark backgrounds.
- **UI/Body:** Inter is used for all functional elements, metadata, and long-form descriptions. 
- **Labels:** Use `label-caps` for small metadata like "YEAR", "GENRE", or "DIRECTOR" to create clear visual separation from body text.

## Layout & Spacing

The layout follows a **Fixed Grid** model for content-heavy views, ensuring that information remains centered and readable, with a **Fluid Grid** for the internal chat/discovery interface.

- **Grid:** Use a 12-column grid for desktop with 24px gutters.
- **Breakpoints:**
    - Mobile: < 768px (4 columns, 16px margins).
    - Tablet: 768px - 1280px (8 columns, 24px margins).
    - Desktop: > 1280px (12 columns, 48px margins).
- **Rhythm:** Spacing should be generous. Use `xl` (40px) between major sections to prevent the dark interface from feeling cramped. Use `md` (16px) for internal card padding.

## Elevation & Depth

Hierarchy is established through **Tonal Layering** and **Glassmorphism** rather than traditional heavy shadows.

- **Surfaces:** Use `#16161B` for the first layer of elevation. Use `#1C1C22` for floating cards or panels.
- **Borders:** Apply a 1px solid border of `#2A2A33` to all elevated surfaces to define edges against the dark background.
- **Backdrop Blur:** For overlays, modals, and the sidebar, apply a `20px` backdrop blur with a 60% opacity fill of the surface color.
- **Shadows:** Use a single, very soft ambient shadow for floating elements: `0 8px 32px rgba(0, 0, 0, 0.4)`.

## Shapes

The design system uses a consistent "Rounded" strategy to soften the technical nature of the AI.

- **Standard Elements:** Buttons, cards, and input fields use a `0.5rem` (8px) radius.
- **Large Containers:** Modals and main content panels use `1rem` (16px) radius for a more "app-like" feel.
- **Pills:** Citation chips and genre tags use a fully rounded (pill) shape to distinguish them from interactive buttons.

## Components

- **Buttons:**
  - *Primary:* Solid Gold (`#E8B457`) with black text. High-gloss finish on hover.
  - *Secondary:* Ghost style with 1px border (`#2A2A33`) and White (`#F5F5F7`) text.
- **Inputs:** 12px rounded corners. Background: `#0E0E11`. Focus state: 1px Gold border with a 2px outer gold glow (low opacity).
- **Chat Bubbles:**
  - *User:* Surface color with a subtle 5% Gold tint overlay and right-aligned.
  - *Assistant:* Surface color (`#1C1C22`) with left-aligned Playfair Display text for the response.
- **Knowledge Graph:** Nodes are glowing circular points (`#E8B457`). Connections are ultra-thin 0.5px lines (`#2A2A33`). Active paths should "pulse" with a gold gradient.
- **Movie Cards:** Poster-centric with a 1px internal stroke. Metadata appears on hover using a bottom-to-top gradient overlay (Black to Transparent).
- **Thinking Indicator:** Three small gold dots that fade in and out sequentially with a "cinematic flicker" timing.
- **Citation Chips:** Small, semi-transparent grey pills with gold text, used to link to sources or specific film timestamps.