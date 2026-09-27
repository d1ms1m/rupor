//! Пилюля — плавающее окно поверх всех окон, которое **никогда не забирает фокус**
//! (иначе распознанный текст напечатается в неё, а не в окно пользователя).
//!
//! Как это обеспечивается:
//! - в tauri.conf.json у окна `focus: false` (первый показ — `SW_SHOWNOACTIVATE`) и
//!   `focusable: false` (tao держит `WS_EX_NOACTIVATE`);
//! - после создания ставим `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` (нет в Alt+Tab и на панели задач);
//! - сабклассинг окна: tao переписывает `GWL_EXSTYLE` при любой смене своих флагов
//!   (например, `setIgnoreCursorEvents`), поэтому в `WM_STYLECHANGING` нужные биты
//!   возвращаются; `WM_MOUSEACTIVATE` → `MA_NOACTIVATE`; `WM_WINDOWPOSCHANGING` → `SWP_NOACTIVATE`;
//!   если окно всё же активировали (например, WebView2 взял фокус), активность сразу
//!   возвращается окну, у которого её отняли.

use std::ptr::null_mut;

use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows_sys::Win32::UI::Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, GetWindowLongPtrW, IsWindow, PostMessageW, SetForegroundWindow,
    SetWindowLongPtrW, SetWindowPos, GWL_EXSTYLE, MA_NOACTIVATE, STYLESTRUCT, SWP_FRAMECHANGED,
    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, WA_INACTIVE, WINDOWPOS, WM_ACTIVATE,
    WM_APP, WM_MOUSEACTIVATE, WM_NCDESTROY, WM_STYLECHANGING, WM_WINDOWPOSCHANGING,
    WS_EX_APPWINDOW, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
};

use crate::settings::UiSettings;

pub const LABEL: &str = "pill";
const SUBCLASS_ID: usize = 0x5255_5052; // «RUPR»
const WM_GIVE_BACK_FOCUS: u32 = WM_APP + 0x52;
/// Отступ пилюли над панелью задач, логические пиксели.
const MARGIN_BOTTOM: f64 = 12.0;

/// Настроить пилюлю после создания окна: стили, позиция, видимость.
pub fn setup(app: &AppHandle, s: &UiSettings) {
    let Some(pill) = app.get_webview_window(LABEL) else {
        crate::log_warn!("Окно пилюли не найдено");
        return;
    };
    match pill.hwnd() {
        // SAFETY: окно создано в этом (главном) потоке и живо.
        Ok(h) => unsafe { install_no_activate(h.0 as HWND) },
        Err(e) => crate::log_warn!("Нет HWND пилюли: {e}"),
    }
    place(app, &pill, s.pill_position);
    if !s.pill_enabled {
        let _ = pill.hide();
    }
}

/// Команда `reset_pill_position`: вернуть пилюлю вниз по центру основного монитора.
pub fn reset_position(app: &AppHandle) -> Result<(), String> {
    let pill = app.get_webview_window(LABEL).ok_or(crate::i18n::t().pill_not_found)?;
    place(app, &pill, None);
    Ok(())
}

/// Команда `set_pill_passthrough`: пропускать клики мыши сквозь пилюлю.
pub fn set_passthrough(app: &AppHandle, on: bool) -> Result<(), String> {
    let pill = app.get_webview_window(LABEL).ok_or(crate::i18n::t().pill_not_found)?;
    pill.set_ignore_cursor_events(on).map_err(|e| e.to_string())
}

fn place(app: &AppHandle, pill: &WebviewWindow, saved: Option<(i32, i32)>) {
    if let Some((x, y)) = saved {
        let size = pill.outer_size().unwrap_or(PhysicalSize::new(360, 96));
        if on_some_monitor(pill, x, y, size) {
            let _ = pill.set_position(PhysicalPosition::new(x, y));
            return;
        }
        crate::log_info!("Сохранённая позиция пилюли ({x}, {y}) вне экранов — ставлю по умолчанию");
    }
    match default_position(app, pill) {
        Some(p) => {
            let _ = pill.set_position(p);
        }
        None => crate::log_warn!("Не удалось определить основной монитор для пилюли"),
    }
}

/// Размер пилюли в логических пикселях — из tauri.conf.json.
fn logical_size(app: &AppHandle) -> (f64, f64) {
    app.config()
        .app
        .windows
        .iter()
        .find(|w| w.label == LABEL)
        .map(|w| (w.width, w.height))
        .unwrap_or((360.0, 96.0))
}

/// Снизу по центру рабочей области основного монитора (над панелью задач).
fn default_position(app: &AppHandle, pill: &WebviewWindow) -> Option<PhysicalPosition<i32>> {
    let mon = pill.primary_monitor().ok().flatten()?;
    let wa = mon.work_area();
    let (lw, lh) = logical_size(app);
    let (x, y) = bottom_center(
        (wa.position.x, wa.position.y, wa.size.width, wa.size.height),
        mon.scale_factor(),
        (lw, lh),
    );
    Some(PhysicalPosition::new(x, y))
}

