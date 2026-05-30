import { useEffect, useRef } from "react";

const LERP_FACTOR = 0.15;
const EPSILON = 0.001;

/**
 * Drives a smoothed `--audio` (0–1) CSS variable on the orb element via rAF,
 * without re-rendering on every frame. The loop sleeps whenever there is no
 * energy to animate (target and current both 0) and is re-kicked when audio
 * arrives or the orb becomes active, so idle/thinking/error states cost nothing.
 */
export function useAudioReactiveOrb(
  orbRef: React.RefObject<HTMLElement | null>,
  audioLevel: number,
  active: boolean
): void {
  const targetRef = useRef(0);
  const currentRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const kickRef = useRef<() => void>(() => {});

  // Build the rAF machinery once; tied to the element ref.
  useEffect(() => {
    const tick = () => {
      const cur = currentRef.current;
      const tgt = targetRef.current;
      let next = cur + (tgt - cur) * LERP_FACTOR;
      if (Math.abs(tgt - next) < EPSILON) next = tgt;
      currentRef.current = next;
      orbRef.current?.style.setProperty("--audio", next.toFixed(3));

      if (next > 0 || tgt > 0) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = null; // settled at rest — sleep
      }
    };

    kickRef.current = () => {
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [orbRef]);

  // Update target on change; wake the loop only when there is work to do.
  useEffect(() => {
    targetRef.current = active ? Math.max(0, Math.min(1, audioLevel)) : 0;
    if (targetRef.current > 0 || currentRef.current > 0) {
      kickRef.current();
    }
  }, [audioLevel, active]);
}
