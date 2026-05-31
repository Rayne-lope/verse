import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import type { VerseState } from "../../types/ws";

interface CompactProps {
  state: VerseState;
  /** Whether we have an active WS connection (controls dot color). */
  connected: boolean;
  /** Whether a physical notch is present on the MacBook. */
  hasNotch?: boolean;
}

function CompactInner({ state, connected, hasNotch = false }: CompactProps) {
  if (connected) {
    // Completely empty and black so it merges and is invisible when connected
    return (
      <motion.div
        key="compact-empty"
        className="island-content island-content--compact-empty"
        variants={contentVariants}
        initial="enter"
        animate="center"
        exit="exit"
      />
    );
  }

  // Show status dot / warning when disconnected, side-aligned if under a notch
  return (
    <motion.div
      key="compact-content"
      className="island-content island-content--compact"
      data-split={hasNotch ? "true" : undefined}
      variants={contentVariants}
      initial="enter"
      animate="center"
      exit="exit"
    >
      <div className="island-leading">
        <span className="island-status-dot" data-state={state} data-connected={connected} />
      </div>
      {hasNotch && <div className="island-notch-spacer" />}
      <div className="island-trailing">
        <span className="island-wordmark" style={{ color: "oklch(60% 0.15 25)" }}>OFFLINE</span>
      </div>
    </motion.div>
  );
}

export const CompactMode = memo(CompactInner);

