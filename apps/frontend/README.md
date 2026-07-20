# Reel frontend

Next.js App Router client for Reel's authenticated movie chat and focused
knowledge-graph explorer.

## Development

Create `.env.local` with the public Supabase URL/key and backend URL:

```text
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Then run:

```powershell
pnpm install
pnpm dev
```

Open `http://localhost:3000`.

## Workspace architecture

`ChatWorkspace` composes four focused client hooks:

- `useAuthSession` owns Supabase browser-session changes and sign-out.
- `useChats` owns conversation history, active transcript loading, and deletion.
- `useChatStream` owns the abortable SSE turn lifecycle.
- `useAnswerGraph` owns answer artifacts and lazy full-network loading.

On small viewports the graph and chat become tabbed panels and conversation
history opens as a drawer. Desktop keeps the resizable three-pane layout.

## Authentication

Next.js 16 `proxy.ts` validates Supabase claims before `/chat` renders, refreshes
auth cookies, and redirects authenticated users away from `/login`. OAuth and
password-recovery links return through `/auth/callback`, where the PKCE code is
exchanged for the cookie session. The browser session remains responsible for
supplying the access token to the authenticated FastAPI API.

## Graph rendering

`GraphCanvas` dynamically loads a client-only Sigma.js runtime. The default
Answer Network renders only the Movie/Person/Genre/Keyword subgraph delivered
with the current answer, which keeps labels and relationships readable.
Citations and source cards focus their stable movie node IDs.

The 48,734-node complete graph is not downloaded during workspace startup.
Selecting Full Network loads it once into a Graphology `MultiDirectedGraph`,
draws it through WebGL, and lays it out with ForceAtlas2 in a Web Worker.
Category controls use Sigma reducers to hide nodes and edges without rebuilding
the graph or restarting layout. The current answer remains highlighted inside
the full explorer.

## Verification

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
pnpm benchmark:graph
```

Vitest covers SSE parsing and the pure chat/graph helpers. Playwright uses a
development-only server guard bypass with mocked browser/API sessions; the
bypass is unavailable in production.
