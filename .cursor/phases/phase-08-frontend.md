# Phase 8 — Next.js Frontend (Port Stitch Screens)

## Objective

Build the `apps/frontend` Next.js (App Router) app by porting the three delivered Stitch screens into clean, typed React components, then wire it to the **existing** backend:
- **Landing** ← `stitch_reel_ai_movie_assistant/reel_cinematic_ai_movie_assistant/code.html`
- **Sign in / Sign up** ← `stitch_reel_ai_movie_assistant/sign_in_to_reel/code.html`
- **Chat (three-pane)** ← `stitch_reel_ai_movie_assistant/reel_movie_intelligence_chat/code.html`

Wire **Supabase auth** (login/session/route-guard), the **SSE streaming** chat to `POST /chat`, and the **conversation history** sidebar to `GET /chats`. Use the design tokens from `stitch_reel_ai_movie_assistant/cinematic_intelligence_system/DESIGN.md`.

> **Implementation update:** the backend now emits real `sources` and `graph`
> SSE events and exposes authenticated `GET /graph`. The frontend loads the
> complete graph once and renders it with Sigma.js WebGL, Graphology
> `MultiDirectedGraph`, and a ForceAtlas2 Web Worker. The historical empty-state
> guidance below is superseded by this live contract.

> Follow the `port-stitch-screen` skill for each screen — it has the per-screen checklist. This document is the **ground truth**: prefer the facts below over assumptions. Do **not** invent endpoints, SSE events, response fields, Tailwind classes, or hex values that are not listed here or present in the source files.

---

## Ground truth A — Backend API contract (do NOT invent)

The backend already exists under `apps/backend/src/api/`. These are the **only** endpoints and the **exact** wire formats. Read the referenced files if in doubt — do not guess.

### Endpoints

| Method | Path | Auth | Source | Notes |
|---|---|---|---|---|
| `GET` | `/health` | none | `routes/health.py` | Liveness: `{ "status": "ok", "detail": "" }`. |
| `GET` | `/ready` | none | `routes/health.py` | Readiness: 200 or 503 `{ "status": "degraded", ... }`. |
| `POST` | `/chat` | **Bearer JWT** | `routes/chat.py` | SSE stream (see below). Rate-limited **20/minute**. |
| `GET` | `/chats` | **Bearer JWT** | `routes/chats.py` | List conversations, newest first. |
| `GET` | `/chats/{id}` | **Bearer JWT** | `routes/chats.py` | One conversation **with messages**; 404 if not owned. |
| `DELETE` | `/chats/{id}` | **Bearer JWT** | `routes/chats.py` | 204 on success; 404 if not owned. |
| `GET` | `/graph` | **Bearer JWT** | `routes/graph.py` | Complete compressed knowledge graph. |

There is no `/sources`, `/search`, `/movies`, or user/profile endpoint. Do not
call any endpoint not in this table.

### `POST /chat` request body (`schemas.py::ChatRequest`)

```json
{ "message": "string (1..2000 chars, required)", "thread_id": "string | null (optional)" }
```

If `thread_id` is omitted the server generates one and returns it in the `meta` event. Persist and reuse it for the rest of that conversation.

### `POST /chat` SSE response — EXACT frame formats

`Content-Type: text/event-stream`. The backend emits three kinds of frames (see `routes/chat.py::_event_stream`). **Frames are separated by a blank line (`\n\n`).** This is the single most important contract to get right — the earlier draft of this plan had it wrong.

1. First frame — a **named** `meta` event (fires once, before any token):

```
event: meta
data: {"thread_id": "<uuid>", "conversation_id": "<uuid>"}
```

2. Zero or more **default** (unnamed) events, one per streamed text token:

```
data: {"token": "<text chunk>"}
```

3. Final frame — a **named** `done` event with empty JSON:

```
event: done
data: {}
```

Notes that will otherwise cause bugs:
- The token frames have **no `event:` line** (default event name is `message`). The `thread_id` is **only** in the `meta` event, and completion is **only** signaled by the `done` event — do **not** look for `thread_id`/`done` inside the token `data:` payloads.
- The stream can also emit named `sources` and `graph` events after retrieval
  and once more after answer-level filtering.
