# QA Documentation Review (C4 Model) — `apps/agents`, `apps/backend`, and `docs/`

**Date:** 2026-04-20
**Reviewer:** QA / Documentation
**Scope:** All standalone docs under `/docs/`, all `README.md` files inside `apps/agents/` and `apps/backend/`, the top-level `README.md`, and in-code documentation (docstrings, type hints, Pydantic descriptions) in both apps.
**Out of scope:** `apps/frontend/`, `gas/` source comments. Doc-internal style nits (Markdown wrapping, table alignment, etc.).
**Companion docs:** `14_QA_SECURITY_REVIEW.md`, `15_QA_CODE_QUALITY_REVIEW.md`.

---

## Executive summary

The team has produced **13 numbered reference docs (~4,200 LOC of Markdown)** plus per-app and per-package READMEs. Mermaid diagrams are used liberally and accurately. Spot-checking a handful of claims against the source found no contradictions — the docs are not just thorough, they're *correct*. That is rare and worth preserving.

The weak spot is **structural**: docs are organised by *topic* (PO parser, FastAPI, Security, …) rather than by *level of abstraction*. Anyone landing on `docs/` sees thirteen equally-weighted files and has no signal about which one to open first or how they fit together. The C4 model gives us a cleaner lens: are we covering **System Context → Container → Component → Code**, and is each level distinct from the next?

**Headline findings:**

1. **No dedicated Level-1 (System Context) diagram.** Doc 01 §1 *contains* one inside a larger flow chart, but it mixes Context (people + external systems) with Container (FastAPI / agents subdirs) and Component (specific files like `main.py + config.py + deps.py`) in the same picture. C4's whole point is that mixing levels makes the diagram unreadable as you scale.
2. **No canonical Level-2 (Container) diagram.** The closest thing is the `uv` workspace graph in Doc 01 §2, which is really a *package* dependency graph — useful, but it shows code-level structure, not deployable units (FastAPI process, Next.js process, Postgres, Airtable, GAS runtime).
3. **Level 3 (Component) is the strongest level.** Docs 02–07 are all good Component-level views. They aren't *labelled* that way, but each one decomposes one container into its components.
4. **Level 4 (Code) docs are weakest.** ~70% of public functions have no docstring. The most important functions in the system — the LangGraph nodes — are silent about what state keys they read and write. Doc 08 (Data Models) is the only formal Code-level reference and is good.
5. **Deployment view exists implicitly** in Doc 11 via `docker-compose.yml`, but there is no diagram showing what runs where (process boundaries, ports, persistence).
6. **Dynamic views are excellent.** Sequence diagrams in Doc 01 §3-§4, Doc 02 §2, Doc 05 §3 carry a lot of weight and are accurate.

Issue counts:

| Severity | Count |
|----------|-------|
| High     | 11 |
| Medium   | 19 |
| Low / Info | 13 |
| **Total** | **43** |

---

## A short C4 primer (so this report stands on its own)

