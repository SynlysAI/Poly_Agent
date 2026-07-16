# Literature RAG Service

Independent KrF photoresist literature ingestion and GraphRAG service for Poly Agent. It keeps PDF acquisition,
cleaning, indexing and provenance outside the Poly_Agent application boundary.

## Capabilities

- Corpus registry for one or more literature corpora. The default demo corpus is `krf_photoresist`.
- Traceable RAG query responses with `answer`, `hits`, `citations`, optional `graph_context` and a stable `message`.
- Chinese/English query normalization for common KrF photoresist terms such as 光刻胶, 文献, 论文, 树脂 and 灵敏度.
- Document inventory intent: questions such as `帮我找全部的文档` return the indexed paper list instead of an insufficient-evidence answer.
- Graph subgraph API for frontend browsing. The memory backend returns Paper/Chunk nodes; the production backend stores Paper/Chunk/Entity nodes in Neo4j.
- Safe public metadata only. Responses strip storage paths, object keys, content hashes, API keys and embeddings.

## Local memory demo

```bash
pip install -r requirements.txt
export LITERATURE_RAG_QUERY_API_KEY=query-demo
export LITERATURE_RAG_ADMIN_API_KEY=admin-demo
uvicorn app.main:app --app-dir services/literature-rag --port 8200
```

Set `LITERATURE_RAG_MEMORY_INLINE_WORKER=true` to process ingestion jobs synchronously in this single-process demo.
Production must leave this disabled and run `python -m app.worker` as a separate process.

The memory demo seeds from `data/corpus_manifest.json` by default. Approved manifest records become indexed paper
records with title/abstract chunks, which is enough for local RAG and graph UI validation.

## Production demo stack

```bash
cd services/literature-rag
cp .env.example .env
docker compose --profile demo up --build
```

Compose reads `.env.example` by default for validation. After creating `.env`, run with
`LITERATURE_RAG_ENV_FILE=.env docker compose --profile demo up --build`.

## Dedicated production instance

For Poly_Agent production, run this service as an isolated instance with its own MongoDB / MinIO / Neo4j and a
separate PM2 process group:

```bash
cp deploy/toolchain/env/literature-rag.env.template services/literature-rag/.env
cd services/literature-rag
pm2 start ecosystem.config.js
```

Point `LITERATURE_RAG_BASE_URL` from Poly_Agent to this dedicated instance. Keep the shared welding / rare-earth /
surface-treatment corpus deployment untouched.

Generate an auditable corpus manifest:

```bash
python scripts/build_krf_manifest.py \
  --notebook ../../refer/pdf_requirement/KrF代码整理0618.ipynb \
  --output data/corpus_manifest.json \
  --email research-contact@example.com
```

Only records marked `selected=true` and `approval_status=approved` may be downloaded automatically. Other selected
records require a legally obtained PDF named `<doi-with-slash-replaced-by-underscore>.pdf` in the authorized upload
directory before running `scripts/import_approved_corpus.py`.

## Runtime modes

| Mode | Storage | Graph/search behavior |
| --- | --- | --- |
| `memory` | In-process repository and object store | Lexical + synonym query over chunks; Paper/Chunk subgraph |
| `production` | MongoDB documents/chunks, MinIO PDFs/parsed artifacts | Neo4j vector search and subgraph; worker indexes extracted entities |

Poly Agent connects through its backend facade, not directly from the browser:

- `GET /api/v1/corpora`
- `POST /api/v1/query`
- `POST /api/v1/query/stream`
- `GET /api/v1/corpora/{corpus_id}/graph/subgraph`

Configure Poly Agent with `LITERATURE_RAG_BASE_URL` and `LITERATURE_RAG_QUERY_API_KEY`. Local development can omit the
base URL when the service is running at `http://127.0.0.1:8200`.

The implementation derives its GraphRAG architecture from `refer/graph-rag-agent-master` under the MIT license. Its
school-specific prompts, Streamlit UI and multi-agent reporting stack are intentionally not included.

## Tests

Run the two test suites separately because both deployable Python services intentionally use a top-level `app` package:

```bash
python -m pytest services/literature-rag/tests -q
python -m pytest backend/tests -q
```

For frontend validation:

```bash
cd frontend && npm run build
```
