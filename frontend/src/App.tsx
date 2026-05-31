import { useCallback, useEffect, useState } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { Bubble } from "./components/Bubble";
import { DynamicIsland } from "./components/DynamicIsland";
import { SettingsPanel } from "./components/SettingsPanel";
import { OnboardingFlow } from "./components/OnboardingFlow";
import { resizeAndPositionWidget, setFullscreen } from "./utils/window";
import { getIslandCalibration } from "./utils/calibration";
import "./App.css";

const WIDGET_W = 480;
const WIDGET_H = 280;
const SETTINGS_W = 480;
const SETTINGS_H = 560;
const ONBOARDING_W = 420;
const ONBOARDING_H = 540;

declare global {
  interface Window {
    __VERSE_WINDOW__?: {
      triggerRelease: () => void;
      triggerPress: () => void;
    };
  }
}

function App() {
  const { connectionStatus, lastState, micStatus, send, onboardingNeeded, transcript, assistantText } = useWebSocket();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [displayMode, setDisplayMode] = useState<"widget" | "canvas">(() => {
    const saved = localStorage.getItem("verse_display_mode");
    return saved === "canvas" ? "canvas" : "widget";
  });

  useEffect(() => {
    const handleCalibration = () => {
      const nextCal = getIslandCalibration();
      if (displayMode === "widget") {
        const w = settingsOpen ? SETTINGS_W : onboardingOpen ? ONBOARDING_W : WIDGET_W;
        const h = settingsOpen ? SETTINGS_H : onboardingOpen ? ONBOARDING_H : WIDGET_H;
        resizeAndPositionWidget(w, h, nextCal);
      }
    };
    window.addEventListener("verse_calibration_changed", handleCalibration);
    return () => window.removeEventListener("verse_calibration_changed", handleCalibration);
  }, [displayMode, settingsOpen, onboardingOpen]);

  const micActive = Boolean(micStatus?.active || lastState === "listening");
  const micMode = lastState === "listening" ? "recording" : micStatus?.mode ?? "off";

  const shrinkIfIdle = useCallback((exceptSettings: boolean, exceptOnboarding: boolean) => {
    setTimeout(() => {
      if (!exceptSettings && !exceptOnboarding) {
        resizeAndPositionWidget(WIDGET_W, WIDGET_H);
      }
    }, 240);
  }, []);

  const toggleDisplayMode = useCallback(async () => {
    const nextMode = displayMode === "widget" ? "canvas" : "widget";
    setDisplayMode(nextMode);
    localStorage.setItem("verse_display_mode", nextMode);

    await setFullscreen(nextMode === "canvas", WIDGET_W);
  }, [displayMode]);

  const handleOpenSettings = useCallback(() => {
    if (displayMode === "widget") {
      resizeAndPositionWidget(SETTINGS_W, SETTINGS_H);
    }
    setSettingsOpen(true);
  }, [displayMode]);

  const handleCloseSettings = useCallback(() => {
    setSettingsOpen(false);
    if (displayMode === "widget") {
      shrinkIfIdle(false, onboardingOpen);
    }
  }, [displayMode, onboardingOpen, shrinkIfIdle]);

  const handleOpenOnboarding = useCallback(() => {
    if (displayMode === "widget") {
      resizeAndPositionWidget(ONBOARDING_W, ONBOARDING_H);
    }
    setOnboardingOpen(true);
  }, [displayMode]);

  const handleCloseOnboarding = useCallback(() => {
    setOnboardingOpen(false);
    if (displayMode === "widget") {
      shrinkIfIdle(settingsOpen, false);
    }
  }, [displayMode, settingsOpen, shrinkIfIdle]);

  useEffect(() => {
    if (onboardingNeeded) handleOpenOnboarding();
  }, [onboardingNeeded, handleOpenOnboarding]);

  useEffect(() => {
    if (displayMode === "canvas") {
      setFullscreen(true, WIDGET_W);
    } else {
      // Ensure widget mode is properly locked on startup
      resizeAndPositionWidget(WIDGET_W, WIDGET_H);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (import.meta.env.DEV) {
      window.__VERSE_WINDOW__ = {
        triggerPress: () => {
          send({ type: "manual_trigger", action: "start_listening" });
        },
        triggerRelease: () => {
          send({ type: "manual_trigger", action: "stop_listening" });
        },
      };
    }
    return () => {
      if (import.meta.env.DEV) {
        delete window.__VERSE_WINDOW__;
      }
    };
  }, [send]);

  useEffect(() => {
    const handleBlur = () => {
      send({ type: "manual_trigger", action: "deactivate_conversation" });
    };
    window.addEventListener("blur", handleBlur);
    return () => {
      window.removeEventListener("blur", handleBlur);
    };
  }, [send]);

  return (
    <main
      className="shell-surface"
      data-display-mode={displayMode}
      data-state={lastState ?? "idle"}
    >
      <div className="window-drag-region" data-tauri-drag-region />

      {displayMode === "canvas" && (
        <header className="canvas-header">
          <div className="canvas-logo">
            <span className="logo-glow" />
            <span className="logo-text">VERSE</span>
          </div>
          <div className="canvas-controls">
            <button
              className="canvas-control-btn settings-btn"
              onClick={handleOpenSettings}
              title="Open Settings"
              aria-label="Open Settings"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </button>
            <button
              className="canvas-control-btn toggle-mode-btn"
              onClick={toggleDisplayMode}
              title="Shrink to Widget"
              aria-label="Shrink to Widget"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 14h6v6" />
                <path d="M20 10h-6V4" />
                <path d="M14 10l7-7" />
                <path d="M10 14l-7 7" />
              </svg>
            </button>
          </div>
        </header>
      )}

      {displayMode === "widget" && (
        <button
          className="display-mode-toggle"
          onClick={toggleDisplayMode}
          title="Expand to Canvas Mode"
          aria-label="Expand to Canvas Mode"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 3h6v6" />
            <path d="M9 21H3v-6" />
            <path d="M21 3l-7 7" />
            <path d="M3 21l7-7" />
          </svg>
        </button>
      )}

      {displayMode === "widget"
        ? <DynamicIsland onOpenSettings={handleOpenSettings} onOpenCanvas={toggleDisplayMode} />
        : <Bubble onOpenSettings={handleOpenSettings} />}

      {displayMode === "canvas" && (transcript || assistantText) && (
        <div className="canvas-subtitles">
          {transcript && (
            <div className="subtitle-line user-line">
              <span className="subtitle-icon user-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </span>
              <p className="subtitle-text">{transcript}</p>
            </div>
          )}
          {assistantText && (
            <div className="subtitle-line assistant-line">
              <span className="subtitle-icon assistant-icon">
                <span className="pulsing-dot" />
              </span>
              <p className="subtitle-text">{assistantText}</p>
            </div>
          )}
        </div>
      )}

      <div
        className="ws-status"
        data-status={connectionStatus}
        data-state={lastState ?? "none"}
        title={`WebSocket: ${connectionStatus}${lastState ? ` · ${lastState}` : ""}`}
      />
      
      <div
        className="privacy-indicator"
        data-active={micActive ? "true" : "false"}
        data-mode={micMode}
        title={micActive ? `Microphone active: ${micMode}` : "Microphone inactive"}
        aria-hidden="true"
      />

      <SettingsPanel open={settingsOpen} onClose={handleCloseSettings} />
      <OnboardingFlow open={onboardingOpen} onClose={handleCloseOnboarding} />
    </main>
  );
}

export default App;