The [C4 model](https://c4model.com) describes software architecture at four nested levels of detail:

| Level | Question it answers | Audience | Diagram zoom |
|-------|--------------------|----------|--------------|
| **1. System Context** | What is *this system* and who interacts with it? | Anyone — exec, ops, new hire | One box (the system) plus people and external systems around it |
| **2. Container** | What deployable units make up the system, and how do they talk? | Engineers, ops | One box per process/runtime/datastore (FastAPI app, browser SPA, Postgres, third-party SaaS) |
| **3. Component** | What are the major modules inside one container? | Engineers working on that container | One box per module/package within a container |
| **4. Code** | How is one component implemented? | Engineers reading the code | Class/schema diagrams, types, docstrings |

**Plus two supplementary views:**
- **Dynamic diagrams** — sequence/flowcharts showing how containers/components collaborate at runtime.
- **Deployment diagrams** — where each container actually runs (machines, VMs, k8s pods, ports).

The cardinal rule: **don't mix levels in the same picture.** A single diagram with users, FastAPI, individual route files, and database tables on it is "everything at once" — readable to its author, opaque to everyone else.

---

## C4 coverage matrix

| C4 view | Where it lives today | Quality | Notes |
|---|---|---|---|
| **Level 1 — System Context** | Doc 01 §1; top-level `README.md` "Architecture" diagram | **Mixed** (level-bleed) | Both diagrams *include* context but layer in container + component detail. No "pure" Level-1 diagram exists. |
| **Level 2 — Container** | Doc 01 §1 (mixed in), Doc 11 §6 (`docker-compose.yml` annotated), Doc 09 §2 (env-var consumer map) | **Implicit, fragmented** | No single canonical Container diagram. Reader assembles it from three places. |
| **Level 3 — Component** | Doc 02 (po_parser nodes), Doc 03 (image_tagging nodes), Doc 04 (services), Doc 05 (backend modules), Doc 06 (frontend), Doc 07 (GAS scripts) | **Strong** | Every container has a Component view. They aren't labelled or styled consistently with one another. |
| **Level 4 — Code** | Doc 08 (data models / schemas); in-code docstrings, type hints, Pydantic models | **Weak** | Doc 08 is solid. Source code itself is heavily under-documented (see Code-level findings below). |
| **Dynamic** | Doc 01 §3 (PO sequence), §4 (image sequence); Doc 02 §2 (routing flow); Doc 05 §3 (bulk upload state machine); Doc 07 §2-§4 (GAS flows) | **Strong** | Sequence diagrams are accurate and pull a lot of weight. |
| **Deployment** | Doc 11 (Dockerfile walkthrough, compose file); scattered hints in Doc 01 and README | **Partial** | No explicit deployment diagram showing nodes/ports/persistence. |

---

## Per-doc C4 mapping

| Doc | Title | Primary C4 level(s) | Notes |
|---|---|---|---|
| 01 | System Architecture | Context + Container + Dynamic | Tries to be all things; level-bleeds (see D1). |
| 02 | PO Parser Agent | Component (of `agents` container) + Dynamic | Clear. |
| 03 | Image Tagging Agent | Component (of `agents` container) + Dynamic | Clear. |
| 04 | Shared Services | Component (of `agents` container) | Clear; ranks the service clients. |
| 05 | FastAPI Backend | Component (of `backend` container) + Dynamic | Clear. |
| 06 | Frontend Dashboard | Component (of `frontend` container) | Clear. |
| 07 | GAS Scripts | Component (of `gas-scripts` container) + Dynamic + How-to (deployment §9) | Mixed: §9 doesn't fit a Component doc. |
| 08 | Data Models & Schemas | Code (level 4) — schemas across containers | Clear; cross-cuts containers. |
| 09 | Configuration & Env | Code (level 4) — config | Clear, but Container-coupled (env vars belong to specific containers). |
| 10 | Security & Auth | Cross-cutting concern | Touches Context (auth boundary), Container (CORS), and Code (HMAC impl). |
| 11 | Deployment & Docker | Deployment (supplementary) | Closest thing to a Deployment view; lacks a single picture. |
| 12 | Development Workflow | Operational guide (no C4 mapping) | Setup + tools. |
| 13 | Tooling Config Files | Code (level 4) — repo-level config | Clear. |
| 14 / 15 | QA reviews | Out of scope (this report's siblings) | — |

The mapping is reasonable. The two structural issues are: (a) Level 1 has no home of its own, and (b) Level 2 is split across three docs.

---

## Findings

### Level 1 — System Context

#### D1. No dedicated System Context diagram (level-bleed in Doc 01 §1)
- **Severity:** High
- **Location:** `docs/01_SYSTEM_ARCHITECTURE.md:9-65`, `README.md` "Architecture" diagram
- **Issue:** The flow chart at the top of Doc 01 simultaneously depicts (a) external systems (Gmail, Drive, Sheets, OpenAI, Airtable, Supabase), (b) deployable containers (`apps/backend`, `apps/agents`, `Next.js`, `gas-scripts`), and (c) internal modules (`main.py + config.py + deps.py`, `routes/`, `services/`). Three C4 levels in one picture.
- **Impact:** Readable to the author, dense for newcomers. There is no place a non-engineer (or a new hire on day one) can see "what is this system and who uses it?" without having to mentally subtract the implementation details.
- **Fix:** Add a true System Context diagram at the top of Doc 01 (or as a new `00_SYSTEM_CONTEXT.md`). One box: **NALM AI Agents Platform**. Around it: **Operations Team** (uploads images via dashboard), **PO Inbox** (Gmail), **Customer Drive Folder** (Google Drive), **External LLM** (OpenAI), **PO System of Record** (Airtable), **Tag Database** (Supabase), **Spreadsheet of Record** (Google Sheets). One arrow per relationship, labelled with the data crossing the boundary. Keep the existing detailed flow chart as `§ 2 Container view` (see D2 below).

#### D2. No human actors named anywhere
- **Severity:** High
- **Location:** All docs
- **Issue:** The docs describe systems talking to systems but never name **who** is using them. Is there an "ops user" who triages flagged images? Is there a "buyer" whose POs are being parsed? Is the GAS callback authored by a "Workspace admin"? Without actors, the system's *purpose* is implicit.
- **Impact:** New contributors infer the use case from the code rather than the docs. Stakeholder communication suffers — there is no diagram to show a non-technical reader.
- **Fix:** In the new System Context diagram, draw human actors as people (C4 conventionally uses a stick-figure shape). At minimum: **Ops user** (image dashboard), **Purchasing team** (sender of PO emails — implicit actor), **Platform engineer** (deploys, rotates secrets).

#### D3. External system trust boundaries are not drawn
- **Severity:** Medium
- **Location:** Doc 10 mentions auth, Doc 01 §1 shows external systems
- **Issue:** No diagram annotates which boundaries are *trusted* (internal) vs *untrusted* (external API or webhook ingress). Security review (`14_QA_SECURITY_REVIEW.md`) lists CORS / webhook secret / SSRF concerns; a Context-level boundary diagram would make those concerns visually obvious.
- **Fix:** In the Context diagram, draw a dashed line marking the internal trust boundary. Annotate every crossing arrow with the auth mechanism (`x-webhook-secret`, `Bearer`, `none`).

---

### Level 2 — Container

#### D4. No single canonical Container diagram
- **Severity:** High
- **Location:** Implied across `01_SYSTEM_ARCHITECTURE.md:9-93`, `09_CONFIGURATION_AND_ENV.md`, `11_DEPLOYMENT_AND_DOCKER.md:6`
- **Issue:** Three diagrams each show *part* of the container picture:
  1. Doc 01 §1 mixes containers with external systems and components.
  2. Doc 01 §2 shows the `uv` workspace as Python packages (a Code-level concern).
  3. Doc 11 walks through `docker-compose.yml` in prose but never draws it.
- **Impact:** The most-asked operational question — *"what processes do I have to run, on what ports, with what persistent stores"* — has no single answer.
- **Fix:** A dedicated Container diagram under `01 §2`:
  ```
  [Browser]
      │ HTTPS
      ▼
  [Next.js  :3000]  ──HTTP──▶  [FastAPI  :8000]  ──in-process──▶  [LangGraph agents]
                                       │                                 │
                                       │ psycopg pool                    │ httpx
                                       ▼                                 ▼
                                 [Postgres / Supabase]            [OpenAI API]
                                       ▲                                 │
                                       │                                 │
   [GAS runtime] ─POST /webhook/email──┤                          [Airtable API]
                  POST /webhook/drive ─┘
   [GAS Sheets] ◀──POST callback (httpx) ──── [LangGraph agents]
  ```
  Same data, single picture, no module-level detail.

#### D5. The `uv` workspace graph is mis-labelled as architecture
- **Severity:** Medium
- **Location:** `docs/01_SYSTEM_ARCHITECTURE.md:68-93`
- **Issue:** The graph in §2 shows package members (`apps/agents`, `apps/backend`) and per-file detail (`main.py`, `config.py`, `langgraph.json`). That's a *build/dependency* view, not a runtime container view. Calling it "uv workspace dependency graph" is honest, but it sits where a Container diagram should live.
- **Fix:** Move it into `13_TOOLING_CONFIG_FILES.md` or `12_DEVELOPMENT_WORKFLOW.md` where build-time concerns belong. Replace the slot with the runtime Container diagram from D4.

#### D6. Container responsibilities are not summarised
- **Severity:** Medium
- **Location:** N/A — missing
- **Issue:** Even after reading every doc, there is no one-line "what each container is responsible for" table. Each container has a doc, but no consolidated table.
- **Fix:** Append to Doc 01:
  ```
  | Container        | Tech                | Responsibility                              | Persistent state |
  |------------------|---------------------|---------------------------------------------|------------------|
  | apps/backend     | FastAPI + uvicorn   | HTTP ingress; auth; orchestrates agents     | None             |
  | apps/agents      | LangGraph (in-proc) | LLM pipelines; talks to OpenAI/Airtable/DB  | None             |
  | apps/frontend    | Next.js             | Image dashboard UI                          | None             |
  | gas-scripts      | Google Apps Script  | Polls Gmail/Drive; receives callbacks       | Google's         |
  | Postgres         | Supabase-managed    | image_tags + LangGraph checkpoints          | Yes              |
  | Airtable         | SaaS                | PO records + items                          | Yes              |
  ```

#### D7. Doc 09 (env vars) is split by container but doesn't show it
- **Severity:** Medium
- **Location:** `docs/09_CONFIGURATION_AND_ENV.md`
- **Issue:** Env vars are owned by specific containers (`OPENAI_API_KEY` → `agents`, `CORS_ALLOW_ORIGINS` → `backend`, `WEBHOOK_SECRET` → `gas-scripts` and `backend`). The doc lists vars in one big table without grouping by consumer.
- **Fix:** Group the env-var table by container (`backend` vars / `agents` vars / `gas-scripts` Script Properties / shared). Once D4 (Container diagram) exists, add a tiny inline icon next to each var pointing to the consuming container.

---

### Level 3 — Component

#### D8. Component docs are not visually consistent across containers
- **Severity:** Medium
- **Location:** Docs 02, 03, 04, 05, 06, 07
- **Issue:** Each Component-level doc uses its own diagram style. Doc 02's "5-node pipeline" looks nothing like Doc 05's "routes/middleware/services" decomposition, even though both are Component diagrams of one container. Mermaid is used everywhere, but the shapes, colours, and groupings drift.
- **Fix:** Adopt a tiny visual contract: every Component diagram has a labelled `subgraph` named after the container, contains only nodes inside that container, and uses one shape style. Half a day of polishing; pays back forever.

#### D9. The `services/` package's component view is buried
- **Severity:** Medium
- **Location:** `docs/04_SHARED_SERVICES.md`
- **Issue:** Doc 04 *is* the Component view of `apps/agents/src/services/`, but it's titled "Shared Services" — a name that reads like a cross-cutting concern doc. A reader looking for "what's inside the agents container?" goes to Doc 02 / 03 (which only cover the two graphs) and misses Doc 04 entirely.
- **Fix:** Either rename Doc 04 to `04_AGENTS_SERVICES_COMPONENTS.md` or add a "Components of `apps/agents`" subsection to Doc 02 that points to it: "agent nodes (this doc) and service clients (Doc 04) together make up the `agents` container".

#### D10. No Component diagram for the FastAPI dependency graph
- **Severity:** Medium
- **Location:** `docs/05_FASTAPI_BACKEND.md`
- **Issue:** Doc 05 describes routes, middleware, and `services/` but does not draw the **dependency injection** graph — `routes/*` → `Depends(get_image_graph)` / `Depends(get_supabase_client)` → `deps.py` → `services.checkpointer` / `services.supabase`. This is the most impactful internal structure to understand when adding a route.
- **Fix:** Add a small `flowchart LR` showing the dep wiring; reference Doc 13 (lifespan) for shutdown order.

#### D11. GAS Scripts §9 is a how-to in the middle of a Component doc
- **Severity:** Medium
- **Location:** `docs/07_GAS_SCRIPTS.md` §9 (deployment steps)
- **Issue:** The bulk of Doc 07 is a Component view of the GAS container. §9 ("clasp login → push → Deploy as Web App → add triggers") is procedural setup. C4 keeps these separate — Component docs answer "what is it"; deployment/setup answers "how do I get one running".
- **Fix:** Move §9 to Doc 11 (Deployment) or to `12_DEVELOPMENT_WORKFLOW.md`. Leave §1-§8 in Doc 07 as the pure Component view.

#### D12. PO Parser nodes README is too thin to act as a Component anchor
- **Severity:** Low
- **Location:** `apps/agents/src/agents/po_parser/nodes/README.md`
- **Issue:** It exists, which is good. But it's a one-line list of files. Doesn't say *what each node is responsible for* or *what state keys it reads/writes*.
- **Fix:** Either grow it into a one-table-per-node summary, or shrink it to a single `→ See docs/02_PO_PARSER_AGENT.md` redirect so there's only one source of truth.

#### D13. `image_tagging/nodes/README.md` likewise minimal
- **Severity:** Low
- **Location:** `apps/agents/src/agents/image_tagging/nodes/README.md`
- **Fix:** Same as D12. Same node-level summary table or redirect to Doc 03.

---

### Level 4 — Code (in-code documentation)

(Per-finding `path:line` references are gathered into themes here; the full per-function inventory is in the appendix at the bottom of this doc.)

#### D14. ~70% of public functions have no docstring
- **Severity:** High
- **Location:** Pervasive across `apps/agents/src/` and `apps/backend/src/`
- **Most damaging gaps** — every LangGraph node:
  - `apps/agents/src/agents/po_parser/nodes/classifier.py:39` — `classify_node`
  - `apps/agents/src/agents/po_parser/nodes/extract_po.py:295` — `extract_po_node`
  - `apps/agents/src/agents/po_parser/nodes/validator.py:34` — `validator_node`
  - `apps/agents/src/agents/po_parser/nodes/airtable_writer.py:26` — `airtable_writer_node`
  - `apps/agents/src/agents/po_parser/nodes/gas_callback.py:25` — `gas_callback_node`
  - `apps/agents/src/agents/po_parser/nodes/routing.py:6` — `route_after_classify`
  - `apps/agents/src/agents/image_tagging/nodes/preprocessor.py:15` — `image_preprocessor` (one-liner only)
  - `apps/agents/src/agents/image_tagging/nodes/vision.py:35` — `vision_analyzer` (one-liner only)
  - `apps/agents/src/agents/image_tagging/nodes/taggers.py:100-164` — all eight `tag_*` wrappers
- **Issue:** A LangGraph node is a contract: "I read these state keys, I write those state keys, I have these side effects". None of the nodes state that contract. Reader has to grep both directions.
- **Impact:** Every refactor (e.g. the recommended consolidations in `15_QA_CODE_QUALITY_REVIEW.md`) is more dangerous than it should be. Onboarding takes longer.
- **Fix:** Adopt a one-paragraph node-docstring template and apply it to every node. Suggested template:
  ```python
  """One-line purpose.

  Reads from state: <list keys>
  Writes to state:  <list keys>
  Side effects:     <none | external API call | DB write>
  Failure mode:     <what happens on exception; what state is returned>
  """
  ```
  This template alone, applied to ~15 functions, would eliminate the worst of the documentation debt.

#### D15. Settings classes have no `Field(description=...)`
- **Severity:** High
- **Location:**
  - `apps/agents/src/services/openai/settings.py:5-18`
  - `apps/agents/src/services/airtable/settings.py:4-22`
  - `apps/agents/src/services/gas_callback/settings.py:5-14`
  - `apps/agents/src/services/supabase/settings.py` (similar)
- **Issue:** `pydantic_settings.BaseSettings` produces fantastic auto-docs *if* you give every field a `description`. Today none do. Doc 09 manually duplicates what `Field(description=...)` would emit for free.
- **Fix:** Add descriptions:
  ```python
  classification_model: str = Field(
      default="gpt-4o-mini",
      description="Model used by classifier_node to decide is_po. Cheap model on purpose.",
  )
  ```
  Then Doc 09's env-var table can be auto-generated from the settings classes (`pydantic-settings` integrates cleanly with `mkdocs`/`sphinx`).

#### D16. Pydantic schemas have class docstrings but no field-level descriptions
- **Severity:** High
- **Location:**
  - `apps/agents/src/agents/po_parser/schemas/po.py` — `Destination`, `POItem`, `ExtractedPO`
  - `apps/agents/src/agents/po_parser/schemas/email.py` — `Attachment`, `IncomingEmail`
  - `apps/agents/src/agents/image_tagging/schemas/models.py` — `TagResult`, `ValidatedTag`, `FlaggedTag`, `HierarchicalTag`, `TagRecord`, `TaggerOutput`
- **Issue:** Doc 08 documents these schemas extensively in Markdown. The same content repeated as `Field(description=...)` would (a) keep the docs in sync with the code (no drift), (b) auto-document FastAPI request/response models in OpenAPI, (c) help LLM tool-use scenarios where the schema's description is part of the prompt.
- **Fix:** Add `description=` to every field. Then update Doc 08 to *generate* its tables from the schemas (or at minimum, link to the source files).

#### D17. Configuration constants have no rationale
- **Severity:** High
- **Location:** `apps/agents/src/agents/image_tagging/configuration.py:5-15`
- **Issue:** `CONFIDENCE_THRESHOLD = 0.65`, `NEEDS_REVIEW_THRESHOLD = 3`, `MAX_COLORS = 5`, `MAX_OBJECTS = 10`, plus per-category overrides. No comment explains *why* these specific numbers.
- **Impact:** Operations cannot tune them safely. New engineers can't tell if the thresholds are load-bearing or arbitrary.
- **Fix:** A two-line "**Why this value:**" comment per constant. If the values came from an A/B test or vendor recommendation, cite it.

#### D18. `__init__.py` files have no module docstrings (17 files)
- **Severity:** Medium
- **Location:** All `__init__.py` under `apps/agents/src/` and `apps/backend/src/`
- **Issue:** Python's convention is that the package's `__init__.py` documents what the package exports and what it's for. Currently they re-export symbols silently.
- **Fix:** One-paragraph module docstring per package: "This package provides X. Public exports: Y. See `docs/0N` for context."

#### D19. State `TypedDict`s describe *what* but not *invariants*
- **Severity:** Medium
- **Location:**
  - `apps/agents/src/agents/po_parser/schemas/states.py:11` — `AgentState`
  - `apps/agents/src/agents/image_tagging/schemas/states.py:7` — `ImageTaggingState`
- **Issue:** TypedDicts have one-line class docstrings. Each *key* needs a comment: when is it set? when is it `None` vs `[]`? does it accumulate or get overwritten? (The reducer issue surfaced in `15_QA_CODE_QUALITY_REVIEW.md` is invisible from the type alone.)
- **Fix:** Per-key inline comments on the `TypedDict` definition. Where reducers are involved, document the merge semantics.

#### D20. Service-client public methods are mostly undocumented
- **Severity:** Medium
- **Location:**
  - `apps/agents/src/services/openai/client.py:52` — `chat_completion`
  - `apps/agents/src/services/openai/client.py:81` — `vision_completion`
  - `apps/agents/src/services/airtable/client.py:86, 90, 94, 106` — create/update/find methods
  - `apps/agents/src/services/supabase/client.py:96, 137, 150, 163, 187` — `upsert_tag_record`, `get_tag_record`, listing/searching
  - `apps/agents/src/services/gas_callback/client.py:21` — `send_results_async`
- **Issue:** These are the public surface area for nodes and routes. No method documents arguments, return shape, exceptions raised, retry behaviour.
- **Fix:** A short Google-style docstring per method (Args / Returns / Raises). Consistent style; ~30 minutes per file.

#### D21. Type-hint coverage ~60%, but the gaps are in the most-flowed types
- **Severity:** Medium
- **Location:** All node return types (`-> dict` instead of `-> NodeUpdate` TypedDict), routes returning untyped `dict` (already noted in `15_QA_CODE_QUALITY_REVIEW.md` § B-Q2)
- **Fix:** Per-node `TypedDict` for the dict-shaped state update. Plays double duty: type checker catches typos *and* the TypedDict is its own documentation.

#### D22. Inline comments occasionally describe WHAT not WHY
- **Severity:** Low
- **Location:**
  - `apps/agents/src/agents/po_parser/nodes/extract_po.py:64-67` (regex strip explained as "remove tags")
  - `apps/agents/src/agents/image_tagging/nodes/taggers.py:85-88` ("Filter to allowed only and confidence > 0.5")
- **Fix:** Replace WHAT-comments with WHY-comments where the rationale is non-obvious; otherwise delete.

#### D23. No `TODO` / `FIXME` / `HACK` markers anywhere — verify they're tracked
- **Severity:** Low (but worth confirming)
- **Location:** Project-wide grep returns zero results.
- **Issue:** Either the code is genuinely clean or known-issues live only in heads / chat. Three open known issues from the QA reports (`time.sleep` in async, `BATCH_STORAGE` leak, async-checkpointer locking) deserve at least a `# TODO(15-QA): see 15_QA_CODE_QUALITY_REVIEW.md § A-O1` marker until they're fixed.
- **Fix:** Add inline `# TODO` markers anchored to QA-report IDs for any deferred fix. Keeps code and reviews in sync.

---

### Dynamic / Runtime view

#### D24. Sequence diagrams are accurate and high-leverage — keep doing them
- **Severity:** Info / positive finding
- **Location:** Doc 01 §3, §4; Doc 02 §2; Doc 05 §3; Doc 07 §2-§4
- **Note:** These are the docs' biggest strength. Spot-checking the PO sequence diagram against `apps/backend/src/api/routes/po_parser.py` and the `po_parser` graph: accurate.

#### D25. Error paths are not drawn
- **Severity:** Medium
- **Location:** Doc 01 §3-§4, Doc 02 §2
- **Issue:** Sequence diagrams show the happy path. There is no diagram for "OpenAI rate-limited", "Airtable down", "GAS callback returns 500".
- **Fix:** Add a small "Failure modes" subsection to the relevant sequence diagrams using mermaid's `alt` blocks. Even one or two failure paths per pipeline goes a long way.

#### D26. No diagram of the bulk upload's parallelism (or lack thereof)
- **Severity:** Low
- **Location:** Doc 05 §3 shows the bulk upload as a state machine, not as concurrency.
- **Fix:** When `15_QA_CODE_QUALITY_REVIEW.md § B-O1` is fixed (parallelise bulk), add a diagram showing fan-out + semaphore. Right now the doc implies parallelism that the code doesn't deliver.

---

### Deployment view

#### D27. No explicit Deployment diagram
- **Severity:** High
- **Location:** Doc 11 covers Dockerfiles and the `docker-compose.yml` in prose
- **Issue:** A Deployment diagram in C4 shows physical/virtual nodes (machines, k8s pods, managed services), the containers running on each, and the network paths between them. Doc 11 has the *ingredients* but not the *picture*.
- **Fix:** One mermaid diagram per environment (local-dev / staging / prod). For local-dev:
  ```
  [Developer machine]
    ├─ docker compose
    │    ├─ frontend container (Next.js :3000)
    │    └─ backend  container (FastAPI :8000)  ──▶ ngrok tunnel ──▶ public URL
    │              └─ talks to: OpenAI, Airtable, Supabase (Postgres)
    └─ uv venv (langgraph dev :8001)  [optional, for graph debugging]
  ```
  For prod: same shape with the actual hosts (e.g., Fly.io / Render / Cloud Run / Vercel — whichever).

#### D28. `docker-compose.yml` annotations live in two places
- **Severity:** Low
- **Location:** Doc 01 §1 mentions ngrok; Doc 11 §6 walks through `docker-compose.yml`
- **Fix:** After D27 lands, the Container diagram (D4) becomes the single picture; Doc 11 reads as the *operational* commentary on it.

#### D29. No documented runtime topology (workers, processes, threads)
- **Severity:** Medium
- **Location:** N/A — missing
- **Issue:** How many uvicorn workers should run? Is the FastAPI app safe to run multi-worker today? (`15_QA_CODE_QUALITY_REVIEW.md § B-D1` says no, because of `BATCH_STORAGE`.) That constraint should be in Doc 11 with a warning.
- **Fix:** A "Runtime topology" subsection in Doc 11 listing the constraints and the recommended deploy shape.

---

### Cross-cutting

#### D30. `docs/README.md` is an alphabetised index, not a router
- **Severity:** Medium
- **Location:** `docs/README.md`
- **Issue:** It lists all 13 docs in numbered order. A reader who lands on it has no signal about where to start. C4-aligned navigation would route the reader by *level of abstraction*: "I want to understand the system at a glance" → Context; "I want to know what runs where" → Container; "I want to know how the PO parser works" → Component.
- **Fix:** Reshape the README around C4 levels:
  ```
  ## Read in this order

  ### Big picture
  - [01] System Architecture — Context + Container diagrams
  - [11] Deployment — where it runs

  ### Inside one container
  - [02] PO Parser Agent
  - [03] Image Tagging Agent
  - [04] Agent service clients
  - [05] FastAPI Backend
  - [06] Frontend Dashboard
  - [07] GAS Scripts

  ### Code-level reference
  - [08] Data Models & Schemas
  - [09] Configuration & Env
  - [13] Tooling Config Files

  ### Operations & cross-cutting
  - [10] Security & Auth
  - [12] Development Workflow
  - [14] / [15] / [16] QA reviews
  ```

#### D31. Top-level `README.md` repeats `docs/01` content
- **Severity:** Low
- **Location:** `README.md` (root)
- **Issue:** The root README has its own architecture diagram and endpoint table. Some drift is inevitable.
- **Fix:** Keep the root README short and route to `docs/01` for the picture. Or treat the root README as the definitive Context view and link `docs/01` from it for Container detail.

#### D32. Per-app READMEs duplicate doc-folder content
- **Severity:** Low
- **Location:** `apps/agents/README.md`, `apps/backend/README.md`
- **Issue:** Both READMEs include diagrams and endpoint lists that overlap with Doc 02/03/05.
- **Fix:** Keep app READMEs short ("this package contains X; see `docs/0N` for the architecture"). The diagrams should live in one place — the docs folder — and be linked, not copied.

#### D33. Doc 12 is a workflow handbook with no C4 home
- **Severity:** Low
- **Location:** `docs/12_DEVELOPMENT_WORKFLOW.md`
- **Note:** It's fine for some docs to sit outside the C4 model — operational guides, runbooks, and contributor playbooks are not architecture. Just be explicit about it. Add a one-liner at the top: "This doc is not an architecture doc; for architecture see [01]."

---

## Per-doc quick findings

These are smaller items the C4 review surfaced — most are accuracy/freshness, not structural.

| Doc | Finding | Severity | Fix |
|---|---|---|---|
| 01 | §8 says "OpenAI SDK + LangChain" but image-tagging uses `langchain_openai`'s `ChatOpenAI` while PO-parser uses bare OpenAI SDK. Calling them both "LangChain" elides the difference. | Low | Split the row: `services/openai/client.py` (raw SDK) vs `image_tagging` nodes (`langchain_openai.ChatOpenAI`). |
| 02 | §3 mentions "rule-based fallback" but only describes the confidence-threshold rule. The keyword fallback in `classifier.py:_rule_fallback` is not mentioned. | Low | List both rules. |
| 03 | §5 says "All 8 taggers share the `run_tagger` function" — accurate. But the doc doesn't explain how `TAGGER_NODE_NAMES` and `ALL_TAGGERS` work together with `graph_builder.py`. After the recommended refactor in `15_QA_CODE_QUALITY_REVIEW.md § A-Q2`, this section will need a refresh anyway. | Low | Defer until after that refactor; rewrite both at once. |
| 04 | Search-index explanation (§5) doesn't show a query example. | Medium | Add `WHERE search_index @> ARRAY['christmas', 'red']` example. |
| 05 | §5 (URL rewriting) flowchart shows 4 decision paths but only 3 outputs. Off-by-one. Also: should mention the security concern (see `14_QA_SECURITY_REVIEW.md § B-C5`) inline. | Medium | Fix the flowchart; add a "Security note" inline. |
| 06 | `VisionResults.tsx` is described as "available but not used" with no rationale. | Low | Add the rationale (placeholder for future feature) or remove the dead file from the docs. |
| 07 | §9 "Deployment" steps belong in Doc 11. (Same as D11.) | Medium | Move. |
| 08 | TagRecord docs note `product_type` can be null with no rationale. | Low | One-liner explaining why (single product per image). |
| 09 | Env vars not grouped by container. (Same as D7.) | Medium | Re-group. |
| 10 | "Deferred items" (§6) cite issues without linking to the QA review. | Low | Add `→ see 14_QA_SECURITY_REVIEW.md § B-C1`-style links. |
| 11 | §1 says "Docker context: . (repo root) but Dockerfile is at apps/backend/Dockerfile" — confusing without the explanation that this is the `uv` workspace constraint. | Medium | Add the one-sentence explanation. |
| 11 | §7 (production checklist) has no priority column. | Low | Add Priority (HIGH / MEDIUM / LOW). |
| 12 | Mixes how-to-set-up with tool reference. | Medium | Optional split, but at minimum add a "Tool reference" anchor at the top so readers can jump straight to it. |
| 13 | `pyproject.toml` `version = "0.0.0"` is correct (not published) — undocumented. | Low | Add a one-liner. |

---

## Top documentation priorities

In order. The goal is to spend the smallest amount of time for the largest C4 coverage gain, then chip away at Code-level docs continuously.

1. **D1 + D2 + D4 — Add a true System Context diagram and a true Container diagram**, both at the top of Doc 01. Demote the existing flow chart to "annotated end-to-end view". One afternoon. Biggest single jump in onboarding clarity.
2. **D27 — Add a Deployment diagram** (one per environment) inside Doc 11. Pairs naturally with D4.
3. **D14 — Apply the node-docstring template to every LangGraph node** (~15 functions). Each docstring takes ~3 minutes; the cumulative payoff is huge because nodes are the system's contract.
4. **D15 + D16 — Add `Field(description=...)` to every Pydantic model and `BaseSettings` field.** Then start auto-generating Doc 09's env-var table.
5. **D30 — Reshape `docs/README.md` around C4 levels**, not numerical order. Half an hour, big navigation win.
6. **D11 — Move GAS deployment steps out of Doc 07** and into Doc 11.
7. **D5 + D6 — Move the `uv` workspace graph into a build/dev doc**; add a Container responsibility table.
8. **D17 — Add "why this value" comments** to every constant in `image_tagging/configuration.py` and `po_parser/nodes/routing.py`.
9. **D8 — Visual-style pass on Component diagrams** so Docs 02-07 look like siblings.
10. **D25 — Add error-path branches to the existing sequence diagrams** (alt blocks).

Items 1, 2, 5, 6 are mechanical — no code changes, no architecture work, just rearranging and adding. Items 3, 4 are mechanical-but-pervasive (one PR per area). Items 7-10 are polish.

---

## Appendix — In-code documentation inventory

### Public-function docstring coverage by file

Numbers below are spot estimates of "% of public functions / methods with at least a one-line docstring":

| Area | File | Coverage |
|---|---|---|
| **agents — po_parser nodes** | `classifier.py` | ~10% |
| | `extract_po.py` | ~5% (1 of ~20 helpers documented) |
| | `validator.py` | ~10% |
| | `airtable_writer.py` | ~10% |
| | `gas_callback.py` | ~10% |
| | `routing.py` | 0% |
| **agents — image_tagging nodes** | `preprocessor.py` | ~50% (one-liner) |
| | `vision.py` | ~50% (one-liner) |
| | `taggers.py` | ~10% (only `run_tagger` partially) |
| | `validator.py` | ~70% (good docstring) |
| | `confidence.py` | ~80% (good docstring) |
| | `aggregator.py` | ~25% |
| **agents — services** | `openai/client.py` | ~10% |
| | `airtable/client.py` | ~15% |
| | `supabase/client.py` | ~30% (one-liners) |
| | `gas_callback/client.py` | ~20% |
| | `checkpointer.py` | ~80% (good module + function docstrings) ✓ |
| | `base.py` | 0% |
| **backend** | `main.py` | ~70% (good module docstring) ✓ |
| | `config.py` | 0% |
| | `deps.py` | ~60% (one-liners on all `get_*`) |
| | `middleware.py` | 0% |
| | `routes/health.py` | 0% |
| | `routes/po_parser.py` | 0% |
| | `routes/images.py` | 0% |
| | `routes/bulk.py` | 0% |
| | `routes/drive_webhook.py` | ~50% (one-liner on the route) |
| | `services/image_pipeline.py` | ~25% (one-liners on two of four) |
| | `services/url_rewriter.py` | ~50% (one-liners) |

**Aggregate:** ~30% of public functions have any docstring. ~5% of `__init__.py` files have a module docstring. ~5% of Pydantic field declarations have a `description=`.

### Pydantic field-description coverage

Zero `Field(..., description="...")` annotations across:
- `apps/agents/src/agents/po_parser/schemas/{po,email,classification,validation}.py`
- `apps/agents/src/agents/image_tagging/schemas/models.py`
- All `services/*/settings.py` files
- `apps/backend/src/api/config.py` (no `BaseSettings` exists yet — see `15 § B-T4`)
