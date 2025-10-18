# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Kyung Hee University Regulations Virtual Assistant** - an AI-powered chatbot that helps users search and understand university regulations, internal guidelines, and academic policies using Retrieval-Augmented Generation (RAG). The system combines vector search (FAISS), query parsing, hybrid re-ranking, and LLM-based answer generation to provide accurate, sourced responses.

**Current Branch Context:**
- `main`: Production-ready RAG system with FAISS vector database
- `feat/pipeline-v2`: KG-first architecture (in development) - includes OWL ontology, SHACL validation, and RDF export capabilities

## Core Architecture

### RAG Pipeline Flow
1. **User Query** → `second_page.py` (Streamlit UI)
2. **Query Parsing** → `query_parser.py` (Lark grammar) or `query_router.py` (regex-based)
   - Extracts metadata: article numbers, clauses, cohort, program, content type
3. **Vector Search** → `chains.py` (FAISS retriever with metadata filtering)
   - History-aware retrieval using chat context
4. **Re-ranking** → `reranker.py` (hybrid scoring: BM25 + cosine + metadata + version + URI)
5. **Answer Generation** → `chains.py` (OpenAI GPT-4o-mini with conversational context)
6. **Quality Evaluation** → RAGAS metrics (faithfulness, answer_relevancy)

### Multi-Category Structure
The system manages 4 distinct regulation categories with optional cohort support:

| Category | Path | Cohort Support |
|----------|------|----------------|
| `regulations` | `faiss_db/regulations/` | No |
| `undergrad_rules` | `faiss_db/undergrad_rules/{cohort}/` | Yes (e.g., 2023) |
| `grad_rules` | `faiss_db/grad_rules/{cohort}/` | Yes |
| `academic_system` | `faiss_db/academic_system/` | No |

**Cohort Model:** Inception year determines applicable rules. Users select their cohort to retrieve program-specific regulations.

### Metadata Schema (v1.0)
All documents follow a standardized metadata structure defined in `docs/schema_and_uri.md`:

```json
{
  "schema_version": "1.0",
  "uri": "urn:khu:reg:{code}:{versionDate}:art{N}[:cl{M}]",
  "articleUri": "https://kg.khu.ac.kr/reg/{code}-{versionDate}#art{N}",
  "clauseUri": "https://kg.khu.ac.kr/reg/{code}-{versionDate}#art{N}-cl{M}",
  "documentCode": "string",
  "versionDate": "YYYY-MM-DD",
  "articleNumber": "int",
  "clauseNumber": "int|null",
  "program": "enum{UG,MS,PHD,IME_MS,IME_PHD}",
  "cohort": "enum{Cohort_2022,Cohort_2023,...}",
  "contentType": "enum{text|table|annex}",
  "sourceFile": "string",
  "md5": "string",
  "overrides": ["uri"],
  "cites": ["uri"],
  "hasExceptionFor": ["string|uri"]
}
```

## Common Development Commands

### Local Testing
```bash
# Setup environment
conda create -n langchain python=3.11
conda activate langchain
pip install -r requirements.txt

# Run application
streamlit run main.py
```

### Document Ingestion & Index Building
```bash
# Single category (no cohort)
python add_document.py --category regulations

# Single category with cohort (undergrad/grad rules only)
python add_document.py --category undergrad_rules --cohort 2023

# All categories at once
python add_document.py --all
```

**File Placement:**
- Place new documents in `todo_documents/<category>[/<cohort>]/`
- Supported formats: `.pdf`, `.txt`, `.ipynb`, `.json`, `.jsonl`
- After processing, files automatically move to `past_documents/`

### Index Backup/Restore
- Backups are automatic when re-running `add_document.py`
- Location: `backup/<category>/<cohort|all>/<timestamp>/`
- Contains: `index.faiss`, `index.pkl`, `doc.jsonl`

## Key Files & Their Roles

### Entry Points
- **`main.py`**: Streamlit app router - initializes LangSmith tracing, manages navigation
- **`first_page.py`**: Authentication via member ID whitelist (from `secrets.toml`)
- **`second_page.py`**: Main chatbot UI (614 lines) - category/cohort selection, chat interface, source display
- **`admin_page.py`**: Administrative controls

### Core Processing
- **`add_document.py`** (472 lines): Document ingestion pipeline
  - Loads PDF/TXT/IPYNB/JSON/JSONL files
  - Chunks text (2048 chars, 256 overlap)
  - Normalizes metadata to schema v1.0
  - Generates URN + HTTP URIs
  - Builds FAISS indices with OpenAI embeddings (text-embedding-3-large)

- **`chains.py`**: LangChain RAG chains
  - `get_vector_store()`: Loads FAISS for category/cohort
  - `get_retriever_chain()`: History-aware retriever (k=5 default, k=7 for tables)
  - `get_conversational_rag()`: Conversational RAG with system prompt

