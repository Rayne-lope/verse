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
        <span className="island-transcript-mask">
          <motion.span
            key={text}
            className="island-transcript-text"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.18, ease: [0.32, 0.72, 0, 1] }}
          >
            {text}
          </motion.span>
        </span>
      </div>

      {hasNotch && <div className="island-notch-spacer" />}

      <div className="island-trailing">
        <span className="island-waveform-slot">
          <Waveform audioLevel={audioLevel} bars={8} height={16} barWidth={2} gap={2} />
        </span>
        <span className="island-brand-logo">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
        </span>
      </div>
    </motion.div>
  );
}

export const SpeakingMode = memo(SpeakingInner);


