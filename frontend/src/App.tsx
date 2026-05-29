import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
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
  const { connectionStatus, lastState } = useWebSocket();

  useEffect(() => {
    if (import.meta.env.DEV) {
      window.__VERSE_WINDOW__ = {
        triggerPress: () => {
          invoke("mock_hotkey_press").catch(console.error);
        },
        triggerRelease: () => {
          invoke("mock_hotkey_release").catch(console.error);
        },
      };
    }
    return () => {
      if (import.meta.env.DEV) {
        delete window.__VERSE_WINDOW__;
      }
    };
  }, []);

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
