import { useEffect, useState } from "react";
import { getNotchGeometry, type NotchGeometry } from "../utils/window";

/**
 * Subscribe to the macOS notch geometry. Returns null on non-macOS or while
 * the first query is in flight. Re-queries on window focus to handle display
 * plug/unplug (the user can drag the Verse window to another monitor and we
 * want fresh dimensions).
 */
const isMac = typeof window !== "undefined" && navigator.userAgent.includes("Mac");

const DEFAULT_MAC_NOTCH: NotchGeometry = {
  hasNotch: true,
  x: 0,
  y: 0,
  width: 190,
  height: 32,
  screenWidth: 1440,
  screenHeight: 900,
  menuBarHeight: 24,
};

export function useNotchGeometry(): NotchGeometry | null {
  const [notch, setNotch] = useState<NotchGeometry | null>(() => {
    return isMac ? DEFAULT_MAC_NOTCH : null;
  });

  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      const geom = await getNotchGeometry();
      if (!cancelled) setNotch(geom);
    };

    refresh();

    const handleFocus = () => {
      refresh();
    };
    window.addEventListener("focus", handleFocus);

    return () => {
      cancelled = true;
      window.removeEventListener("focus", handleFocus);
    };
  }, []);

  return notch;
}
