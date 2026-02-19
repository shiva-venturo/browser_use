# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file Python automation script (`main.py`, ~440 lines) that uses the `browser-use` library with a **local LLM** to automatically register queue slots at the Logam Mulia gold bullion website (https://antrean.logammulia.com/). The agent navigates the site, logs in (solving a math captcha), iterates through all branch locations checking quota availability, and books a slot when found.

## Commands

```bash
# Install dependencies (uses uv package manager)
uv sync

# Install browser for Playwright
playwright install chromium

# Run the automation
python main.py
```

There are no tests, linting, or build steps — this is a single-script automation project.

## Environment Setup

Copy `.env.example` to `.env` and configure:
- `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` — local LLM server (Ollama, LM Studio, etc.)
- `LOGAM_EMAIL` / `LOGAM_PASSWORD` — Logam Mulia account credentials

Python 3.11 required (`.python-version`).

## Architecture & Key Design Decisions

The entire codebase is `main.py` with these sections:

1. **Configuration** — loads env vars via `python-dotenv`
2. **Task prompt (`TASK`)** — detailed step-by-step instructions in Bahasa Indonesia for the LLM agent (login → navigate → loop branches → book slot)
3. **CDPClient monkey-patch** — overrides `CDPClient.start()` to increase WebSocket `ping_timeout` from 20s to 120s, preventing `ConnectionClosedError` when the local LLM is slow
4. **`LocalLLMChatOpenAI`** — subclass of `browser_use.llm.openai.chat.ChatOpenAI` (not the langchain one) that intercepts `ainvoke()` to clean malformed LLM output before Pydantic parsing. Key cleanups:
   - Strips XML-like wrappers (`<output>...</output>`, `<action>...</action>`)
   - Extracts JSON from surrounding text
   - Fixes string indices to integers (e.g. `"[285]<a /> Log In"` → `285`)
   - Truncates action arrays to 1 element (matching `max_actions_per_step=1`)
   - Removes trailing commas before `}` or `]`
5. **`count_tokens()` helper** — uses tiktoken with fallback to `len//4`
6. **`main()` async function** — creates `LocalLLMChatOpenAI`, `BrowserSession`, and `Agent`, then runs the agent

### Local LLM constraints drive all configuration choices:

| Setting | Value | Why |
|---|---|---|
| `dont_force_structured_output` | `True` | Local models don't support OpenAI JSON schema mode |
| `add_schema_to_system_prompt` | `True` | Injects action schema as text so local model knows valid action formats |
| `use_vision` | `False` | Local LLMs lack vision capabilities |
| `max_actions_per_step` | `1` | Each action changes page state, invalidating element indices |
| `max_history_items` | `10` | Prevents context overflow on small-context models |
| `max_steps` | `150` | ~4 steps/branch × 25+ branches + login + booking |
| `disable_security` | `True` | Required for Cloudflare Turnstile cross-origin iframe |
| `temperature` | `0.0` | Deterministic output |
| `flash_mode` | `True` | Faster agent execution |
| `extend_system_message` | JSON format rules | Extra instructions enforcing valid JSON output, integer indices, single action per response |

### Key dependencies

- `browser-use` (>=0.11.9) — AI-driven browser automation framework (uses Playwright + CDP under the hood); the `ChatOpenAI` base class comes from `browser_use.llm.openai.chat`, not from langchain
- `langchain-openai` (>=1.1.10) — transitive dependency required by browser-use
- `cdp-use` (transitive) — Chrome DevTools Protocol client (monkey-patched for timeout)

### Known issues

- Local LLMs (especially smaller models like 8B) sometimes produce invalid action formats despite `add_schema_to_system_prompt=True`. The `LocalLLMChatOpenAI` wrapper handles many common cases, but novel malformations may still cause `ValidationError`.
- The `ainvoke()` override in `LocalLLMChatOpenAI` duplicates significant logic from the parent class. If `browser-use` updates its `ChatOpenAI.ainvoke()`, the override may need to be synced.
