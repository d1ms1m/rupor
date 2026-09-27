//! Простой журнал оболочки: `%APPDATA%\Rupor\logs\ui.log` с ротацией (1 МБ × 2 файла).
//! Ядро пишет свой журнал (`rupor.log`) само. Секреты (токен ядра) сюда не пишутся.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;

const MAX_BYTES: u64 = 1_000_000;

static LOCK: Mutex<()> = Mutex::new(());

/// Папка данных Рупора — та же, что у ядра (`config.app_dir()`).
pub fn app_dir() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("USERPROFILE").map(PathBuf::from))?;
    Some(base.join("Rupor"))
}

fn log_path() -> Option<PathBuf> {
    let dir = app_dir()?.join("logs");
    fs::create_dir_all(&dir).ok()?;
    Some(dir.join("ui.log"))
}

fn timestamp() -> String {
    use windows_sys::Win32::Foundation::SYSTEMTIME;
    use windows_sys::Win32::System::SystemInformation::GetLocalTime;
    // SAFETY: GetLocalTime только заполняет переданную структуру.
    let t = unsafe {
        let mut t: SYSTEMTIME = std::mem::zeroed();
        GetLocalTime(&mut t);
        t
    };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02},{:03}",
        t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, t.wMilliseconds
    )
}

/// Записать строку журнала. Ошибки записи игнорируются — журнал не должен ронять приложение.
pub fn write(level: &str, msg: &str) {
    let line = format!("{} {} ui: {}\r\n", timestamp(), level, msg);
    if cfg!(debug_assertions) {
        eprint!("{line}");
    }
    if cfg!(test) {
        return; // тесты не пишут в журнал пользователя
    }
    let _guard = LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let Some(path) = log_path() else { return };
    if fs::metadata(&path).map(|m| m.len() > MAX_BYTES).unwrap_or(false) {
        let _ = fs::rename(&path, path.with_extension("log.1"));
    }
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&path) {
        let _ = f.write_all(line.as_bytes());
    }
}
