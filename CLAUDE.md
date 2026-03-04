# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FreeCAD AI Assistant — a FreeCAD addon (workbench) that lets users describe CAD operations in natural language, sends the request to an LLM, and executes the generated Python code inside FreeCAD. Supports Anthropic Claude, OpenAI, Google Gemini, and local models (Ollama, LM Studio).

## Development Environment

This is a **FreeCAD addon**, not a standalone Python project. There is no `setup.py`, `pyproject.toml`, pip install, or test suite. The code runs inside FreeCAD's embedded Python interpreter.

- **Install**: Symlink or copy the repo to `~/.local/share/FreeCAD/Mod/AIAssistant/`
- **Run**: Launch FreeCAD, switch to the "AI Assistant" workbench
- **Test manually**: Use the chat panel to send prompts and verify generated code executes correctly
- **No external dependencies**: Uses only `urllib` (no `requests`, no SDK libraries). UI uses PySide (Qt), bundled with FreeCAD.

## Architecture

The addon follows the standard FreeCAD workbench pattern:

- `package.xml` — FreeCAD addon metadata (name, version, dependencies)
- `Init.py` — App-level init (currently a no-op)
- `InitGui.py` — Registers `AIAssistantWorkbench`, the `Assistant_Chat` command, and the preferences page. Auto-opens the chat panel when the workbench activates.

### Core modules (all in `assistant/`)

| File | Role |
|---|---|
| `command.py` | FreeCAD GUI command that toggles the dock widget |
| `chat_panel.py` | `ChatWidget` (QTextBrowser-based chat UI) + `AssistantDockWidget`. Manages conversation history, renders messages with HTML, handles code block execute/copy actions via anchor URLs (`execute:N`, `copy:N`) |
| `llm_client.py` | `LLMClient` — HTTP-based LLM client using `urllib`. Routes Anthropic to its native API, all others (OpenAI, Gemini, custom/Ollama) to OpenAI-compatible `/v1/chat/completions`. Constructed from FreeCAD preferences. |
| `llm_worker.py` | `LLMWorker(QThread)` — runs `LLMClient.send_message()` off the GUI thread, emits `response_ready` / `error_occurred` signals |
| `system_prompt.py` | Builds the system prompt with FreeCAD coding rules/patterns and `build_document_context()` which introspects the active document's objects and selection |
| `executor.py` | `CodeExecutor` — runs generated Python code inside a FreeCAD transaction with captured stdout/stderr. Pre-loads `FreeCAD`, `Part`, `Sketcher`, `Draft`, `Mesh`, and `doc` into the exec namespace. |
| `preferences.py` | `DlgSettingsAssistant` — Qt preferences page (provider, API key, base URL, model, auto-execute toggle). Settings stored at `User parameter:BaseApp/Preferences/Mod/Assistant` |

### Request flow

1. User types in `ChatInput` → `ChatWidget._on_send()`
2. `LLMClient.from_preferences()` builds client from FreeCAD prefs
3. System prompt = `build_system_prompt()` + `build_document_context()`
4. `LLMWorker` thread calls the LLM API
5. Response rendered in QTextBrowser with `[Execute]`/`[Copy]` links per code block
6. Execute runs code via `CodeExecutor.execute()` inside a FreeCAD transaction

### Preferences path

All settings use `FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Assistant")` with keys: `Provider`, `ApiKey`, `BaseUrl`, `Model`, `AutoExecute`.

## Key Constraints

- **No pip packages**: FreeCAD's embedded Python has limited package availability. All HTTP is done via `urllib.request`. UI uses `PySide` (not PySide2/PySide6 — FreeCAD re-exports as `PySide`).
- **Import `FreeCAD`/`FreeCADGui` at module level is fine** in files loaded by `InitGui.py`, but these modules only exist inside FreeCAD's interpreter.
- **Generated code assumes pre-loaded namespace**: The executor provides `FreeCAD`, `FreeCADGui`, `App`, `Gui`, `doc`, `Part`, `PartDesign`, `Sketcher`, `Draft`, `Mesh`. The system prompt tells the LLM not to import these.
- **License**: LGPL-2.1-or-later. All source files should have the SPDX header.

## Planned Features (see docs/PLAN.md)

RAG system for FreeCAD API knowledge, plan-then-execute orchestrator for multi-step tasks, and auto-retry on code execution failure.
