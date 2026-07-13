# Reel frontend

Next.js App Router client for Reel's authenticated movie chat and complete
knowledge-graph view.

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

`GraphCanvas` dynamically loads a client-only Sigma.js runtime. The complete
Movie/Person/Genre/Keyword graph is held in a Graphology
`MultiDirectedGraph`, drawn through WebGL, and laid out with ForceAtlas2 in a
Web Worker. Answer artifacts are applied with Sigma node and edge reducers so
the full dataset remains loaded while cited neighborhoods are highlighted.

## Verification

```powershell
pnpm lint
pnpm exec tsc --noEmit
pnpm build
```
