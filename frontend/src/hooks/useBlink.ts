import { useEffect, useState } from "react";

const MIN_INTERVAL_MS = 3000;
const MAX_INTERVAL_MS = 6000;
const BLINK_DURATION_MS = 130;

/** Toggles a blink flag at natural, jittered intervals. */
export function useBlink(): boolean {
  const [isBlinking, setIsBlinking] = useState(false);

  useEffect(() => {
    let openTimer: ReturnType<typeof setTimeout>;
    let nextTimer: ReturnType<typeof setTimeout>;

    const scheduleNext = () => {
      const delay =
        MIN_INTERVAL_MS + Math.random() * (MAX_INTERVAL_MS - MIN_INTERVAL_MS);
      nextTimer = setTimeout(() => {
        setIsBlinking(true);
        openTimer = setTimeout(() => {
          setIsBlinking(false);
          scheduleNext();
        }, BLINK_DURATION_MS);
      }, delay);
    };

    scheduleNext();
    return () => {
      clearTimeout(nextTimer);
      clearTimeout(openTimer);
    };
  }, []);

  return isBlinking;
}
