"""
Logam Mulia Queue Registration Automation - v2
Uses browser-use >= 0.11.9 with local LLM for automated queue booking.
"""

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("output.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─── Konfigurasi ────────────────────────────────────────────────────────────
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_API_KEY = os.getenv("LLM_API_KEY")

EMAIL = os.getenv("LOGAM_EMAIL")
PASSWORD = os.getenv("LOGAM_PASSWORD")

# ─── Task Prompt ────────────────────────────────────────────────────────────
TASK = f"""
Kamu adalah asisten otomasi untuk mendaftar antrean di website Logam Mulia.
Ikuti langkah-langkah berikut secara berurutan dan teliti:

## Langkah 1: Buka Website
- Navigasi ke https://antrean.logammulia.com/
- Akan muncul halaman Pengumuman dengan informasi pendaftaran antrean.
- Di bagian bawah halaman, ada dua tombol: "Log In" (biru) dan "Register".
- Klik tombol "Log In".

## Langkah 2: Login
- Kamu akan berada di halaman login "Antrean Butik Emas Logam Mulia (BELM)".
- Masukkan email '{EMAIL}' ke kolom Username.
- Masukkan password '{PASSWORD}' ke kolom Password.
- PENTING - Soal Matematika: Ada kolom bertuliskan "Berapa hasil perhitungan dari X ditambah Y?".
  Baca angka X dan Y dari pertanyaan tersebut, hitung penjumlahannya (X + Y), dan masukkan hasilnya.
  Contoh: jika tertulis "8 ditambah 10", jawabannya adalah 18.
- Jika ada checkbox Cloudflare "Verify you are human", klik checkbox tersebut dan tunggu verifikasi selesai.
- Klik tombol "Log in" untuk masuk.

## Langkah 3: Navigasi ke Menu Antrean
- Setelah login berhasil, kamu akan berada di halaman Profile.
- Cari tombol berwarna ungu bertuliskan "Menu Antrean".
- Klik tombol "Menu Antrean".

## Langkah 4: Pilih Cabang dan Cek Kuota (LOOP)
- Kamu sekarang berada di halaman "Antrean BELM".
- Ada dropdown dengan label "-- Pilih BELM --".
- Pilih cabang PERTAMA yang tersedia di dropdown.
- Klik tombol "Tampilkan Butik".
- Periksa status kuota:
  * Jika tertulis "Kuota Tidak Tersedia" atau "Sisa: 0" atau tombol "Penuh":
    → Cabang ini tidak ada slot. Kembali ke dropdown, pilih cabang BERIKUTNYA.
    → Klik "Tampilkan Butik" lagi.
    → ULANGI proses ini untuk SETIAP cabang sampai menemukan kuota tersedia.
  * Jika tertulis "Kuota Tersedia" atau "Sisa:" dengan angka lebih dari 0:
    → Lanjut ke Langkah 5.

## Langkah 5: Ambil Antrean
- Setelah menemukan cabang dengan kuota tersedia:
  - Pilih waktu kedatangan dari dropdown "--Pilih Waktu Kedatangan--".
  - Jika muncul Cloudflare verification, selesaikan verifikasinya.
  - Klik tombol "Ambil Antrean" (tombol merah/oranye).
  - Konfirmasi jika ada popup yang muncul.

## Langkah 6: Laporan
- Jika berhasil mengambil antrean: laporkan "BERHASIL - Antrean diambil di [nama cabang]"
- Jika SEMUA cabang sudah dicoba dan tidak ada kuota: laporkan "GAGAL - Semua cabang penuh"

## Catatan Penting
- Untuk soal matematika: baca angka dengan teliti dan hitung penjumlahan dengan benar.
- Saat mencoba cabang, gunakan dropdown untuk melihat semua pilihan, lalu pilih satu per satu secara berurutan.
- Jika halaman lambat loading, scroll ke bawah untuk mencari elemen yang diperlukan.
- Jika ada dialog konfirmasi, klik OK/Konfirmasi.
- Jangan berhenti sampai antrean berhasil diambil atau semua cabang sudah dicoba.
"""

# ─── Monkey Patch CDP Client ────────────────────────────────────────────────
# Patch ini diperlukan untuk mencegah "ConnectionClosedError: keepalive ping timeout"
# saat browser sedang busy rendering halaman berat atau LLM lambat merespon.
try:
    import websockets
    from cdp_use.client import CDPClient

    async def patched_start(self):
        """Monkey-patched start method to increase ping_timeout."""
        if self.ws is not None:
            raise RuntimeError("Client is already started")

        logger.info(
            f"Connecting to {self.url} with patched config (ping_timeout=120s)"
        )
        connect_kwargs = {
            "max_size": self.max_ws_frame_size,
            "ping_timeout": 120,
            "close_timeout": 120,
        }
        if self.additional_headers:
            connect_kwargs["additional_headers"] = self.additional_headers

        self.ws = await websockets.connect(self.url, **connect_kwargs)
        self._message_handler_task = asyncio.create_task(self._handle_messages())

    CDPClient.start = patched_start
    logger.info("Applied CDPClient.start monkey patch for stable connection")

except ImportError as e:
    logger.warning(f"Could not import CDPClient for patching: {e}")


# ─── Local LLM ChatOpenAI Wrapper ──────────────────────────────────────────
# Subclass ChatOpenAI to clean up malformed JSON from local LLMs before parsing.
# Local models often wrap JSON in XML tags, use string indices, etc.
try:
    from browser_use.llm.openai.chat import ChatOpenAI as _BaseChatOpenAI
    from browser_use.llm.views import ChatInvokeCompletion
    from browser_use.llm.messages import BaseMessage as LLMBaseMessage

    T = TypeVar("T", bound=BaseModel)

    @dataclass
    class LocalLLMChatOpenAI(_BaseChatOpenAI):
        """ChatOpenAI wrapper that cleans malformed LLM output before Pydantic parsing."""

        def _clean_json_response(self, raw: str) -> str:
            """Clean up common local LLM output issues."""
            text = raw.strip()

            # 1. Strip XML-like wrappers: <output>...</output>, <action>...</action>, etc.
            xml_pattern = re.compile(
                r"^<(?:output|action|response|json|result)>\s*(.*?)\s*</(?:output|action|response|json|result)>$",
                re.DOTALL,
            )
            m = xml_pattern.match(text)
            if m:
                text = m.group(1).strip()

            # 2. Extract JSON object if there's surrounding text
            # Find the first '{' and last '}'
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                text = text[first_brace : last_brace + 1]

            # 3. Try to parse and fix common issues
            try:
                data = json.loads(text)
                data = self._fix_parsed_data(data)
                return json.dumps(data)
            except json.JSONDecodeError:
                pass

            # 4. Try fixing common JSON syntax issues
            # Remove trailing commas before } or ]
            text = re.sub(r",\s*([}\]])", r"\1", text)
            # Fix single quotes to double quotes (rough)
            try:
                data = json.loads(text)
                data = self._fix_parsed_data(data)
                return json.dumps(data)
            except json.JSONDecodeError:
                pass

            return text

        def _fix_parsed_data(self, data: dict) -> dict:
            """Fix parsed JSON data: integer indices, action limits, etc."""
            # Fix action indices - convert string indices like '[285]<a /> Log In' to 285
            if "action" in data and isinstance(data["action"], list):
                for action in data["action"]:
                    if not isinstance(action, dict):
                        continue
                    for action_type, params in action.items():
                        if not isinstance(params, dict):
                            continue
                        if "index" in params and isinstance(params["index"], str):
                            # Extract integer from strings like '[285]<a /> Log In' or '285'
                            idx_match = re.search(r"\[?(\d+)\]?", params["index"])
                            if idx_match:
                                params["index"] = int(idx_match.group(1))

                # Limit to 1 action (matching max_actions_per_step=1)
                if len(data["action"]) > 1:
                    data["action"] = data["action"][:1]

            return data

        async def ainvoke(
            self, messages: list[LLMBaseMessage], output_format: type[T] | None = None, **kwargs: Any
        ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
            """Override ainvoke to clean LLM response before Pydantic parsing."""
            from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
            from browser_use.llm.openai.serializer import OpenAIMessageSerializer
            from browser_use.llm.schema import SchemaOptimizer
            from openai import APIConnectionError, APIStatusError, RateLimitError
            from openai.types.shared_params.response_format_json_schema import (
                JSONSchema,
                ResponseFormatJSONSchema,
            )

            openai_messages = OpenAIMessageSerializer.serialize_messages(messages)

            try:
                model_params: dict[str, Any] = {}

                if self.temperature is not None:
                    model_params["temperature"] = self.temperature
                if self.frequency_penalty is not None:
                    model_params["frequency_penalty"] = self.frequency_penalty
                if self.max_completion_tokens is not None:
                    model_params["max_completion_tokens"] = self.max_completion_tokens
                if self.top_p is not None:
                    model_params["top_p"] = self.top_p
                if self.seed is not None:
                    model_params["seed"] = self.seed
                if self.service_tier is not None:
                    model_params["service_tier"] = self.service_tier

                if self.reasoning_models and any(
                    str(m).lower() in str(self.model).lower() for m in self.reasoning_models
                ):
                    model_params["reasoning_effort"] = self.reasoning_effort
                    model_params.pop("temperature", None)
                    model_params.pop("frequency_penalty", None)

                if output_format is None:
                    response = await self.get_client().chat.completions.create(
                        model=self.model,
                        messages=openai_messages,
                        **model_params,
                    )
                    usage = self._get_usage(response)
                    return ChatInvokeCompletion(
                        completion=response.choices[0].message.content or "",
                        usage=usage,
                        stop_reason=response.choices[0].finish_reason if response.choices else None,
                    )
                else:
                    response_format: JSONSchema = {
                        "name": "agent_output",
                        "strict": True,
                        "schema": SchemaOptimizer.create_optimized_json_schema(
                            output_format,
                            remove_min_items=self.remove_min_items_from_schema,
                            remove_defaults=self.remove_defaults_from_schema,
                        ),
                    }

                    if (
                        self.add_schema_to_system_prompt
                        and openai_messages
                        and openai_messages[0]["role"] == "system"
                    ):
                        schema_text = f"\n<json_schema>\n{response_format}\n</json_schema>"
                        if isinstance(openai_messages[0]["content"], str):
                            openai_messages[0]["content"] += schema_text

                    if self.dont_force_structured_output:
                        response = await self.get_client().chat.completions.create(
                            model=self.model,
                            messages=openai_messages,
                            **model_params,
                        )
                    else:
                        response = await self.get_client().chat.completions.create(
                            model=self.model,
                            messages=openai_messages,
                            response_format=ResponseFormatJSONSchema(
                                json_schema=response_format, type="json_schema"
                            ),
                            **model_params,
                        )

                    raw_content = response.choices[0].message.content
                    if raw_content is None:
                        raise ModelProviderError(
                            message="Failed to parse structured output from model response",
                            status_code=500,
                            model=self.name,
                        )

                    # Clean the response before parsing
                    cleaned = self._clean_json_response(raw_content)
                    if cleaned != raw_content:
                        logger.debug(f"Cleaned LLM response:\n  BEFORE: {raw_content[:200]}\n  AFTER:  {cleaned[:200]}")

                    usage = self._get_usage(response)
                    parsed = output_format.model_validate_json(cleaned)

                    return ChatInvokeCompletion(
                        completion=parsed,
                        usage=usage,
                        stop_reason=response.choices[0].finish_reason if response.choices else None,
                    )

            except RateLimitError as e:
                raise ModelRateLimitError(message=e.message, model=self.name) from e
            except APIConnectionError as e:
                raise ModelProviderError(message=str(e), model=self.name) from e
            except APIStatusError as e:
                raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
            except Exception as e:
                raise ModelProviderError(message=str(e), model=self.name) from e

    logger.info("LocalLLMChatOpenAI class loaded successfully")

except ImportError as e:
    logger.warning(f"Could not import ChatOpenAI for subclassing: {e}")
    LocalLLMChatOpenAI = None


# ─── Helper ─────────────────────────────────────────────────────────────────
def count_tokens(text: str) -> int:
    """Estimate token count for a given text."""
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except ImportError:
        return len(text) // 4


# ─── Main ───────────────────────────────────────────────────────────────────
async def main():
    logger.info("Memulai otomasi antrean Logam Mulia v2...")
    logger.info(f"  Model  : {LLM_MODEL}")
    logger.info(f"  Server : {LLM_BASE_URL}")

    try:
        from browser_use.agent.service import Agent
        from browser_use.browser import BrowserProfile, BrowserSession
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Pastikan dependencies terinstall: uv sync && playwright install chromium")
        sys.exit(1)

    if LocalLLMChatOpenAI is None:
        logger.error("LocalLLMChatOpenAI not available, cannot proceed")
        sys.exit(1)

    task_tokens = count_tokens(TASK)
    logger.info(f"Estimasi token task prompt: {task_tokens}")

    # Konfigurasi LLM lokal (menggunakan wrapper yang membersihkan output)
    llm = LocalLLMChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=0.0,
        dont_force_structured_output=True,
        add_schema_to_system_prompt=True,
    )

    # Konfigurasi browser (non-headless untuk monitoring)
    browser_profile = BrowserProfile(
        headless=False,
        disable_security=True,
    )

    browser_session = BrowserSession(
        browser_profile=browser_profile,
    )

    # Instruksi tambahan agar LLM lokal menghasilkan JSON yang valid
    extra_instructions = """
CRITICAL OUTPUT FORMAT RULES:
- You MUST respond with ONLY a valid JSON object. No XML tags, no markdown, no extra text.
- Do NOT wrap your response in <output>, <action>, <response>, or any other tags.
- The "index" field in actions MUST be an integer number (e.g. 285), NOT a string.
- You MUST output exactly ONE action per response in the "action" array.
- Example valid response:
{"action": [{"click": {"index": 5}}]}
"""

    # Buat agent
    agent = Agent(
        task=TASK,
        llm=llm,
        browser_session=browser_session,
        use_vision=False,
        max_actions_per_step=1,
        max_history_items=10,
        max_failures=5,
        flash_mode=True,
        use_thinking=False,
        extend_system_message=extra_instructions,
    )

    try:
        logger.info("Agent mulai bekerja...")
        result = await agent.run(max_steps=150)

        if result:
            logger.info(f"Agent selesai. Hasil:\n{result}")
        else:
            logger.warning("Agent selesai tanpa hasil.")

    except KeyboardInterrupt:
        logger.info("Dihentikan oleh pengguna.")
    except Exception as e:
        error_msg = str(e)
        if "context" in error_msg.lower() and "token" in error_msg.lower():
            logger.error("=" * 60)
            logger.error("GAGAL: CONTEXT LENGTH TOKEN OVERFLOW")
            logger.error("=" * 60)
            logger.error(f"Detail: {error_msg}")
            logger.error("SOLUSI:")
            logger.error("  1. Gunakan model dengan context length lebih besar")
            logger.error("  2. Restart LLM server dengan --context-size lebih besar")
            logger.error("=" * 60)
        else:
            logger.error(f"Error: {e}", exc_info=True)
    finally:
        try:
            await browser_session.close()
        except Exception:
            pass
        logger.info("Browser ditutup.")


if __name__ == "__main__":
    asyncio.run(main())
