import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence, LayoutGroup } from "framer-motion";
import { useWebSocket } from "../hooks/useWebSocket";
import { useIslandMode } from "../hooks/useIslandMode";
import { useNotchGeometry } from "../hooks/useNotchGeometry";
import { ISLAND_SPRING, getShellSizes } from "./island-modes/motion";
import { CompactMode } from "./island-modes/CompactMode";
import { ListeningMode } from "./island-modes/ListeningMode";
import { SpeakingMode } from "./island-modes/SpeakingMode";
import { ExpandedMode } from "./island-modes/ExpandedMode";
import { getIslandCalibration } from "../utils/calibration";
import "./DynamicIsland.css";

interface DynamicIslandProps {
  onOpenSettings: () => void;
  onOpenCanvas?: () => void;
}

const OPTIMISTIC_LISTENING_MS = 1200;

export function DynamicIsland({ onOpenSettings, onOpenCanvas }: DynamicIslandProps) {
  const { connectionStatus, lastState, audioLevel, transcript, assistantText, micStatus, send } = useWebSocket();
  const state = lastState ?? "idle";
  const connected = connectionStatus === "open";

  const [optimisticListening, setOptimisticListening] = useState(false);
  const optimisticTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { mode, expand, collapse, pokeExpanded, isExpanded } = useIslandMode({
    state,
    optimisticListening,
  });

  const [calibration, setCalibration] = useState(getIslandCalibration);

  useEffect(() => {
    const handleCalibration = () => {
      setCalibration(getIslandCalibration());
    };
    window.addEventListener("verse_calibration_changed", handleCalibration);
    return () => window.removeEventListener("verse_calibration_changed", handleCalibration);
  }, []);

  const notch = useNotchGeometry();
  const isMac = useMemo(() => {
    return typeof window !== "undefined" && navigator.userAgent.includes("Mac");
  }, []);
  const hasNotch = Boolean(notch) || isMac;
  const notchHeight = hasNotch ? (notch?.height && notch.height > 0 ? notch.height : 32) : 0;
  const shellSizes = useMemo(() => getShellSizes(notch, calibration), [notch, calibration]);
  const shellSize = shellSizes[mode];

  const notchSafeWidth = useMemo(() => {
    return hasNotch
      ? (notch?.width && notch.width > 0 ? notch.width : 190) * calibration.widthScale + calibration.notchSafePadding * 2
      : 0;
  }, [notch, hasNotch, calibration]);

  // Clear optimistic flag once backend confirms a non-idle state
  useEffect(() => {
    if (state !== "idle" && optimisticTimerRef.current !== null) {
      clearTimeout(optimisticTimerRef.current);
      optimisticTimerRef.current = null;
      setOptimisticListening(false);
    }
  }, [state]);

  useEffect(() => () => {
    if (optimisticTimerRef.current !== null) clearTimeout(optimisticTimerRef.current);
  }, []);

  const toggleConversation = useCallback(() => {
    if (!connected) return;
    send({ type: "manual_trigger", action: "toggle_conversation" });
    if (state === "idle") {
      setOptimisticListening(true);
      if (optimisticTimerRef.current !== null) clearTimeout(optimisticTimerRef.current);
      optimisticTimerRef.current = setTimeout(() => {
        setOptimisticListening(false);
        optimisticTimerRef.current = null;
      }, OPTIMISTIC_LISTENING_MS);
    }
  }, [connected, send, state]);

  const handleShellClick = useCallback(() => {
    // Compact pill → trigger listening; any active state → expand for controls
    if (mode === "compact") {
      toggleConversation();
    } else if (!isExpanded) {
      expand();
    }
  }, [mode, isExpanded, toggleConversation, expand]);

  const handleToggleMic = useCallback(() => {
    toggleConversation();
    pokeExpanded();
  }, [toggleConversation, pokeExpanded]);

  const handleStopSession = useCallback(() => {
    if (!connected) return;
    send({ type: "manual_trigger", action: "deactivate_conversation" });
    collapse();
  }, [connected, send, collapse]);

  const handleSettingsClick = useCallback(() => {
    onOpenSettings();
    collapse();
  }, [onOpenSettings, collapse]);

  const handleCanvasClick = useCallback(() => {
    onOpenCanvas?.();
    collapse();
  }, [onOpenCanvas, collapse]);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    onOpenSettings();
  }, [onOpenSettings]);

  const micActive = Boolean(micStatus?.active || state === "listening");

  return (
    <div className="island-stage" data-state={state} data-mode={mode}>
      <LayoutGroup>
        <motion.div
          layout
          layoutId="island-shell"
          className="island-shell"
          data-mode={mode}
          data-has-notch={hasNotch ? "true" : "false"}
          data-clickable={connected ? "" : undefined}
          onClick={handleShellClick}
          onContextMenu={handleContextMenu}
          onMouseEnter={pokeExpanded}
          onMouseMove={pokeExpanded}
          animate={{
            width: shellSize.width,
            height: shellSize.height,
            borderTopLeftRadius: shellSize.borderTopLeftRadius,
            borderTopRightRadius: shellSize.borderTopRightRadius,
            borderBottomLeftRadius: shellSize.borderBottomLeftRadius,
            borderBottomRightRadius: shellSize.borderBottomRightRadius,
          }}
          transition={ISLAND_SPRING}
          style={{
            scale: 1,
            "--notch-height": `${notchHeight}px`,
            "--notch-safe-width": `${notchSafeWidth}px`,
          } as React.CSSProperties}
        >
          {/* Subtle audio-reactive glow halo */}
          <div
            className="island-glow"
            style={{
              opacity: (mode === "listening" || mode === "speaking") && !hasNotch
                ? 0.35 + Math.min(audioLevel, 1) * 0.5
                : 0,
            }}
            aria-hidden="true"
          />

          <AnimatePresence mode="wait" initial={false}>
            {mode === "compact" && (
              <CompactMode state={state} connected={connected} hasNotch={hasNotch} />
            )}
            {mode === "listening" && (
              <ListeningMode audioLevel={audioLevel} hasNotch={hasNotch} />
            )}
            {mode === "speaking" && (
              <SpeakingMode
                audioLevel={audioLevel}
                thinking={state === "thinking"}
                preparing={state === "preparing_audio"}
                hasNotch={hasNotch}
              />
            )}
            {mode === "expanded" && (
              <ExpandedMode
                state={state}
                transcript={transcript}
                assistantText={assistantText}
                audioLevel={audioLevel}
                micActive={micActive}
                onToggleMic={handleToggleMic}
                onStopSession={handleStopSession}
                onOpenSettings={handleSettingsClick}
                onOpenCanvas={handleCanvasClick}
                onCollapse={collapse}
              />
            )}
            {mode === "error" && (
              <motion.div
                key="error-content"
                className="island-content island-content--error"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <span className="island-status-dot" data-state="error" data-connected={connected} />
                <span>Error</span>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </LayoutGroup>
    </div>
  );
}
