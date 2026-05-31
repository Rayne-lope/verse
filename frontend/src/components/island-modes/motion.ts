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

/** Shell dimensions per mode. Border-radius is always half of height for pill modes. */
export const SHELL_SIZES = {
  compact:   { width: 140, height: 34,  borderRadius: 17 },
  listening: { width: 280, height: 38,  borderRadius: 19 },
  speaking:  { width: 380, height: 46,  borderRadius: 23 },
  expanded:  { width: 380, height: 210, borderRadius: 28 },
  error:     { width: 240, height: 38,  borderRadius: 19 },
} as const;

export type IslandKind = keyof typeof SHELL_SIZES;

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