- Response headers include `Cache-Control: no-store` and `X-Accel-Buffering: no`.

### `GET /chats` response (`schemas.py::ConversationSummary[]`)

```json
[
  {
    "id": "uuid",
    "thread_id": "string",
    "title": "string | null",
    "created_at": "ISO-8601 datetime",
    "updated_at": "ISO-8601 datetime"
  }
]
```

### `GET /chats/{id}` response (`schemas.py::ConversationDetail`)

`ConversationSummary` **plus**:

```json
{ "messages": [ { "role": "user | assistant", "content": "string", "created_at": "ISO-8601" } ] }
```

`role` is only ever `"user"` or `"assistant"`. Messages are already ordered chronologically.

### Auth & CORS (must match, or requests fail)

- Auth is a **Supabase JWT** verified via JWKS (`auth.py`, RS256/ES256, audience `authenticated`). Send it as `Authorization: Bearer <access_token>`, where the token is `session.access_token` from `supabase.auth.getSession()`.
- CORS allowlist defaults to **`http://localhost:3000`** with `allow_credentials=True`, methods `GET, POST, DELETE`, headers `Authorization, Content-Type` (`main.py`). Therefore the dev frontend **must run on port 3000**; if you change the port, add it to the backend `CORS_ALLOW_ORIGINS` env.
- On `401`/`403`, treat the session as invalid → redirect to `/login`. On `429` (rate limit), surface a friendly "slow down" message.

---

## Ground truth B — Design tokens & assets (do NOT guess hex)

The three `code.html` files each embed the **same** `tailwind.config` block and share custom CSS. `DESIGN.md` is the design spec; the `code.html` render is the pixel source of truth. **Copy values; do not eyeball them.**

### Important conflict to reconcile (this is a real gotcha)

The token palette defines `surface`/`background` as `#17130d`, but every screen's inline `<style>` overrides the page background to **`#0E0E11`**, and the markup uses **arbitrary hex** that are NOT in the token set: `#0E0E11` (true canvas), `#1C1C22` (elevated cards/bubbles), `#2A2A33` (1px hairline borders), and `#E8B457` (gold — identical to `primary-container`). To honor "no hardcoded hex in components," **add these as named tokens** and use them everywhere the Stitch HTML used `bg-[#0E0E11]`, `bg-[#1C1C22]`, `border-[#2A2A33]`, etc. The near-white text in the exports is `on-surface` = `#ebe1d6` (the `#F5F5F7` mentioned in `DESIGN.md` prose is not actually used — match the export).

### `apps/frontend/tailwind.config.ts` — full token map

