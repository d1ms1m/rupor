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
//!
//! Пилюля не должна пропадать, пока Рупор работает:
//! - «поверх всех» подтверждается при каждой смене активного окна (`EVENT_SYSTEM_FOREGROUND`)
//!   и в начале записи (`pill_raise`): полноэкранный RDP тоже «поверх всех», и окно,
//!   активированное позже, иначе закрывало бы пилюлю;
//! - после смены мониторов, разрешения, масштаба или рабочей области (`WM_DISPLAYCHANGE`,
//!   `WM_DPICHANGED`, `WM_SETTINGCHANGE`/`SPI_SETWORKAREA`) пилюля, оказавшаяся вне экранов,
//!   возвращается вниз по центру основного монитора;
//! - упал процесс WebView2 (`ProcessFailed`: страница, GPU) — страница перезагружается, упал
//!   сам браузерный процесс — оболочка перезапускается (без этого прозрачное окно пустое,
//!   а диктовка идёт «невидимо»);
//! - пункт трея «Вернуть пилюлю» — то же вручную: на место, наверх, перезагрузить.

use std::collections::HashMap;
use std::ptr::null_mut;
use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, WebviewWindow};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    GetMonitorInfoW, MonitorFromPoint, MONITORINFO, MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTOPRIMARY,
};
use windows_sys::Win32::UI::Accessibility::{SetWinEventHook, HWINEVENTHOOK};
use windows_sys::Win32::UI::HiDpi::{GetDpiForMonitor, GetDpiForWindow, MDT_EFFECTIVE_DPI};
use windows_sys::Win32::UI::Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, GetWindowLongPtrW, GetWindowRect, IsWindow, IsWindowVisible, PostMessageW,
    SetForegroundWindow, SetWindowLongPtrW, SetWindowPos, EVENT_SYSTEM_FOREGROUND, GWL_EXSTYLE,
    HWND_TOPMOST, MA_NOACTIVATE, SPI_SETWORKAREA, STYLESTRUCT, SWP_FRAMECHANGED, SWP_NOACTIVATE,
    SWP_NOMOVE, SWP_NOOWNERZORDER, SWP_NOSIZE, SWP_NOZORDER, WA_INACTIVE, WINDOWPOS,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS, WM_ACTIVATE, WM_APP, WM_DISPLAYCHANGE,
    WM_DPICHANGED, WM_MOUSEACTIVATE, WM_NCDESTROY, WM_SETTINGCHANGE, WM_STYLECHANGING,
    WM_WINDOWPOSCHANGING, WS_EX_APPWINDOW, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
};

use crate::settings::UiSettings;

pub const LABEL: &str = "pill";
const SUBCLASS_ID: usize = 0x5255_5052; // «RUPR»
const WM_GIVE_BACK_FOCUS: u32 = WM_APP + 0x52;
/// Мониторы или рабочая область изменились — проверить, видна ли пилюля.
const WM_RESCUE: u32 = WM_APP + 0x53;
/// Отступ пилюли над панелью задач, логические пиксели.
const MARGIN_BOTTOM: f64 = 12.0;
/// Браузерный процесс WebView2 упал раньше — оболочку сама не перезапускает (защита от цикла;
/// вручную — пункт трея «Вернуть пилюлю»).
const RESTART_AFTER: Duration = Duration::from_secs(120);
/// Зависание страницы пилюли: перезагрузить, если WebView2 сообщил о нём столько раз за окно
/// (событие повторяется примерно раз в 15 с, пока страница не ответит).
const UNRESPONSIVE_TIMES: usize = 3;
const UNRESPONSIVE_WINDOW: Duration = Duration::from_secs(60);
/// Не больше стольких автоматических перезагрузок окна за окно времени — дальше только журнал.
const RELOADS_MAX: usize = 3;
const RELOADS_WINDOW: Duration = Duration::from_secs(300);

