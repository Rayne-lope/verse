import { useEffect, useRef } from "react";

const LERP_FACTOR = 0.08;
const EPSILON = 0.0005;
const MAX_OFFSET_PX = 5;
const RETURN_LERP = 0.04;

export function useMouseGaze(
  orbRef: React.RefObject<HTMLElement | null>,
  state: string
): void {
  const currentRef = useRef({ x: 0, y: 0 });
  const targetRef = useRef({ x: 0, y: 0 });
  const rafRef = useRef<number | null>(null);
  const kickRef = useRef<() => void>(() => {});
  const mouseOnScreenRef = useRef(false);

  useEffect(() => {
    const prefersReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (prefersReduced) return;

    const tick = () => {
      const cur = currentRef.current;
      const tgt = targetRef.current;
      const lf = mouseOnScreenRef.current ? LERP_FACTOR : RETURN_LERP;

      let nx = cur.x + (tgt.x - cur.x) * lf;
      let ny = cur.y + (tgt.y - cur.y) * lf;
      if (Math.abs(tgt.x - nx) < EPSILON) nx = tgt.x;
      if (Math.abs(tgt.y - ny) < EPSILON) ny = tgt.y;
      currentRef.current = { x: nx, y: ny };

      orbRef.current?.style.setProperty(
        "--gaze-x",
        `${nx.toFixed(2)}px`
      );
      orbRef.current?.style.setProperty(
        "--gaze-y",
        `${ny.toFixed(2)}px`
      );

      const settled =
        Math.abs(tgt.x - nx) < EPSILON &&
        Math.abs(tgt.y - ny) < EPSILON;
      if (!settled || mouseOnScreenRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        rafRef.current = null;
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

  useEffect(() => {
    if (state !== "idle") {
      targetRef.current = { x: 0, y: 0 };
      return;
    }

    const onMove = (e: PointerEvent) => {
      mouseOnScreenRef.current = true;
      const el = orbRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const maxDist = Math.max(window.innerWidth, window.innerHeight);
      const norm = Math.min(dist / maxDist, 1);
      const angle = Math.atan2(dy, dx);
      targetRef.current = {
        x: Math.cos(angle) * norm * MAX_OFFSET_PX,
        y: Math.sin(angle) * norm * MAX_OFFSET_PX,
      };
      kickRef.current();
    };

    const onLeave = () => {
      mouseOnScreenRef.current = false;
      targetRef.current = { x: 0, y: 0 };
      kickRef.current();
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerleave", onLeave);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerleave", onLeave);
    };
  }, [state, orbRef]);
}