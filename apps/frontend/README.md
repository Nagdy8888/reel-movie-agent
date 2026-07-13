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
pnpm exec tsc --noEmit
pnpm build
pnpm exec playwright test tests/graph-focused.spec.ts
pnpm benchmark:graph
```
