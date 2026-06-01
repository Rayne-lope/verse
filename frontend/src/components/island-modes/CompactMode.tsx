import { memo, useEffect, useRef } from "react";
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

function SpotifyIcon({ size = 20 }: { size?: number }) {
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
        d="M12.0529 2.00014C10.0751 1.98968 8.13867 2.56593 6.48839 3.65602C4.83812 4.74611 3.54815 6.30108 2.78162 8.1243C2.01508 9.94751 1.8064 11.9571 2.18197 13.8989C2.55753 15.8407 3.50048 17.6276 4.89156 19.0335C6.28264 20.4394 8.05938 21.4012 9.99711 21.7974C11.9348 22.1935 13.9465 22.0061 15.7777 21.259C17.609 20.5118 19.1776 19.2384 20.2851 17.5998C21.3926 15.9612 21.9894 14.0309 21.9999 12.0532C22.0112 9.40183 20.9702 6.85431 19.1054 4.96961C17.2405 3.0849 14.7042 2.01697 12.0529 2.00014ZM15.9447 16.5707C15.8781 16.6695 15.7881 16.7503 15.6826 16.8058C15.5771 16.8613 15.4595 16.8899 15.3403 16.8888C15.1909 16.8904 15.0453 16.8418 14.9267 16.7509C14.1052 16.2635 13.1672 16.007 12.212 16.0086C11.2591 15.9997 10.3226 16.2568 9.50783 16.7509C9.42845 16.8143 9.33659 16.8601 9.23827 16.8855C9.13994 16.9109 9.03737 16.9152 8.93726 16.8981C8.83715 16.8811 8.74176 16.8432 8.65734 16.7867C8.57292 16.7303 8.50138 16.6567 8.44738 16.5707C8.38564 16.4907 8.34114 16.3987 8.31668 16.3007C8.29222 16.2026 8.28833 16.1006 8.30527 16.0009C8.32221 15.9013 8.3596 15.8063 8.41508 15.7218C8.47057 15.6374 8.54295 15.5653 8.62766 15.5102C9.68482 14.8216 10.9185 14.4533 12.1802 14.4498C13.4443 14.459 14.6798 14.8267 15.7432 15.5102C15.8255 15.5678 15.8951 15.6418 15.9475 15.7274C16 15.8131 16.0343 15.9087 16.0482 16.0081C16.0621 16.1076 16.0554 16.2089 16.0285 16.3057C16.0016 16.4025 15.955 16.4927 15.8917 16.5707H15.9447ZM17.2279 13.6332C17.1555 13.7353 17.0602 13.8191 16.9498 13.878C16.8394 13.9369 16.7167 13.9693 16.5916 13.9726C16.4272 13.9757 16.2666 13.9234 16.1356 13.8241C14.9009 13.0882 13.4903 12.6997 12.0529 12.6997C10.6155 12.6997 9.20489 13.0882 7.97019 13.8241C7.79863 13.9436 7.58661 13.9901 7.38077 13.9533C7.17494 13.9165 6.99216 13.7995 6.87263 13.6279C6.7531 13.4564 6.70661 13.2443 6.7434 13.0385C6.78019 12.8327 6.89724 12.6499 7.06881 12.5304C8.5652 11.6012 10.2915 11.1089 12.0529 11.1089C13.8143 11.1089 15.5406 11.6012 17.037 12.5304C17.1186 12.5936 17.1869 12.6724 17.238 12.7621C17.2891 12.8518 17.322 12.9507 17.3348 13.0532C17.3476 13.1556 17.3401 13.2596 17.3126 13.3591C17.2852 13.4587 17.2384 13.5518 17.1749 13.6332H17.2279ZM18.7231 10.6958C18.6424 10.7986 18.5394 10.8817 18.4218 10.9386C18.3042 10.9956 18.1751 11.025 18.0444 11.0245C17.8603 11.0179 17.6827 10.9549 17.5354 10.8443C15.9181 9.74553 14.0081 9.15808 12.0529 9.15808C10.0977 9.15808 8.18765 9.74553 6.5704 10.8443C6.48197 10.9139 6.38069 10.9654 6.27234 10.9959C6.164 11.0264 6.05071 11.0352 5.93894 11.0219C5.82718 11.0087 5.71913 10.9735 5.62096 10.9184C5.52279 10.8634 5.43642 10.7895 5.36679 10.7011C5.29716 10.6127 5.24563 10.5114 5.21514 10.403C5.18465 10.2947 5.1758 10.1814 5.1891 10.0696C5.20239 9.95787 5.23757 9.84982 5.29262 9.75165C5.34767 9.65348 5.42152 9.56712 5.50995 9.49749C7.4264 8.17173 9.70137 7.46152 12.0317 7.46152C14.362 7.46152 16.637 8.17173 18.5534 9.49749C18.7237 9.64359 18.8309 9.84987 18.8527 10.0732C18.8744 10.2965 18.809 10.5196 18.6701 10.6958H18.7231Z"
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

const FREQS  = [5.3, 7.1, 6.2, 8.4, 5.8];
const PHASES = [0,   1.2, 2.4, 0.6, 3.1];
const BAR_COUNT = 5;

function PlayingVisualizer({ color }: { color: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const els = Array.from(container.querySelectorAll<HTMLDivElement>(".cpv-bar"));
    const start = performance.now();

    const tick = (ts: number) => {
      const t = (ts - start) / 1000;
      els.forEach((el, i) => {
        const wave = (Math.sin(t * FREQS[i] + PHASES[i]) + 1) / 2;
        const scale = 0.15 + wave * 0.85;
        el.style.transform = `scaleY(${scale.toFixed(3)})`;
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ display: "flex", alignItems: "center", gap: "2.5px", height: "16px" }}
      aria-hidden="true"
    >
      {Array.from({ length: BAR_COUNT }).map((_, i) => (
        <div
          key={i}
          className="cpv-bar"
          style={{
            width: "2.5px",
            height: "16px",
            background: color,
            borderRadius: "1.5px",
            transformOrigin: "center",
            transform: "scaleY(0.15)",
            willChange: "transform",
          }}
        />
      ))}
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
            {nowPlaying.artwork_url
              ? (
                <span className="island-spotify-icon">
                  <img
                    src={nowPlaying.artwork_url}
                    alt={nowPlaying.track}
                    className="island-artwork-img"
                  />
                </span>
              )
              : isSpotify
                ? <span className="island-spotify-icon"><SpotifyIcon /></span>
                : <MusicIcon />}
          </div>
          {hasNotch && <div className="island-notch-spacer" />}
          <div className="island-trailing">
            <PlayingVisualizer color={brandColor} />
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


