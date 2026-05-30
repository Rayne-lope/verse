import { useRef } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { useAudioReactiveOrb } from "../hooks/useAudioReactiveOrb";
import { Eyes } from "./Eyes";
import "./Bubble.css";

export function Bubble() {
  const { lastState, audioLevel } = useWebSocket();
  const state = lastState ?? "idle";

  const orbRef = useRef<HTMLDivElement>(null);
  const active = state === "listening" || state === "speaking";
  useAudioReactiveOrb(orbRef, audioLevel, active);

  return (
    <div className="bubble-stage" data-tauri-drag-region>
      <div ref={orbRef} className="orb" data-state={state} aria-label={`Verse state: ${state}`}>
        <div className="orb__glow" />
        <div className="orb__body" />
        <div className="orb__iridescence" />
        <div className="orb__highlight" />
        <div className="orb__rim" />
        <Eyes />
      </div>
    </div>
  );
}
