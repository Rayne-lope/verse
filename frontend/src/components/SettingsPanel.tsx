import { useState } from "react";
import ReactDOM from "react-dom";
import type { ApiKeyStatus } from "../types/ws";
import { useWebSocket } from "../hooks/useWebSocket";
import { getIslandCalibration, setIslandCalibration } from "../utils/calibration";
import "./SettingsPanel.css";

type Section = "API Keys" | "Voice" | "STT" | "LLM" | "Hotkeys" | "Always-On" | "Memory" | "Calibration";
const SECTIONS: Section[] = ["API Keys", "Voice", "STT", "LLM", "Hotkeys", "Always-On", "Memory"];

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: Props) {
  const [activeSection, setActiveSection] = useState<Section>("API Keys");

  function handleBackdrop(e: React.MouseEvent) {
    if (e.target === e.currentTarget) onClose();
  }

  return ReactDOM.createPortal(
    <div
      className="settings-overlay"
      data-open={open ? "true" : "false"}
      onClick={handleBackdrop}
    >
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <span className="settings-title">Settings</span>
          <button className="settings-close" onClick={onClose} aria-label="Close settings">
            ×
          </button>
        </div>

        <nav className="settings-nav">
          {SECTIONS.map((s) => (
            <button
              key={s}
              className="settings-nav-btn"
              data-active={activeSection === s ? "true" : "false"}
              onClick={() => setActiveSection(s)}
            >
              {s}
            </button>
          ))}
        </nav>

        <div className="settings-content">
          {activeSection === "API Keys" && <ApiKeysSection />}
          {activeSection === "Voice" && <VoiceSection />}
          {activeSection === "STT" && <STTSection />}
          {activeSection === "LLM" && <LLMSection />}
          {activeSection === "Hotkeys" && <HotkeysSection />}
          {activeSection === "Always-On" && <AlwaysOnSection />}
          {activeSection === "Memory" && <MemorySection />}
          {activeSection === "Calibration" && <CalibrationSection />}
        </div>
      </div>
    </div>,
    document.body
  );
}

function ApiKeysSection() {
  const { apiKeys, send } = useWebSocket();

  const keys: Array<{ name: keyof ApiKeyStatus; label: string; placeholder: string }> = [
    { name: "groq", label: "Groq (STT)", placeholder: "gsk_..." },
    { name: "deepseek", label: "DeepSeek (LLM)", placeholder: "sk-..." },
    { name: "gemini", label: "Gemini (LLM/TTS)", placeholder: "AIza..." },
    { name: "brave", label: "Brave Search", placeholder: "BSA..." },
    { name: "spotify", label: "Spotify Client ID", placeholder: "client id..." },
    { name: "picovoice", label: "Picovoice (wake word)", placeholder: "AccessKey..." },
  ];

  return (
    <>
      <p className="settings-section-hint">
        API keys are stored securely in macOS Keychain. Keys already set are shown with a status badge.
      </p>
      {keys.map(({ name, label, placeholder }) => (
        <ApiKeyRow
          key={name}
          label={label}
          isSet={apiKeys ? apiKeys[name] : false}
          placeholder={placeholder}
          onSave={(value) => send({ type: "set_api_key", key_name: name, value })}
        />
      ))}
    </>
  );
}

function ApiKeyRow({
  label,
  isSet,
  placeholder,
  onSave,
}: {
  label: string;
  isSet: boolean;
  placeholder: string;
  onSave: (v: string) => void;
}) {
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [editing, setEditing] = useState(false);

  function handleBlur() {
    if (value.trim()) {
      onSave(value.trim());
      setValue("");
      setEditing(false);
    }
  }

  return (
    <div className="settings-row">
      <span className="settings-label">{label}</span>
      <div className="settings-row-right">
        {!editing && isSet ? (
          <>
            <span className="settings-key-status" data-set="true">set</span>
            <button
              className="settings-pw-toggle"
              style={{ position: "static", fontSize: "11px", color: "oklch(55% 0 0)" }}
              onClick={() => setEditing(true)}
            >
              change
            </button>
          </>
        ) : (
          <>
            {!isSet && (
              <span className="settings-key-status" data-set="false">not set</span>
            )}
            <div className="settings-pw-wrap">
              <input
                className="settings-input"
                type={visible ? "text" : "password"}
                placeholder={placeholder}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onBlur={handleBlur}
                onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
                autoFocus={editing}
                data-1p-ignore
                data-lpignore="true"
              />
              <button
                className="settings-pw-toggle"
                onClick={() => setVisible((v) => !v)}
                tabIndex={-1}
                type="button"
              >
                {visible ? "hide" : "show"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function VoiceSection() {
  const { config, send } = useWebSocket();
  if (!config) return <p className="settings-section-hint">Connecting to backend…</p>;

  const { tts } = config;

  return (
    <>
      <div className="settings-row">
        <span className="settings-label">Provider</span>
        <select
          className="settings-select"
          value={tts.provider}
          onChange={(e) => send({ type: "update_config", section: "tts", key: "provider", value: e.target.value })}
        >
          <option value="edge-tts">Edge TTS (free)</option>
          <option value="google">Google TTS (free)</option>
          <option value="gemini">Gemini TTS</option>
          <option value="macos">macOS Say (offline)</option>
          <option value="openai">OpenAI TTS</option>
          <option value="elevenlabs">ElevenLabs</option>
        </select>
      </div>

      <div className="settings-row">
        <span className="settings-label">Voice ID</span>
        <input
          key={tts.voice_id}
          className="settings-input"
          type="text"
          defaultValue={tts.voice_id}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== tts.voice_id) send({ type: "update_config", section: "tts", key: "voice_id", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Model</span>
        <input
          key={tts.model}
          className="settings-input settings-input-wide"
          type="text"
          list="gemini-tts-models"
          defaultValue={tts.model}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== tts.model) send({ type: "update_config", section: "tts", key: "model", value: v });
          }}
        />
        <datalist id="gemini-tts-models">
          <option value="gemini-3.1-flash-tts" />
          <option value="gemini-2.5-flash-tts" />
        </datalist>
      </div>

      <div className="settings-row">
        <span className="settings-label">Base URL</span>
        <input
          key={tts.base_url}
          className="settings-input settings-input-wide"
          type="text"
          defaultValue={tts.base_url}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== tts.base_url) send({ type: "update_config", section: "tts", key: "base_url", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Speed</span>
        <input
          key={tts.speed}
          className="settings-input"
          type="number"
          min={0.5}
          max={3.0}
          step={0.1}
          defaultValue={tts.speed}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v) && v !== tts.speed) send({ type: "update_config", section: "tts", key: "speed", value: v });
          }}
        />
      </div>
    </>
  );
}