- **`query_parser.py`**: Lark grammar-based parser
  - Extracts article/clause ranges: "제15조", "15조의2", "2항 및 3항"
  - Detects page references: "p.12", "12페이지"
  - Identifies table/annex requests
  - Parses cohort: "2023학번" → "Cohort_2023"

- **`query_router.py`**: Regex-based routing (faster fallback)
  - Returns `metadata_filter` (for FAISS) + `routing_hints` (for re-ranking)

- **`reranker.py`**: Hybrid re-ranking algorithm
  - Vector Similarity: 40%
  - BM25 (keyword matching): 25%
  - Metadata Match (article/clause/program/cohort): 25%
  - Version Score (prefers latest): 5%
  - URI Match: 5%
  - MMR (Maximal Marginal Relevance) for diversity

- **`utils.py`**: JSONL I/O helpers
  - **Status:** ⚠️ Only provides `load_docs_from_jsonl()` and `save_docs_to_jsonl()`
  - **Missing:** URI normalization utilities (currently embedded in `add_document._attach_uri_and_schema()`)

### Knowledge Graph Layer (feat/pipeline-v2 branch)
- **`ontology/uni.ttl`**: OWL ontology - defines classes (Norm, Article, Clause, Version, Program, Cohort) and relations (overrides, cites, appliesToProgram)
- **`ontology/shapes.ttl`**: SHACL validation rules - temporal constraints, URI requirements, override precedence
- **`ingest/rdf_export.py`**: Converts processed documents to RDF/Turtle format
  - **Status:** Minimal skeleton implementation (5-10 sample triples recommended)
  - Uses `http://example.org/uni#` namespace (should align with production namespace)
  - Currently uses URN as URIRef; dual URN+HTTP URI support recommended
  - **Missing:** SHACL validation hook (`pyshacl.validate()`)
- **`docs/schema_and_uri.md`**: Metadata specification and URI scheme documentation
  - **Status:** Core spec complete, minor inconsistencies remain
  - **Known Issues:** "appendix" missing from contentType enum, program case inconsistency (PhD vs PHD)

### Processing Utilities
- **`process_pdf.py`**: PDF chunking and table extraction
  - **Status:** ✅ Chunk generation with metadata (document_title, page_number, article_number, content_type)
  - **Missing:** versionDate, effectiveFrom/Until, program, cohort, documentCode (handled by add_document.py)
  - **Missing:** sourceFile, md5 assignment

- **`upgrade_tables.py`**: Table content upgrade utility
  - **Status:** ⚠️ Partial - upgrades table content to Markdown format
  - Finds entries where `content_type == "table"` and re-extracts from PDF
  - **Missing:** Schema validation/enforcement (schema_version, HTTP URI, dates, program/cohort, contentType standardization)

## Important Patterns & Conventions

### Metadata Normalization
When working with document metadata:
1. Always use `_attach_uri_and_schema()` from `add_document.py` to normalize metadata
2. Program codes must be uppercase: `UG`, `MS`, `PHD`, `IME_MS`, `IME_PHD`
3. Cohort format: `Cohort_YYYY` (e.g., `Cohort_2023`)
4. Content type detection: automatic for tables (pipe `|` detection) or explicit via `content_type` field
5. URIs are dual-format: URN (`urn:khu:reg:...`) + HTTP URI (`https://kg.khu.ac.kr/reg/...`)

**Current Implementation Status (add_document.py):**
- ✅ Schema version injection (`schema_version: "1.0"`)
- ✅ Program/cohort normalization (enforces whitelist, applies `Cohort_YYYY` format)
- ✅ Article/clause normalization (consolidates various key variants into `articleNumber`/`clauseNumber`)
- ✅ Content type enforcement (table detection + explicit `contentType` field)
- ✅ Relation fields default (`overrides`/`cites`/`hasExceptionFor` → `[]` when absent)
- ✅ URN generation (`uri` field)
- ✅ HTTP URI generation (`articleUri`/`clauseUri` fields) - **Added in Phase 1**
- ✅ Source tracking (`sourceFile` from filename, `md5` hash from page content) - **Added in Phase 1**
- ✅ Temporal fields (`effectiveFrom`/`effectiveUntil` → `None` when absent)

**Improvement Recommendations:**
1. **utils.py refactoring:** Extract URI generation logic from `add_document._attach_uri_and_schema()` into reusable utilities in `utils.py`
2. **Schema validation:** Add explicit validation function to ensure all required fields are present before indexing
3. **process_pdf.py enhancement:** Inject `versionDate`, `documentCode`, `program`, `cohort` at PDF processing stage (currently delegated to add_document.py)
4. **upgrade_tables.py alignment:** Add schema enforcement after table content upgrade to ensure `contentType` standardization
5. **docs/schema_and_uri.md updates:**
   - Add "appendix" to contentType enum
   - Standardize program case (use PHD consistently, not PhD)
   - Document dual URN+HTTP URI policy explicitly

