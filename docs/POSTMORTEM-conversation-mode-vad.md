# Postmortem — Conversation Mode (`shift+alt+space`) Stuck Listening

> Status: **RESOLVED** (2026-05-30) · Issues terkait: `verse-q6h`, `verse-4dt`
> Tujuan dokumen ini: bug ini sudah di-"fix" berkali-kali tapi balik lagi. Catat
> akar masalah + guardrail biar **tidak terulang**.

---

## TL;DR

Conversation mode (toggle `shift+alt+space`) tidak pernah merespons: orb membesar
saat bicara, tapi terminal cuma spam `Still listening...` tiap ~5 detik, tak pernah
`Heard you, listening...`, tak pernah STT/LLM/TTS.

Penyebabnya **3 lapis bug yang menumpuk** di jalur VAD. Tiap sesi sebelumnya cuma
mengupas 1 lapisan, lalu mengira beres → bug "balik lagi". Yang akhirnya bikin kelar:
betulkan **ukuran window Silero (256, bukan 512)** + tambah **RMS fallback** sebagai
jaring pengaman.

---

## Gejala (cara mengenali bug ini kalau muncul lagi)

- `shift+alt+space` → ngomong → orb di bubble membesar (artinya audio level/RMS jalan).
- Terminal: `Listening (conversation)...` → `Still listening...` berulang, **tanpa**
  `Heard you, listening...`.
- Tidak ada `[Debug] STT/LLM/TTS`, tidak ada balasan `Verse: ...`.
- PTT (`alt+space`) tetap normal → ini petunjuk kunci: **masalahnya di VAD, bukan di
  STT/LLM/TTS**, karena PTT tidak lewat VAD (kirim seluruh rekaman langsung ke Whisper).

---

## Akar masalah (3 lapis, harus dibetulkan semua)

### Lapis 1 — Toggle dipanggil dari thread yang salah
`on_conversation_toggle` dipicu callback `pynput` yang **bukan** di asyncio loop.
`asyncio.get_running_loop()` gagal → loop `None` → VAD task tak pernah dibuat.
**Fix:** jadwalkan via `asyncio.run_coroutine_threadsafe(coro, loop)`.

### Lapis 2 — Blok device bukan kelipatan window → semua frame di-drop
Mic default = `MacBook Pro Microphone @ 48000 Hz`; recorder minta 16000 Hz →
PortAudio resample → ukuran blok callback **sering bukan persis** ukuran window.
`_run_vad_loop` lama nge-drop tiap blok yang ukurannya tidak pas (`continue`) →
`process_frame` tak pernah dipanggil → tak pernah ENDED/TIMEOUT.
**Fix:** rolling buffer (`np.concatenate` + slice) untuk memotong stream jadi frame
ukuran-tetap, apa pun ukuran blok device.

### Lapis 3 (DECISIVE) — Ukuran window Silero salah: 256, bukan 512
Model `~/.verse/models/silero_vad.onnx` yang terunduh **mengharap window 256 sampel
(16ms @ 16kHz)**, bukan 512. Memberi 512 sampel **jalan tanpa error** tapi
mengembalikan prob ~0 untuk SEMUA input → VAD buta total → selalu TIMEOUT.

Bukti empiris (speech 16kHz bersih dibuat via `say --data-format=LEI16@16000`,
dilewatkan langsung ke ONNX session):

| window | speech | silence |
|--------|--------|---------|
| **256** | max **0.996**, mean 0.59, 66% frame >0.5 | max 0.029, 0% >0.5 |
| 512 (dipakai app) | max 0.068, 0% >0.5 | max 0.001 |
| 768/1024/1536 | LSTM shape **ERROR** | — |

Diskriminasi sehat di 256 → threshold `start=0.55 / end=0.35` **tetap pas**, yang
salah cuma ukuran window.
**Fix:** konstanta `VAD_WINDOW_SAMPLES = 256`, `VAD_FRAME_MS = 16` di `vad.py`; guard
`predict()` jadi `!= VAD_WINDOW_SAMPLES`; `_frame_ms = 16`. Semua durasi berbasis ms
(`speech_start_ms`, `end_silence_ms`, `min/max_utterance_ms`, `pre_roll_ms`) otomatis
benar karena dibagi `_frame_ms`.

---

## Solusi final (yang sekarang ada di kode)

1. **Window 256 + frame 16ms** (`backend/verse/audio/vad.py`) — primary path Silero
   sekarang benar-benar mendeteksi speech.
2. **Reframe rolling-buffer** (`backend/verse/orchestrator.py::_run_vad_loop`) — slice
   per `VAD_WINDOW_SAMPLES`, `duration_ms *= VAD_FRAME_MS`. Recorder `blocksize=512`
   dibiarkan; reframe yang menangani.
