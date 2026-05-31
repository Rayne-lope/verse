import type { Transition, Variants } from "framer-motion";

/** Primary morph spring — tuned to match iOS Dynamic Island shell transitions. */
export const ISLAND_SPRING: Transition = {
  type: "spring",
  stiffness: 400,
  damping: 30,
  mass: 1,
};

/** Snappy iOS-style fade for content swap (cubic-bezier 0.32, 0.72, 0, 1). */
export const CONTENT_FADE: Transition = {
  duration: 0.2,
  ease: [0.32, 0.72, 0, 1],
};

export type IslandKind = "compact" | "listening" | "speaking" | "expanded" | "error";

export interface ShellSize {
  width: number;
  height: number;
  borderTopLeftRadius: number;
  borderTopRightRadius: number;
  borderBottomLeftRadius: number;
  borderBottomRightRadius: number;
}

export type ShellSizes = Record<IslandKind, ShellSize>;

interface NotchHint {
  hasNotch: boolean;
  width: number;
  height: number;
}

/** Compute mode shell sizes. When a notch is present, compact mode matches the
 *  notch dimensions exactly so the pill visually merges with the hardware notch.
 *  Active modes grow outward symmetrically from that anchor. */
export function getShellSizes(notch: NotchHint | null): ShellSizes {
  const hasNotch = Boolean(notch?.hasNotch);
  const notchHeight = notch?.hasNotch ? notch.height : 0;

  // With notch: extend slightly wider and taller than the physical camera cutout to frame it beautifully.
  const compactW = notch?.hasNotch ? notch.width + 24 : 140;
  // Compact has 20px of visible area below the notch
  const compactH = notch?.hasNotch ? notchHeight + 20 : 36;

  return {
    compact: {
      width: compactW,
      height: compactH,
      borderTopLeftRadius: hasNotch ? 0 : compactH / 2,
      borderTopRightRadius: hasNotch ? 0 : compactH / 2,
      borderBottomLeftRadius: hasNotch ? 16 : compactH / 2,
      borderBottomRightRadius: hasNotch ? 16 : compactH / 2,
    },
    listening: {
      width: Math.max(280, compactW + 100),
      height: hasNotch ? notchHeight + 38 : 42,
      borderTopLeftRadius: hasNotch ? 0 : 42 / 2,
      borderTopRightRadius: hasNotch ? 0 : 42 / 2,
      borderBottomLeftRadius: hasNotch ? 20 : 42 / 2,
      borderBottomRightRadius: hasNotch ? 20 : 42 / 2,
    },
    speaking: {
      width: hasNotch ? Math.max(420, compactW + 240) : 380,
      height: hasNotch ? notchHeight + 40 : 44,
      borderTopLeftRadius: hasNotch ? 0 : 44 / 2,
      borderTopRightRadius: hasNotch ? 0 : 44 / 2,
      borderBottomLeftRadius: hasNotch ? 20 : 44 / 2,
      borderBottomRightRadius: hasNotch ? 20 : 44 / 2,
    },
    expanded: {
      width: 400,
      height: hasNotch ? notchHeight + 210 : 220,
      borderTopLeftRadius: hasNotch ? 0 : 28,
      borderTopRightRadius: hasNotch ? 0 : 28,
      borderBottomLeftRadius: 28,
      borderBottomRightRadius: 28,
    },
    error: {
      width: Math.max(260, compactW + 80),
      height: hasNotch ? notchHeight + 38 : 42,
      borderTopLeftRadius: hasNotch ? 0 : 42 / 2,
      borderTopRightRadius: hasNotch ? 0 : 42 / 2,
      borderBottomLeftRadius: hasNotch ? 20 : 42 / 2,
      borderBottomRightRadius: hasNotch ? 20 : 42 / 2,
    },
  };
}

/** Default sizes (no notch) — kept for components that don't have access to notch context. */
export const SHELL_SIZES: ShellSizes = getShellSizes(null);

/** Content swap variants — fades out fast, swaps, fades in scaled. */
export const contentVariants: Variants = {
  enter: { opacity: 0, scale: 0.85, y: 2 },
  center: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { ...CONTENT_FADE, delay: 0.08 },
  },
  exit: {
    opacity: 0,
    scale: 0.92,
    y: -2,
    transition: { duration: 0.12, ease: [0.32, 0.72, 0, 1] },
  },
};
