# AI Assistant Planning, Auto-Retry, and RAG Implementation Plan

## Context

The FreeCAD AI Assistant addon currently sends a single LLM request with a static system prompt containing basic FreeCAD API patterns. Complex requests fail because: (1) the LLM tries to do everything in one code block, (2) when code fails there's no retry, and (3) the LLM has limited FreeCAD API knowledge. This plan adds three capabilities: plan-then-execute for multi-step tasks, auto-retry on failure, and RAG-based API knowledge retrieval.

## Overview

Three new subsystems, implemented in phases:

1. **RAG system** — Semantic chunking of FreeCAD API docs, embedding via provider APIs, SQLite vector store, retrieval at query time
2. **Orchestrator** — State machine that manages plan detection, step-by-step execution, and auto-retry
3. **UI updates** — Plan display, step progress, retry indicators

## Files to Create

- `assistant/rag/` — New package for RAG system
  - `assistant/rag/__init__.py`
  - `assistant/rag/chunker.py` — FreeCAD API doc chunking and runtime introspection
  - `assistant/rag/embeddings.py` — Embedding client (OpenAI/Gemini compatible endpoints)
  - `assistant/rag/store.py` — SQLite vector store with cosine similarity search
  - `assistant/rag/retriever.py` — Top-level retriever: embed query → search → return chunks
- `assistant/orchestrator.py` — Central state machine for plan execution and retry
- `assistant/plan_parser.py` — Parse LLM plan output into step objects

## Files to Modify

- `assistant/system_prompt.py` — Add plan-mode instructions, step/retry prompt builders, RAG context injection
- `assistant/chat_panel.py` — Wire up orchestrator, plan rendering, retry UI
- `assistant/preferences.py` — Add max retries setting
- `assistant/llm_client.py` — Add `get_embedding()` method for RAG

## Files Unchanged

- `assistant/executor.py`, `assistant/command.py`, `assistant/llm_worker.py`, `InitGui.py`

---

## Phase 1: RAG System

### 1a. API Knowledge Source (`assistant/rag/chunker.py`)

Two approaches combined:

**Runtime introspection** (primary, version-accurate):
- On first run or when index is empty, introspect FreeCAD modules: `Part`, `PartDesign`, `Sketcher`, `Draft`, `Mesh`, `FreeCAD`, `FreeCADGui`
- For each module: `dir(module)` → for each callable, extract `__doc__`, signature, and type info
- Group into semantic chunks by class/function (e.g., "Part.makeBox", "PartDesign::Pad properties")

**Bundled recipe chunks** (curated):
- Ship `assistant/rag/recipes.json` with ~50-100 curated code recipes covering common tasks
- Each recipe: `{"title": "Create a box with filleted edges", "code": "...", "description": "...", "tags": ["Part", "fillet", "boolean"]}`
- Recipes cover the priority areas: primitives, booleans, PartDesign workflows, sketcher constraints, Draft objects, placement, selection

Chunk format:
```python
{"id": str, "text": str, "metadata": {"module": str, "type": "api"|"recipe", "tags": list}}
```

### 1b. Embedding Client (`assistant/rag/embeddings.py`)

Uses the same provider configured in preferences, via urllib (no SDK):

- **OpenAI**: `POST /v1/embeddings` with model `text-embedding-3-small`
- **Gemini**: `POST /v1/embeddings` to `generativelanguage.googleapis.com/v1beta/openai/` with model `gemini-embedding-001`
- **Anthropic**: No embedding API — fall back to OpenAI endpoint if key available, or use keyword-based fallback (SQLite FTS5)
- **Custom/Ollama**: `POST /api/embed` with configured model (Ollama supports embeddings)

Returns `list[float]` for a given text string. Supports batching for initial indexing.

### 1c. Vector Store (`assistant/rag/store.py`)

SQLite database at `~/.local/share/FreeCAD/Mod/AIAssistant/rag.db` (or FreeCAD user data dir):

```sql
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    metadata TEXT,  -- JSON
    embedding BLOB  -- packed float32 via struct.pack
);
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

- `store_embedding(id, text, metadata, vector)` — pack floats with `struct.pack`, store as BLOB
- `search(query_vector, top_k=5)` — load all embeddings, compute cosine similarity in pure Python, return top K
- `cosine_similarity(a, b)` — pure Python: `dot(a,b) / (mag(a) * mag(b))` using `math.fsum` and `math.sqrt`
- `needs_rebuild()` — check meta table for version/timestamp, compare to FreeCAD version

**Keyword fallback** for providers without embeddings (Anthropic):
- Use SQLite FTS5: `CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content=chunks)`
- `search_keyword(query, top_k=5)` — FTS5 match query

### 1d. Retriever (`assistant/rag/retriever.py`)

Top-level interface used by the orchestrator/system_prompt:

```python
class Retriever:
    def __init__(self, store, embeddings_client):
        ...
    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Returns top-K relevant chunks for the user's query."""
    def ensure_indexed(self):
        """Build/rebuild index if needed (first run or version change)."""
