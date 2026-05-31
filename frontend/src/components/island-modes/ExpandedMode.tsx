import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import { Waveform } from "./Waveform";
import type { VerseState } from "../../types/ws";

interface ExpandedProps {
  state: VerseState;
  transcript: string;
  userPartialTranscript: string;
  assistantText: string;
  audioLevel: number;
  micActive: boolean;
  onToggleMic: () => void;
  onStopSession: () => void;
  onOpenSettings: () => void;
  onOpenCanvas: () => void;
  onCollapse: () => void;
}

function ExpandedInner({
  state,
  transcript,
  userPartialTranscript,
  assistantText,
  audioLevel,
  micActive,
  onToggleMic,
  onStopSession,
  onOpenSettings,
  onOpenCanvas,
  onCollapse,
}: ExpandedProps) {
  const statusLabel =
    state === "listening" ? "Listening" :
    state === "thinking" ? "Thinking…" :
    state === "preparing_audio" ? "Preparing audio…" :
    state === "speaking" ? "Speaking" :
    state === "error" ? "Error" :
    "Verse";

  // Show user partial transcript while listening (before speech ends)
  // Fall back to final transcript, then to assistant text
  const displayText = assistantText || transcript || userPartialTranscript || (state === "idle" ? "Tap mic to start a conversation." : "");

  return (
    <motion.div
      key="expanded-content"
      className="island-content island-content--expanded"
      variants={contentVariants}
      initial="enter"
      animate="center"
      exit="exit"
    >
      <div className="island-expanded-header">
        <span className="island-status-dot" data-state={state} data-connected="true" />
        <span className="island-status-label">{statusLabel}</span>
        <button
          className="island-iconbtn island-iconbtn--close"
          onClick={onCollapse}
          aria-label="Collapse"
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <line x1="6" y1="6" x2="18" y2="18" />
            <line x1="18" y1="6" x2="6" y2="18" />
          </svg>
        </button>
      </div>

      <div className="island-expanded-body">
        <div className="island-expanded-viz">
          <Waveform audioLevel={audioLevel} bars={32} height={44} barWidth={3} gap={3} />
        </div>
        <p className={`island-expanded-text${userPartialTranscript && !transcript ? " is-partial" : ""}`}>{displayText}</p>
      </div>

      <div className="island-expanded-controls">
        <button
          className="island-control-btn"
          data-active={micActive ? "true" : "false"}
          onClick={onToggleMic}
          aria-label={micActive ? "Mute mic" : "Unmute mic"}
          title={micActive ? "Mute mic" : "Unmute mic"}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="2" width="6" height="12" rx="3" />
            <path d="M5 10v2a7 7 0 0 0 14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
            {!micActive && <line x1="3" y1="3" x2="21" y2="21" />}
          </svg>
        </button>
        <button
          className="island-control-btn island-control-btn--stop"
          onClick={onStopSession}
          aria-label="End session"
          title="End session"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="2" />
          </svg>
        </button>
        <button
          className="island-control-btn"
          onClick={onOpenSettings}
          aria-label="Settings"
          title="Settings"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <button
          className="island-control-btn"
          onClick={onOpenCanvas}
          aria-label="Expand to canvas"
          title="Expand to canvas"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 3h6v6" />
            <path d="M9 21H3v-6" />
            <path d="M21 3l-7 7" />
            <path d="M3 21l7-7" />
          </svg>
        </button>
      </div>
    </motion.div>
  );
}

export const ExpandedMode = memo(ExpandedInner);
