# Panduan Kerja — Beads Kanban

Panduan singkat untuk siapapun (manusia atau AI agent) yang mau ngerjain
task di proyek ini. Baca **sekali**, lalu pakai sebagai referensi.

> Source of truth task tracking di proyek ini adalah `bd` (Beads).
> **JANGAN** pakai TodoWrite, markdown TODO, atau MEMORY.md untuk tracking.

---

## 1. Konsep Inti — 30 detik

- Setiap pekerjaan = satu **issue** dengan ID format `verse-xxx`.
- Issue punya **status** yang berpindah-pindah seiring kerja jalan.
- Issue punya **assignee** (siapa yang ngerjain) dan **labels** (tag).
- File `.beads/issues.jsonl` adalah export pasif — **jangan** edit manual.
  Semua perubahan via `bd` command.

### Status Lifecycle (PENTING — ini yang sering kelewat)

```
open → in_progress → [review] → closed
        ↓
     blocked  (kalau ada dependency belum selesai)
```

Aturan transisi:

| Dari → Ke | Cara | Kapan |
|-----------|------|-------|
| `open` → `in_progress` | `bd update <id> --claim` | Mulai ngerjain |
| `in_progress` → **`review`** | `bd update <id> --add-label human` | **Selesai coding, butuh review manusia** |
| `review` → `closed` | `bd close <id> --reason="..."` | Manusia approve hasilnya |
| any → `blocked` | otomatis dari `bd dep add` | Ada dependency belum done |

> **AI agent (Claude/Codex/Gemini) TIDAK boleh langsung `bd close`.**
> Workflow yang benar: kerjain → flag `human` → tunggu user close.
> Ini convention proyek — supaya manusia tetap punya kontrol final.

---

## 2. Flow Lengkap — Contoh Konkret

Skenario: Manusia minta feature baru, dikerjain agent, lalu ditutup.

### Step 1 — Manusia bikin issue

```bash
bd create \
  --title="Tambah get_weather tool di registry" \
  --description="Why: user request agar bisa tanya cuaca saat ini lewat suara.
What: daftarkan get_weather tool di tools/builtin/weather.py dan registry.py.
Out of scope: widget visual detail cuaca 5 harian di UI (cukup TTS response dulu)." \
  --type=feature \
  --priority=2
```

Output: `✓ Created issue: verse-abc — ...`

### Step 2 — Agent cari kerjaan

```bash
bd ready                    # list issue yang siap dikerjain
bd show verse-abc           # baca detail lengkap
```

### Step 3 — Agent claim & set assignee

```bash
bd update verse-abc --claim --assignee=claude
# atau --assignee=gemini
```

`--claim` set status ke `in_progress` + assignee otomatis ke `$USER`.
Pakai `--assignee=claude` / `--assignee=gemini` / `--assignee=other`
supaya icon brand muncul di kanban app (sparkles gold untuk Claude,
cpu ungu untuk Gemini/GPT/bot, chevrons biru untuk Codex).

### Step 4 — Agent kerjain

Coding, testing, dll. Selama kerja:

- `bd show <id>` — review konteks lagi.
- `bd update <id> --notes="progress: X selesai, Y in flight"` — log
  progress (opsional, untuk hand-off ke sesi berikut).

### Step 5 — Selesai → flag review (BUKAN close)

```bash
bd update verse-abc \
  --add-label human \
  --notes="Implemented get_weather tool. pytest passed, tauri dev builds successfully. Added weather.py in backend/verse/tools/builtin/, registered in registry.py. Manual smoke pending."
```

Issue sekarang masuk **Review** column di kanban app. **Stop di sini.**
Tunggu manusia.

### Step 6 — Manusia review & close

```bash
bd close verse-abc --reason="Verified manually. Tool executes fine and LLM calls it correctly."
```

---

## 3. Cheat Sheet Command

### Cari & lihat

```bash
bd ready                           # issue siap dikerjain (no blockers)
bd list --status=open              # semua open
bd list --status=in_progress       # yang lagi dikerjain
bd list --status=review            # yang nunggu manusia
bd blocked                         # yang ke-block
bd show <id>                       # detail lengkap satu issue
bd search "<keyword>"              # cari by teks
bd stats                           # angka ringkas open/closed/blocked
```

### Bikin & ubah

```bash
bd create --title="..." --description="..." --type=task --priority=2
bd update <id> --claim                      # claim + in_progress
bd update <id> --assignee=claude            # set assignee
bd update <id> --add-label human            # flag for review
bd update <id> --remove-label human         # un-flag
bd update <id> --status=open                # rollback ke open
bd update <id> --notes="..."                # tambah catatan
bd update <id> --title="..." --description="..."   # edit field
bd close <id> --reason="..."                # tutup (manusia saja!)
bd close <id1> <id2> ...                    # tutup banyak sekaligus
```

