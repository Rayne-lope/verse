//! macOS notch geometry + window elevation.
//!
//! Reads NSScreen.safeAreaInsets / auxiliaryTopLeftArea / auxiliaryTopRightArea
//! to compute the notch bounds in logical points, and elevates the Tauri window
//! to NSStatusWindowLevel so it can render OVER the menu bar / notch area.
//!
//! All NSScreen / NSWindow access must run on the main thread — Tauri commands
//! are dispatched on worker threads by default, so we hop via `run_on_main_thread`.

use objc2_app_kit::{
    NSScreen, NSWindow, NSWindowCollectionBehavior, NSWindowLevel,
};
use objc2_foundation::MainThreadMarker;
use serde::Serialize;
use tauri::{AppHandle, Manager, Runtime};

/// NSWindowLevel is a type alias for NSInteger (isize) in objc2-app-kit 0.2.
/// Order: Normal(0) < Floating(3) < Menu(24) < Status(25) < ScreenSaver(1000)
const NS_STATUS_WINDOW_LEVEL: NSWindowLevel = 25;

#[derive(Serialize, Clone, Copy, Debug)]
#[serde(rename_all = "camelCase")]
pub struct NotchGeometry {
    pub has_notch: bool,
    /// Left edge of the notch in logical points relative to the main screen origin.
    pub x: f64,
    /// Top edge — always 0 (notch sits at the very top of the screen).
    pub y: f64,
    /// Notch width in logical points (~190pt on 14"/16" M-series).
    pub width: f64,
    /// Notch height (= safeAreaInsets.top, ~32pt).
    pub height: f64,
    /// Full screen width in logical points.
    pub screen_width: f64,
    /// Full screen height in logical points.
    pub screen_height: f64,
    /// Menu bar height in logical points (used for fallback positioning on non-notch displays).
    pub menu_bar_height: f64,
}

impl NotchGeometry {
    fn fallback_no_notch(screen_width: f64, screen_height: f64, menu_bar_height: f64) -> Self {
        Self {
            has_notch: false,
            x: (screen_width - 190.0) / 2.0,
            y: 0.0,
            width: 190.0,
            height: 32.0,
            screen_width,
            screen_height,
            menu_bar_height,
        }
    }

    fn unknown() -> Self {
        Self {
            has_notch: false,
            x: 0.0,
            y: 0.0,
            width: 190.0,
            height: 32.0,
            screen_width: 1440.0,
            screen_height: 900.0,
            menu_bar_height: 24.0,
        }
    }
}

/// Public Tauri command: query notch geometry. Runs on main thread.
#[tauri::command]
pub async fn get_notch_geometry<R: Runtime>(app: AppHandle<R>) -> Result<NotchGeometry, String> {
    let (tx, rx) = std::sync::mpsc::channel();
    app.run_on_main_thread(move || {
        let geom = read_notch_geometry_on_main().unwrap_or_else(NotchGeometry::unknown);
        let _ = tx.send(geom);
    })
    .map_err(|e| e.to_string())?;
    rx.recv().map_err(|e| e.to_string())
}

/// Public Tauri command: elevate the main window above the menu bar / notch.
#[tauri::command]
pub async fn elevate_above_menu_bar<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window not found".to_string())?;

    // ns_window() returns *mut c_void; we need to access it on the main thread.
    let ns_window_ptr = window.ns_window().map_err(|e| e.to_string())? as *mut NSWindow;
    if ns_window_ptr.is_null() {
        return Err("ns_window pointer is null".into());
    }

    let (tx, rx) = std::sync::mpsc::channel();
    let ptr_addr = ns_window_ptr as usize;
    app.run_on_main_thread(move || {
        // Safety: we're on the main thread; the NSWindow lives as long as the Tauri window.
        let ns_window: &NSWindow = unsafe { &*(ptr_addr as *const NSWindow) };
        unsafe {
            ns_window.setLevel(NS_STATUS_WINDOW_LEVEL);
            let behavior = NSWindowCollectionBehavior::CanJoinAllSpaces
                | NSWindowCollectionBehavior::FullScreenAuxiliary
                | NSWindowCollectionBehavior::Stationary
                | NSWindowCollectionBehavior::IgnoresCycle;
            ns_window.setCollectionBehavior(behavior);
        }
        let _ = tx.send(());
    })
    .map_err(|e| e.to_string())?;
    rx.recv().map_err(|e| e.to_string())
}

/// Read NSScreen geometry. MUST be called on main thread (caller dispatches via run_on_main_thread).
fn read_notch_geometry_on_main() -> Option<NotchGeometry> {
    // SAFETY: caller guarantees we're on main thread via run_on_main_thread dispatch.
    let mtm = unsafe { MainThreadMarker::new_unchecked() };

    // NOTE: objc2-foundation 0.2 has a known bug where NSArray::count() trips a
    // type-mismatch panic on `NSScreen::screens()` (returns NSUInteger 'Q' but
    // the binding declares NSInteger 'q'). Avoid iterating screens for now.
    // For macOS with notch, mainScreen() returns the built-in display when the
    // app's key window is on it — which is true at startup.
    let screen = NSScreen::mainScreen(mtm)?;

    let frame = screen.frame();
    let visible = screen.visibleFrame();
    // visibleFrame excludes menu bar + dock; menu bar height ≈ frame.height - visible.height
    // (this also subtracts dock if at top, but on macOS dock is bottom/side by default)
    let menu_bar_height = (frame.size.height - visible.size.height - visible.origin.y).max(24.0);

    let insets = unsafe { screen.safeAreaInsets() };

    if insets.top <= 0.0 {
        return Some(NotchGeometry::fallback_no_notch(
            frame.size.width,
            frame.size.height,
            menu_bar_height,
        ));
    }

    // Has notch: query auxiliary areas. These return CGRect directly in 0.2; on a
    // display without a notch they'd be zero-rects, but we already guarded above.
    let aux_left = unsafe { screen.auxiliaryTopLeftArea() };
    let aux_right = unsafe { screen.auxiliaryTopRightArea() };

    let nx = aux_left.size.width;
    let nw = (frame.size.width - aux_left.size.width - aux_right.size.width).max(0.0);
    // Sanity: if both aux are zero, fall back to centered ~190pt notch.
    let (notch_x, notch_width) = if aux_left.size.width <= 0.1 && aux_right.size.width <= 0.1 {
        let w = 190.0_f64;
        ((frame.size.width - w) / 2.0, w)
    } else {
        (nx, nw)
    };

    Some(NotchGeometry {
        has_notch: true,
        x: notch_x,
        y: 0.0,
        width: notch_width,
        height: insets.top,
        screen_width: frame.size.width,
        screen_height: frame.size.height,
        menu_bar_height,
    })
}