Reproduce the config verbatim from `code.html`, then append the reconciliation tokens (`canvas`, `elevated`, `hairline`). Gold is already `primary-container`; do not add a separate gold token.

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // --- verbatim from code.html tailwind.config ---
        "surface-variant": "#39342d",
        "surface-container-highest": "#39342d",
        "on-surface": "#ebe1d6",
        "primary-fixed": "#ffdeaa",
        "on-tertiary": "#00315d",
        "tertiary-fixed-dim": "#a4c9ff",
        "surface-container-low": "#1f1b14",
        "surface-container-high": "#2e2922",
        "tertiary-container": "#94bffc",
        "on-secondary-container": "#ff9f93",
        "on-tertiary-container": "#1b4d83",
        "on-primary-fixed-variant": "#5f4100",
        "on-tertiary-fixed": "#001c39",
        surface: "#17130d",
        "surface-container": "#231f18",
        "surface-tint": "#f3be60",
        "on-primary": "#422c00",
        "secondary-fixed": "#ffdad5",
        tertiary: "#c3daff",
        "on-secondary-fixed-variant": "#891d18",
        background: "#17130d",
        primary: "#ffd185",
        error: "#ffb4ab",
        "inverse-primary": "#7d5700",
        "on-error": "#690005",
        "secondary-container": "#8c1f1a",
        "inverse-on-surface": "#353028",
        "on-surface-variant": "#d3c4b1",
        "inverse-surface": "#ebe1d6",
        "error-container": "#93000a",
        "on-primary-fixed": "#271900",
        "secondary-fixed-dim": "#ffb4aa",
        "on-error-container": "#ffdad6",
        secondary: "#ffb4aa",
        "surface-bright": "#3e3831",
        "outline-variant": "#4f4537",
        "surface-dim": "#17130d",
        "on-secondary": "#680105",
        "surface-container-lowest": "#110e08",
        "on-tertiary-fixed-variant": "#13487d",
        "primary-container": "#e8b457",
        "on-primary-container": "#654600",
        outline: "#9b8f7d",
        "primary-fixed-dim": "#f3be60",
        "on-background": "#ebe1d6",
        "tertiary-fixed": "#d4e3ff",
        "on-secondary-fixed": "#410002",
        // --- reconciliation tokens for the arbitrary hex in the markup ---
        canvas: "#0E0E11", // page/pane background enforced by code.html body style
        elevated: "#1C1C22", // floating cards, chat bubbles
        hairline: "#2A2A33", // 1px borders on elevated surfaces
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px",
      },
      spacing: {
        xs: "4px",
        sm: "8px",
        md: "16px",
        lg: "24px",
        xl: "40px",
        gutter: "24px",
        unit: "4px",
        "margin-mobile": "16px",
        "margin-desktop": "48px",
      },
      fontFamily: {
        "display-lg": ["var(--font-playfair)", "serif"],
        "display-md": ["var(--font-playfair)", "serif"],
        "headline-lg": ["var(--font-playfair)", "serif"],
        "headline-lg-mobile": ["var(--font-playfair)", "serif"],
        "title-md": ["var(--font-inter)", "sans-serif"],
        "body-lg": ["var(--font-inter)", "sans-serif"],
        "body-sm": ["var(--font-inter)", "sans-serif"],
        "label-caps": ["var(--font-inter)", "sans-serif"],
      },
      fontSize: {
        "display-lg": ["48px", { lineHeight: "1.1", letterSpacing: "0.02em", fontWeight: "700" }],
        "display-md": ["36px", { lineHeight: "1.2", letterSpacing: "0.02em", fontWeight: "600" }],
        "headline-lg": ["28px", { lineHeight: "1.3", letterSpacing: "0.01em", fontWeight: "600" }],
        "headline-lg-mobile": ["24px", { lineHeight: "1.3", letterSpacing: "0.01em", fontWeight: "600" }],
        "title-md": ["18px", { lineHeight: "1.5", letterSpacing: "0.01em", fontWeight: "600" }],
        "body-lg": ["16px", { lineHeight: "1.6", letterSpacing: "0.01em", fontWeight: "400" }],
        "body-sm": ["14px", { lineHeight: "1.6", letterSpacing: "0.01em", fontWeight: "400" }],
        "label-caps": ["12px", { lineHeight: "1", letterSpacing: "0.1em", fontWeight: "700" }],
      },
    },
  },
  plugins: [],
};
export default config;
```

The Stitch markup combines a family and size token that share a name, e.g. `class="font-display-md text-display-md"`, `class="font-label-caps text-label-caps"`. Keep both classes when porting — they are two separate utilities (family + size), not a typo.

### Custom CSS → `apps/frontend/app/globals.css`

The screens rely on hand-written CSS classes and keyframes (in each `<style>` block) that Tailwind cannot express. Port them **verbatim** into `globals.css` (below the Tailwind directives). These are used by the components; if you omit them the screens will look broken.

```css
/* Page canvas (matches the code.html body override) */
body { background-color: #0E0E11; }

/* Glassmorphism panels (nav bars, floating headers, feature cards) */
.glass-panel {
  background: rgba(28, 28, 34, 0.6);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid #2A2A33;
}

/* Warm gold ambient glow (icon chips, hover states) */
.gold-glow { box-shadow: 0 0 20px rgba(232, 180, 87, 0.15); }

/* Landing hero radial wash */
.hero-gradient {
  background: radial-gradient(circle at 50% 30%, rgba(232, 180, 87, 0.05) 0%, rgba(14, 14, 17, 1) 70%);
}

/* Gold text shadow (brand wordmark, movie titles on cards) */
.text-glow { text-shadow: 0 0 10px rgba(232, 180, 87, 0.3); }

/* Thin gold scrollbar used in scroll containers */
.thin-scrollbar::-webkit-scrollbar { width: 4px; }
.thin-scrollbar::-webkit-scrollbar-track { background: transparent; }
.thin-scrollbar::-webkit-scrollbar-thumb { background: rgba(232, 180, 87, 0.2); border-radius: 4px; }

/* Input focus glow (sign-in fields) */
.input-glow:focus { border-color: #ffd185; box-shadow: 0 0 0 2px rgba(255, 209, 133, 0.15); }

/* Decorative graph-node pulse (landing hero / visual band SVGs) */
@keyframes pulse-node {
  0% { transform: scale(1); opacity: 0.8; }
  50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 15px rgba(232, 180, 87, 0.5); }
  100% { transform: scale(1); opacity: 0.8; }
}
.node { animation: pulse-node 3s infinite ease-in-out; }
.node:nth-child(2) { animation-delay: 0.5s; }
.node:nth-child(3) { animation-delay: 1s; }
.node:nth-child(4) { animation-delay: 1.5s; }

/* Chat "thinking" indicator flicker */
@keyframes flicker {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 1; text-shadow: 0 0 8px rgba(232, 180, 87, 0.8); }
}
.thinking-dot { animation: flicker 1.5s infinite; }
.thinking-dot:nth-child(2) { animation-delay: 0.5s; }
.thinking-dot:nth-child(3) { animation-delay: 1s; }
```

### Fonts & icons

- **Playfair Display** weights **600, 700** (headlines/serif); **Inter** weights **400, 600, 700** (UI/body). Load via `next/font/google` and expose `--font-playfair` / `--font-inter` (referenced by the Tailwind `fontFamily` above).
- **Material Symbols Outlined** for icons: `<span className="material-symbols-outlined">movie_filter</span>`. Filled vs outlined is controlled by `font-variation-settings: 'FILL' 0|1`. Icon names actually used in the exports: `movie_filter`, `arrow_upward`, `chat_bubble`, `account_tree`, `auto_awesome_motion`, `hub`, `verified`, `search_insights`, `favorite`, `auto_awesome`, `psychology`, `menu`, `add`, `chat_bubble_outline`, `settings`, `visibility_off`/`visibility`, `database`.

### Images / assets

The Stitch HTML uses remote `lh3.googleusercontent.com` placeholder images (hero collage, avatars, movie posters). These are **mock assets** — do not hardcode those URLs. Replace with: a local/gradient background for the hero, an initials/icon avatar for the user (derive initial from the Supabase user email), and real poster data only if it exists (it does not yet — see Ground truth D). Keep the decorative inline **SVG node graphs** (they are self-contained markup, not external images).

---

## Ground truth C — Screen anatomy (what to build, per screen)

Break each `code.html` into small typed components under `apps/frontend/components/` and a route under `apps/frontend/app/`. Convert `class=`→`className=`, inline styles→Tailwind tokens (or the `globals.css` classes above), and repeated blocks→reusable components with typed props.

### Landing — `app/page.tsx` (from `reel_cinematic_ai_movie_assistant/code.html`)

Sections, top to bottom:
1. `TopNavBar` (shared) — brand "Reel", desktop nav links (Discover / Features / Library, anchor links `#discover`/`#features`/`#library`), and a "Sign In" action. Note the export renders "Sign In" twice (a hidden text link + a button) — **dedupe** to one primary "Sign In" button linking to `/login`.
2. `Hero` — `.hero-gradient` background, decorative SVG node graph overlay (`.node` pulse), headline "Ask anything about movies.", subcopy, two CTAs ("Start chatting" → `/chat` or `/login`; "See a demo" → anchor), and a **disabled** chat-input mockup (decorative only — it is not the real chat).
3. `HowItWorks` (`#discover`) — 3 `.glass-panel` cards (chat_bubble / account_tree / auto_awesome_motion).
4. `FeatureGrid` (`#features`) — 4 cards (hub / verified / search_insights / favorite).
5. `VisualBand` — a static chat mockup + an entity-graph SVG (Fincher / Se7en / Fight Club example).
6. `Footer` (shared) — brand, copyright, links, GitHub icon (inline SVG).

