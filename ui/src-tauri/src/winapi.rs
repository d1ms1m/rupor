//! Обёртки над Win32: UAC-перезапуск, ожидание процесса, job object для ядра, MessageBox,
//! проверка именованного мьютекса.

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::ptr::{null, null_mut};
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ACCESS_DENIED, HANDLE, HWND,
};
use windows_sys::Win32::System::Com::{
    CoInitializeEx, CoUninitialize, COINIT_APARTMENTTHREADED, COINIT_DISABLE_OLE1DDE,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{
    OpenMutexW, OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE, SYNCHRONIZATION_SYNCHRONIZE,
};
use windows_sys::Win32::UI::Shell::ShellExecuteW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetForegroundWindow, MessageBoxW, MB_ICONERROR, MB_OK, MB_SETFOREGROUND, SW_SHOWNORMAL,
};

/// Строка → UTF-16 с завершающим нулём.
pub fn wide(s: impl AsRef<OsStr>) -> Vec<u16> {
    s.as_ref().encode_wide().chain(std::iter::once(0)).collect()
}

/// Есть ли в системе именованный мьютекс (его держит какой-то процесс).
/// Нет доступа (мьютекс создан процессом администратора) — тоже «есть».
pub fn named_mutex_exists(name: &str) -> bool {
    let name = wide(name);
    // SAFETY: строка живёт до конца вызова; дескриптор проверяется и закрывается.
    unsafe {
        let h = OpenMutexW(SYNCHRONIZATION_SYNCHRONIZE, 0, name.as_ptr());
        if h.is_null() {
            return GetLastError() == ERROR_ACCESS_DENIED;
        }
        CloseHandle(h);
        true
    }
}

