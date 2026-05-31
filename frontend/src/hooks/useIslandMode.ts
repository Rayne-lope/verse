import { useCallback, useEffect, useRef, useState } from "react";
import type { VerseState } from "../types/ws";
import type { IslandKind } from "../components/island-modes/motion";

const EXPANDED_AUTO_COLLAPSE_MS = 5000;

interface UseIslandModeArgs {
  state: VerseState;
  /** True briefly after the user clicks the pill to start listening before backend confirms. */
  optimisticListening?: boolean;
}

export interface UseIslandModeResult {
  mode: IslandKind;
  expand: () => void;
  collapse: () => void;
  /** Reset the auto-collapse timer (call on hover/interaction inside expanded). */
  pokeExpanded: () => void;
  isExpanded: boolean;
}

/**
 * Derives the visible island mode from backend state + user expand intent.
 * Priority:
 *   error          → "error"
 *   expanded by user → "expanded"
 *   listening       → "listening"
 *   speaking/thinking/preparing_audio → "speaking"
 *   idle/null       → "compact"
 *
 * Expanded auto-collapses after EXPANDED_AUTO_COLLAPSE_MS unless poked.
 */
export function useIslandMode({ state, optimisticListening = false }: UseIslandModeArgs): UseIslandModeResult {
  const [isExpanded, setIsExpanded] = useState(false);
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (collapseTimerRef.current !== null) {
      clearTimeout(collapseTimerRef.current);
      collapseTimerRef.current = null;
    }
  }, []);

  const scheduleCollapse = useCallback(() => {
    clearTimer();
    collapseTimerRef.current = setTimeout(() => {
      setIsExpanded(false);
      collapseTimerRef.current = null;
    }, EXPANDED_AUTO_COLLAPSE_MS);
  }, [clearTimer]);

  const expand = useCallback(() => {
    setIsExpanded(true);
    scheduleCollapse();
  }, [scheduleCollapse]);

  const collapse = useCallback(() => {
    clearTimer();
    setIsExpanded(false);
  }, [clearTimer]);

  const pokeExpanded = useCallback(() => {
    if (isExpanded) scheduleCollapse();
  }, [isExpanded, scheduleCollapse]);

  useEffect(() => () => clearTimer(), [clearTimer]);

  // Derive mode
  let mode: IslandKind;
  if (state === "error") {
    mode = "error";
  } else if (isExpanded) {
    mode = "expanded";
  } else if (state === "listening" || optimisticListening) {
    mode = "listening";
  } else if (state === "speaking" || state === "thinking" || state === "preparing_audio") {
    mode = "speaking";
  } else {
    mode = "compact";
  }

  return { mode, expand, collapse, pokeExpanded, isExpanded };
}
