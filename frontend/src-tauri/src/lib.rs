use tauri::{AppHandle, Listener, Manager, PhysicalPosition, WebviewWindow};

#[cfg(target_os = "macos")]
mod macos_notch;

const MAIN_WINDOW_LABEL: &str = "main";
const WINDOW_MARGIN: i32 = 24;

#[tauri::command]
fn show_verse_window(app: AppHandle) -> Result<(), String> {
    let window = main_window(&app)?;
    configure_floating_window(&window)?;
    position_top_right(&window)?;
    window.show().map_err(|error| error.to_string())
}

#[tauri::command]
fn hide_verse_window(app: AppHandle) -> Result<(), String> {
    main_window(&app)?
        .hide()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn toggle_verse_window(app: AppHandle) -> Result<(), String> {
    let window = main_window(&app)?;
    if window.is_visible().map_err(|error| error.to_string())? {
        window.hide().map_err(|error| error.to_string())
    } else {
        configure_floating_window(&window)?;
        position_top_right(&window)?;
        window.show().map_err(|error| error.to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let app_handle = app.handle().clone();
            if let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) {
                configure_floating_window(&window)?;
                // Don't force position_top_right here — JS will call positionAtNotch()
                // on mount with proper notch geometry. Falls back gracefully if not macOS.

                #[cfg(target_os = "macos")]
                {
                    // Re-elevate above menu bar on focus events to work around tauri#5566
                    // where setLevel sometimes resets after fullscreen transitions.
                    let elevate_handle = app_handle.clone();
                    window.on_window_event(move |event| {
                        if let tauri::WindowEvent::Focused(true) = event {
                            let h = elevate_handle.clone();
                            tauri::async_runtime::spawn(async move {
                                let _ = macos_notch::elevate_above_menu_bar(h).await;
                            });
                        }
                    });
                }
            }

            let show_handle = app_handle.clone();
            app.listen("verse://window/show", move |_| {
                let _ = show_verse_window(show_handle.clone());
            });

            let hide_handle = app_handle.clone();
            app.listen("verse://window/hide", move |_| {
                let _ = hide_verse_window(hide_handle.clone());
            });

            app.listen("verse://window/toggle", move |_| {
                let _ = toggle_verse_window(app_handle.clone());
            });

            Ok(())
        })
        .invoke_handler({
            #[cfg(target_os = "macos")]
            {
                tauri::generate_handler![
                    show_verse_window,
                    hide_verse_window,
                    toggle_verse_window,
                    macos_notch::get_notch_geometry,
                    macos_notch::elevate_above_menu_bar,
                ]
            }
            #[cfg(not(target_os = "macos"))]
            {
                tauri::generate_handler![
                    show_verse_window,
                    hide_verse_window,
                    toggle_verse_window,
                ]
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn main_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or_else(|| "Verse main window is not available".to_string())
}

fn configure_floating_window(window: &WebviewWindow) -> Result<(), String> {
    window
        .set_decorations(false)
        .map_err(|error| error.to_string())?;
    window
        .set_always_on_top(true)
        .map_err(|error| error.to_string())?;
    window
        .set_visible_on_all_workspaces(true)
        .map_err(|error| error.to_string())?;
    Ok(())
}

fn position_top_right(window: &WebviewWindow) -> Result<(), String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window.primary_monitor().map_err(|error| error.to_string())?);

    let Some(monitor) = monitor else {
        return Ok(());
    };

    let monitor_position = monitor.position();
    let monitor_size = monitor.size();
    let window_size = window.outer_size().map_err(|error| error.to_string())?;

    let x = monitor_position.x
        + monitor_size.width as i32
        - window_size.width as i32
        - WINDOW_MARGIN;
    let y = monitor_position.y + WINDOW_MARGIN;

    window
        .set_position(PhysicalPosition::new(x.max(monitor_position.x), y))
        .map_err(|error| error.to_string())
}
