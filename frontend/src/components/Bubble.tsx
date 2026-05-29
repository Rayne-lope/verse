import { useWebSocket } from "../hooks/useWebSocket";
import { useAudioLevel } from "../hooks/useAudioLevel";
import "./Bubble.css";

export function Bubble() {
  const { lastState } = useWebSocket();
  const audioLevel = useAudioLevel();

  const state = lastState ?? "idle";

  // Calculate dynamic scale transformation based on audio level
  const showReactivity = state === "listening" || state === "speaking";
  const scale = showReactivity ? 1 + audioLevel * 0.45 : 1.0;

  return (
    <div className="bubble-container" data-tauri-drag-region>
      <div
        className="bubble-element"
        data-state={state}
        style={{
          transform: `scale(${scale})`,
        }}
        aria-label={`Verse state: ${state}`}
      />
    </div>
  );
}
