# Build and load the 5,000-movie graph

The application uses a deterministic 5,000-movie subset of the Kaggle Movies
Dataset. Kaggle supplies trusted relationships, so ingestion maps the CSV data
directly into Neo4j instead of asking an LLM to extract a graph.

## Graph schema

- `Movie(tmdbId, title, year, overview, tagline, posterUrl, rating, voteCount, ...)`
- `Person(tmdbId, name, profileUrl)`
- `Genre(name)`
- `Keyword(name)`
- `ACTED_IN`, `DIRECTED`, `WROTE`, `PRODUCED`, `IN_GENRE`, and `HAS_KEYWORD`

Movie and Person identity is based on TMDB IDs. Titles and names are display
values and are intentionally not unique.

## Prerequisites

Put these Kaggle exports in one local directory:

- `movies_metadata.csv`
- `credits.csv`
- `keywords.csv`

Configure `.env` with the Neo4j and OpenAI values documented in `.env.example`.
The embedding model is `text-embedding-3-small` with 1,536 dimensions.

## Run order

Run all commands from the repository root:

```powershell
uv run python scripts/build_movies_graph.py "C:\path\to\kaggle" --limit 5000
uv run python -m ingestion.load_graph --replace-existing --batch-size 200
uv run python -m ingestion.build_index --batch-size 100
```

`--replace-existing` deletes the current Neo4j graph. It is deliberately
required when obsolete sample nodes are present; omit it for an idempotent merge
after the initial replacement.

The generated asset is
`apps/agents/src/agents/data/movies_subset.json.gz`. It is deterministic and
included in the agents wheel.

## Measured bundle

The current package contains:

- 5,000 Movie nodes
- 35,419 Person nodes
- 19 Genre nodes
- 8,296 Keyword nodes
- 48,734 total nodes
- 136,709 total relationships

This is below Aura Free's 200,000-node and 400,000-relationship limits.
Embedding the current documents used exactly 1,152,639 input tokens. At
`$0.02 / 1M` tokens, the one-time embedding cost is about `$0.0231`.

## Verification

The loader compares every node and relationship count with the bundle manifest
and fails on any difference. The index builder drops incompatible indexes,
writes vectors by `Movie.tmdbId`, and waits for these indexes to become online:

- `movie_plot_embeddings`: VECTOR, cosine, 1,536 dimensions
- `movie_fulltext`: FULLTEXT over `title`, `tagline`, `overview`, and `embed_text`

Useful read-only checks:

```cypher
MATCH (m:Movie) RETURN count(m);
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY type(r);
SHOW INDEXES YIELD name, type, state, properties, options RETURN *;
```

The frontend requests the authenticated complete graph once. FastAPI compresses
the JSON response, Sigma.js renders it with WebGL, and ForceAtlas2 runs in a Web
Worker so layout does not block the browser's main thread.

Run `pnpm --dir apps/frontend benchmark:graph` to repeat the complete-graph
browser check. The implementation benchmark rendered 48,734 nodes and 136,709
links in 5.98 seconds in headless Edge; a 100 ms responsiveness probe completed
in 144 ms while worker layout was active, and pan/zoom/reset remained usable.
