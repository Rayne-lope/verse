export async function resizeWindow(width: number, height: number): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize } = await import("@tauri-apps/api/dpi");
    await getCurrentWindow().setSize(new LogicalSize(width, height));
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}

export async function setFullscreen(fullscreen: boolean): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setFullscreen(fullscreen);
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


