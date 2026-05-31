import { useEffect, useRef, useState, useCallback } from "react";

const SLEEP_DELAY_MS = 60000;

export function useSleepMode(
  orbRef: React.RefObject<HTMLElement | null>,
  state: string
): boolean {
  const [isSleeping, setIsSleeping] = useState(false);
  const sleepingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const wakeUp = useCallback(() => {
    sleepingRef.current = false;
    setIsSleeping(false);
    if (orbRef.current) {
      delete orbRef.current.dataset.sleep;
      delete orbRef.current.dataset.sphere;
    }
    if (timerRef.current !== undefined) {
      clearTimeout(timerRef.current);
      timerRef.current = undefined;
    }
  }, [orbRef]);

  useEffect(() => {
    if (state !== "idle") {
      wakeUp();
      return;
    }

    const prefersReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (prefersReduced) return;

    const scheduleSleep = () => {
      if (timerRef.current !== undefined) {
        clearTimeout(timerRef.current);
      }
      timerRef.current = setTimeout(() => {
        sleepingRef.current = true;
        setIsSleeping(true);
        if (orbRef.current) {
          orbRef.current.dataset.sleep = "";
          delete orbRef.current.dataset.sphere;
        }
      }, SLEEP_DELAY_MS);
    };

    scheduleSleep();

    const onMove = () => {
      if (sleepingRef.current) {
        wakeUp();
      }
      scheduleSleep();
    };

    window.addEventListener("pointermove", onMove);
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (timerRef.current !== undefined) {
        clearTimeout(timerRef.current);
        timerRef.current = undefined;
      }
    };
  }, [state, orbRef, wakeUp]);

  return isSleeping;
}