import type { IslandCalibration } from "./calibration";
import { getIslandCalibration } from "./calibration";

export interface NotchGeometry {
  hasNotch: boolean;
  /** Notch left-edge X in logical points relative to the screen origin. */
  x: number;
  /** Notch top-edge Y (always 0). */
  y: number;
  /** Notch width in logical points (~190 on 14"/16" M-series). */
  width: number;
  /** Notch height (= safeAreaInsets.top, ~32). */
  height: number;
  /** Full screen width in logical points. */
  screenWidth: number;
  /** Full screen height in logical points. */
  screenHeight: number;
  /** Menu bar height in logical points (used for fallback positioning). */
  menuBarHeight: number;
}

/** Query the macOS notch geometry. Returns null on non-macOS or if query fails. */
export async function getNotchGeometry(): Promise<NotchGeometry | null> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<NotchGeometry>("get_notch_geometry");
  } catch {
    return null;
  }
}

/** Elevate the Tauri window above the menu bar (NSStatusWindowLevel = 25). */
export async function elevateAboveMenuBar(): Promise<void> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("elevate_above_menu_bar");
  } catch {
    // non-macOS or command not registered — ignore
  }
}

/** Position the Tauri window so its horizontal center aligns with the notch center.
 *  Returns the notch geometry on success (used by callers to size the pill). */
export async function positionAtNotch(containerWidth: number): Promise<NotchGeometry | null> {
  const notch = await getNotchGeometry();
  if (!notch) {
    await positionTopCenter(containerWidth);
    return null;
  }

  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalPosition } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();

    if (notch.hasNotch) {
      const notchCenterX = notch.x + notch.width / 2;
      const x = notchCenterX - containerWidth / 2;
      const y = 0; // flush with screen top — pill anchored to top of container
      await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
    } else {
      // No notch on this display — center horizontally just below menu bar
      const x = (notch.screenWidth - containerWidth) / 2;
      await win.setPosition(new LogicalPosition(Math.round(x), 0));
    }
  } catch {
    // ignore
  }

  return notch;
}

/** Resize and position the widget window atomically using calibration parameters. */
export async function resizeAndPositionWidget(
  width: number,
  height: number,
  calibration?: IslandCalibration
): Promise<NotchGeometry | null> {
  const cal = calibration || getIslandCalibration();
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize, LogicalPosition } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    const notch = await getNotchGeometry();

    // Enforce lock behaviors
    await win.setResizable(false);
    await win.setAlwaysOnTop(true);
    await win.setVisibleOnAllWorkspaces(true);
    await win.setSize(new LogicalSize(width, height));
    await elevateAboveMenuBar();

    if (!notch) {
      // Center top fallback
      await positionTopCenter(width);
      return null;
    }

    const notchCenterX = notch.x + notch.width / 2;
    const x = notchCenterX - width / 2 + cal.xOffset;
    const y = notch.y + cal.yOffset - cal.attachOverlap;

    await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
    return notch;
  } catch {
    return null;
  }
}

/** Called on startup in widget mode to lock the window to island container size. */
export async function lockWidgetMode(width: number, height: number): Promise<NotchGeometry | null> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    await win.setResizable(false);
    await win.setAlwaysOnTop(true);
    await win.setVisibleOnAllWorkspaces(true);
    await win.setSize(new LogicalSize(width, height));
    await elevateAboveMenuBar();
    return await positionAtNotch(width);
  } catch {
    return null;
  }
}

export async function resizeWindow(width: number, height: number): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize } = await import("@tauri-apps/api/dpi");
    await getCurrentWindow().setSize(new LogicalSize(width, height));
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}

export async function setFullscreen(fullscreen: boolean, widgetWidth: number = 480, widgetHeight: number = 280): Promise<void> {
  try {
    const { getCurrentWindow, currentMonitor } = await import("@tauri-apps/api/window");
    const { PhysicalSize, PhysicalPosition, LogicalSize } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    const monitor = await currentMonitor();

    if (fullscreen) {
      if (monitor) {
        const { width, height } = monitor.size;
        const { x, y } = monitor.position;

        // Enable resize + disable always-on-top so window behaves as a normal fullscreen
        await win.setResizable(true);
        await win.setAlwaysOnTop(false);
        await win.setVisibleOnAllWorkspaces(false);
        await win.setPosition(new PhysicalPosition(x, y));
        await win.setSize(new PhysicalSize(width, height));
        await win.setFocus();
      }
    } else {
      await win.setSize(new LogicalSize(widgetWidth, widgetHeight));
      await elevateAboveMenuBar();
      await positionAtNotch(widgetWidth);
      // Lock back to widget behaviour
      await win.setResizable(false);
      await win.setAlwaysOnTop(true);
      await win.setVisibleOnAllWorkspaces(true);
    }
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}

/** Position the window at the top-center of the active monitor (fallback for non-notch).
 *  Uses logical units throughout to avoid Retina/scale-factor mismatches. */
export async function positionTopCenter(widthLogical: number): Promise<void> {
  try {
    const { getCurrentWindow, currentMonitor } = await import("@tauri-apps/api/window");
    const { LogicalPosition } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    const monitor = await currentMonitor();
    if (!monitor) return;

    const scale = monitor.scaleFactor || 1;
    const monitorLogicalW = monitor.size.width / scale;
    const monitorLogicalX = monitor.position.x / scale;
    const monitorLogicalY = monitor.position.y / scale;

    const x = monitorLogicalX + (monitorLogicalW - widthLogical) / 2;
    const y = monitorLogicalY;

    await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}
