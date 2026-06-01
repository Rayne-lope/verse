import { memo } from "react";
import { motion } from "framer-motion";
import { contentVariants } from "./motion";
import type { VerseState } from "../../types/ws";
import { useWebSocket } from "../../hooks/useWebSocket";

interface CompactProps {
  state: VerseState;
  /** Whether we have an active WS connection (controls dot color). */
  connected: boolean;
  /** Whether a physical notch is present on the MacBook. */
  hasNotch?: boolean;
}

function SpotifyIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ color: "oklch(76% 0.22 142)" }}
    >
      <path
        d="M12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2ZM16.5772 16.4228C16.3772 16.7456 15.9529 16.8485 15.6301 16.6485C13.1029 15.1029 10.0057 14.7629 6.27429 15.6143C5.90857 15.7029 5.54 15.4743 5.45429 15.1057C5.36857 14.74 5.59714 14.3743 5.96571 14.2857C10.04 13.3543 13.4686 13.7371 16.3514 15.4772C16.6714 15.6743 16.7772 16.1 16.5772 16.4228ZM17.9714 13.8829C17.72 14.2943 17.18 14.4314 16.7686 14.18C14.0771 12.5257 10.0143 12.0514 7.00857 12.9629C6.54571 13.1029 6.05714 12.84 5.91429 12.3771C5.77143 11.9143 6.03429 11.4257 6.49714 11.2829C10.0171 10.2171 14.5029 10.7486 17.6714 12.6886C18.0857 12.9371 18.22 13.4714 17.9714 13.8829ZM18.1143 11.2171C15.1486 9.45429 10.2629 9.29143 7.42286 10.1543C6.96571 10.2914 6.48571 10.0343 6.34857 9.57714C6.21143 9.12 6.46857 8.64 6.92571 8.50286C10.2 7.50857 15.5886 7.69714 19.0343 9.74286C19.4457 9.98857 19.58 10.5229 19.3343 10.9343C19.0886 11.3457 18.5543 11.48 18.1143 11.2171Z"
        fill="currentColor"
      />
    </svg>
  );
}

function MusicIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ color: "oklch(65% 0.23 0)" }}
    >
      <path
        d="M12 3V13.55C11.41 13.21 10.73 13 10 13C7.79 13 6 14.79 6 17C6 19.21 7.79 21 10 21C12.21 21 14 19.21 14 17V7H18V3H12ZM10 19C8.9 19 8 18.1 8 17C8 15.9 8.9 15 10 15C11.1 15 12 15.9 12 17C12 18.1 11.1 19 10 19Z"
        fill="currentColor"
      />
    </svg>
  );
}

function MusicVisualizer({ color }: { color: string }) {
  return (
    <div className="island-music-visualizer">
      <span className="island-music-bar" style={{ backgroundColor: color }} />
      <span className="island-music-bar" style={{ backgroundColor: color }} />
      <span className="island-music-bar" style={{ backgroundColor: color }} />
    </div>
  );
}

function CompactInner({ state, connected, hasNotch = false }: CompactProps) {
  const { nowPlaying } = useWebSocket();

  if (connected) {
    if (nowPlaying?.playing) {
      const isSpotify = nowPlaying.player === "spotify";
      const brandColor = isSpotify ? "oklch(76% 0.22 142)" : "oklch(65% 0.23 0)";

      return (
        <motion.div
          key="compact-playing"
          className="island-content island-content--compact-playing"
          data-split={hasNotch ? "true" : undefined}
          variants={contentVariants}
          initial="enter"
          animate="center"
          exit="exit"
        >
          <div className="island-leading">
            {isSpotify ? <SpotifyIcon /> : <MusicIcon />}
          </div>
          {hasNotch && <div className="island-notch-spacer" />}
          <div className="island-trailing">
            <MusicVisualizer color={brandColor} />
          </div>
        </motion.div>
      );
    }

    if (hasNotch) {
      return (
        <motion.div
          key="compact-idle-notch"
          className="island-content island-content--compact-idle-notch"
          data-split="true"
          variants={contentVariants}
          initial="enter"
          animate="center"
          exit="exit"
        >
          <div className="island-leading">
            <span className="island-idle-indicator" />
          </div>
          <div className="island-notch-spacer" />
          <div className="island-trailing" />
        </motion.div>
      );
    }

    // Completely empty and black so it merges and is invisible when connected on non-notch screens
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