function STTSection() {
  const { config, send } = useWebSocket();
  if (!config) return <p className="settings-section-hint">Connecting to backend…</p>;

  return (
    <div className="settings-row">
      <span className="settings-label">Language</span>
      <div>
        <input
          className="settings-input"
          type="text"
          defaultValue={config.stt.language}
          placeholder="auto / en / id / ja"
          onBlur={(e) => {
            const v = e.target.value.trim() || "auto";
            if (v !== config.stt.language) send({ type: "update_config", section: "stt", key: "language", value: v });
          }}
        />
        <p className="settings-hint">Use BCP-47 code or "auto" for auto-detect.</p>
      </div>
    </div>
  );
}

function LLMSection() {
  const { config, send } = useWebSocket();
  if (!config) return <p className="settings-section-hint">Connecting to backend…</p>;

  const { llm } = config;

  return (
    <>
      <div className="settings-row">
        <span className="settings-label">Provider</span>
        <select
          className="settings-select"
          value={llm.provider}
          onChange={(e) => send({ type: "update_config", section: "llm", key: "provider", value: e.target.value })}
        >
          <option value="deepseek">DeepSeek</option>
          <option value="openai">OpenAI</option>
          <option value="claude">Claude</option>
          <option value="gemini">Gemini</option>
        </select>
      </div>

      <div className="settings-row">
        <span className="settings-label">Model</span>
        <input
          className="settings-input"
          type="text"
          defaultValue={llm.model}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== llm.model) send({ type: "update_config", section: "llm", key: "model", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Base URL</span>
        <input
          className="settings-input"
          type="text"
          defaultValue={llm.base_url}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== llm.base_url) send({ type: "update_config", section: "llm", key: "base_url", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Temperature</span>
        <input
          className="settings-input"
          type="number"
          min={0}
          max={2}
          step={0.05}
          defaultValue={llm.temperature}
          onBlur={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v) && v !== llm.temperature) send({ type: "update_config", section: "llm", key: "temperature", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">History</span>
        <input
          className="settings-input"
          type="number"
          min={1}
          max={50}
          step={1}
          defaultValue={llm.max_history}
          onBlur={(e) => {
            const v = parseInt(e.target.value, 10);
            if (!isNaN(v) && v !== llm.max_history) send({ type: "update_config", section: "llm", key: "max_history", value: v });
          }}
        />
      </div>
    </>
  );
}

function HotkeysSection() {
  const { config } = useWebSocket();
  if (!config) return <p className="settings-section-hint">Connecting to backend…</p>;

  return (
    <>
      <div className="settings-row">
        <span className="settings-label">Push-to-talk</span>
        <kbd className="settings-kbd">{config.hotkey.trigger}</kbd>
      </div>
      <p className="settings-hint" style={{ marginTop: 12 }}>
        To change hotkeys, edit <code style={{ fontFamily: "ui-monospace, monospace", fontSize: 11 }}>~/.verse/config.toml</code> and restart.
      </p>
    </>
  );
}

function AlwaysOnSection() {
  const { config, apiKeys, send } = useWebSocket();
  if (!config) return <p className="settings-section-hint">Connecting to backend…</p>;

  const alwaysOn = config.always_on;

  return (
    <>
      <p className="settings-section-hint">
        Always-On keeps a tiny wake-word listener active while Verse is idle. Restart Verse after changing these values.
      </p>

      <div className="settings-row">
        <span className="settings-label">Enabled</span>
        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={alwaysOn.enabled}
            onChange={(e) => send({ type: "update_config", section: "always_on", key: "enabled", value: e.target.checked })}
          />
          <span className="settings-toggle-track" />
          <span className="settings-toggle-thumb" />
        </label>
      </div>

      <div className="settings-row">
        <span className="settings-label">AccessKey</span>
        <span className="settings-key-status" data-set={apiKeys?.picovoice ? "true" : "false"}>
          {apiKeys?.picovoice ? "set" : "not set"}
        </span>
      </div>

      <div className="settings-row">
        <span className="settings-label">Wake file</span>
        <input
          className="settings-input"
          type="text"
          defaultValue={alwaysOn.keyword_path}
          placeholder="~/.verse/wake/hey_verse.ppn"
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v !== alwaysOn.keyword_path) send({ type: "update_config", section: "always_on", key: "keyword_path", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Fallback keyword</span>
        <input
          className="settings-input"
          type="text"
          defaultValue={alwaysOn.keyword}
          placeholder="picovoice"
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v !== alwaysOn.keyword) send({ type: "update_config", section: "always_on", key: "keyword", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Sensitivity</span>
        <input
          className="settings-input"
          type="number"
          min={0}
          max={1}
          step={0.05}
          defaultValue={alwaysOn.sensitivity}
          onBlur={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v) && v !== alwaysOn.sensitivity) {
              send({ type: "update_config", section: "always_on", key: "sensitivity", value: v });
            }
          }}
        />
      </div>
    </>
  );
}

function MemorySection() {
  const { config, send } = useWebSocket();
  if (!config) return <p className="settings-section-hint">Connecting to backend…</p>;

  const { memory } = config;

  return (
    <>
      <div className="settings-row">
        <span className="settings-label">Enabled</span>
        <label className="settings-toggle">
          <input
            type="checkbox"
            checked={memory.enabled}
            onChange={(e) => send({ type: "update_config", section: "memory", key: "enabled", value: e.target.checked })}
          />
          <span className="settings-toggle-track" />
          <span className="settings-toggle-thumb" />
        </label>
      </div>

      <div className="settings-row">
        <span className="settings-label">Max facts</span>
        <input
          className="settings-input"
          type="number"
          min={10}
          max={200}
          step={5}
          defaultValue={memory.max_facts}
          onBlur={(e) => {
            const v = parseInt(e.target.value, 10);
            if (!isNaN(v) && v !== memory.max_facts) send({ type: "update_config", section: "memory", key: "max_facts", value: v });
          }}
        />
      </div>
    </>
  );
}

function CalibrationSection() {
  const [cal, setCal] = useState(getIslandCalibration);

  const update = (key: keyof typeof cal, val: number) => {
    const next = { ...cal, [key]: val };
    setCal(next);
    setIslandCalibration(next);
  };

  return (
    <>
      <p className="settings-section-hint">
        Tune the Dynamic Island's scale, position, and safety padding to align perfectly with your MacBook's physical notch in real time.
      </p>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">X Offset (px)</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.xOffset}px</span>
        </div>
        <input
          type="range"
          min={-50}
          max={50}
          step={1}
          value={cal.xOffset}
          onChange={(e) => update("xOffset", parseInt(e.target.value, 10))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">Y Offset (px)</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.yOffset}px</span>
        </div>
        <input
          type="range"
          min={-20}
          max={20}
          step={1}
          value={cal.yOffset}
          onChange={(e) => update("yOffset", parseInt(e.target.value, 10))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">Width Scale</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.widthScale.toFixed(2)}x</span>
        </div>
        <input
          type="range"
          min={0.8}
          max={1.5}
          step={0.01}
          value={cal.widthScale}
          onChange={(e) => update("widthScale", parseFloat(e.target.value))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">Height Scale</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.heightScale.toFixed(2)}x</span>
        </div>
        <input
          type="range"
          min={0.8}
          max={1.5}
          step={0.01}
          value={cal.heightScale}
          onChange={(e) => update("heightScale", parseFloat(e.target.value))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">Attach Overlap (px)</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.attachOverlap}px</span>
        </div>
        <input
          type="range"
          min={-5}
          max={15}
          step={1}
          value={cal.attachOverlap}
          onChange={(e) => update("attachOverlap", parseInt(e.target.value, 10))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">Bottom Radius (px)</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.bottomRadius}px</span>
        </div>
        <input
          type="range"
          min={0}
          max={40}
          step={1}
          value={cal.bottomRadius}
          onChange={(e) => update("bottomRadius", parseInt(e.target.value, 10))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>

      <div className="settings-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="settings-label">Notch Safe Padding (px)</span>
          <span style={{ fontSize: "12px", color: "oklch(55% 0 0)" }}>{cal.notchSafePadding}px</span>
        </div>
        <input
          type="range"
          min={0}
          max={40}
          step={1}
          value={cal.notchSafePadding}
          onChange={(e) => update("notchSafePadding", parseInt(e.target.value, 10))}
          style={{ width: "100%", accentColor: "oklch(60% 0.15 250)" }}
        />
      </div>
    </>
  );
}
