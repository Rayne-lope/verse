import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import { Waveform } from "./Waveform";

interface SpeakingProps {
  transcript: string;
  audioLevel: number;
  /** When true, render thinking pulse instead of speaker (state was 'thinking'). */
  thinking?: boolean;
}

function SpeakingInner({ transcript, audioLevel, thinking = false }: SpeakingProps) {
  const text = transcript || (thinking ? "Thinking…" : "Speaking…");
  return (
    <motion.div
      key="speaking-content"
      className="island-content island-content--speaking"
      data-thinking={thinking || undefined}
      variants={contentVariants}
      initial="enter"
      animate="center"
      exit="exit"
    >
      <span className="island-icon island-icon--mini-wf" aria-hidden="true">
        <Waveform audioLevel={audioLevel} bars={3} height={14} barWidth={2} gap={2} />
      </span>
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
    </motion.div>
  );
}

export const SpeakingMode = memo(SpeakingInner);
