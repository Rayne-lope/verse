import { useEffect, useRef, useCallback } from "react";

const MIN_INTERVAL_MS = 20000;
const MAX_INTERVAL_MS = 40000;
const MIN_DURATION_MS = 3000;
const MAX_DURATION_MS = 5000;
const GAZE_INTERVAL_MS = 1800;
const GAZE_LERP = 0.1;
const SPHERE_GAZE_MAX_PX = 18;
const EPSILON = 0.0005;

function randomRange(min: number, max: number) {
  return min + Math.random() * (max - min);
}

export function useSphereMode(
  orbRef: React.RefObject<HTMLElement | null>,
  state: string
): void {
  const rafRef = useRef<number | null>(null);
  const gazeTargetRef = useRef({ x: 0, y: 0 });
  const gazeCurrentRef = useRef({ x: 0, y: 0 });
  const gazeTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const kickRef = useRef<() => void>(() => {});

  const setSphere = useCallback(
    (on: boolean) => {
      if (orbRef.current) {
        if (on) {
          orbRef.current.dataset.sphere = "";
        } else {
          delete orbRef.current.dataset.sphere;
        }
      }
    },
    [orbRef]
  );

  const pickGazeTarget = useCallback(() => {
    const angle = Math.random() * Math.PI * 2;
    const dist = randomRange(6, SPHERE_GAZE_MAX_PX);
    gazeTargetRef.current = {
      x: Math.cos(angle) * dist,
      y: Math.sin(angle) * dist,
    };
  }, []);

  useEffect(() => {
    const prefersReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (prefersReduced) return;

    const tick = () => {
      const cur = gazeCurrentRef.current;
      const tgt = gazeTargetRef.current;
      let nx = cur.x + (tgt.x - cur.x) * GAZE_LERP;
      let ny = cur.y + (tgt.y - cur.y) * GAZE_LERP;
      if (Math.abs(tgt.x - nx) < EPSILON) nx = tgt.x;
      if (Math.abs(tgt.y - ny) < EPSILON) ny = tgt.y;
      gazeCurrentRef.current = { x: nx, y: ny };

      orbRef.current?.style.setProperty(
        "--sphere-gaze-x",
        `${nx.toFixed(2)}px`
      );
      orbRef.current?.style.setProperty(
        "--sphere-gaze-y",
        `${ny.toFixed(2)}px`
      );

      rafRef.current = requestAnimationFrame(tick);
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
      if (gazeTimerRef.current) clearTimeout(gazeTimerRef.current);
    };
  }, [orbRef]);

  useEffect(() => {
    if (state !== "idle") {
      setSphere(false);
      gazeTargetRef.current = { x: 0, y: 0 };
      gazeCurrentRef.current = { x: 0, y: 0 };
      return;
    }

    let durationTimer: ReturnType<typeof setTimeout>;
    let nextTimer: ReturnType<typeof setTimeout>;

    const scheduleNext = () => {
      const delay = randomRange(MIN_INTERVAL_MS, MAX_INTERVAL_MS);
      nextTimer = setTimeout(() => {
        const duration = randomRange(MIN_DURATION_MS, MAX_DURATION_MS);
        setSphere(true);
        pickGazeTarget();
        kickRef.current();

        const gazeInterval = setInterval(() => {
          pickGazeTarget();
        }, GAZE_INTERVAL_MS);

        durationTimer = setTimeout(() => {
          setSphere(false);
          gazeTargetRef.current = { x: 0, y: 0 };
          clearInterval(gazeInterval);
          scheduleNext();
        }, duration);
      }, delay);
    };

    scheduleNext();
    return () => {
      clearTimeout(nextTimer);
      clearTimeout(durationTimer);
      setSphere(false);
    };
  }, [state, orbRef, setSphere, pickGazeTarget]);
}