### Source Prefix Convention
All document chunks must start with `Source : <filename>\n` prefix. This is:
- Added automatically by `_make_source_prefix()` in `add_document.py`
- Used by `second_page.py` to extract and display source information
- Critical for document tracking and download features

### Session State Management
Streamlit session variables (all in `st.session_state`):
- `student_id`: Authenticated user
- `kb_category_slug`: Selected category
- `kb_cohort`: Dict mapping {category: cohort}
- `chat_histories`: Dict mapping {f"{category}:{cohort}": messages}
- `vector_stores`: Cached FAISS instances
- `dialog_identifier`: UUID for run tracking
- `run_id`: LangSmith trace ID

### Query Metadata Extraction
When adding query parsing features:
1. Update Lark grammar in `query_parser.py` for complex patterns
2. Update regex patterns in `query_router.py` for simple/fast patterns
3. Metadata filter keys must match FAISS metadata schema
4. Routing hints guide re-ranking (e.g., `"prefer_tables": True`)

## Configuration & Secrets

### Environment Setup
Create `.streamlit/secrets.toml`:
```toml
LANGCHAIN_API_KEY = "lsv2_pt_..."
OPENAI_API_KEY = "sk-..."
student_ids = ["member1", "member2", "member3"]
```

Same keys should also be in `.env` for local development compatibility.

### LangSmith Tracing
Configured in `main.py`:
```python
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_API_KEY"] = st.secrets["LANGCHAIN_API_KEY"]
os.environ["LANGCHAIN_PROJECT"] = "KyungHee-chatbot"
```

## Data Flow & File Movement

### Document Lifecycle
```
1. New files placed in: todo_documents/<category>[/<cohort>]/
2. run add_document.py:
   → Load & chunk files
   → Normalize metadata (URI, schema, program, cohort)
   → Embed with OpenAI (text-embedding-3-large)
   → Build/merge FAISS index
   → Backup old index to: backup/<category>/<cohort|all>/<timestamp>/
   → Save new index to: faiss_db/<category>[/<cohort>]/
   → Export metadata to: docs/<category>[/<cohort>]/doc.jsonl
   → Move files to: past_documents/<category>[/<cohort>]/
```

### Index Merging Strategy
- **New Index Only:** Creates fresh index if none exists
- **Merge Mode:** If existing index found, loads old index → merges with new → saves combined
- **Backup Before Overwrite:** Old `index.faiss` + `index.pkl` + `doc.jsonl` moved to timestamped backup folder

## Technical Stack

### LLM & Embeddings
- **Chat Model:** `gpt-4o-mini` (OpenAI) - temperature=0 for deterministic answers
- **Embeddings:** `text-embedding-3-large` (OpenAI) - 3072 dimensions

### Frameworks
- **UI:** Streamlit 1.38.0
- **RAG:** LangChain 0.3.0, LangChain-OpenAI 0.2.0, LangChain-Community 0.3.0
- **Vector DB:** FAISS (CPU version) with metadata filtering
- **Query Parsing:** Lark parser (grammar-based)
- **Re-ranking:** rank-bm25, rapidfuzz (fuzzy matching)
- **Evaluation:** RAGAS 0.2.4 (faithfulness, answer_relevancy metrics)
- **Tracing:** LangSmith 0.1.120

### Semantic Layer (Phase 2)
- **Ontology:** OWL (Web Ontology Language)
- **Validation:** SHACL (Shapes Constraint Language)
- **Export:** RDF/Turtle format

## System Prompt Customization

The system prompt is defined in `chains.py` as `SYSTEM_PROMPT`:

```python
SYSTEM_PROMPT = (
    f"Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n"
    "You are a Virtual Assistant dedicated solely to providing guidance on the regulations, internal rules, and guidelines of Kyung Hee University.\n"
    "This assistant retrieves short context snippets from KHU's Regulation Management System.\n"
    "Each context chunk begins with a 'Source : <filename>' line that indicates its origin.\n"
    "Do not fabricate or guess source names. You do NOT need to write a 'Source:' section yourself; the application will append the exact sources automatically.\n"
    "If context is used, focus on answering clearly and completely. Avoid adding extra citation text in your answer.\n"
    "Context:\n"
)
```

**When customizing:**
- Current date is injected automatically via `datetime.now()`
- Emphasize NOT fabricating sources (UI handles source display)
- Keep instructions focused on RAG-specific behavior
- Context will be appended by LangChain's document chain

## Deployment

