import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import type { VerseState } from "../../types/ws";

interface CompactProps {
  state: VerseState;
  /** Whether we have an active WS connection (controls dot color). */
  connected: boolean;
}

function CompactInner({ state, connected }: CompactProps) {
  return (
    <motion.div
      key="compact-content"
      className="island-content island-content--compact"
      variants={contentVariants}
      initial="enter"
      animate="center"
      exit="exit"
    >
      <span className="island-status-dot" data-state={state} data-connected={connected} />
      <span className="island-wordmark">VERSE</span>
    </motion.div>
  );
}

export const CompactMode = memo(CompactInner);
