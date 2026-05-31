import { useState } from "react";
import ReactDOM from "react-dom";
import { useWebSocket } from "../hooks/useWebSocket";
import "./OnboardingFlow.css";

type Step = "welcome" | "groq" | "deepseek" | "brave" | "done";
const STEPS: Step[] = ["welcome", "groq", "deepseek", "brave", "done"];

interface Props {
  open: boolean;
  onClose: () => void;
}

export function OnboardingFlow({ open, onClose }: Props) {
  const { send } = useWebSocket();
  const [step, setStep] = useState<Step>("welcome");
  const [groqKey, setGroqKey] = useState("");
  const [deepseekKey, setDeepseekKey] = useState("");
  const [braveKey, setBraveKey] = useState("");

  const stepIndex = STEPS.indexOf(step);

  function saveAndAdvance(keyName: string | null, value: string, next: Step) {
    if (keyName && value.trim()) {
      send({ type: "set_api_key", key_name: keyName, value: value.trim() });
    }
    setStep(next);
  }

  function handleComplete() {
    localStorage.setItem("verse.onboarded", "dismissed");
    onClose();
  }

  function handleDismiss() {
    localStorage.setItem("verse.onboarded", "dismissed");
    onClose();
  }

  return ReactDOM.createPortal(
    <div className="onboarding-overlay" data-open={open ? "true" : "false"}>
      <div className="onboarding-panel">
        <div className="onboarding-viewport">
          <div
            className="onboarding-track"
            style={{ transform: `translateX(-${stepIndex * 100}%)` }}
          >
            {/* Welcome */}
            <div className="onboarding-step">
              <span className="onboarding-icon">✦</span>
              <h2 className="onboarding-step-title">Welcome to Verse</h2>
              <p className="onboarding-step-desc">
                Your voice assistant needs a couple of API keys to work. This takes about a minute — keys are stored securely in macOS Keychain.
              </p>
              <div className="onboarding-footer">
                <button className="onboarding-btn-skip" onClick={handleDismiss}>
                  Skip for now
                </button>
                <button className="onboarding-btn-next" onClick={() => setStep("groq")}>
                  Get started →
                </button>
              </div>
            </div>

            {/* Groq */}
            <div className="onboarding-step">
              <span className="onboarding-icon">🎙</span>
              <h2 className="onboarding-step-title">Speech Recognition</h2>
              <p className="onboarding-step-desc">
                Verse uses Groq's Whisper API to transcribe your voice. It's fast and free to start.
              </p>
              <div className="onboarding-input-wrap">
                <KeyInput
                  value={groqKey}
                  onChange={setGroqKey}
                  placeholder="gsk_..."
                />
              </div>
              <p className="onboarding-input-hint">Get your key at console.groq.com → API Keys</p>
              <div className="onboarding-footer">
                <button className="onboarding-btn-skip" onClick={() => setStep("deepseek")}>
                  Skip
                </button>
                <button
                  className="onboarding-btn-next"
                  onClick={() => saveAndAdvance("groq", groqKey, "deepseek")}
                >
                  Next →
                </button>
              </div>
            </div>

            {/* DeepSeek */}
            <div className="onboarding-step">
              <span className="onboarding-icon">🧠</span>
              <h2 className="onboarding-step-title">Language Model</h2>
              <p className="onboarding-step-desc">
                DeepSeek powers Verse's understanding. It's affordable and capable for voice interactions.
              </p>
              <div className="onboarding-input-wrap">
                <KeyInput
                  value={deepseekKey}
                  onChange={setDeepseekKey}
                  placeholder="sk-..."
                />
              </div>
              <p className="onboarding-input-hint">Get your key at platform.deepseek.com → API Keys</p>
              <div className="onboarding-footer">
                <button className="onboarding-btn-skip" onClick={() => setStep("brave")}>
                  Skip
                </button>
                <button
                  className="onboarding-btn-next"
                  onClick={() => saveAndAdvance("deepseek", deepseekKey, "brave")}
                >
                  Next →
                </button>
              </div>
            </div>

            {/* Brave Search */}
            <div className="onboarding-step">
              <span className="onboarding-icon">🔍</span>
              <h2 className="onboarding-step-title">Web Search (Optional)</h2>
              <p className="onboarding-step-desc">
                Optionally add a Brave Search key to enable web search. You can skip this and add it later in Settings.
              </p>
              <div className="onboarding-input-wrap">
                <KeyInput
                  value={braveKey}
                  onChange={setBraveKey}
                  placeholder="BSA..."
                />
              </div>
              <p className="onboarding-input-hint">Get your key at api.search.brave.com</p>
              <div className="onboarding-footer">
                <button className="onboarding-btn-skip" onClick={() => setStep("done")}>
                  Skip
                </button>
                <button
                  className="onboarding-btn-next"
                  onClick={() => saveAndAdvance("brave", braveKey, "done")}
                >
                  Next →
                </button>
              </div>
            </div>

            {/* Done */}
            <div className="onboarding-step">
              <div className="onboarding-done-icon">✓</div>
              <h2 className="onboarding-step-title">You're all set!</h2>
              <p className="onboarding-step-desc">
                Click the orb once to start listening, then click it again to stop. You can still use <strong style={{ color: "oklch(78% 0.06 255)" }}>Alt+Space</strong> and update settings anytime by right-clicking the orb.
              </p>
              <div className="onboarding-footer">
                <span />
                <button className="onboarding-btn-next" onClick={handleComplete}>
                  Start using Verse
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="onboarding-dots">
          {STEPS.map((s, i) => (
            <div
              key={s}
              className="onboarding-dot"
              data-active={stepIndex === i ? "true" : "false"}
            />
          ))}
        </div>
      </div>
    </div>,
    document.body
  );
}

function KeyInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <>
      <input
        className="onboarding-input"
        type={visible ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        data-1p-ignore
        data-lpignore="true"
      />
      <button
        className="onboarding-input-toggle"
        type="button"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
      >
        {visible ? "hide" : "show"}
      </button>
    </>
  );
}
