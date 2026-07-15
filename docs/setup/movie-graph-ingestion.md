# Hybrid CMU ingestion (LightRAG + Supabase projection)

Reel ingests a **deterministic 1,000-movie** subset of the CMU MovieSummaries
corpus two ways:

1. **LightRAG (retrieval)** — full LLM extraction over each plot summary into a
   self-hosted PostgreSQL 16.6+ with Apache AGE + pgvector.
2. **Supabase projection (UI graph)** — typed `Movie` / `Person` / `Genre`
   tables (with TMDB posters) that power the sources panel, result graph, and
   full graph.

The two writes are not one atomic transaction. Correctness comes from
idempotent upserts, resumable LightRAG doc status, and a post-load referential
integrity check.

## Data files

Download [CMU MovieSummaries](https://www.cs.cmu.edu/~ark/personas/) and unpack
into `datasets/MovieSummaries/`:

| File | Role |
|------|------|
| `plot_summaries.txt` | `wikipedia_id \\t summary` |
| `movie.metadata.tsv` | title, release date, box office, genres JSON |
| `character.metadata.tsv` | cast rows with Freebase actor IDs |

## Subset selection

Keep movies with a summary, joinable metadata, ≥1 cast row, and **non-null box
office**. Sort by `box_office DESC, wikipedia_id ASC`, take `SUBSET_SIZE`
(default 1000). Deterministic and repeatable.

IDs:

- `movie:{wikipedia_id}`
- `person:{percent-quoted freebase_actor_id}`
- `genre:{percent-quoted casefold(name)}`

## Prerequisites

Configure `.env` from `.env.example`:

- `RAG_PG_*` — AGE+pgvector Postgres for LightRAG
- `SUPABASE_DB_URL` — projection + LangGraph memory
- `OPENAI_API_KEY`, `TMDB_API_ACCESS_TOKEN`, `LANGSMITH_*`
- `INGEST_CONCURRENCY` (default 4), `SUBSET_SIZE` (default 1000)

Start the RAG database:

```bash
docker compose up -d rag-postgres
```

## Run order

From the repository root:

```bash
# Smoke (≈ minutes)
uv run python -m ingestion.ingest --limit 25

# Full subset (hours; ~$2–3 on gpt-4o-mini + embeddings)
uv run python -m ingestion.ingest --limit 1000
```

Each movie is inserted as its own LightRAG document with
`ids=[file_paths]=[movie:{wikipedia_id}]` so retrieved context carries a
recoverable key. Already-`processed` documents are skipped (restartable).
Existing poster URLs are reused on reruns. `--limit` is authoritative for the
Supabase projection: movies outside the selected deterministic prefix are
pruned, with relationship rows removed by foreign-key cascades.

### Current quota-limited state

The 2026-07-15 run passed the 25-movie smoke ingest, then reached the OpenAI API
limit during the 1,000-movie extraction. The largest fully processed
deterministic prefix was finalized at 503 movies:

```bash
uv run python -m ingestion.ingest --limit 503
```

This produced 503/503 posters, 503 processed LightRAG documents, and a matching
503-movie Supabase projection. Set `SUBSET_SIZE=503` until quota is available.
To continue toward the original target, restore `SUBSET_SIZE=1000` and rerun;
processed documents are skipped.

## Verification

The ingest CLI asserts:

- Supabase `movies` count == selected subset size
- No orphan `acted_in` / `in_genre` movie FKs
- LightRAG processed-doc count == subset size

Manual checks:

- A context-only query returns text containing `movie:{id}` tokens
- `/graph` returns Movies, People, Genres with `Acted In` / `In Genre` links
- LangSmith shows token usage for ingestion and query-time LLM calls

## Production note

Managed Postgres (including Supabase) **does not** offer Apache AGE. LightRAG's
four stores must live on a self-hosted AGE+pgvector image (Compose service
`rag-postgres`, or equivalent VM/container). The UI projection stays on
Supabase.
