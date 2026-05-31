import { useCallback, useEffect, useState } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { Bubble } from "./components/Bubble";
import { SettingsPanel } from "./components/SettingsPanel";
import { OnboardingFlow } from "./components/OnboardingFlow";
import { resizeWindow } from "./utils/window";
import "./App.css";

const BUBBLE_W = 180;
const BUBBLE_H = 180;
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
  const { connectionStatus, lastState, send, onboardingNeeded } = useWebSocket();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  const shrinkIfIdle = useCallback((exceptSettings: boolean, exceptOnboarding: boolean) => {
    setTimeout(() => {
      if (!exceptSettings && !exceptOnboarding) {
        resizeWindow(BUBBLE_W, BUBBLE_H);
      }
    }, 240);
  }, []);

  const handleOpenSettings = useCallback(() => {
    resizeWindow(SETTINGS_W, SETTINGS_H);
    setSettingsOpen(true);
  }, []);

  const handleCloseSettings = useCallback(() => {
    setSettingsOpen(false);
    shrinkIfIdle(false, onboardingOpen);
  }, [onboardingOpen, shrinkIfIdle]);

  const handleOpenOnboarding = useCallback(() => {
    resizeWindow(ONBOARDING_W, ONBOARDING_H);
    setOnboardingOpen(true);
  }, []);

  const handleCloseOnboarding = useCallback(() => {
    setOnboardingOpen(false);
    shrinkIfIdle(settingsOpen, false);
  }, [settingsOpen, shrinkIfIdle]);

  useEffect(() => {
    if (onboardingNeeded) handleOpenOnboarding();
  }, [onboardingNeeded, handleOpenOnboarding]);

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
    <main className="shell-surface" data-tauri-drag-region>
      <Bubble onOpenSettings={handleOpenSettings} />
      <div
        className="ws-status"
        data-status={connectionStatus}
        data-state={lastState ?? "none"}
        title={`WebSocket: ${connectionStatus}${lastState ? ` · ${lastState}` : ""}`}
      />
      <SettingsPanel open={settingsOpen} onClose={handleCloseSettings} />
      <OnboardingFlow open={onboardingOpen} onClose={handleCloseOnboarding} />
    </main>
  );
}

export default App;