> **Decision — the landing page is a marketing surface, not the app.** Its sample content is **intentionally static** and must **NOT** be wired to the backend: the hero's disabled chat-input mockup, the `HowItWorks`/`FeatureGrid` copy, and the `VisualBand` Fincher chat + entity-graph SVG all stay as hardcoded presentational markup (port them faithfully as JSX, do not fabricate an API for them). This is deliberately different from the **app screens** (chat / sidebar / sources / graph), where every dynamic element must come from live data or an honest empty state. Rationale: there is no backend endpoint that could feed the landing samples (Ground truth A), so turning them "live" would mean inventing data — exactly what this plan forbids.

### Sign in — `app/(auth)/login/page.tsx` (from `sign_in_to_reel/code.html`)

- Two-column layout: left visual canvas (hidden on mobile) with brand wordmark, tagline, node-motif SVG; right auth card.
- The export toggles between **Sign in** and **Sign up** via inline JS (`toggleView`). Reimplement as React state (`useState<'signin' | 'signup'>`), not DOM class toggling.
- **Sign in** fields: EMAIL, PASSWORD (with a show/hide `visibility_off`↔`visibility` toggle button), a "Forgot?" link, primary "Sign in" button, an "or continue with" divider, a **Google** OAuth button, and a "New here? Create an account" toggle.
- **Sign up** fields: FULL NAME, EMAIL, PASSWORD, "Create account" button, and a toggle back to sign in.
- Keep the "Powered by Supabase" footer note.
- Fields use `.input-glow` focus styling.

