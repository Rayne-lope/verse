import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import { Waveform } from "./Waveform";

interface SpeakingProps {
  transcript: string;
  audioLevel: number;
  /** When true, render thinking pulse instead of speaker (state was 'thinking'). */
  thinking?: boolean;
  /** TTS has started, but playback has not produced audio yet. */
  preparing?: boolean;
  hasNotch?: boolean;
}

function SpeakingInner({ transcript, audioLevel, thinking = false, preparing = false, hasNotch = false }: SpeakingProps) {
  const text = transcript || (thinking ? "Thinking…" : preparing ? "Preparing audio…" : "Speaking…");
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
        <span className="island-icon island-icon--mini-wf" aria-hidden="true">
          <Waveform audioLevel={audioLevel} bars={8} height={16} barWidth={2} gap={2} />
        </span>
      </div>

      {hasNotch && <div className="island-notch-spacer" />}

      <div className="island-trailing">
        <span className="island-transcript-mask">
          <motion.span
            key={text}
            className="island-transcript-text"
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
          >
            {text}
          </motion.span>
        </span>
      </div>
    </motion.div>
  );
}

export const SpeakingMode = memo(SpeakingInner);

