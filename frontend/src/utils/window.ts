/** Called on startup in widget mode to lock the window to island container size. */
export async function lockWidgetMode(width: number, height: number): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    await win.setResizable(false);
    await win.setAlwaysOnTop(true);
    await win.setVisibleOnAllWorkspaces(true);
    await win.setSize(new LogicalSize(width, height));
    await positionTopCenter(width);
  } catch {
    // browser preview or non-Tauri env — ignore
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

export async function setFullscreen(fullscreen: boolean, widgetWidth: number = 600, widgetHeight: number = 280): Promise<void> {
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
      await positionTopCenter(widgetWidth);
      // Lock back to widget behaviour
      await win.setResizable(false);
      await win.setAlwaysOnTop(true);
      await win.setVisibleOnAllWorkspaces(true);
    }
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}

/** Position the window at the top-center of the active monitor (Dynamic Island style).
 *  Uses logical units throughout to avoid Retina/scale-factor mismatches. */
export async function positionTopCenter(widthLogical: number): Promise<void> {
  try {
    const { getCurrentWindow, currentMonitor } = await import("@tauri-apps/api/window");
    const { LogicalPosition } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    const monitor = await currentMonitor();
    if (!monitor) return;

    const scale = monitor.scaleFactor || 1;
    // monitor.size and monitor.position are PHYSICAL; convert to logical for setPosition
    const monitorLogicalW = monitor.size.width / scale;
    const monitorLogicalX = monitor.position.x / scale;
    const monitorLogicalY = monitor.position.y / scale;

    const x = monitorLogicalX + (monitorLogicalW - widthLogical) / 2;
    const y = monitorLogicalY; // flush with top of screen

    await win.setPosition(new LogicalPosition(Math.round(x), Math.round(y)));
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}

/** Legacy — kept for backwards compatibility if any caller still references it. */
export async function positionTopRight(width: number): Promise<void> {
  try {
    const { getCurrentWindow, currentMonitor } = await import("@tauri-apps/api/window");
    const { PhysicalPosition } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    const monitor = await currentMonitor();
    if (monitor) {
      const scaleFactor = monitor.scaleFactor;
      const monitorWidth = monitor.size.width;
      const monitorX = monitor.position.x;
      const monitorY = monitor.position.y;

      const margin = 24 * scaleFactor;
      const x = monitorX + monitorWidth - (width * scaleFactor) - margin;
      const y = monitorY + margin;

      await win.setPosition(new PhysicalPosition(Math.max(monitorX, Math.round(x)), Math.round(y)));
    }
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}