### Chat (three-pane) — `app/chat/page.tsx` (from `reel_movie_intelligence_chat/code.html`)

Left `Sidebar` (`w-[260px]`):
- Brand + collapse `menu` button; "New Discovery" button (starts a fresh conversation — clears the active `thread_id`).
- Conversation history grouped by recency ("Today", "Previous 7 Days"), each item = `chat_bubble_outline` + truncated title. **Wire to `GET /chats`** (see Ground truth D) — the "Blade Runner 2049 Discussion", "A24 Horror Gems" etc. are mock and must go.
- User footer: avatar (initials), name, Settings.

Center `main` pane:
- Sticky `.glass-panel` header with the active conversation title + a decorative model badge (`psychology` "GPT-4 Movie Graph") — the badge is a **static label**, not data; keep or drop, but don't fabricate model info.
- `ChatThread` (scrollable, `.thin-scrollbar`): a list of `MessageBubble`s. User bubbles right-aligned (`elevated` bg, gold tint overlay); assistant bubbles left-aligned with an avatar icon and Playfair-styled text. A `ThinkingIndicator` ("Reel is searching the graph..." + `.thinking-dot` flicker) shown while awaiting the first token.
- `CitationChip` component exists in the mock (①②) but there is **no citation data** from the backend — render chips only if/when sources exist; otherwise omit them (do not hardcode the Blade Runner citations).
- `ChatInput`: `SuggestionChips` row (static prompt starters are acceptable as UX affordances) + an auto-growing `<textarea>` and a send button. Enter-to-send, Shift+Enter for newline.

Right `aside` pane (`w-[340px]`) — `SourcesPanel` / `GraphPanel` behind a **tabs** header ("Sources" / "Graph"). See Ground truth D — there is no live source/graph feed yet, so these render honest empty states.

---

## Ground truth D — Honest data wiring (no fabricated content)

The backend returns real structured sources and answer-level graph artifacts in
the SSE stream. It also returns the literal complete graph from authenticated
`GET /graph`. Source cards, citations, and highlighted nodes must use those live
payloads; never hardcode movie data.

- **Sources panel:** render `sources` events and preserve an honest empty state
  before retrieval.
- **Graph panel:** render the complete graph with the latest answer artifact
  overlaid through reducers.
- **Sidebar history:** this **is** live — use `GET /chats`, group by `updated_at` into "Today" / "Previous 7 Days" client-side, and refresh after each completed message (a new conversation is persisted server-side). Clicking an item loads it via `GET /chats/{id}` and sets the active `thread_id`.

---

## Prerequisites

