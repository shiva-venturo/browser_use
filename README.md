# Logam Mulia Queue Automation v2

Skrip otomasi Python untuk mendaftarkan slot antrean di website [Logam Mulia BELM](https://antrean.logammulia.com/) menggunakan `browser-use` dengan **Local LLM**.

Agent akan otomatis: login (termasuk menyelesaikan captcha matematika), iterasi semua cabang BELM, dan langsung memesan slot ketika kuota tersedia.

## Requirements

- Python 3.11
- [uv](https://docs.astral.sh/uv/) package manager
- Local LLM server (Ollama, LM Studio, dsb.) dengan endpoint kompatibel OpenAI
- Akun Logam Mulia yang sudah terdaftar

## Setup

**1. Install dependencies**

```bash
uv sync
```

**2. Install browser Chromium**

```bash
playwright install chromium
```

**3. Konfigurasi environment**

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Local LLM (Ollama, LM Studio, dsb.)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=nama-model-anda
LLM_API_KEY=sk-dummy

# Kredensial Logam Mulia
LOGAM_EMAIL=email@anda.com
LOGAM_PASSWORD=password-anda
```

## Menjalankan

```bash
python main.py
```

Browser Chromium akan terbuka dan agent mulai bekerja secara otomatis. Log disimpan ke `output.log`.

## Cara Kerja

1. **Login** — Navigasi ke halaman login, isi email/password, hitung captcha matematika, handle Cloudflare Turnstile
2. **Menu Antrean** — Klik tombol "Menu Antrean" setelah masuk
3. **Loop Cabang** — Iterasi setiap cabang BELM via dropdown, cek status kuota
4. **Booking** — Jika kuota tersedia, pilih waktu kedatangan dan klik "Ambil Antrean"
5. **Laporan** — Output hasil: berhasil (nama cabang) atau gagal (semua cabang penuh)

## Arsitektur

Seluruh kode ada di satu file `main.py` (~440 baris) dengan komponen:

| Komponen | Deskripsi |
|---|---|
| `TASK` | Prompt instruksi lengkap dalam Bahasa Indonesia untuk LLM agent |
| `CDPClient` monkey-patch | Meningkatkan WebSocket `ping_timeout` ke 120s agar tidak putus saat LLM lambat |
| `LocalLLMChatOpenAI` | Subclass `ChatOpenAI` yang membersihkan output JSON malformed dari local LLM |
| `main()` | Setup LLM, BrowserSession, Agent, lalu jalankan |

### Kenapa Local LLM?

Konfigurasi dibuat khusus untuk local LLM (misalnya model 8B) yang tidak mendukung structured output OpenAI:

- `dont_force_structured_output=True` — model tidak perlu support JSON schema mode
- `add_schema_to_system_prompt=True` — schema action disisipkan sebagai teks
- `use_vision=False` — tidak butuh kemampuan vision
- `max_actions_per_step=1` — satu aksi per langkah agar index elemen tidak berubah
- `temperature=0.0` — output deterministik

### Output Cleaning

`LocalLLMChatOpenAI._clean_json_response()` menangani output malformed umum:
- Strip XML wrapper (`<output>...</output>`, `<action>...</action>`, dll.)
- Ekstrak JSON dari teks sekitar
- Konversi string index ke integer (`"[285]<a />"` → `285`)
- Hapus trailing comma sebelum `}` atau `]`
- Truncate action array ke 1 elemen

## Konfigurasi Agent

| Setting | Nilai | Alasan |
|---|---|---|
| `max_steps` | 150 | ~4 langkah/cabang × 25+ cabang + login + booking |
| `max_history_items` | 10 | Mencegah context overflow pada model kecil |
| `max_failures` | 5 | Toleransi error sebelum berhenti |
| `flash_mode` | True | Eksekusi lebih cepat |
| `disable_security` | True | Diperlukan untuk Cloudflare Turnstile cross-origin iframe |

## Troubleshooting

**Context length overflow** — Gunakan model dengan context lebih besar atau naikkan `--context-size` di server LLM.

**ValidationError dari Pydantic** — Local LLM menghasilkan format action yang tidak dikenal. Coba model yang lebih besar atau tambahkan kasus pembersih di `_clean_json_response()`.

**ConnectionClosedError** — Sudah ditangani oleh CDPClient monkey-patch (ping_timeout=120s). Jika masih terjadi, pastikan LLM server responsif.
