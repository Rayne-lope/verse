import { useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

declare global {
  interface Window {
    __VERSE_WINDOW__?: {
      show: () => Promise<void>;
      hide: () => Promise<void>;
      toggle: () => Promise<void>;
    };
  }
}

function App() {
  useEffect(() => {
    if (import.meta.env.DEV) {
      window.__VERSE_WINDOW__ = {
        show: () => invoke("show_verse_window"),
        hide: () => invoke("hide_verse_window"),
        toggle: () => invoke("toggle_verse_window"),
      };

      return () => {
        delete window.__VERSE_WINDOW__;
      };
    }
  }, []);

  return (
    <main className="shell-surface" data-tauri-drag-region>
      <div className="shell-anchor" aria-label="Verse floating shell" />
    </main>
  );
}

export default App;