> ⚠️ **JANGAN PAKAI `bd edit`** — buka $EDITOR (vim/nano) yang nge-block
> agent. Selalu pakai `bd update <id> --field=value`.

### Dependency

```bash
bd dep add <issue> <depends-on>    # issue depends-on harus selesai dulu
bd dep remove <issue> <depends-on>
bd blocked                         # lihat siapa yang ke-block
```

bd otomatis detect cycle, jadi `A blocks B, B blocks A` bakal di-reject.

### Memori antar-sesi

```bash
bd remember "insight penting"      # simpan catatan persistent
bd memories <keyword>              # cari catatan
```

Pakai ini untuk knowledge yang lintas-sesi (konvensi proyek, gotcha,
keputusan arsitektur). Jangan bikin file MEMORY.md.

---

## 4. Convention Proyek (yang gampang kelewat)

### Priority

| Value | Label | Kapan |
|-------|-------|-------|
| `0` / `P0` | Must / Critical | Production down, security |
| `1` / `P1` | Important | Blocker untuk milestone |
| `2` / `P2` | High | Default untuk feature normal |
| `3` / `P3` | Medium | Nice-to-have |
| `4` / `P4` | Backlog | Suatu hari |

Pakai angka, **bukan** "high"/"medium"/"low".

### Type

`task`, `bug`, `feature`, `epic`, `chore`. Pilih yang paling deskriptif.

### Assignee Convention

- `claude` → icon **sparkles** gold (Claude AI)
- `codex` → icon **chevrons** biru (OpenAI Codex)
- `other` / `gemini` / `gpt` / `llm` / `bot` → icon **cpu** ungu (AI lain seperti Gemini)
- Apapun lainnya (`rayne`, dll.) → text initials (manusia)

Resolver match token case-insensitive substring, jadi `Claude`,
`claude-code`, `anthropic` semua valid untuk kind Claude. Begitu juga
`Gemini` atau `agent` → kind Other (ungu).

### Description Style

```
Why: <alasan kenapa issue ini ada — masalah / kebutuhan>
What:
- <poin konkret apa yang harus dilakukan>
- <poin lain>
Out of scope:
- <yang sengaja tidak dikerjain biar fokus>
```

Ini bukan wajib, tapi bikin issue jauh lebih clear untuk dikerjain orang
lain (atau agent) tanpa nanya balik.

---

## 5. Sebelum Bilang "Selesai"

Checklist mandatory untuk AI agent setelah implementasi:

```
[ ] pytest                         — pastikan semua backend test hijau
[ ] tauri build / npm run build    — pastikan frontend compile clean
[ ] bd update <id> --add-label human --notes="..."
[ ] (JANGAN bd close — biar manusia)
```

Checklist untuk manusia setelah review:

```
[ ] bd close <id> --reason="..."
[ ] (kalau ada follow-up) bd create issue baru, jangan reopen
```

---

## 6. Common Pitfalls

| Salah | Benar | Kenapa |
|-------|-------|--------|
| `bd close` setelah agent selesai | `bd update --add-label human` | Manusia harus review dulu |
| `--assignee="Gemini Code Executor"` | `--assignee=gemini` | Token pendek lebih ergonomis, resolver pinter |
| `bd edit <id>` | `bd update <id> --field=value` | edit buka vim, block agent |
| Edit `.beads/issues.jsonl` manual | `bd update` | File itu export pasif |
| `bd create` tanpa description | Selalu kasih Why + What | Issue tanpa konteks = nanya balik |
| Bikin file MEMORY.md / TODO.md | `bd remember` / `bd create` | Fragmen, gampang lost |
| Lupa pindahin ke review | `--add-label human` setelah selesai | Kanban macet di "In Progress" |

---

## 7. Recovery Quick Reference

| Masalah | Solusi |
|---------|--------|
| Sesi habis di tengah jalan | `bd prime` lalu `bd list --status=in_progress` |
| Lupa apa yang dikerjain | `bd show <id>` baca notes & description |
| Issue salah di-close | `bd update <id> --status=open` |
| Mau batalin claim | `bd update <id> --status=open --assignee=""` |
| Cycle detected | `bd show <id>` lalu `bd dep remove` salah satu edge |
| Ngerasa stuck / butuh diskusi | `bd human <id>` flag untuk human decision |

---

## 7.5. Recurring Tasks

Ada **dua jenis issue** di proyek ini:

1. **One-shot** (default) — dikerjain, di-close, selesai.
2. **Recurring** — task yang berulang berkala (refactoring, housekeeping,
   audit, dst). Sisa terbuka selamanya, tapi punya **history run**.

