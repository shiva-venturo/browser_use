# Plan: Browser-Use v2 - Logam Mulia Queue Registration Automation

## Context
The user needs to automate queue registration at https://antrean.logammulia.com/ using the `browser-use` library with a **local LLM** (same approach as the v1 project). The v1 project at `/Users/muhammadshiva/Work/Venturo/Research/browser-use/` had issues with invalid action formats and connection timeouts. The v2 project will be a cleaner, improved implementation that addresses those issues while keeping the local LLM approach.

## Automation Flow
1. Navigate to https://antrean.logammulia.com/ → Click "Log In" button on announcement page
2. Fill login form: email, password, solve math captcha (addition question from DOM text), handle Cloudflare Turnstile → Click "Log in"
3. On Profile page → Click "Menu Antrean"
4. On Antrean BELM page → Select first branch from dropdown → Click "Tampilkan Butik"
5. **Retry loop**: If "Kuota Tidak Tersedia" (Sisa: 0) → select next branch → repeat for ALL branches
6. When "Kuota Tersedia" (Sisa > 0) → Select arrival time from dropdown → Handle Cloudflare if present → Click "Ambil Antrean"

## Files to Create (all in `/Users/muhammadshiva/Work/Venturo/Research/browser-use-v2/`)

### 1. `pyproject.toml`
```toml
[project]
name = "browser-use-v2"
version = "0.1.0"
description = "Automated queue registration for Logam Mulia BELM"
requires-python = ">=3.11"
dependencies = [
    "browser-use>=0.11.9",
    "langchain-openai>=1.1.10",
    "playwright>=1.58.0",
    "python-dotenv>=1.2.1",
]
```

### 2. `.env.example`
```ini
# Local LLM Configuration (Ollama, LM Studio, etc.)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=your-model-name
LLM_API_KEY=sk-dummy

# Logam Mulia Credentials
LOGAM_EMAIL=your-email@example.com
LOGAM_PASSWORD=your-password
```

### 3. `.env` (actual credentials, gitignored)
- LLM connection details pointing to user's local LLM server
- LOGAM_EMAIL=alifhamdanrifai@gmail.com
- LOGAM_PASSWORD=Bismillah12345*

### 4. `.gitignore`, `.python-version` (3.11)

### 5. `main.py` - Core automation script

**Key architecture decisions for local LLM:**

- **`create_llm()`**: Uses `browser_use.llm.openai.chat.ChatOpenAI` with:
  - `base_url` from env (local server endpoint)
  - `temperature=0.0` for deterministic output
  - `dont_force_structured_output=True` (local models don't support OpenAI's JSON schema)
  - `add_schema_to_system_prompt=True` (inject action schema as text in system prompt)

- **CDPClient monkey-patch**: Carried over from v1 - increases WebSocket `ping_timeout` from 20s → 120s to prevent `ConnectionClosedError` when local LLM is slow to respond

- **`TASK` prompt**: Clear step-by-step instructions written for local LLM comprehension:
  - Step 1: Navigate to site, click "Log In" button
  - Step 2: Fill email, password, solve math captcha (parse "X ditambah Y" from DOM, compute sum), click Cloudflare checkbox, click "Log in"
  - Step 3: Click "Menu Antrean" on Profile page
  - Step 4: Loop through branches - use dropdown to select each branch, click "Tampilkan Butik", check for "Kuota Tidak Tersedia" vs "Kuota Tersedia"
  - Step 5: When quota found - select arrival time, handle Cloudflare, click "Ambil Antrean"
  - Step 6: Report result

- **Agent configuration**:
  - `use_vision=False` - local LLMs don't support vision
  - `max_actions_per_step=1` - prevents stale element indices (critical)
  - `max_steps=150` - high limit for branch cycling (~4 steps/branch × 25+ branches)
  - `max_history_items=10` - limit context to avoid token overflow with smaller models
  - `max_failures=5` - retry tolerance
  - `headless=False` - visible browser for monitoring
  - `disable_security=True` - needed for Cloudflare Turnstile cross-origin iframe

### Key Design Decisions
| Decision | Rationale |
|----------|-----------|
| Local LLM via ChatOpenAI | User's preference, free, uses existing local server |
| `use_vision=False` | Local LLMs lack multimodal vision capabilities |
| `dont_force_structured_output=True` | Local models don't support OpenAI JSON schema mode |
| `add_schema_to_system_prompt=True` | Injects action schema as text so local model knows valid formats |
| CDPClient monkey-patch | Prevents WebSocket timeout when local LLM responds slowly |
| `max_actions_per_step=1` | Each action changes page state, invalidating element indices |
| `max_steps=150` | ~4 steps/branch × 25+ branches + login + booking |
| `max_history_items=10` | Prevents context overflow on models with small context windows |
| `disable_security=True` | Needed for Cloudflare Turnstile cross-origin iframe interaction |
| Try all branches sequentially | No preferred branch - iterate from first to last in dropdown |

### Reusable code from v1 reference
- CDPClient monkey-patch: `/Users/muhammadshiva/Work/Venturo/Research/browser-use/main.py` lines 77-114
- count_tokens helper: `/Users/muhammadshiva/Work/Venturo/Research/browser-use/main.py` lines 306-312
- Logging setup pattern: `/Users/muhammadshiva/Work/Venturo/Research/browser-use/main.py` lines 15-19

## Setup & Run
```bash
cd /Users/muhammadshiva/Work/Venturo/Research/browser-use-v2
# After files are created:
uv sync
playwright install chromium
# Fill in .env with local LLM server details and credentials
python main.py
```

## Verification
1. Run `python main.py` - browser opens to https://antrean.logammulia.com/
2. Agent clicks "Log In" on announcement page
3. Agent fills email, password, solves math captcha, handles Cloudflare
4. Agent navigates Profile → Menu Antrean → Antrean BELM
5. Agent cycles through branches sequentially checking quota
6. Agent takes queue when quota found OR reports all branches full
7. Check `output.log` for execution trace and any errors
