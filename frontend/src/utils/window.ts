export async function resizeWindow(width: number, height: number): Promise<void> {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const { LogicalSize } = await import("@tauri-apps/api/dpi");
    await getCurrentWindow().setSize(new LogicalSize(width, height));
  } catch {
    // browser preview or non-Tauri env — ignore
  }
}