### Apa yang Recurring Task punya

| Field | Asal | Contoh |
|-------|------|--------|
| `isRecurring` | sidecar JSON | `true` |
| `cadenceDays` | sidecar JSON | `7`, `30`, `90`, atau `null` |
| `history[]` | sidecar JSON | array `{completedAt, completedBy, notes}` |
| `completionCount` | derived (`history.count`) | `3` |
| `lastCompletedAt` | derived (max completedAt) | `2026-04-22T...` |
| `isOverdue` | derived (`now - lastCompletedAt > cadenceDays`) | `true`/`false` |

### Di mana disimpan

Sidecar JSON terpisah dari beads core, **bukan** label / field di issue:

```
.beads/recurring/<issue-id>.json
```

Contoh isi:

```json
{
  "cadenceDays" : 30,
  "history" : [
    { "id": "<uuid>", "completedAt": "2026-04-22T10:00:00Z",
      "completedBy": "claude", "notes": "Q2 sweep done" }
  ],
  "isRecurring" : true,
  "issueID" : "verse-d5v"
}
```

> **Kenapa sidecar, bukan label?** Label gak bisa nyimpen history,
> count, atau cadence. Sidecar JSON clean, di-track git, gampang
> di-edit manual kalau perlu.

### Cara buat recurring task

**Opsi A — via UI (rekomendasi)**

1. `bd create ...` issue biasa kayak biasa.
2. Buka app, pilih issue, scroll detail panel ke section
   **"Recurring Task"**.
3. Toggle **"Mark as recurring"** → on.
4. Pilih cadence chip (None / 7d / 30d / 90d) sesuai kebutuhan.
5. Tiap kali run selesai → tombol **"Mark Run Complete"** (boleh
   isi notes). Ini akan:
   - Append `RecurringHistoryEntry` ke history.
   - Hapus label `human` kalau ada.
   - Reset status ke `open` → issue balik ke Ready.
   - **TIDAK** `bd close` (issue tetap idup).

**Opsi B — programatik (untuk seed atau scripting)**

Tulis langsung file `.beads/recurring/<id>.json` dengan format di atas.
`RecurringStore.load()` (dipanggil saat workspace dibuka) bakal nge-load
otomatis. Catatan: kalau app lagi jalan, perlu tutup-buka workspace
biar reload.

### Konvensi untuk AI Agent

- Kalau user nyebut task "berulang" / "tiap N hari" / "recurring" /
  "rutin" — itu kandidat recurring task.
- Jangan `bd close` recurring task — di-cycle balik via "Mark Run
  Complete", bukan ditutup.
- Kalau bikin recurring task untuk user lewat CLI: `bd create` dulu,
  baru tulis sidecar JSON. Cadence default rekomendasi:
  - Refactoring sweep / audit besar → 30 atau 90 hari.
  - Housekeeping / cleanup → 7 hari.
  - Quarterly review → 90 hari.
- Counter di card (`#N`) = berapa kali sudah dijalanin. Badge orange
  `Overdue Nd` muncul kalau lewat cadence.

---

## 8. Untuk AI Agent Khusus

Saat dipanggil untuk ngerjain task di proyek ini:

1. **`bd prime`** dulu di awal sesi (auto-load context).
2. **Baca issue lengkap** sebelum coding: `bd show <id>`.
3. **Claim** dengan assignee yang benar: `bd update <id> --claim --assignee=gemini` (atau claude).
4. Coding + testing. Pakai test framework yang ada (`pytest` untuk backend).
5. **Selesai → flag review**, BUKAN close:
   ```bash
   bd update <id> --add-label human --notes="<ringkasan apa yang dilakukan, hasil test>"
   ```
6. Hand-off: kasih manusia ringkasan singkat (1-2 kalimat) di chat.

Yang **TIDAK boleh** dilakukan AI agent tanpa izin eksplisit:
- `bd close` — itu hak manusia.
- `git push` ke main — kecuali user minta.
- `bd dep add/remove` di issue yang bukan kerjaannya.
- Edit `bd` config (`bd config set ...`).

---

## 9. Referensi Cepat

- **Project**: Voice-first AI companion for macOS (Tauri React frontend + Python FastAPI backend).
- **Build**: Backend setup (Python setup/poetry) / Frontend build (`npm run tauri build` or `npm run build`).
- **Test**: `pytest` untuk backend test.
- **Style guide**: `verse-prd.md` (Core design decision, adapters, and tools flow).
- **UI komponen**: `frontend/src/` (React UI components & state), `backend/verse/` (Python core backend, adapters, tools registry).
