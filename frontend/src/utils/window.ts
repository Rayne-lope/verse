/** Called on startup in widget mode to lock the window to bubble size. */
export async function lockWidgetMode(width: number, height: number): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize } = await import("@tauri-apps/api/dpi");
    const win = getCurrentWindow();
    await win.setResizable(false);
    await win.setAlwaysOnTop(true);
    await win.setVisibleOnAllWorkspaces(true);
    await win.setSize(new LogicalSize(width, height));
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

export async function setFullscreen(fullscreen: boolean, bubbleWidth: number = 180): Promise<void> {
  try {
    const { getCurrentWindow, currentMonitor } = await import("@tauri-apps/api/window");
    const { PhysicalSize, PhysicalPosition } = await import("@tauri-apps/api/dpi");
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
      if (monitor) {
        const { scaleFactor } = monitor;
        const size = Math.round(bubbleWidth * scaleFactor);

        await win.setSize(new PhysicalSize(size, size));
        await positionTopRight(bubbleWidth);
        // Lock back to widget behaviour
        await win.setResizable(false);
        await win.setAlwaysOnTop(true);
        await win.setVisibleOnAllWorkspaces(true);
      }
    }
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}

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