/// Подождать (не дольше `timeout`), пока окно `hwnd` станет активным. Запрос UAC появляется
/// сразу, только если окно-владелец на переднем плане; иначе Windows лишь мигает кнопкой
/// на панели задач. Окна Tauri показываются асинхронно — поэтому ждём.
pub fn wait_foreground(hwnd: isize, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        // SAFETY: функция без аргументов, только читает состояние.
        if unsafe { GetForegroundWindow() } as isize == hwnd {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Аргумент командной строки по правилам Windows (CommandLineToArgvW, разбор аргументов Rust
/// и MSVC): кавычки вокруг пробелов, `\"` для кавычек, удвоение обратных косых перед ними.
pub fn quote_arg(arg: &str) -> String {
    if !arg.is_empty() && !arg.contains([' ', '\t', '\n', '\x0b', '"']) {
        return arg.to_string();
    }
    let mut out = String::with_capacity(arg.len() + 2);
    out.push('"');
    let mut backslashes = 0usize;
    for c in arg.chars() {
        match c {
            '\\' => backslashes += 1,
            '"' => {
                out.push_str(&"\\".repeat(backslashes * 2 + 1));
                out.push('"');
                backslashes = 0;
            }
            _ => {
                out.push_str(&"\\".repeat(backslashes));
                out.push(c);
                backslashes = 0;
            }
        }
    }
    out.push_str(&"\\".repeat(backslashes * 2));
    out.push('"');
    out
}

/// Запустить `exe` с правами администратора (UAC, глагол `runas`). `owner` — HWND окна,
/// над которым должен появиться запрос UAC (0 — без владельца).
/// Блокирует поток до ответа пользователя в окне UAC — вызывать не из главного потока.
pub fn shell_execute_runas(owner: isize, exe: &Path, params: &str) -> Result<(), String> {
    let verb = wide("runas");
    let file = wide(exe.as_os_str());
    let params = wide(params);
    let dir = exe.parent().map(|d| wide(d.as_os_str()));
    // SAFETY: все строки живут до конца вызова; COM инициализируется и освобождается
    // в этом же потоке (ShellExecute может делегировать работу расширениям оболочки).
    let code = unsafe {
        let hr = CoInitializeEx(null(), (COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE) as u32);
        let r = ShellExecuteW(
            owner as HWND,
            verb.as_ptr(),
            file.as_ptr(),
            params.as_ptr(),
            dir.as_ref().map_or(null(), |d| d.as_ptr()),
            SW_SHOWNORMAL,
        ) as isize;
        if hr >= 0 {
            CoUninitialize();
        }
        r
    };
    if code > 32 {
        return Ok(());
    }
    // 5 — SE_ERR_ACCESSDENIED: пользователь нажал «Нет» в окне UAC.
    let t = crate::i18n::t();
    if code == 5 || code == 1223 {
        Err(t.relaunch_cancelled.into())
    } else {
        Err(crate::i18n::fill(t.relaunch_failed, &[("code", &code)]))
    }
}

/// Подождать завершения процесса `pid` (не дольше `timeout`). Нужен при перезапуске
/// от администратора: новый экземпляр ждёт, пока старый освободит single-instance и ядро.
pub fn wait_process_exit(pid: u32, timeout: Duration) {
    // SAFETY: дескриптор проверяется на null и закрывается.
    unsafe {
        let h = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
        if h.is_null() {
            return; // процесса уже нет
        }
        WaitForSingleObject(h, timeout.as_millis().min(u32::MAX as u128) as u32);
        CloseHandle(h);
    }
}

/// Окно с ошибкой (когда интерфейс не поднялся и показать её больше негде).
pub fn error_box(text: &str) {
    let title = wide(crate::i18n::t().tray.app);
    let text = wide(text);
    // SAFETY: строки живут до конца вызова.
    unsafe {
        MessageBoxW(
            null_mut(),
            text.as_ptr(),
            title.as_ptr(),
            MB_OK | MB_ICONERROR | MB_SETFOREGROUND,
        );
    }
}

/// Job object с `KILL_ON_JOB_CLOSE`: всё, что в него помещено (ядро и его дочерние процессы),
/// Windows завершит вместе с Рупором, даже если оболочка упадёт.
pub struct Job(HANDLE);

// SAFETY: дескриптор job object можно использовать из любого потока.
unsafe impl Send for Job {}
unsafe impl Sync for Job {}

impl Job {
    pub fn new() -> Option<Job> {
        // SAFETY: структура инициализирована нулями, размер передаётся точный.
        unsafe {
            let h = CreateJobObjectW(null(), null());
            if h.is_null() {
                return None;
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                h,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const core::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );
            if ok == 0 {
                CloseHandle(h);
                return None;
            }
            Some(Job(h))
        }
    }

    /// Поместить процесс в job. `process` — сырой дескриптор (`Child::as_raw_handle`).
    pub fn assign(&self, process: HANDLE) -> bool {
        // SAFETY: оба дескриптора действительны на момент вызова.
        unsafe { AssignProcessToJobObject(self.0, process) != 0 }
    }

    /// Завершить все процессы в job (ядро и всё, что оно запустило).
    pub fn terminate(&self) {
        // SAFETY: дескриптор job действителен, пока жив `self`.
        unsafe {
            TerminateJobObject(self.0, 1);
        }
    }
}

impl Drop for Job {
    fn drop(&mut self) {
        // SAFETY: дескриптор принадлежит нам и закрывается один раз.
        unsafe {
            CloseHandle(self.0);
        }
    }
}

/// Разбор командной строки так, как его сделает Windows для нового процесса (CommandLineToArgvW).
#[cfg(test)]
pub fn command_line_to_argv(cmdline: &str) -> Vec<String> {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::UI::Shell::CommandLineToArgvW;
    let w = wide(cmdline);
    let mut n = 0i32;
    // SAFETY: строка живёт до конца вызова; массив освобождается LocalFree.
    unsafe {
        let argv = CommandLineToArgvW(w.as_ptr(), &mut n);
        assert!(!argv.is_null());
        let out = (0..n as usize)
            .map(|i| {
                let p = *argv.add(i);
                let len = (0..).take_while(|&j| *p.add(j) != 0).count();
                String::from_utf16_lossy(std::slice::from_raw_parts(p, len))
            })
            .collect();
        LocalFree(argv as _);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows_sys::Win32::System::Threading::CreateMutexW;

    fn parse(cmdline: &str) -> Vec<String> {
        command_line_to_argv(cmdline)
    }

    #[test]
    fn quoted_args_round_trip() {
        let args = [
            "--core-args",
            "--no-hook --no-mutex -v",
            r#""C:\Program Files\py.exe" -m rupor"#,
            r"C:\dir with space\",
            r"a\\b",
            r#"\\"quoted\\""#,
            "",
            r#"x\"y"#,
            "простой",
        ];
        let line = std::iter::once("rupor.exe".to_string())
            .chain(args.iter().map(|a| quote_arg(a)))
            .collect::<Vec<_>>()
            .join(" ");
        assert_eq!(parse(&line)[1..], args.map(String::from));
        assert_eq!(quote_arg("--elevated"), "--elevated");
    }

    #[test]
    fn named_mutex_is_detected() {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let name = format!("Local\\RuporTest-{}-{nanos}", std::process::id());
        assert!(!named_mutex_exists(&name));
        let w = wide(&name);
        // SAFETY: строка живёт до конца вызова, дескриптор закрывается.
        let h = unsafe { CreateMutexW(null(), 0, w.as_ptr()) };
        assert!(!h.is_null());
        assert!(named_mutex_exists(&name));
        // SAFETY: дескриптор наш и закрывается один раз.
        unsafe { CloseHandle(h) };
        assert!(!named_mutex_exists(&name));
    }
}
