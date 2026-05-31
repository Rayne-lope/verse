import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import { Waveform } from "./Waveform";

interface SpeakingProps {
  audioLevel: number;
  /** When true, render thinking pulse instead of speaker (state was 'thinking'). */
  thinking?: boolean;
  /** TTS has started, but playback has not produced audio yet. */
  preparing?: boolean;
  hasNotch?: boolean;
}

function SpeakingInner({ audioLevel, thinking = false, preparing = false, hasNotch = false }: SpeakingProps) {
  return (
    <motion.div
      key="speaking-content"
      className="island-content island-content--speaking"
      data-thinking={thinking || preparing || undefined}
      data-split={hasNotch ? "true" : undefined}
      variants={contentVariants}
      initial="enter"
      animate="center"
      exit="exit"
    >
      <div className="island-leading">
        <span className="island-state-label">
          {thinking ? "Thinking" : preparing ? "Preparing" : "Speaking"}
        </span>
      </div>

      {hasNotch && <div className="island-notch-spacer" />}

      <div className="island-trailing">
        <span className="island-waveform-slot">
          <Waveform audioLevel={audioLevel} bars={4} height={14} barWidth={2.5} gap={2} />
        </span>
      </div>
    </motion.div>
  );
}

export const SpeakingMode = memo(SpeakingInner);