### Streamlit Cloud
1. Push repository to GitHub
2. Configure secrets in Streamlit Cloud UI:
   - `LANGCHAIN_API_KEY`
   - `OPENAI_API_KEY`
   - `student_ids` (array of authorized member IDs)
3. Deploy from `main.py`

### Git LFS Setup
Large FAISS indices use Git LFS (configured in `.gitattributes`):
```
*.faiss filter=lfs diff=lfs merge=lfs -text
```

Ensure Git LFS is installed before cloning:
```bash
git lfs install
git clone <repo-url>
```

## Testing & Quality Assurance

### Regression Tests
- Location: `tests/regression/`
- Contains sample queries for RAG quality validation
- Run after re-indexing to verify retrieval quality

### RAGAS Evaluation
Metrics calculated in `second_page.py`:
- **Faithfulness:** Answer fidelity to retrieved context
- **Answer Relevancy:** Response relevance to user query

Displayed in UI as quality scores (0.0 - 1.0 scale).

## Unicode & File Handling

### Korean Text Normalization
- Uses NFC (Canonical Decomposition followed by Canonical Composition)
- Applies to filenames, metadata, and content
- Critical for consistent file matching across platforms

### Whitespace Handling
Text processing in `add_document.py`:
- Form feed (`\x0c`) → space
- Newlines → space (for dense retrieval)
- Multiple spaces → single space
- Applied via `_norm_spaces()` function

## Implementation Status Summary

### Phase 1 (Metadata Standardization) - ✅ Complete
- ✅ Schema v1.0 enforcement in `add_document.py`
- ✅ Dual URI generation (URN + HTTP permanent URIs)
- ✅ Source tracking (`sourceFile`, `md5` hash)
- ✅ Program/cohort normalization with whitelist validation
- ✅ Article/clause/contentType standardization
- ✅ Temporal fields (`effectiveFrom`/`effectiveUntil`) support

### Phase 2 (KG-first Architecture) - ⚠️ In Progress (feat/pipeline-v2)
- ✅ OWL ontology (`ontology/uni.ttl`) - classes and relations defined
- ✅ SHACL shapes (`ontology/shapes.ttl`) - validation rules defined
- ⚠️ RDF export (`ingest/rdf_export.py`) - minimal skeleton, needs sample triples
- ⚠️ SHACL validation hook - not yet implemented
- ⚠️ Namespace alignment - currently using `http://example.org/uni#` (should align with production)

### Known Gaps & Recommended Next Steps
1. **RDF Export Enhancement:**
   - Add 5-10 sample triples for `overrides`/`cites`/`hasExceptionFor` relations
   - Implement SHACL validation hook using `pyshacl.validate()`
   - Align namespace from `example.org` to production URI scheme

2. **Schema Consistency:**
   - Update `docs/schema_and_uri.md` to include "appendix" in contentType enum
   - Standardize program codes (use PHD, not PhD) across documentation
   - Document dual URN+HTTP URI policy explicitly

3. **Utility Refactoring:**
   - Extract URI generation from `add_document._attach_uri_and_schema()` to `utils.py`
   - Create standalone schema validation function
   - Add helper for metadata normalization that can be reused across scripts

4. **Processing Pipeline Enhancement:**
   - Update `process_pdf.py` to inject more metadata fields upfront (versionDate, documentCode, program, cohort)
   - Add schema enforcement to `upgrade_tables.py` after table content upgrade
   - Ensure `sourceFile` and `md5` are consistently set across all processing paths

## Important Notes

1. **Never commit real API keys** - use `secrets.toml` (gitignored)
2. **Cohort is mandatory** for undergrad_rules/grad_rules categories
3. **Metadata schema v1.0** is current standard - extensible for future needs
4. **Source prefix** (`Source : <filename>\n`) is critical for UI functionality
5. **HTTP URI namespace** (`https://kg.khu.ac.kr/reg/`) should remain stable for linked data
6. **Multilingual content** - primarily Korean with English fallbacks
7. **Deterministic answers** - temperature=0 ensures consistent responses
8. **Metadata filtering** happens at FAISS retrieval time for efficiency
9. **Re-ranking is hybrid** - combines vector similarity, BM25, metadata, version, and URI matching
10. **Dual URI strategy** - URN for internal reference, HTTP URI for linked data/Fuseki navigation

## Reference Documentation

- **Official Regulations:** https://rule.khu.ac.kr/lmxsrv/main/main.do
- **Metadata Schema:** `docs/schema_and_uri.md`
- **OWL Ontology:** `ontology/uni.ttl`
- **SHACL Shapes:** `ontology/shapes.ttl`
- **README:** `README.md`

## Contact

For questions about this codebase:
- **Developer:** HYUNJONG JANG
- **Email:** lezelamu@naver.com
