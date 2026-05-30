import { useRef } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { useAudioReactiveOrb } from "../hooks/useAudioReactiveOrb";
import { useMouseGaze } from "../hooks/useMouseGaze";
import { useSphereMode } from "../hooks/useSphereMode";
import { Eyes } from "./Eyes";
import "./Bubble.css";

export function Bubble() {
  const { lastState, audioLevel } = useWebSocket();
  const state = lastState ?? "idle";

  const orbRef = useRef<HTMLDivElement>(null);
  const active = state === "listening" || state === "speaking";
  useAudioReactiveOrb(orbRef, audioLevel, active);
  useMouseGaze(orbRef, state);
  useSphereMode(orbRef, state);

  return (
    <div className="bubble-stage" data-tauri-drag-region>
      <div ref={orbRef} className="orb" data-state={state} aria-label={`Verse state: ${state}`}>
        <div className="orb__aura" />
        <div className="orb__glow" />
        <div className="orb__body" />
        <div className="orb__sphere-sclera" />
        <div className="orb__iridescence" />
        <div className="orb__iridescence2" />
        <div className="orb__caustics" />
        <div className="orb__highlight" />
        <div className="orb__rim" />
        <div className="orb__sphere-eye" />
        <Eyes />
      </div>
    </div>
  );
}