- Phase 6 complete (backend secured; `/chat` requires a Supabase JWT). The backend runs on `http://localhost:8000`.
- Node 20+ and `pnpm` installed.
- The **`Reel` Supabase project** for the browser auth client. Fetch its config via the Supabase MCP plugin (see `.cursor/rules/supabase-mcp.mdc`): `get_project_url` and `get_publishable_keys` for `project_id: "bkhmqtcxoxtrydumgwfd"`. Write these into `apps/frontend/.env.local` (step 9) — never commit them.

## Steps

### 1. Create the Next.js app in `apps/frontend`

```powershell
cd apps
pnpm create next-app@latest frontend --ts --app --tailwind --eslint --src-dir=false --import-alias "@/*"
cd frontend
pnpm add @supabase/supabase-js @supabase/ssr
pnpm add @react-sigma/core @react-sigma/layout-forceatlas2 graphology
cd ../..
```

> **Tailwind version gotcha:** `create-next-app` may scaffold **Tailwind v4**, which configures theme in CSS via `@theme` in `globals.css` and does **not** create a `tailwind.config.ts`. This plan (and the `frontend` rule) are written around a `tailwind.config.ts`. Pick one, do not mix:
> - **Recommended (matches this plan):** pin v3 — `pnpm add -D tailwindcss@3 postcss autoprefixer` then `npx tailwindcss init -p`, and use the `tailwind.config.ts` in Ground truth B.
> - **Or v4:** translate the same tokens into the `@theme { --color-*, --font-*, ... }` block in `globals.css` and skip the JS config.
>
> **Sigma client-only requirement:** dynamically import the Sigma runtime with
> `next/dynamic` and `{ ssr: false }`. Use deterministic initial positions and
> run ForceAtlas2 in its worker API.

### 2. Port design tokens → `apps/frontend/tailwind.config.ts`

Use the **full** token map in **Ground truth B**. Do not abbreviate with "add remaining tokens" — copy the whole `colors`/`borderRadius`/`spacing`/`fontFamily`/`fontSize` set, then the `canvas`/`elevated`/`hairline` reconciliation tokens.

### 3. Custom CSS → `apps/frontend/app/globals.css`

Below the Tailwind directives, paste the **custom CSS block** from Ground truth B (`.glass-panel`, `.gold-glow`, `.hero-gradient`, `.text-glow`, `.thin-scrollbar`, `.input-glow`, and the `pulse-node`/`flicker` keyframes with `.node`/`.thinking-dot`). Also add the `.material-symbols-outlined` base rule if you self-host the icon font.

### 4. Fonts + icons — `apps/frontend/app/layout.tsx`

Load fonts via `next/font` (replaces the Stitch Google Fonts `<link>` tags), add Material Symbols, and expose the CSS vars the Tailwind config references. Use `bg-canvas` on `body` to match the export.

```tsx
import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--font-inter" });
const playfair = Playfair_Display({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-playfair" });

export const metadata: Metadata = { title: "Reel AI — Cinema Intelligence" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${inter.variable} ${playfair.variable}`}>
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
        />
      </head>
      <body className="bg-canvas text-on-surface font-body-lg text-body-lg antialiased">{children}</body>
    </html>
  );
}
```

**Do NOT** keep the Tailwind CDN `<script>` or the inline `tailwind.config` from the Stitch HTML — Tailwind is compiled by Next.js.

### 5. Supabase client + route protection

`apps/frontend/lib/supabaseClient.ts`:

```ts
import { createBrowserClient } from "@supabase/ssr";

/** Browser Supabase client for auth + session. */
export const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);
```

Protect `/chat`: guard it (client-side redirect to `/login` when `supabase.auth.getSession()` returns no session, and subscribe to `supabase.auth.onAuthStateChange`), or use Next middleware with `@supabase/ssr` cookies. After a successful login, redirect to `/chat`.

> **Auth wiring facts (verified against `apps/backend/src/api/auth.py`):** the backend verifies the Bearer token **asymmetrically** via Supabase JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, algorithms `RS256`/`ES256`, audience `authenticated`). The `Reel` project uses the new API-key format (the publishable key is `sb_publishable_...`, already present in the root `.env` as `SUPABASE_KEY`), which means it is on asymmetric JWT signing keys — so the `session.access_token` from the browser client **will** validate server-side. The browser client only ever needs the **publishable/anon** key (`NEXT_PUBLIC_SUPABASE_ANON_KEY`); never expose a service-role or secret key to the frontend. Get the token precisely with `const { data: { session } } = await supabase.auth.getSession(); const token = session?.access_token;` and send it as `Authorization: Bearer <token>`.

### 6. Typed API client (SSE + history) — `apps/frontend/lib/api.ts`

Single source for backend calls. **The SSE parser must handle named `event:` frames** (see Ground truth A) — this is the key correctness fix. No scattered `fetch` in components.

```ts
const API = process.env.NEXT_PUBLIC_API_URL!;