3. **RMS fallback** (Codex, `verse-4dt`) — jaring pengaman: kalau Silero tetap WAITING
   tapi RMS mic bertahan di atas ambang, fallback "arm", endpoint saat RMS senyap,
   lalu proses utterance. Config baru di `VADConfig`: `rms_fallback_enabled=True`,
   `rms_start_level=0.03`, `rms_end_level=0.02`. Event observability:
   `rms_speech_started/ended/discarded`. Diagnostics timeout:
   `max_probability/max_rms_level/rms_fallback_armed`.
4. **Observability** — print `Listening (conversation)...`, `Heard you, listening...`,
   `Still listening...`, plus WebSocket pipeline events.
5. **PTT one-shot vs toggle kontinu** dipisah; `_auto_timeout` re-arm saat
   `conversation_mode_active`; auto-deactivate saat window blur.

---

## Kenapa bug ini berulang (anti-pattern yang harus dihindari)

1. **Berhenti di lapisan pertama.** Tiap sesi membetulkan 1 lapis (threading, lalu
   reframe) dan langsung deklarasi "fixed" tanpa verifikasi live → lapis berikutnya
   tetap memblokir. **Bug berlapis butuh diuji sampai end-to-end benar-benar jalan.**
2. **Percaya unit test hijau = fitur jalan.** Test lama selalu menyuapi frame 512
   sempurna, jadi lolos meski produksi buta. Test tidak mereproduksi kondisi mic asli
   (48kHz resample, window salah).
3. **Asumsi "512 itu standar Silero".** Build model yang terunduh ternyata varian 256.
   API yang "jalan tanpa error tapi salah diam-diam" (silent wrong) bikin susah dilacak.
4. **Tidak ada diagnostic yang memisahkan jalur.** Sebelum ada print/observability,
   "terminal gada apa apa" tak bisa dibedakan: VAD buta? loop mati? thread salah?

---

## Guardrail biar tidak terulang

- [ ] **Jangan ubah `VAD_WINDOW_SAMPLES` jadi 512** tanpa mengganti file model. Kalau
      `predict()` tiba-tiba return ~0 untuk semua input, **cek ukuran window dulu**,
      bukan threshold.
- [ ] **Jangan hapus reframe rolling-buffer** di `_run_vad_loop`. Mic 48kHz resample
      tidak menjamin ukuran blok = window.
- [ ] **Jangan hapus RMS fallback** (`rms_fallback_enabled`). Itu jaring pengaman kalau
      Silero gagal di mic/lingkungan tertentu.
- [ ] **Verifikasi LIVE wajib** sebelum tutup issue conversation mode — unit test hijau
      TIDAK cukup. Harus dengar `Heard you, listening...` di terminal dengan mic asli.
- [ ] Saat debugging "VAD tak merespons", **selalu cek PTT dulu**: kalau PTT jalan,
      masalahnya di VAD path, bukan STT/LLM/TTS.

---

## Cara verifikasi cepat

**1. Diagnostic model (tanpa mic) — buktikan Silero hidup di window 256:**
```bash
cd backend
TMP=$(mktemp).wav; say -o "$TMP" --data-format=LEI16@16000 "Halo Verse putar lagu jazz"
poetry run python -c "import soundfile as sf,numpy as np; from verse.audio.vad import SileroVADManager,VAD_WINDOW_SAMPLES as W; \
d,_=sf.read('$TMP',dtype='float32'); d=d[:,0] if d.ndim>1 else d; m=SileroVADManager(); \
p=[m.predict(d[i:i+W]) for i in range(0,len(d)-W,W)]; print('max_prob',round(max(p),3))"; rm -f "$TMP"
# Harus: max_prob > 0.9   (kalau ~0.07 -> window/model salah lagi)
```

**2. Unit test:**
```bash
cd backend && poetry run python -m pytest -q   # harus hijau
```

**3. Live (wajib):**
```bash
cd backend && poetry run python -m verse.main
# shift+alt+space -> ngomong -> diam ~1.2s
# Harapan: "Heard you, listening..." -> STT/LLM/TTS -> "Verse: ..." -> dengar lagi
# TIDAK lagi spam "Still listening..."
# alt+space -> PTT one-shot, 1 jawaban -> idle
```

---

## File kunci
- `backend/verse/audio/vad.py` — `VAD_WINDOW_SAMPLES`, `VAD_FRAME_MS`, guard `predict()`, state machine.
- `backend/verse/orchestrator.py` — `_run_vad_loop` (reframe + RMS fallback), `_auto_timeout`.
- `backend/verse/config.py` — `VADConfig` (threshold + `rms_fallback_*`).
- `backend/verse/main.py` — toggle hotkey via `run_coroutine_threadsafe`.
