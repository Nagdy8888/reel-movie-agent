# Phase 8 — Next.js Frontend (Port Stitch Screens)

## Objective

Build the `apps/frontend` Next.js app by porting the three delivered Stitch screens into clean React components, then wire it to the backend:
- **Landing** ← `stitch_reel_ai_movie_assistant/reel_cinematic_ai_movie_assistant/code.html`
- **Sign in** ← `stitch_reel_ai_movie_assistant/sign_in_to_reel/code.html`
- **Chat (three-pane)** ← `stitch_reel_ai_movie_assistant/reel_movie_intelligence_chat/code.html`

Wire **Supabase auth** (login/session), **SSE streaming** chat to the backend `/chat`, and the **Sources** + **Graph** panels to live data. Use the design tokens from `stitch_reel_ai_movie_assistant/cinematic_intelligence_system/DESIGN.md`.

> Follow the `port-stitch-screen` skill for each screen — it has the exact checklist.

## Prerequisites

- Phase 6 complete (backend secured; `/chat` requires a Supabase JWT).
- Node 20+ and `pnpm` installed.
- The **`Reel` Supabase project** for the browser auth client. Fetch its config via the Supabase MCP plugin (see `.cursor/rules/supabase-mcp.mdc`): `get_project_url` and `get_publishable_keys` for `project_id: "bkhmqtcxoxtrydumgwfd"`. Write these into `apps/frontend/.env.local` (step 8) — never commit them.

## Steps

### 1. Create the Next.js app in `apps/frontend`

```powershell
cd apps
pnpm create next-app@latest frontend --ts --app --tailwind --eslint --src-dir=false --import-alias "@/*"
cd frontend
pnpm add @supabase/supabase-js @supabase/ssr
pnpm add react-force-graph-2d   # for the Graph panel (or cytoscape)
cd ../..
```

### 2. Port design tokens → `apps/frontend/tailwind.config.ts`

Open `stitch_reel_ai_movie_assistant/cinematic_intelligence_system/DESIGN.md` and each `code.html` (they contain an inline `tailwind.config`). Lift the palette/typography/radii into `theme.extend`. The palette is noir + gold:

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#17130d",
        "surface-2": "#211a10",
        primary: "#ffd185",
        "primary-container": "#e8b457",
        crimson: "#b3261e",
        // add remaining tokens verbatim from DESIGN.md / code.html
      },
      fontFamily: {
        display: ["var(--font-playfair)", "serif"],
        sans: ["var(--font-inter)", "sans-serif"],
      },
      borderRadius: { xl: "1rem", "2xl": "1.5rem" },
    },
  },
  plugins: [],
};
export default config;
```

Verify the exact hex values against `DESIGN.md` — do not guess; copy them.

### 3. Fonts + icons — `apps/frontend/app/layout.tsx`

Load fonts via `next/font` (replace the Stitch Google Fonts `<link>` tags), add Material Symbols, and expose CSS vars used by the Tailwind config:

```tsx
import { Inter, Playfair_Display } from "next/font/google";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const playfair = Playfair_Display({ subsets: ["latin"], variable: "--font-playfair" });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${playfair.variable}`}>
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined"
        />
      </head>
      <body className="bg-surface text-white font-sans">{children}</body>
    </html>
  );
}
```

**Do NOT** keep the Tailwind CDN `<script>` from the Stitch HTML — Tailwind is compiled by Next.js.

### 4. Supabase client — `apps/frontend/lib/supabaseClient.ts`

```ts
import { createBrowserClient } from "@supabase/ssr";

/** Browser Supabase client for auth + session. */
export const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);
```

### 5. Typed API client (SSE) — `apps/frontend/lib/api.ts`

```ts
/** Streaming client for the backend /chat SSE endpoint. */
export async function* streamChat(
  message: string,
  token: string,
  threadId?: string,
): AsyncGenerator<{ token?: string; thread_id?: string; done?: boolean }> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message, thread_id: threadId }),
  });
  if (!res.body) throw new Error("No stream");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (line) yield JSON.parse(line.slice(5).trim());
    }
  }
}
```

### 6. Componentize the screens

Break each `code.html` into small typed components under `apps/frontend/components/` and routes under `apps/frontend/app/`:

- Routes: `app/page.tsx` (landing), `app/(auth)/login/page.tsx` (sign in), `app/chat/page.tsx` (three-pane chat).
- Components: `Sidebar`, `ChatThread`, `MessageBubble`, `CitationChip`, `SourcesPanel`, `GraphPanel`, `ChatInput`, `SuggestionChips`.

For each: convert `class=` → `className=`, inline styles → Tailwind tokens, static markup → JSX, and repeated blocks (message bubble, source card, sidebar item) → reusable components with typed props.

### 7. Wire real data

- **Login page:** `supabase.auth.signInWithPassword(...)`; on success, redirect to `/chat`.
- **Chat page:** get the session token via `supabase.auth.getSession()`; on send, consume `streamChat(...)` and append tokens to the streaming `MessageBubble`. Persist `thread_id` per conversation.
- **SourcesPanel / GraphPanel:** render the movies/citations the backend returned. (If the backend does not yet emit structured sources over SSE, add a `sources` SSE event in the backend chat route and consume it here.)
- Replace ALL Stitch mock content (the Blade Runner example, fake history, static sources/graph) with live data.

### 8. Env + Docker

Create `apps/frontend/.env.local` (gitignored). Populate the Supabase values from the MCP plugin (`get_project_url` + `get_publishable_keys`, project_id `bkhmqtcxoxtrydumgwfd`) — do not paste them into any committed file:
```
NEXT_PUBLIC_SUPABASE_URL=https://bkhmqtcxoxtrydumgwfd.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<publishable/anon key from get_publishable_keys>
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Create `apps/frontend/Dockerfile` (multi-stage, non-root) and add a `frontend` service to `docker-compose.yml` (build context `apps/frontend`, port `3000:3000`, `depends_on: backend`).

Run locally:
```powershell
pnpm --dir apps/frontend dev
```

## Environment variables

`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`.

## Acceptance criteria

- [ ] All three screens render in Next.js and visually match the Stitch `code.html` (noir + gold, Playfair/Inter).
- [ ] No hardcoded hex in components — only Tailwind theme tokens.
- [ ] No Tailwind CDN script; Tailwind is compiled by Next.js.
- [ ] Login authenticates via Supabase; the chat page attaches the JWT to `/chat`.
- [ ] Sending a message streams tokens into the chat thread in real time.
- [ ] Sources/Graph panels show live data (no mock content left).
- [ ] `pnpm --dir apps/frontend lint` and `pnpm --dir apps/frontend tsc --noEmit` pass.

## Do NOT

- Do NOT keep Stitch's inline `tailwind.config` script or CDN Tailwind in the React app.
- Do NOT leave mock/demo content (Blade Runner sample, fake sources).
- Do NOT scatter `fetch` calls in components — use `lib/api.ts`.
- Do NOT use `any` for props or API responses.

## Relevant rules & skills

- Rules: `frontend`.
- Skill: `port-stitch-screen` (run it per screen).