/** Shapes returned by the backend (mirror apps/backend/src/api/schemas.py). */
export interface ConversationSummary {
  id: string;
  thread_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}
export interface MessageOut {
  role: "user" | "assistant";
  content: string;
  created_at: string;
}
export interface ConversationDetail extends ConversationSummary {
  messages: MessageOut[];
}

/** Discriminated union of SSE events emitted by POST /chat. */
export type ChatEvent =
  | { type: "meta"; thread_id: string; conversation_id: string }
  | { type: "token"; text: string }
  | { type: "done" };

/** Stream an answer from POST /chat, decoding the meta/token/done SSE frames. */
export async function* streamChat(
  message: string,
  token: string,
  threadId?: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  });
  if (res.status === 401 || res.status === 403) throw new Error("unauthorized");
  if (res.status === 429) throw new Error("rate_limited");
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? ""; // keep incomplete trailing frame
    for (const frame of frames) {
      let eventName = "message";
      let dataLine = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
      }
      if (!dataLine) continue;
      const payload = JSON.parse(dataLine) as Record<string, unknown>;
      if (eventName === "meta") {
        yield { type: "meta", thread_id: String(payload.thread_id), conversation_id: String(payload.conversation_id) };
      } else if (eventName === "done") {
        yield { type: "done" };
      } else if (typeof payload.token === "string") {
        yield { type: "token", text: payload.token };
      }
    }
  }
}

/** List the current user's conversations (newest first). */
export async function listChats(token: string): Promise<ConversationSummary[]> {
  const res = await fetch(`${API}/chats`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`listChats failed: ${res.status}`);
  return res.json();
}

/** Fetch one conversation with its messages. */
export async function getChat(id: string, token: string): Promise<ConversationDetail> {
  const res = await fetch(`${API}/chats/${id}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`getChat failed: ${res.status}`);
  return res.json();
}

/** Delete a conversation. */
export async function deleteChat(id: string, token: string): Promise<void> {
  const res = await fetch(`${API}/chats/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok && res.status !== 204) throw new Error(`deleteChat failed: ${res.status}`);
}
```

> Use `fetch` (not `EventSource`) for `/chat` because `EventSource` cannot send an `Authorization` header. Pass an `AbortController.signal` and abort on unmount / when the user sends a new message.

### 7. Componentize the screens

Follow **Ground truth C** for the anatomy of each screen. Routes: `app/page.tsx` (landing), `app/(auth)/login/page.tsx` (auth), `app/chat/page.tsx` (three-pane chat). Components under `apps/frontend/components/`: `TopNavBar`, `Footer`, `Sidebar`, `ChatThread`, `MessageBubble`, `CitationChip`, `SourcesPanel`, `SourceCard`, `GraphPanel`, `ChatInput`, `SuggestionChips`, `ThinkingIndicator`. Type every prop; no `any`.

### 8. Wire real data (per Ground truth A & D)

- **Login page:** `supabase.auth.signInWithPassword({ email, password })`; **Sign up:** `supabase.auth.signUp({ email, password, options: { data: { full_name } } })`; **Google:** `supabase.auth.signInWithOAuth({ provider: "google" })` (or hide the Google button if OAuth isn't configured — don't leave a dead button). On success redirect to `/chat`; show inline errors on failure.
- **Chat page:** get the token via `supabase.auth.getSession()` → `session.access_token`. On send: append the user message, show `ThinkingIndicator`, consume `streamChat(...)`; on the `meta` event store `thread_id`; append each `token` to the streaming assistant `MessageBubble`; stop on `done`. Persist `thread_id` for the conversation; "New Discovery" resets it.
- **Sidebar:** load `listChats(token)`, group by `updated_at`, refresh after each completed answer. Item click → `getChat(id, token)` loads messages and sets `thread_id`.
- **Sources/Graph:** consume live SSE artifacts and `GET /graph`; preserve honest
  empty states while loading. **Remove ALL Stitch mock content from the app
  screens** (chat/auth).

### 9. Env + Docker

Create `apps/frontend/.env.local` (gitignored). Populate the Supabase values from the MCP plugin (`get_project_url` + `get_publishable_keys`, project_id `bkhmqtcxoxtrydumgwfd`) — do not paste them into any committed file:

```
NEXT_PUBLIC_SUPABASE_URL=https://bkhmqtcxoxtrydumgwfd.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable/anon key from get_publishable_keys>
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Create `apps/frontend/Dockerfile` (multi-stage, non-root; use Next.js `output: "standalone"`) and add a `frontend` service to `docker-compose.yml` (build context `apps/frontend`, map `3000:3000`, `depends_on: backend`). Keep the container on port 3000 so it stays inside the backend CORS allowlist.

