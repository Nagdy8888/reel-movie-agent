---
name: port-stitch-screen
description: Convert a Google Stitch export screen (HTML + Tailwind) into the Next.js app under apps/frontend, using the DESIGN.md design tokens and real data. Use when porting or updating any Stitch-generated screen (landing, sign-in, chat) into React components.
disable-model-invocation: true
---

# Port a Stitch Screen

Convert a screen from `stitch_reel_ai_movie_assistant/` into clean Next.js App Router components using the shared design tokens (see the `frontend` rule).

## Workflow

```
- [ ] 1. Read the screen's code.html and view its screen.png
- [ ] 2. Ensure DESIGN.md tokens are in tailwind.config.ts (once)
- [ ] 3. Set up fonts (next/font) + Material Symbols
- [ ] 4. Split the HTML into React components + a route
- [ ] 5. Replace mock content with real data (hooks/props)
- [ ] 6. Keep tokens - no hardcoded hex
- [ ] 7. Verify (lint + typecheck)
```

### 1. Read the source

Read `stitch_reel_ai_movie_assistant/<screen>/code.html` and view `stitch_reel_ai_movie_assistant/<screen>/screen.png` to understand layout and intent. Screens: `reel_cinematic_ai_movie_assistant` (landing), `sign_in_to_reel` (auth), `reel_movie_intelligence_chat` (three-pane chat).

### 2. Tokens (once)

Port the palette/typography/radii/spacing from `stitch_reel_ai_movie_assistant/cinematic_intelligence_system/DESIGN.md` into `apps/frontend/tailwind.config.ts`. The Stitch `code.html` has an inline `tailwind.config` — lift those `theme.extend.colors` verbatim. Do this only if not already present.

### 3. Fonts & icons

Load Inter + Playfair Display via `next/font/google`; add Material Symbols Outlined. Replace the Stitch CDN `<link>`/`<script>` tags — do NOT keep the Tailwind CDN script in the React app.

### 4. Componentize

Break the HTML into small components under `apps/frontend/components/` and a route under `app/`. Map repeated blocks (message bubble, source card, sidebar item, graph node) to components with typed props. Convert `class=` to `className=`, inline styles to Tailwind tokens, and static markup to JSX.

### 5. Real data

Replace hardcoded mock content (the Blade Runner example, fake history, static sources/graph) with props/hooks fed by `lib/api.ts` (SSE stream, sources, graph nodes) and Supabase session.

### 6. Tokens only

No hardcoded hex in components — use theme tokens (`bg-surface`, `text-primary`, ...). Keep components small and colocated.

### 7. Verify

Run the frontend checks (`pnpm lint`, `pnpm tsc --noEmit`) and confirm the screen renders and matches the `screen.png`. See the `frontend` rule for standing conventions.