/// HWND пилюли (0 — ещё нет): нужен хуку смены активного окна.
static PILL_HWND: AtomicIsize = AtomicIsize::new(0);
static STARTED: OnceLock<Instant> = OnceLock::new();
static RESTARTING: AtomicBool = AtomicBool::new(false);
/// Браузерный процесс WebView2 умер: окна интерфейса не оживить без перезапуска оболочки.
static BROWSER_DEAD: AtomicBool = AtomicBool::new(false);
static UNRESPONSIVE: Mutex<Vec<Instant>> = Mutex::new(Vec::new());
static RELOADS: OnceLock<Mutex<HashMap<String, Vec<Instant>>>> = OnceLock::new();

/// Настроить пилюлю после создания окна: стили, позиция, видимость, защита от пропадания.
pub fn setup(app: &AppHandle, s: &UiSettings) {
    STARTED.get_or_init(Instant::now);
    let Some(pill) = app.get_webview_window(LABEL) else {
        crate::log_warn!("Окно пилюли не найдено");
        return;
    };
    match pill.hwnd() {
        // SAFETY: окно создано в этом (главном) потоке и живо; хук ставится в нём же —
        // этот поток крутит цикл сообщений Tauri, через него приходят события хука.
        Ok(h) => unsafe {
            let hwnd = h.0 as HWND;
            PILL_HWND.store(hwnd as isize, Ordering::SeqCst);
            install_no_activate(hwnd);
            install_foreground_hook();
        },
        Err(e) => crate::log_warn!("Нет HWND пилюли: {e}"),
    }
    place(app, &pill, s.pill_position);
    if !s.pill_enabled {
        let _ = pill.hide();
    }
    for label in [LABEL, crate::MAIN_LABEL] {
        if let Some(w) = app.get_webview_window(label) {
            watch_webview(app, &w);
        }
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

/// Поднять пилюлю наверх слоя «поверх всех» — без активации; скрытую не трогаем.
pub fn raise() {
    let h = PILL_HWND.load(Ordering::SeqCst);
    if h == 0 {
        return;
    }
    let hwnd = h as HWND;
    // SAFETY: SetWindowPos можно звать из любого потока; окно проверяется на жизнь.
    unsafe {
        if IsWindow(hwnd) != 0 && IsWindowVisible(hwnd) != 0 {
            SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
            );
        }
    }
}

/// Пункт трея «Вернуть пилюлю»: на место по умолчанию (и в настройках — через интерфейс,
/// `tray-action pill_restore`), показать, наверх и перезагрузить страницу — на случай, если
/// её содержимое пропало. WebView2 умер целиком — перезапустить оболочку; пилюля выключена
/// в настройках — открыть настройки.
pub fn restore(app: &AppHandle) {
    if BROWSER_DEAD.load(Ordering::SeqCst) {
        crate::log_warn!("Трей «Вернуть пилюлю»: WebView2 не работает — перезапускаю оболочку");
        restart_shell(app);
        return;
    }
    let Some(pill) = app.get_webview_window(LABEL) else {
        crate::log_warn!("Окно пилюли не найдено");
        return;
    };
    place(app, &pill, None);
    if let Err(e) = app.emit("tray-action", serde_json::json!({ "id": "pill_restore" })) {
        crate::log_warn!("Не удалось отправить tray-action: {e}");
    }
    if !crate::settings::load().pill_enabled {
        crate::log_info!("Трей «Вернуть пилюлю»: пилюля выключена в настройках — открываю их");
        crate::show_main(app, Some("settings".into()));
        return;
    }
    let _ = pill.show();
    raise();
    if let Err(e) = pill.reload() {
        crate::log_warn!("Не удалось перезагрузить пилюлю: {e}");
    }
    crate::log_info!("Пилюля возвращена на место (трей)");
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

/// Позиция окна размером `size` (физ. px) снизу по центру рабочей области
/// `work` = (left, top, right, bottom) с отступом `margin`.
pub fn bottom_center_in(work: (i32, i32, i32, i32), size: (i32, i32), margin: i32) -> (i32, i32) {
    let (l, _t, r, b) = work;
    (l + (r - l - size.0) / 2, b - size.1 - margin)
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

/// Пилюля вне всех мониторов (после смены мониторов, разрешения, масштаба) — вернуть вниз по
/// центру основного; в любом случае — наверх. Только Win32: зовётся из оконной процедуры.
unsafe fn rescue(hwnd: HWND) {
    let mut r: RECT = std::mem::zeroed();
    if GetWindowRect(hwnd, &mut r) == 0 {
        return;
    }
    let center = POINT { x: (r.left + r.right) / 2, y: (r.top + r.bottom) / 2 };
    if !MonitorFromPoint(center, MONITOR_DEFAULTTONULL).is_null() {
        raise();
        return;
    }
    let mon = MonitorFromPoint(POINT { x: 0, y: 0 }, MONITOR_DEFAULTTOPRIMARY);
    let mut mi: MONITORINFO = std::mem::zeroed();
    mi.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
    if GetMonitorInfoW(mon, &mut mi) == 0 {
        return;
    }
    // Размер и отступ — в масштабе основного монитора (окно переедет туда, и tao пересчитает
    // его размер по WM_DPICHANGED)
    let win_dpi = GetDpiForWindow(hwnd).max(1);
    let (mut mx, mut my) = (0u32, 0u32);
    let mon_dpi = if GetDpiForMonitor(mon, MDT_EFFECTIVE_DPI, &mut mx, &mut my) == 0 && mx > 0 {
        mx
    } else {
        win_dpi
    };
    let k = mon_dpi as f64 / win_dpi as f64;
    let size = (
        ((r.right - r.left) as f64 * k).round() as i32,
        ((r.bottom - r.top) as f64 * k).round() as i32,
    );
    let w = &mi.rcWork;
    let (x, y) = bottom_center_in(
        (w.left, w.top, w.right, w.bottom),
        size,
        (MARGIN_BOTTOM * mon_dpi as f64 / 96.0).round() as i32,
    );
    SetWindowPos(hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER);
    crate::log_info!(
        "Пилюля оказалась вне экранов после смены мониторов — вернул вниз по центру основного"
    );
}

/// Хук смены активного окна: после каждой — пилюля снова наверх слоя «поверх всех».
unsafe fn install_foreground_hook() {
    let hook = SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND,
        EVENT_SYSTEM_FOREGROUND,
        null_mut(),
        Some(on_foreground),
        0,
        0,
        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
    );
    if hook.is_null() {
        crate::log_warn!("Не удалось поставить хук смены активного окна для пилюли");
    }
}

unsafe extern "system" fn on_foreground(
    _hook: HWINEVENTHOOK,
    _event: u32,
    _hwnd: HWND,
    _id_object: i32,
    _id_child: i32,
    _thread: u32,
    _time: u32,
) {
    raise();
}

/// Подписаться на падение процессов WebView2 окна: страница или GPU — перезагрузить окно,
/// браузерный процесс — перезапустить оболочку. Без этого упавшее прозрачное окно пустое.
fn watch_webview(app: &AppHandle, win: &WebviewWindow) {
    use webview2_com::Microsoft::Web::WebView2::Win32::COREWEBVIEW2_PROCESS_FAILED_KIND;
    use webview2_com::ProcessFailedEventHandler;

    let label = win.label().to_string();
    let handle = app.clone();
    let res = win.with_webview(move |pw| {
        // SAFETY: COM-вызовы WebView2 — в его (главном) потоке, куда with_webview и зовёт.
        unsafe {
            let core = match pw.controller().CoreWebView2() {
                Ok(c) => c,
                Err(e) => {
                    crate::log_warn!("WebView2 окна {label} недоступен: {e}");
                    return;
                }
            };
            let lbl = label.clone();
            let handler = ProcessFailedEventHandler::create(Box::new(move |_wv, args| {
                let kind = args
                    .map(|a| {
                        let mut k = COREWEBVIEW2_PROCESS_FAILED_KIND(-1);
                        let _ = a.ProcessFailedKind(&mut k);
                        k.0
                    })
                    .unwrap_or(-1);
                on_process_failed(&handle, &lbl, kind);
                Ok(())
            }));
            let mut token = 0i64;
            if let Err(e) = core.add_ProcessFailed(&handler, &mut token) {
                crate::log_warn!("Не удалось подписаться на сбои WebView2 окна {label}: {e}");
            }
        }
    });
    if let Err(e) = res {
        crate::log_warn!("Нет доступа к WebView2 окна {}: {e}", win.label());
    }
}

/// Что делать при сбое процесса WebView2 (`COREWEBVIEW2_PROCESS_FAILED_KIND`).
#[derive(Debug, PartialEq, Eq)]
pub enum Recovery {
    /// Упал браузерный процесс — живых окон интерфейса нет: перезапустить оболочку.
    Restart,
    /// Упала страница окна — перезагрузить окно.
    Reload,
    /// Зависла страница пилюли — перезагрузить, если это повторяется.
    ReloadIfRepeated,
    /// Не фатально: GPU, утилиты, плагины WebView2 поднимает сам (перезагрузка только сбила
    /// бы пилюлю посреди диктовки и состояние главного окна); зависание главного окна ждём.
    Nothing,
}

/// Восстановление по виду сбоя: 0 — браузерный процесс, 1/3 — страница, 2 — зависание
/// страницы, остальное (6 — GPU, 4 — утилиты…) — WebView2 справится сам.
pub fn recovery(kind: i32, pill: bool) -> Recovery {
    match kind {
        0 => Recovery::Restart,
        1 | 3 => Recovery::Reload,
        2 if pill => Recovery::ReloadIfRepeated,
        _ => Recovery::Nothing,
    }
}

/// Отметить событие и сказать, набралось ли `times` за `window` (тогда счётчик обнуляется).
fn repeated(events: &mut Vec<Instant>, now: Instant, times: usize, window: Duration) -> bool {
    events.retain(|t| now.duration_since(*t) < window);
    events.push(now);
    if events.len() >= times {
        events.clear();
        return true;
    }
    false
}

/// Ещё можно перезагрузить окно автоматически (не больше RELOADS_MAX за RELOADS_WINDOW)?
fn reload_allowed(label: &str, now: Instant) -> bool {
    let map = RELOADS.get_or_init(|| Mutex::new(HashMap::new()));
    let mut map = map.lock().unwrap_or_else(|e| e.into_inner());
    let list = map.entry(label.to_string()).or_default();
    list.retain(|t| now.duration_since(*t) < RELOADS_WINDOW);
    if list.len() >= RELOADS_MAX {
        return false;
    }
    list.push(now);
    true
}

fn on_process_failed(app: &AppHandle, label: &str, kind: i32) {
    let what = recovery(kind, label == LABEL);
    crate::log_warn!("Сбой процесса WebView2 окна {label} (вид {kind}) — {what:?}");
    let reload = match what {
        Recovery::Nothing => false,
        Recovery::Reload => true,
        Recovery::ReloadIfRepeated => {
            let mut ev = UNRESPONSIVE.lock().unwrap_or_else(|e| e.into_inner());
            repeated(&mut ev, Instant::now(), UNRESPONSIVE_TIMES, UNRESPONSIVE_WINDOW)
        }
        Recovery::Restart => {
            BROWSER_DEAD.store(true, Ordering::SeqCst);
            let uptime = STARTED.get().map(|t| t.elapsed()).unwrap_or_default();
            if uptime < RESTART_AFTER {
                crate::log_error!(
                    "WebView2 упал сразу после запуска — оболочку сам не перезапускаю \
                     (вручную: трей «Вернуть пилюлю»)"
                );
            } else if !RESTARTING.swap(true, Ordering::SeqCst) {
                restart_shell(app);
            }
            false
        }
    };
    if !reload {
        return;
    }
    if !reload_allowed(label, Instant::now()) {
        crate::log_error!("Окно {label} падает снова и снова — больше не перезагружаю");
        return;
    }
    let app = app.clone();
    let label = label.to_string();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(300));
        if let Some(w) = app.get_webview_window(&label) {
            if let Err(e) = w.reload() {
                crate::log_warn!("Не удалось перезагрузить окно {label}: {e}");
            }
        }
    });
}