Run locally (frontend must be on port 3000):

```powershell
pnpm --dir apps/frontend dev
```

## Environment variables

`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` (all `NEXT_PUBLIC_*` because they're read in the browser).

## Acceptance criteria

- [ ] All three screens render in Next.js and visually match the Stitch `code.html` (noir + gold canvas `#0E0E11`, Playfair/Inter, `.glass-panel` surfaces, gold accents).
- [ ] No hardcoded hex in components — only Tailwind theme tokens (including `canvas`/`elevated`/`hairline`) and the shared `globals.css` classes.
- [ ] No Tailwind CDN script and no inline `tailwind.config` from Stitch; Tailwind is compiled by Next.js.
- [ ] Login authenticates via Supabase and redirects to `/chat`; `/chat` is guarded (redirects unauthenticated users to `/login`); the chat page attaches the JWT to `/chat` and `/chats`.
- [ ] Sending a message streams tokens into the assistant bubble in real time, correctly decoding the `meta` → `token` → `done` SSE frames; `thread_id` is captured from `meta` and reused.
- [ ] Sidebar history is populated from `GET /chats` (grouped by recency) and refreshes after each answer; selecting an item loads it via `GET /chats/{id}`.
- [ ] Sources and graph panels contain only live backend data; the complete
  graph remains responsive under WebGL rendering and worker layout.
- [ ] All Stitch mock content is gone **from the app screens** (chat/auth): Blade Runner sample answer/citations, fake history titles, static source cards, remote placeholder image URLs.
- [ ] The **landing page** marketing samples (hero mockup, HowItWorks/FeatureGrid copy, VisualBand chat + graph SVG) are ported faithfully as static JSX and are **not** wired to any backend call.
- [ ] `pnpm --dir apps/frontend lint` and `pnpm --dir apps/frontend exec tsc --noEmit` pass.

## Do NOT

- Do NOT parse the SSE stream by looking for `thread_id`/`done` inside token `data:` payloads — they arrive as named `event: meta` / `event: done` frames.
- Do NOT invent backend endpoints or SSE events beyond the implemented
  `/graph`, `sources`, and `graph` contracts.
- Do NOT hardcode movie sources, graph nodes, citation chips, or history titles **in the app screens** — use live data or an empty state. (The landing page's static marketing samples are the deliberate exception — see the decision note in Ground truth C.)
- Do NOT keep Stitch's inline `tailwind.config` script, the CDN Tailwind, or the remote `lh3.googleusercontent.com` images.
- Do NOT scatter `fetch` calls in components — use `lib/api.ts`.
- Do NOT use `any` for props or API responses.
- Do NOT use `EventSource` for `/chat` (it can't send the `Authorization` header).
- Do NOT run the frontend on a port outside the backend CORS allowlist (default 3000) without updating `CORS_ALLOW_ORIGINS`.

## Relevant rules & skills

- Rules: `frontend`, `project-structure`, `security`, `documentation`.
- Skill: `port-stitch-screen` (run it per screen).