/// Чистая арифметика позиции по умолчанию: `work_area` = (x, y, ширина, высота) в физических px.
pub fn bottom_center(
    work_area: (i32, i32, u32, u32),
    scale: f64,
    logical: (f64, f64),
) -> (i32, i32) {
    let (wx, wy, ww, wh) = work_area;
    let w = (logical.0 * scale).round() as i32;
    let h = (logical.1 * scale).round() as i32;
    let margin = (MARGIN_BOTTOM * scale).round() as i32;
    (wx + (ww as i32 - w) / 2, wy + wh as i32 - h - margin)
}

/// Центр пилюли попадает на какой-нибудь монитор?
fn on_some_monitor(pill: &WebviewWindow, x: i32, y: i32, size: PhysicalSize<u32>) -> bool {
    let cx = x + size.width as i32 / 2;
    let cy = y + size.height as i32 / 2;
    pill.available_monitors()
        .map(|mons| {
            mons.iter().any(|m| {
                let p = m.position();
                let s = m.size();
                cx >= p.x && cy >= p.y && cx < p.x + s.width as i32 && cy < p.y + s.height as i32
            })
        })
        .unwrap_or(true)
}

/// Навсегда запретить окну активироваться. Вызывать в потоке, владеющем окном.
unsafe fn install_no_activate(hwnd: HWND) {
    if SetWindowSubclass(hwnd, Some(subclass_proc), SUBCLASS_ID, 0) == 0 {
        crate::log_warn!("Не удалось установить сабкласс окна пилюли");
    }
    let ex = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) as u32;
    SetWindowLongPtrW(hwnd, GWL_EXSTYLE, no_activate_style(ex) as isize);
    SetWindowPos(
        hwnd,
        null_mut(),
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    );
}

/// Расширенный стиль пилюли: не активируется, служебное окно, без кнопки на панели задач.
pub fn no_activate_style(ex: u32) -> u32 {
    (ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & !WS_EX_APPWINDOW
}

unsafe extern "system" fn subclass_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    _id: usize,
    _data: usize,
) -> LRESULT {
    match msg {
        // клик мышью не активирует окно (сам клик до страницы доходит)
        WM_MOUSEACTIVATE => return MA_NOACTIVATE as LRESULT,
        // tao пересчитывает GWL_EXSTYLE из своих флагов — возвращаем наши биты
        WM_STYLECHANGING if wparam as i32 == GWL_EXSTYLE => {
            if let Some(ss) = (lparam as *mut STYLESTRUCT).as_mut() {
                ss.styleNew = no_activate_style(ss.styleNew);
            }
        }
        // любые перемещения/показы — без активации
        WM_WINDOWPOSCHANGING => {
            if let Some(wp) = (lparam as *mut WINDOWPOS).as_mut() {
                wp.flags |= SWP_NOACTIVATE;
            }
        }
        // если окно всё же стало активным — вернуть активность прежнему окну
        WM_ACTIVATE => {
            if (wparam & 0xFFFF) as u32 != WA_INACTIVE && lparam != 0 {
                PostMessageW(hwnd, WM_GIVE_BACK_FOCUS, 0, lparam);
            }
        }
        WM_GIVE_BACK_FOCUS => {
            let prev = lparam as HWND;
            if prev != hwnd && IsWindow(prev) != 0 && GetForegroundWindow() == hwnd {
                SetForegroundWindow(prev);
            }
            return 0;
        }
        WM_NCDESTROY => {
            RemoveWindowSubclass(hwnd, Some(subclass_proc), SUBCLASS_ID);
        }
        _ => {}
    }
    DefSubclassProc(hwnd, msg, wparam, lparam)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_position_is_bottom_center() {
        // 1920×1040 рабочая область (панель задач 40 px), масштаб 100 %
        assert_eq!(bottom_center((0, 0, 1920, 1040), 1.0, (360.0, 96.0)), (780, 1040 - 96 - 12));
        // 150 %: 2560×1392, пилюля 540×144, отступ 18
        assert_eq!(bottom_center((0, 0, 2560, 1392), 1.5, (360.0, 96.0)), (1010, 1392 - 144 - 18));
        // основной монитор не в (0,0) и панель задач сверху
        assert_eq!(
            bottom_center((-1920, 48, 1920, 1032), 1.0, (360.0, 96.0)),
            (-1140, 48 + 1032 - 108)
        );
    }

    #[test]
    fn style_bits() {
        let s = no_activate_style(WS_EX_APPWINDOW | 0x8 /* WS_EX_TOPMOST */);
        assert_eq!(s & WS_EX_APPWINDOW, 0);
        assert_ne!(s & WS_EX_NOACTIVATE, 0);
        assert_ne!(s & WS_EX_TOOLWINDOW, 0);
        assert_ne!(s & 0x8, 0);
    }
}