```

### 1e. Integration with system prompt

Modify `build_document_context()` or add new `build_rag_context(query)` in `system_prompt.py`:
- Call `retriever.retrieve(user_query, top_k=5)`
- Format retrieved chunks as a "RELEVANT API REFERENCE" section appended to the system prompt
- This gives the LLM targeted API knowledge for each specific request

---

## Phase 2: Orchestrator (Planning + Auto-Retry)

### 2a. Plan Parser (`assistant/plan_parser.py`)

Data classes:
```python
class PlanStep:  # number, description, status, code, result, retries
class Plan:      # steps list, raw_text
```

Functions:
- `parse_response(text)` — detect `<<<PLAN>>>...<<<END_PLAN>>>` markers, extract steps, return `(Plan, preamble)` or `(None, text)`
- `extract_code_block(text)` — regex extract first ```python block

### 2b. Orchestrator (`assistant/orchestrator.py`)

QObject-based state machine. States: `idle → waiting_for_llm → showing_plan → executing_step → waiting_for_step_code → retrying`

Signals emitted to ChatWidget:
- `status_changed(str)` — "Thinking...", "Step 2/5: Generating code..."
- `plan_received(Plan, str)` — plan object + preamble text
- `direct_response(str)` — non-plan LLM response
- `step_completed(int, bool, str, str)` — step index, success, stdout, stderr
- `retry_started(int, int)` — step index, attempt number
- `all_done()` — plan finished
- `error_occurred(str)` — fatal error

Key behaviors:
- **Plan detection**: LLM decides via system prompt instructions. Parser checks for markers.
- **Step execution loop**: For each step, refresh document context + RAG context, ask LLM to implement just that step, execute code, advance or retry.
- **Auto-retry**: On failure, send error + failed code back to LLM. Max 3 retries (configurable). Works for both plan steps and direct responses.
- **Document context refresh**: Call `build_document_context()` before each LLM request so it sees objects created by previous steps.
- **RAG context refresh**: Call `retriever.retrieve(step_description)` before each step to inject relevant API knowledge.

### 2c. System Prompt Updates (`assistant/system_prompt.py`)

Add to `build_system_prompt()`:

```
EXECUTION MODES:
- Simple requests: respond with a single ```python code block
- Complex multi-step requests: output a plan in <<<PLAN>>>...<<<END_PLAN>>> format with STEP N: description lines, then STOP (no code)

When implementing a plan step:
- Output exactly ONE ```python code block
- Reference objects from previous steps by their document names

When fixing code after an error:
- Read the error carefully
- Output a complete corrected ```python code block
```

Add helper functions:
- `build_step_prompt(step_number, description, total_steps)`
- `build_retry_prompt(code, error, step_info="")`

---

## Phase 3: UI Updates (`assistant/chat_panel.py`)

### Changes to ChatWidget:

- **`__init__`**: Add `self._orchestrator = None`, `self._current_plan = None`
- **`_on_send`**: Delegate to orchestrator instead of creating LLMWorker directly
- **New signal handlers**: `_on_plan_received`, `_on_step_completed`, `_on_retry_started`, `_on_all_done`
- **Plan rendering**: Show step list with status indicators (pending/running/done/failed), retry badges
- **Plan controls**: `[Execute Plan]` button (or auto-start if auto-execute enabled), `[Cancel]` button during execution
- **New anchor schemes**: `plan-execute:0`, `plan-cancel:0` handled in `_on_anchor_clicked`

CSS additions for plan steps: `.step-pending`, `.step-running`, `.step-done`, `.step-failed`, `.retry-badge`

---

## Implementation Order

1. **RAG foundation**: `rag/store.py` → `rag/embeddings.py` → `rag/chunker.py` → `rag/retriever.py`
2. **RAG integration**: Update `system_prompt.py` and `llm_client.py`
3. **Plan parser**: `plan_parser.py`
4. **Orchestrator**: `orchestrator.py` (direct mode + retry first, then plan mode)
5. **UI updates**: `chat_panel.py` modifications
6. **Preferences**: Add max retries to `preferences.py`

## Verification

1. **RAG**: Start FreeCAD → switch to AI Assistant → first request triggers index build → check `rag.db` is created with chunks → verify relevant chunks appear in LLM context
2. **Auto-retry**: Send a request that generates code with a known error pattern → verify the addon automatically retries with the error context → check retry count badge in UI
3. **Planning**: Send a complex request like "Create a house with a peaked roof, two windows, and a door" → verify plan appears with steps → click Execute Plan → watch steps execute sequentially → verify document contains all objects
4. **Failure recovery in plan**: During a multi-step plan, if a step fails, verify retry kicks in and the plan continues to subsequent steps
