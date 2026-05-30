import { useEffect } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { Bubble } from "./components/Bubble";
import "./App.css";

declare global {
  interface Window {
    __VERSE_WINDOW__?: {
      triggerRelease: () => void;
      triggerPress: () => void;
    };
  }
}

function App() {
  const { connectionStatus, lastState, send } = useWebSocket();

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
      <Bubble />
      <div
        className="ws-status"
        data-status={connectionStatus}
        data-state={lastState ?? "none"}
        title={`WebSocket: ${connectionStatus}${lastState ? ` · ${lastState}` : ""}`}
      />
    </main>
  );
}

export default App;
