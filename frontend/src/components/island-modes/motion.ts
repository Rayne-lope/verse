import type { Transition, Variants } from "framer-motion";
import type { IslandCalibration } from "../../utils/calibration";
import { DEFAULT_ISLAND_CALIBRATION } from "../../utils/calibration";

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
export function getShellSizes(notch: NotchHint | null, calibration: IslandCalibration = DEFAULT_ISLAND_CALIBRATION): ShellSizes {
  const hasNotch = Boolean(notch);
  const notchHeight = hasNotch ? (notch?.height && notch.height > 0 ? notch.height : 32) : 0;

  // Base dimensions adjusted by calibration scales
  const baseWidth = hasNotch ? (notch?.width && notch.width > 0 ? notch.width : 190) : 140;
  const compactW = baseWidth * calibration.widthScale;

  // Desired vertical content heights
  const hCompact = hasNotch ? notchHeight : 34;
  const hListening = 22;
  const hSpeaking = 22;
  const hExpanded = 220;
  const hError = 22;

  const listeningH = (notchHeight + hListening) * calibration.heightScale;
  const speakingH = (notchHeight + hSpeaking) * calibration.heightScale;
  const expandedH = (notchHeight + hExpanded) * calibration.heightScale;
  const errorH = (notchHeight + hError) * calibration.heightScale;

  return {
    compact: {
      width: compactW,
      height: hCompact * calibration.heightScale,
      borderTopLeftRadius: hasNotch ? 0 : hCompact / 2,
      borderTopRightRadius: hasNotch ? 0 : hCompact / 2,
      borderBottomLeftRadius: hasNotch ? calibration.bottomRadius : hCompact / 2,
      borderBottomRightRadius: hasNotch ? calibration.bottomRadius : hCompact / 2,
    },
    listening: {
      width: compactW + 220,
      height: hasNotch ? hCompact * calibration.heightScale : listeningH,
      borderTopLeftRadius: hasNotch ? 0 : hListening / 2,
      borderTopRightRadius: hasNotch ? 0 : hListening / 2,
      borderBottomLeftRadius: hasNotch ? calibration.bottomRadius : hListening / 2,
      borderBottomRightRadius: hasNotch ? calibration.bottomRadius : hListening / 2,
    },
    speaking: {
      width: compactW + 280,
      height: hasNotch ? hCompact * calibration.heightScale : speakingH,
      borderTopLeftRadius: hasNotch ? 0 : hSpeaking / 2,
      borderTopRightRadius: hasNotch ? 0 : hSpeaking / 2,
      borderBottomLeftRadius: hasNotch ? calibration.bottomRadius : hSpeaking / 2,
      borderBottomRightRadius: hasNotch ? calibration.bottomRadius : hSpeaking / 2,
    },
    expanded: {
      width: 380,
      height: expandedH,
      borderTopLeftRadius: 28,
      borderTopRightRadius: 28,
      borderBottomLeftRadius: 28,
      borderBottomRightRadius: 28,
    },
    error: {
      width: compactW + 120,
      height: hasNotch ? hCompact * calibration.heightScale : errorH,
      borderTopLeftRadius: hasNotch ? 0 : hError / 2,
      borderTopRightRadius: hasNotch ? 0 : hError / 2,
      borderBottomLeftRadius: hasNotch ? calibration.bottomRadius : hError / 2,
      borderBottomRightRadius: hasNotch ? calibration.bottomRadius : hError / 2,
    },
  };
}

/** Default sizes (no notch) — kept for components that don't have access to notch context. */
export const SHELL_SIZES: ShellSizes = getShellSizes(null, DEFAULT_ISLAND_CALIBRATION);

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
