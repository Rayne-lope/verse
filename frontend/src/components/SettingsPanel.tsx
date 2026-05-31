import { useState } from "react";
import ReactDOM from "react-dom";
import type { ApiKeyStatus } from "../types/ws";
import { useWebSocket } from "../hooks/useWebSocket";
import "./SettingsPanel.css";

type Section = "API Keys" | "Voice" | "STT" | "LLM" | "Hotkeys" | "Always-On" | "Memory";
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
          <option value="macos">macOS Say (offline)</option>
          <option value="openai">OpenAI TTS</option>
          <option value="elevenlabs">ElevenLabs</option>
        </select>
      </div>

      <div className="settings-row">
        <span className="settings-label">Voice ID</span>
        <input
          className="settings-input"
          type="text"
          defaultValue={tts.voice_id}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== tts.voice_id) send({ type: "update_config", section: "tts", key: "voice_id", value: v });
          }}
        />
      </div>

      <div className="settings-row">
        <span className="settings-label">Speed</span>
        <input
          className="settings-input"
          type="number"
          min={0.5}
          max={3.0}
          step={0.1}
          defaultValue={tts.speed}
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
