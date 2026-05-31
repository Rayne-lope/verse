import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import { Waveform } from "./Waveform";

interface ListeningProps {
  audioLevel: number;
  hasNotch?: boolean;
}

function ListeningInner({ audioLevel, hasNotch = false }: ListeningProps) {
  return (
    <motion.div
      key="listening-content"
      className="island-content island-content--listening"
      data-split={hasNotch ? "true" : undefined}
      variants={contentVariants}
      initial="enter"
      animate="center"
      exit="exit"
    >
      <div className="island-leading">
        <span className="island-icon" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10v2a7 7 0 0 0 14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
        </span>
        <span className="island-listening-label">Listening</span>
      </div>

      {hasNotch && <div className="island-notch-spacer" />}

      <div className="island-trailing">
        <span className="island-waveform-slot">
          <Waveform audioLevel={audioLevel} bars={14} height={20} />
        </span>
      </div>
    </motion.div>
  );
}

export const ListeningMode = memo(ListeningInner);

