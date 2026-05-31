import { useEffect, useRef, memo } from "react";

interface WaveformProps {
  /** Live audio level 0–1. Drives bar heights with smoothing + per-bar offset. */
  audioLevel: number;
  /** Number of bars. */
  bars?: number;
  /** Color of bars (CSS color string). */
  color?: string;
  /** Height of the tallest possible bar in px. */
  height?: number;
  /** Width of each bar in px. */
  barWidth?: number;
  /** Gap between bars in px. */
  gap?: number;
}

/**
 * Lightweight CSS-driven waveform — bars are flex children with scaleY animated
 * via rAF + LERP. No canvas, no re-renders per frame.
 */
function WaveformInner({
  audioLevel,
  bars = 14,
  color = "currentColor",
  height = 22,
  barWidth = 2.5,
  gap = 3,
}: WaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef(0);
  const phasesRef = useRef<number[]>([]);
  const rafRef = useRef<number | null>(null);

  // Initialize per-bar phase offsets once
  if (phasesRef.current.length !== bars) {
    phasesRef.current = Array.from({ length: bars }, (_, i) => i * 0.7);
  }

  useEffect(() => {
    targetRef.current = Math.max(0, Math.min(1, audioLevel));
  }, [audioLevel]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const barEls = Array.from(container.querySelectorAll<HTMLDivElement>(".island-wf-bar"));
    let startTs = performance.now();

    const tick = (ts: number) => {
      const elapsed = (ts - startTs) / 1000;
      const level = targetRef.current;
      // base idle wobble at very low level for liveliness even on silence
      const baseLevel = 0.08 + level * 0.92;
      barEls.forEach((el, i) => {
        const phase = phasesRef.current[i];
        // Mix per-bar sine wobble with audio level
        const wobble = (Math.sin(elapsed * 6 + phase) + 1) / 2; // 0..1
        const target = baseLevel * (0.55 + wobble * 0.45);
        el.style.transform = `scaleY(${target.toFixed(3)})`;
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [bars]);

  return (
    <div
      ref={containerRef}
      className="island-waveform"
      style={{
        display: "flex",
        alignItems: "center",
        gap: `${gap}px`,
        height: `${height}px`,
        color,
      }}
      aria-hidden="true"
    >
      {Array.from({ length: bars }).map((_, i) => (
        <div
          key={i}
          className="island-wf-bar"
          style={{
            width: `${barWidth}px`,
            height: `${height}px`,
            background: "currentColor",
            borderRadius: `${barWidth / 2}px`,
            transformOrigin: "center",
            transform: "scaleY(0.1)",
            willChange: "transform",
          }}
        />
      ))}
    </div>
  );
}

export const Waveform = memo(WaveformInner);
