import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import { Waveform } from "./Waveform";

interface ListeningProps {
  audioLevel: number;
  hasNotch?: boolean;
  statusText?: string;
}

function ListeningInner({ audioLevel, hasNotch = false, statusText }: ListeningProps) {
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
        <span className="island-state-label">{statusText || "Listening"}</span>
      </div>

      {hasNotch && <div className="island-notch-spacer" />}

      <div className="island-trailing">
        <span className="island-waveform-slot">
          <Waveform audioLevel={audioLevel} bars={5} height={12} barWidth={2.5} gap={2} />
        </span>
      </div>
    </motion.div>
  );
}

export const ListeningMode = memo(ListeningInner);

