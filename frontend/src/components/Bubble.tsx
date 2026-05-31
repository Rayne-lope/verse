import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "../hooks/useWebSocket";
import { useAudioReactiveOrb } from "../hooks/useAudioReactiveOrb";
import { useMouseGaze } from "../hooks/useMouseGaze";
import { useSphereMode } from "../hooks/useSphereMode";
import { useSleepMode } from "../hooks/useSleepMode";
import { Eyes } from "./Eyes";
import "./Bubble.css";

interface BubbleProps {
  onOpenSettings: () => void;
}

const OPTIMISTIC_LISTENING_MS = 1200;

export function Bubble({ onOpenSettings }: BubbleProps) {
  const { connectionStatus, lastState, audioLevel, send } = useWebSocket();
  const state = lastState ?? "idle";
  const [activation, setActivation] = useState<"listening" | null>(null);

  const orbRef = useRef<HTMLDivElement>(null);
  const activationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = state === "listening" || state === "speaking";
  const canToggleConversation = connectionStatus === "open";
  useAudioReactiveOrb(orbRef, audioLevel, active);
  useMouseGaze(orbRef, state);
  useSphereMode(orbRef, state);
  useSleepMode(orbRef, state);

  const clearActivation = useCallback(() => {
    if (activationTimerRef.current !== null) {
      clearTimeout(activationTimerRef.current);
      activationTimerRef.current = null;
    }
    setActivation(null);
  }, []);

  useEffect(() => {
    if (state !== "idle") {
      clearActivation();
    }
  }, [state, clearActivation]);

  useEffect(() => {
    return () => {
      if (activationTimerRef.current !== null) {
        clearTimeout(activationTimerRef.current);
        activationTimerRef.current = null;
      }
    };
  }, []);

  const handleBubbleClick = useCallback(() => {
    if (!canToggleConversation) return;

    send({ type: "manual_trigger", action: "toggle_conversation" });

    if (state === "idle") {
      setActivation("listening");
      if (activationTimerRef.current !== null) {
        clearTimeout(activationTimerRef.current);
      }
      activationTimerRef.current = setTimeout(() => {
        activationTimerRef.current = null;
        setActivation(null);
      }, OPTIMISTIC_LISTENING_MS);
    } else {
      clearActivation();
    }
  }, [canToggleConversation, clearActivation, send, state]);

  return (
    <div
      className="bubble-stage"
      data-tauri-drag-region
      onContextMenu={(e) => { e.preventDefault(); onOpenSettings(); }}
    >
      <div
        ref={orbRef}
        className="orb"
        data-state={state}
        data-clickable={canToggleConversation ? "" : undefined}
        data-activation={activation ?? undefined}
        role="button"
        tabIndex={canToggleConversation ? 0 : -1}
        aria-disabled={!canToggleConversation}
        aria-label={`Verse state: ${state}`}
        onClick={handleBubbleClick}
      >
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
        <div className="orb__zzz" aria-hidden="true">
          <span>z</span>
          <span>z</span>
          <span>Z</span>
        </div>
      </div>
    </div>
  );
}