/// Запустить новый экземпляр оболочки, который дождётся выхода этого (`--wait-pid`, иначе
/// single-instance отдал бы запуск старому), и выйти. Ядро перезапустится вместе с ней.
fn restart_shell(app: &AppHandle) {
    let exe = match std::env::current_exe() {
        Ok(p) => p,
        Err(e) => {
            crate::log_error!("Не найден путь к Рупору для перезапуска: {e}");
            return;
        }
    };
    let pid = std::process::id().to_string();
    match std::process::Command::new(exe).args(["--wait-pid", &pid]).spawn() {
        Ok(_) => {
            crate::log_warn!("Перезапускаю оболочку после сбоя WebView2");
            crate::quit(app);
        }
        Err(e) => crate::log_error!("Не удалось перезапустить оболочку: {e}"),
    }
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
        // мониторы, разрешение, масштаб, рабочая область — проверить, видна ли пилюля
        // (после того как tao и Windows обработают сообщение — поэтому отложенно)
        WM_DISPLAYCHANGE | WM_DPICHANGED => {
            PostMessageW(hwnd, WM_RESCUE, 0, 0);
        }
        WM_SETTINGCHANGE if wparam as u32 == SPI_SETWORKAREA => {
            PostMessageW(hwnd, WM_RESCUE, 0, 0);
        }
        WM_RESCUE => {
            rescue(hwnd);
            return 0;
        }
        WM_NCDESTROY => {
            PILL_HWND.store(0, Ordering::SeqCst);
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
    fn rescue_position_is_bottom_center_of_work_area() {
        // рабочая область 2752×1104 (панель задач 48 px), пилюля 360×96, отступ 12
        assert_eq!(bottom_center_in((0, 0, 2752, 1104), (360, 96), 12), (1196, 996));
        // монитор слева с отрицательными координатами
        assert_eq!(bottom_center_in((-1920, 0, 0, 1032), (360, 96), 12), (-1140, 924));
        // совпадает с позицией по умолчанию при тех же числах
        assert_eq!(
            bottom_center_in((0, 0, 1920, 1040), (360, 96), 12),
            bottom_center((0, 0, 1920, 1040), 1.0, (360.0, 96.0))
        );
    }

    #[test]
    fn webview_failure_recovery() {
        assert_eq!(recovery(0, true), Recovery::Restart); // браузерный процесс
        assert_eq!(recovery(1, false), Recovery::Reload); // страница упала
        assert_eq!(recovery(2, true), Recovery::ReloadIfRepeated); // пилюля зависла
        assert_eq!(recovery(2, false), Recovery::Nothing); // главное окно — ждём
        assert_eq!(recovery(6, true), Recovery::Nothing); // GPU — WebView2 сам
        assert_eq!(recovery(4, true), Recovery::Nothing); // утилиты
        assert_eq!(recovery(-1, true), Recovery::Nothing);
    }

    #[test]
    fn unresponsive_needs_repeats_and_reloads_are_limited() {
        let t0 = Instant::now();
        let mut ev = Vec::new();
        let w = Duration::from_secs(60);
        assert!(!repeated(&mut ev, t0, 3, w));
        assert!(!repeated(&mut ev, t0 + Duration::from_secs(15), 3, w));
        assert!(repeated(&mut ev, t0 + Duration::from_secs(30), 3, w));
        assert!(ev.is_empty()); // после перезагрузки — с нуля
                                // события дальше окна друг от друга не накапливаются
        assert!(!repeated(&mut ev, t0 + Duration::from_secs(100), 3, w));
        assert!(!repeated(&mut ev, t0 + Duration::from_secs(200), 3, w));
        assert!(!repeated(&mut ev, t0 + Duration::from_secs(300), 3, w));

        let now = Instant::now();
        for _ in 0..RELOADS_MAX {
            assert!(reload_allowed("test-window", now));
        }
        assert!(!reload_allowed("test-window", now));
        assert!(reload_allowed("other-window", now));
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
