export type IslandCalibration = {
  xOffset: number;
  yOffset: number;
  widthScale: number;
  heightScale: number;
  attachOverlap: number;
  bottomRadius: number;
  notchSafePadding: number;
};

export const DEFAULT_ISLAND_CALIBRATION: IslandCalibration = {
  xOffset: 0,
  yOffset: 0,
  widthScale: 1.0,
  heightScale: 1.0,
  attachOverlap: 2,
  bottomRadius: 20,
  notchSafePadding: 18,
};

export function getIslandCalibration(): IslandCalibration {
  try {
    const saved = localStorage.getItem("verse_island_calibration");
    if (saved) {
      return { ...DEFAULT_ISLAND_CALIBRATION, ...JSON.parse(saved) };
    }
  } catch {
    // ignore
  }
  return DEFAULT_ISLAND_CALIBRATION;
}

export function setIslandCalibration(calibration: IslandCalibration) {
  try {
    localStorage.setItem("verse_island_calibration", JSON.stringify(calibration));
    // Dispatch custom event to notify components in real-time
    window.dispatchEvent(new Event("verse_calibration_changed"));
  } catch {
    // ignore
  }
}
