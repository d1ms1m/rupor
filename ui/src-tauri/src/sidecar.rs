//! Супервизор Python-ядра: запуск, ожидание готовности, перезапуск с паузой, остановка.
//!
//! Контракт (docs/ARCHITECTURE.md, «Процессы»):
//! - порт — свободный порт 127.0.0.1 (bind :0 → закрыть), токен — 32 hex;
//! - аргументы ядра: `--sidecar --ws-port <p> --token <t> --ui-pid <pid>`;
//! - поиск ядра: `RUPOR_CORE` → `<resource_dir>/core/rupor-core.exe` → (debug) `.venv` + `-m rupor`;
//! - `CREATE_NO_WINDOW`, stdio → null;
//! - ядро умерло не по «Выходу» → перезапуск через 1 / 3 / 10 с (счётчик сбрасывается после 60 с
//!   стабильной работы), событие `core-restarted` во все окна, новые порт и токен;
//! - выход: готовому ядру — WS `quit`, ожидание выхода до [`GRACEFUL_EXIT`], потом `kill`
//!   (ядро успевает вернуть звук других приложений, приглушённый на время записи).
//!
//! Расширение контракта: ядро, которое выходит, так и не открыв порт, не перезапускается
//! бесконечно. Если мьютекс ядра занят (работает другой Рупор, например старая версия из
//! автозагрузки) — статус «уже запущен другой Рупор», новый запуск — когда тот закроется.
//! Иначе после [`MAX_EARLY_EXITS`] таких выходов подряд — статус «ядро не запускается»
//! и попытка раз в минуту; причина (последняя ошибка из журнала ядра) — в `backend_info`.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::i18n::{self, fill};
use crate::tray::CoreStatus;
use crate::winapi::Job;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// Мьютекс единственного экземпляра ядра (`_MUTEX_NAME` в core/rupor/__main__.py).
pub const CORE_MUTEX: &str = "Local\\RuporSingleInstance";
/// Сколько запусков подряд ядро может завершиться, не став готовым, прежде чем
/// считаться «не запускается».
pub const MAX_EARLY_EXITS: usize = 3;
/// Сколько `backend_info` ждёт готовности ядра.
pub const READY_TIMEOUT: Duration = Duration::from_secs(30);
const POLL: Duration = Duration::from_millis(150);
const PROBE_TIMEOUT: Duration = Duration::from_millis(250);
/// Сколько байт журнала ядра читать в поисках причины выхода.
const LOG_TAIL: u64 = 64 * 1024;
/// Выход: сколько ждать, пока ядро завершится само по WS-команде `quit`. Ядро первым делом
/// возвращает громкость других приложений, приглушённых на время записи (ждёт до 2 с), —
/// после `kill` посреди записи звук вернул бы только следующий запуск (docs/ARCHITECTURE.md).
const GRACEFUL_EXIT: Duration = Duration::from_millis(2500);
/// Таймаут чтения и записи короткого WS-соединения с командой `quit`.
const QUIT_IO_TIMEOUT: Duration = Duration::from_millis(1000);

/// Паузы супервизора (в тестах — короче).
#[derive(Debug, Clone, Copy)]
struct Timing {
    /// Паузы перед перезапуском упавшего ядра.
    delays: [Duration; 3],
    /// Сколько ядро должно проработать, чтобы счётчик падений сбросился.
    stable_run: Duration,
    /// Пауза между попытками, когда ядро «не запускается».
    failed_retry: Duration,
    /// Как часто проверять, не закрылся ли другой Рупор, занявший мьютекс ядра.
    other_core_poll: Duration,
}

impl Timing {
    const DEFAULT: Timing = Timing {
        delays: [Duration::from_secs(1), Duration::from_secs(3), Duration::from_secs(10)],
        stable_run: Duration::from_secs(60),
        failed_retry: Duration::from_secs(60),
        other_core_poll: Duration::from_secs(2),
    };
}

/// Ответ команды `backend_info`.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct BackendInfo {
    pub port: u16,
    pub token: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CoreCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
    /// Откуда взята команда — для журнала.
    pub source: &'static str,
}

/// Окружение супервизора: где взять ядро и куда сообщать о перезапусках.
/// В приложении — [`AppHost`], в тестах — заглушка.
pub trait Host: Send + 'static {
    /// Команда запуска ядра (порядок поиска — [`resolve_command_from`]).
    fn resolve(&self) -> Result<CoreCommand, String>;
    /// Ядро перезапущено: новые порт и токен уже доступны через `backend_info`.
    fn restarted(&self);
    /// Состояние ядра для трея.
    fn status(&self, status: CoreStatus);
    /// Журнал ядра: из него берётся причина, если ядро завершилось, не став готовым.
    fn core_log(&self) -> Option<PathBuf> {
        None
    }
    /// Занят ли мьютекс единственного экземпляра ядра, то есть работает другой Рупор.
    fn other_core_running(&self) -> bool {
        false
    }
}

/// Хост приложения: ресурсы Tauri, событие `core-restarted` во все окна, иконка трея.
pub struct AppHost(pub AppHandle);

impl Host for AppHost {
    fn resolve(&self) -> Result<CoreCommand, String> {
        resolve_command(&self.0)
    }

    fn restarted(&self) {
        crate::tray::set_core_status(&self.0, CoreStatus::Restarting);
        if let Err(e) = self.0.emit("core-restarted", serde_json::json!({})) {
            crate::log_warn!("Не удалось отправить core-restarted: {e}");
        }
    }

    fn status(&self, status: CoreStatus) {
        crate::tray::set_core_status(&self.0, status);
    }

    fn core_log(&self) -> Option<PathBuf> {
        Some(crate::logger::app_dir()?.join("logs").join("rupor.log"))
    }

    fn other_core_running(&self) -> bool {
        crate::winapi::named_mutex_exists(CORE_MUTEX)
    }
}

/// Чем закончилось наблюдение за процессом ядра.
enum Watch {
    /// Выход из приложения — ядро остановлено по команде.
    Quit,
    /// Ядро завершилось само — нужен перезапуск. `ready` — успело ли оно открыть порт.
    Exited { code: i32, ready: bool },
}

/// Запущенное ядро.
struct Run {
    pid: u32,
    /// Ядро проверяет единственный экземпляр (нет `--no-mutex`).
    single_instance: bool,
    /// Журнал ядра и его длина на момент запуска: причину выхода ищем только в новых строках.
    log: Option<(PathBuf, u64)>,
}

#[derive(Default)]
struct Inner {
    generation: u64,
    port: u16,
    token: String,
    ready: bool,
    child: Option<Child>,
    /// Последняя ошибка запуска/падения — показывается, если `backend_info` не дождался ядра.
    last_error: Option<String>,
}

pub struct Supervisor {
    inner: Mutex<Inner>,
    cv: Condvar,
    quitting: AtomicBool,
    job: Option<Job>,
    timing: Timing,
}

impl Supervisor {
    pub fn new() -> Self {
        Self::with_timing(Timing::DEFAULT)
    }

    fn with_timing(timing: Timing) -> Self {
        let job = Job::new();
        if job.is_none() {
            crate::log_warn!("Не удалось создать job object — ядро не будет привязано к оболочке");
        }
        Self {
            inner: Mutex::new(Inner::default()),
            cv: Condvar::new(),
            quitting: AtomicBool::new(false),
            job,
            timing,
        }
    }

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn is_quitting(&self) -> bool {
        self.quitting.load(Ordering::SeqCst)
    }

    /// Запустить поток-супервизор.
    pub fn start(self: &Arc<Self>, host: impl Host) {
        let me = Arc::clone(self);
        let spawned = std::thread::Builder::new()
            .name("rupor-core-supervisor".into())
            .spawn(move || me.supervise(&host));
        if let Err(e) = spawned {
            crate::log_error!("Не удалось запустить поток супервизора ядра: {e}");
            self.lock().last_error = Some(fill(i18n::t().core_supervisor_failed, &[("error", &e)]));
        }
    }

    /// Остановить ядро навсегда (выход из приложения). Повторные вызовы безопасны.
    /// Готовое ядро сначала просим выйти само (WS `quit`, ждём до [`GRACEFUL_EXIT`]) —
    /// так оно успевает вернуть приглушённый звук; не вышло — `kill`.
    pub fn shutdown(&self) {
        let first = !self.quitting.swap(true, Ordering::SeqCst);
        let (child, port, token, ready) = {
            let mut g = self.lock();
            (g.child.take(), g.port, g.token.clone(), g.ready)
        };
        if let Some(mut child) = child {
            let pid = child.id();
            let exited = ready
                && match send_quit(port, &token) {
                    Ok(()) => wait_exit(&mut child, GRACEFUL_EXIT),
                    Err(e) => {
                        crate::log_warn!("Не удалось попросить ядро выйти (pid {pid}): {e}");
                        false
                    }
                };
            if exited {
                crate::log_info!("Ядро завершилось само по команде «Выход» (pid {pid})");
            } else {
                crate::log_info!("Останавливаю ядро (pid {pid})");
                let _ = child.kill();
                let _ = child.wait();
            }
        }
        if let Some(job) = &self.job {
            job.terminate(); // добить дочерние процессы (например, python из venv-лаунчера)
        }
        if first {
            crate::log_info!("Ядро остановлено");
        }
        self.cv.notify_all();
    }

    /// Дождаться готовности ядра (TCP-подключение к его порту) и вернуть порт и токен.
    pub fn wait_ready(&self, timeout: Duration) -> Result<BackendInfo, String> {
        let deadline = Instant::now() + timeout;
        let mut g = self.lock();
        loop {
            if self.is_quitting() {
                return Err(i18n::t().core_quitting.into());
            }
            if g.ready {
                return Ok(BackendInfo { port: g.port, token: g.token.clone() });
            }
            let now = Instant::now();
            if now >= deadline {
                let why = g.last_error.clone().unwrap_or_else(|| i18n::t().core_no_response.into());
                return Err(fill(
                    i18n::t().core_not_ready,
                    &[("seconds", &timeout.as_secs()), ("reason", &why)],
                ));
            }
            g = self.cv.wait_timeout(g, deadline - now).unwrap_or_else(|e| e.into_inner()).0;
        }
    }

    fn supervise(&self, host: &dyn Host) {
        let t = self.timing;
        let mut fails: usize = 0;
        // запуски подряд, завершившиеся до готовности ядра
        let mut early: usize = 0;
        let mut first = true;
        while !self.is_quitting() {
            let started = Instant::now();
            let mut status = CoreStatus::Restarting;
            match self.spawn(host) {
                Ok(run) => {
                    if !first {
                        host.restarted();
                    }
                    let Watch::Exited { code, ready } = self.watch(run.pid) else { break };
                    // причина — на языке оболочки: она же уходит в ошибку `backend_info`
                    let msg = if ready {
                        early = 0;
                        fill(i18n::t().core_exited, &[("code", &code)])
                    } else {
                        early += 1;
                        if run.single_instance && host.other_core_running() {
                            status = CoreStatus::AlreadyRunning;
                            i18n::t().core_already_running.to_string()
                        } else {
                            if early >= MAX_EARLY_EXITS {
                                status = CoreStatus::Failed;
                            }
                            let why =
                                run.log.as_ref().and_then(|(p, from)| log_error_since(p, *from));
                            match why {
                                Some(why) => fill(
                                    i18n::t().core_exited_at_start_reason,
                                    &[("code", &code), ("reason", &why)],
                                ),
                                None => fill(i18n::t().core_exited_at_start, &[("code", &code)]),
                            }
                        }
                    };
                    crate::log_warn!(
                        "Ядро (pid {}) остановилось через {} с: {msg}",
                        run.pid,
                        started.elapsed().as_secs()
                    );
                    self.lock().last_error = Some(msg);
                }
                Err(e) => {
                    crate::log_error!("{e}");
                    self.lock().last_error = Some(e);
                    status = CoreStatus::Failed;
                }
            }
            first = false;
            if self.is_quitting() {
                break;
            }
            host.status(status);
            if status == CoreStatus::AlreadyRunning {
                // Перезапуск бесполезен, пока мьютекс занят: ждём, когда другой Рупор закроется.
                crate::log_info!("Жду, пока закроется другой Рупор");
                if !self.wait_while(t.other_core_poll, || host.other_core_running()) {
                    break;
                }
                crate::log_info!("Другой Рупор закрылся — запускаю ядро");
                fails = 0;
                early = 0;
                continue;
            }
            if started.elapsed() >= t.stable_run {
                fails = 0;
            }
            let delay = if early >= MAX_EARLY_EXITS {
                t.failed_retry
            } else {
                t.delays[fails.min(t.delays.len() - 1)]
            };
            fails += 1;
            crate::log_info!("Перезапуск ядра через {} с (попытка {fails})", delay.as_secs());
            if !self.sleep(delay) {
                break;
            }
        }
        crate::log_info!("Супервизор ядра остановлен");
    }

    /// Ждать, пока `cond` истинно (проверка раз в `poll`). `false` — пора выходить.
    fn wait_while(&self, poll: Duration, cond: impl Fn() -> bool) -> bool {
        while cond() {
            if !self.sleep(poll) {
                return false;
            }
        }
        !self.is_quitting()
    }

    /// Запустить ядро с новыми портом и токеном.
    fn spawn(&self, host: &dyn Host) -> Result<Run, String> {
        let cmd = host.resolve()?;
        let port = free_port().map_err(|e| fill(i18n::t().core_port_failed, &[("error", &e)]))?;
        let token = new_token().map_err(|e| fill(i18n::t().core_token_failed, &[("error", &e)]))?;
        let mut args = cmd.args.clone();
        args.extend(core_args(port, &token, std::process::id()));
        args.extend(extra_args_from_env());
        let single_instance = !args.iter().any(|a| a == "--no-mutex");
        let log = host.core_log().map(|p| {
            let len = std::fs::metadata(&p).map_or(0, |m| m.len());
            (p, len)
        });

        let mut c = Command::new(&cmd.program);
        c.args(&args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW);
        if let Some(dir) = &cmd.cwd {
            c.current_dir(dir);
        }
        let child = c.spawn().map_err(|e| {
            fill(i18n::t().core_spawn_failed, &[("path", &cmd.program.display()), ("error", &e)])
        })?;
        let pid = child.id();
        if let Some(job) = &self.job {
            if !job.assign(child.as_raw_handle() as _) {
                crate::log_warn!("Не удалось поместить ядро в job object");
            }
        }
        // токен в журнал не пишем
        crate::log_info!(
            "Ядро запущено (pid {pid}, порт {port}, источник: {}): {}",
            cmd.source,
            cmd.program.display()
        );

        let mut g = self.lock();
        if self.is_quitting() {
            drop(g);
            let mut child = child;
            let _ = child.kill();
            let _ = child.wait();
            return Err(i18n::t().core_quitting.into());
        }
        g.generation += 1;
        g.port = port;
        g.token = token;
        g.ready = false;
        g.child = Some(child);
        Ok(Run { pid, single_instance, log })
    }

    /// Следить за ядром: отмечать готовность, дождаться завершения.
    fn watch(&self, pid: u32) -> Watch {
        let (generation, port) = {
            let g = self.lock();
            (g.generation, g.port)
        };
        loop {
            let ready = {
                let mut g = self.lock();
                if self.is_quitting() {
                    return Watch::Quit;
                }
                let Some(child) = g.child.as_mut() else { return Watch::Quit };
                match child.try_wait() {
                    Ok(Some(status)) => {
                        g.child = None;
                        let ready = std::mem::replace(&mut g.ready, false);
                        return Watch::Exited { code: status.code().unwrap_or(-1), ready };
                    }
                    Ok(None) => {}
                    Err(e) => {
                        crate::log_warn!("Не удалось проверить процесс ядра (pid {pid}): {e}");
                    }
                }
                g.ready
            };
            if !ready && probe(port) {
                let mut g = self.lock();
                if g.generation == generation {
                    g.ready = true;
                    g.last_error = None;
                    crate::log_info!("Ядро готово (pid {pid}, порт {port})");
                    self.cv.notify_all();
                }
                continue;
            }
            let g = self.lock();
            if self.is_quitting() {
                return Watch::Quit;
            }
            let _unused = self.cv.wait_timeout(g, POLL).unwrap_or_else(|e| e.into_inner());
        }
    }

    /// Пауза, прерываемая выходом. `false` — пора выходить.
    fn sleep(&self, d: Duration) -> bool {
        let deadline = Instant::now() + d;
        let mut g = self.lock();
        loop {
            if self.is_quitting() {
                return false;
            }
            let now = Instant::now();
            if now >= deadline {
                return true;
            }
            g = self.cv.wait_timeout(g, deadline - now).unwrap_or_else(|e| e.into_inner()).0;
        }
    }
}

/// Аргументы ядра по контракту.
pub fn core_args(port: u16, token: &str, ui_pid: u32) -> Vec<String> {
    vec![
        "--sidecar".into(),
        "--ws-port".into(),
        port.to_string(),
        "--token".into(),
        token.to_string(),
        "--ui-pid".into(),
        ui_pid.to_string(),
    ]
}

/// Дополнительные аргументы из `RUPOR_CORE_ARGS` (через пробел), например `--no-hook --no-mutex -v`.
fn extra_args_from_env() -> Vec<String> {
    std::env::var("RUPOR_CORE_ARGS").map(|s| split_command_line(&s)).unwrap_or_default()
}

/// Где взять ядро (порядок из контракта).
pub fn resolve_command(app: &AppHandle) -> Result<CoreCommand, String> {
    let resource_dir = app.path().resource_dir().ok();
    resolve_command_from(
        std::env::var("RUPOR_CORE").ok().as_deref(),
        resource_dir.as_deref(),
        dev_root(),
    )
}

/// Корень проекта для debug-сборки (`<CARGO_MANIFEST_DIR>/../..`).
fn dev_root() -> Option<PathBuf> {
    if cfg!(debug_assertions) {
        Path::new(env!("CARGO_MANIFEST_DIR")).parent()?.parent().map(Path::to_path_buf)
    } else {
        None
    }
}

pub fn resolve_command_from(
    env_core: Option<&str>,
    resource_dir: Option<&Path>,
    dev_root: Option<PathBuf>,
) -> Result<CoreCommand, String> {
    // 1. RUPOR_CORE — полная командная строка (для отладки)
    if let Some(line) = env_core.filter(|s| !s.trim().is_empty()) {
        let mut parts = split_command_line(line).into_iter();
        let program = parts.next().map(PathBuf::from).ok_or("RUPOR_CORE пустая")?;
        let cwd = dev_root.as_ref().map(|r| r.join("core")).filter(|d| d.is_dir());
        return Ok(CoreCommand { program, args: parts.collect(), cwd, source: "RUPOR_CORE" });
    }
    // 2. установленная версия: <resource_dir>/core/rupor-core.exe
    if let Some(res) = resource_dir {
        let dir = res.join("core");
        let exe = dir.join("rupor-core.exe");
        if exe.is_file() {
            return Ok(CoreCommand {
                program: exe,
                args: vec![],
                cwd: Some(dir),
                source: "resources",
            });
        }
    }
    // 3. только debug: python из .venv проекта
    if let Some(root) = dev_root {
        let py = root.join(".venv").join("Scripts").join("python.exe");
        if py.is_file() {
            return Ok(CoreCommand {
                program: py,
                args: vec!["-m".into(), "rupor".into()],
                cwd: Some(root.join("core")),
                source: "venv (debug)",
            });
        }
    }
    Err(i18n::t().core_not_found.into())
}

/// Разбить командную строку по пробелам; двойные кавычки объединяют части с пробелами.
pub fn split_command_line(s: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut quoted = false;
    let mut has = false;
    for ch in s.chars() {
        match ch {
            '"' => {
                quoted = !quoted;
                has = true;
            }
            c if c.is_whitespace() && !quoted => {
                if has {
                    out.push(std::mem::take(&mut cur));
                    has = false;
                }
            }
            c => {
                cur.push(c);
                has = true;
            }
        }
    }
    if has {
        out.push(cur);
    }
    out
}

/// Свободный порт на 127.0.0.1: bind :0 → взять порт → закрыть.
pub fn free_port() -> std::io::Result<u16> {
    let l = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(l.local_addr()?.port())
}

/// Случайный токен: 16 байт → 32 hex.
pub fn new_token() -> Result<String, getrandom::Error> {
    let mut buf = [0u8; 16];
    getrandom::fill(&mut buf)?;
    Ok(buf.iter().map(|b| format!("{b:02x}")).collect())
}

/// Попросить ядро выйти самому: WS-команда `quit` на ws://127.0.0.1:<port>/?token=<t>.
/// Минимальный клиент RFC 6455 без зависимостей: рукопожатие, текстовый кадр с командой,
/// ожидание ответа `{"id":1,"ok":true…}` (команда выполнена), кадр закрытия и чтение до
/// закрытия соединения сервером (соединение, не ответившее на закрытие, сервер ядра при
/// выходе ждал бы до 3 с). Токен не логируется.
fn send_quit(port: u16, token: &str) -> Result<(), String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut s = TcpStream::connect_timeout(&addr, PROBE_TIMEOUT).map_err(|e| e.to_string())?;
    s.set_read_timeout(Some(QUIT_IO_TIMEOUT)).map_err(|e| e.to_string())?;
    s.set_write_timeout(Some(QUIT_IO_TIMEOUT)).map_err(|e| e.to_string())?;
    let mut rnd = [0u8; 24]; // 16 байт — ключ рукопожатия, по 4 — маски двух кадров
    getrandom::fill(&mut rnd).map_err(|e| e.to_string())?;
    let key = base64(&rnd[..16]);
    let req = [
        format!("GET /?token={token} HTTP/1.1"),
        format!("Host: 127.0.0.1:{port}"),
        "Upgrade: websocket".into(),
        "Connection: Upgrade".into(),
        format!("Sec-WebSocket-Key: {key}"),
        "Sec-WebSocket-Version: 13".into(),
        String::new(),
        String::new(),
    ]
    .join("\r\n");
    s.write_all(req.as_bytes()).map_err(|e| e.to_string())?;
    // заголовки ответа — побайтно до пустой строки: следом сервер шлёт событие hello
    let mut head = Vec::new();
    let mut b = [0u8; 1];
    while !head.ends_with(b"\r\n\r\n") {
        if head.len() > 8192 {
            return Err("слишком длинный ответ на рукопожатие".into());
        }
        match s.read(&mut b) {
            Ok(0) => return Err("ядро закрыло соединение".into()),
            Ok(_) => head.push(b[0]),
            Err(e) => return Err(e.to_string()),
        }
    }
    let status = String::from_utf8_lossy(&head);
    let status = status.lines().next().unwrap_or_default();
    if !status.starts_with("HTTP/1.1 101") {
        return Err(format!("рукопожатие отклонено: {status}"));
    }
    let mask = |i: usize| [rnd[i], rnd[i + 1], rnd[i + 2], rnd[i + 3]];
    s.write_all(&ws_frame(WS_TEXT, br#"{"id":1,"cmd":"quit","args":{}}"#, mask(16)))
        .map_err(|e| e.to_string())?;
    // Ответ на команду (перед ним — событие hello и другие). Закрыть соединение раньше нельзя:
    // сервер, не успевший отправить hello, не стал бы читать команду.
    let deadline = Instant::now() + QUIT_IO_TIMEOUT;
    loop {
        let (op, payload) = read_frame(&mut s).map_err(|e| e.to_string())?;
        if op == WS_TEXT && payload.starts_with(br#"{"id":1,"#) {
            if payload.starts_with(br#"{"id":1,"ok":true"#) {
                break;
            }
            return Err("ядро не выполнило команду выхода".into());
        }
        if op == WS_CLOSE {
            return Err("ядро закрыло соединение".into());
        }
        if Instant::now() >= deadline {
            return Err("нет ответа на команду выхода".into());
        }
    }
    // Закрыть как положено и дочитать до закрытия сервером (сокет с непрочитанными данными
    // закрылся бы сбросом соединения).
    let _ = s.write_all(&ws_frame(WS_CLOSE, &1000u16.to_be_bytes(), mask(20)));
    let mut buf = [0u8; 4096];
    loop {
        match s.read(&mut buf) {
            Ok(n) if n > 0 && Instant::now() < deadline => {}
            _ => break,
        }
    }
    Ok(())
}

const WS_TEXT: u8 = 0x1;
const WS_CLOSE: u8 = 0x8;

/// Кадр WebSocket от сервера (без маски): (код операции, полезная нагрузка).
fn read_frame(s: &mut impl Read) -> std::io::Result<(u8, Vec<u8>)> {
    let mut h = [0u8; 2];
    s.read_exact(&mut h)?;
    let len = match h[1] & 0x7f {
        126 => {
            let mut b = [0u8; 2];
            s.read_exact(&mut b)?;
            usize::from(u16::from_be_bytes(b))
        }
        127 => {
            let mut b = [0u8; 8];
            s.read_exact(&mut b)?;
            usize::try_from(u64::from_be_bytes(b)).unwrap_or(usize::MAX)
        }
        n => usize::from(n),
    };
    if len > 1 << 20 {
        return Err(std::io::Error::other("слишком длинный кадр"));
    }
    let mut payload = vec![0u8; len];
    s.read_exact(&mut payload)?;
    Ok((h[0] & 0x0f, payload))
}

/// Кадр WebSocket от клиента (FIN, маска обязательна), полезная нагрузка < 126 байт.
fn ws_frame(opcode: u8, payload: &[u8], mask: [u8; 4]) -> Vec<u8> {
    let len = u8::try_from(payload.len()).ok().filter(|n| *n < 126).expect("короткий кадр");
    let mut f = vec![0x80 | opcode, 0x80 | len];
    f.extend_from_slice(&mask);
    f.extend(payload.iter().enumerate().map(|(i, b)| b ^ mask[i % 4]));
    f
}

/// Base64 (RFC 4648, с `=`) — для ключа рукопожатия WebSocket.
fn base64(data: &[u8]) -> String {
    const ABC: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let n = c.iter().enumerate().fold(0u32, |n, (i, b)| n | u32::from(*b) << (16 - 8 * i));
        for i in 0..4 {
            out.push(if i <= c.len() {
                char::from(ABC[(n >> (18 - 6 * i)) as usize & 63])
            } else {
                '='
            });
        }
    }
    out
}

/// Дождаться завершения процесса не дольше `timeout`. `true` — завершился.
fn wait_exit(child: &mut Child, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return true,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(25)),
            _ => return false,
        }
    }
}

/// Ядро слушает порт? (TCP-подключение с коротким таймаутом, сразу закрывается.)
fn probe(port: u16) -> bool {
    TcpStream::connect_timeout(&SocketAddr::from(([127, 0, 0, 1], port)), PROBE_TIMEOUT).is_ok()
}

/// Последняя ошибка в журнале ядра среди строк, дописанных после смещения `from`
/// (длина файла на момент запуска), — старые ошибки прошлых запусков не подхватываются.
fn log_error_since(path: &Path, from: u64) -> Option<String> {
    let mut f = File::open(path).ok()?;
    let len = f.metadata().ok()?.len();
    // файл стал короче — журнал сменился (ротация), новый читаем с начала
    let from = if len < from { 0 } else { from };
    let start = from.max(len.saturating_sub(LOG_TAIL));
    f.seek(SeekFrom::Start(start)).ok()?;
    let mut buf = Vec::new();
    f.take(len - start).read_to_end(&mut buf).ok()?;
    last_error_line(&String::from_utf8_lossy(&buf))
}

/// Сообщение последней строки уровня ERROR/CRITICAL из журнала ядра
/// (формат `%(asctime)s %(levelname)s %(name)s: %(message)s`), не длиннее 300 символов.
pub fn last_error_line(text: &str) -> Option<String> {
    const MAX_CHARS: usize = 300;
    text.lines().rev().find_map(|line| {
        let mut parts = line.splitn(4, ' ');
        let (_date, _time, level, rest) =
            (parts.next()?, parts.next()?, parts.next()?, parts.next()?);
        if level != "ERROR" && level != "CRITICAL" {
            return None;
        }
        let msg = rest.split_once(": ").map_or(rest, |(_, m)| m).trim();
        if msg.is_empty() {
            return None;
        }
        let mut short: String = msg.chars().take(MAX_CHARS).collect();
        if short.len() < msg.len() {
            short.push('…');
        }
        Some(short)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_is_32_hex() {
        let t = new_token().unwrap();
        assert_eq!(t.len(), 32);
        assert!(t.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        assert_ne!(t, new_token().unwrap());
    }

    #[test]
    fn port_is_free() {
        let p = free_port().unwrap();
        assert!(p > 0);
        // порт действительно свободен — его можно занять снова
        let l = TcpListener::bind(("127.0.0.1", p)).unwrap();
        assert!(probe(p));
        drop(l);
    }

    #[test]
    fn args_match_contract() {
        assert_eq!(
            core_args(5123, "ab", 42),
            ["--sidecar", "--ws-port", "5123", "--token", "ab", "--ui-pid", "42"]
        );
    }

    #[test]
    fn split_handles_quotes() {
        assert_eq!(split_command_line("  a  b\tc "), ["a", "b", "c"]);
        assert_eq!(
            split_command_line(r#""C:\Program Files\py.exe" -m rupor --no-hook"#),
            [r"C:\Program Files\py.exe", "-m", "rupor", "--no-hook"]
        );
        assert_eq!(split_command_line(r#"x """#), ["x", ""]);
        assert!(split_command_line("   ").is_empty());
    }

    struct TestHost {
        cmd: Result<CoreCommand, String>,
        restarts: Arc<std::sync::atomic::AtomicUsize>,
        statuses: Arc<Mutex<Vec<CoreStatus>>>,
        log: Option<PathBuf>,
        other_core: Arc<AtomicBool>,
    }

    impl Host for TestHost {
        fn resolve(&self) -> Result<CoreCommand, String> {
            self.cmd.clone()
        }
        fn restarted(&self) {
            self.restarts.fetch_add(1, Ordering::SeqCst);
        }
        fn status(&self, status: CoreStatus) {
            self.statuses.lock().unwrap().push(status);
        }
        fn core_log(&self) -> Option<PathBuf> {
            self.log.clone()
        }
        fn other_core_running(&self) -> bool {
            self.other_core.load(Ordering::SeqCst)
        }
    }

    fn test_host(
        cmd: Result<CoreCommand, String>,
    ) -> (TestHost, Arc<std::sync::atomic::AtomicUsize>, Arc<Mutex<Vec<CoreStatus>>>) {
        let restarts = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let statuses = Arc::new(Mutex::new(Vec::new()));
        (
            TestHost {
                cmd,
                restarts: restarts.clone(),
                statuses: statuses.clone(),
                log: None,
                other_core: Arc::new(AtomicBool::new(false)),
            },
            restarts,
            statuses,
        )
    }

    fn venv_python() -> Option<PathBuf> {
        dev_root()
            .map(|r| r.join(".venv").join("Scripts").join("python.exe"))
            .filter(|p| p.is_file())
    }

    /// Короткие паузы для тестов; «не запускается» — по-прежнему долгая пауза.
    fn fast_timing() -> Timing {
        Timing {
            delays: [Duration::from_millis(50); 3],
            stable_run: Duration::from_secs(60),
            failed_retry: Duration::from_secs(60),
            other_core_poll: Duration::from_millis(50),
        }
    }

    fn wait_for(what: &str, timeout: Duration, cond: impl Fn() -> bool) {
        let t = Instant::now();
        while !cond() {
            assert!(t.elapsed() < timeout, "не дождались: {what}");
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn temp_dir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("rupor-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    /// Ядро выходит, не открыв порт: не бесконечный перезапуск, а после MAX_EARLY_EXITS попыток
    /// статус «не запускается», долгая пауза и причина из новых строк журнала ядра.
    /// С `--no-mutex` занятый мьютекс не считается «другим Рупором».
    #[test]
    fn supervisor_gives_up_on_core_failing_at_start() {
        let Some(py) = venv_python() else {
            eprintln!("нет .venv — тест пропущен");
            return;
        };
        let dir = temp_dir("early-exit");
        let log = dir.join("rupor.log");
        std::fs::write(&log, "2026-01-01 00:00:00,000 ERROR rupor: старая ошибка\n").unwrap();
        let script = "import sys; open(sys.argv[1], 'a', encoding='utf-8').write(\
            '2026-01-01 00:00:01,000 INFO rupor: старт\\n\
            2026-01-01 00:00:01,001 ERROR rupor: Не удалось открыть порт 1: занят\\n'); sys.exit(1)";
        let cmd = CoreCommand {
            program: py,
            args: vec!["-c".into(), script.into(), log.display().to_string(), "--no-mutex".into()],
            cwd: None,
            source: "test",
        };
        let (mut host, restarts, statuses) = test_host(Ok(cmd));
        host.log = Some(log.clone());
        host.other_core.store(true, Ordering::SeqCst);
        let sup = Arc::new(Supervisor::with_timing(fast_timing()));
        sup.start(host);

        wait_for("статус «не запускается»", Duration::from_secs(30), || {
            statuses.lock().unwrap().contains(&CoreStatus::Failed)
        });
        let runs = || std::fs::read_to_string(&log).unwrap().matches("INFO rupor: старт").count();
        assert_eq!(runs(), MAX_EARLY_EXITS);
        assert_eq!(
            *statuses.lock().unwrap(),
            [CoreStatus::Restarting, CoreStatus::Restarting, CoreStatus::Failed]
        );
        assert_eq!(restarts.load(Ordering::SeqCst), MAX_EARLY_EXITS - 1);
        // дальше — долгая пауза, а не перезапуск каждые несколько секунд
        std::thread::sleep(Duration::from_millis(400));
        assert_eq!(runs(), MAX_EARLY_EXITS);

        let err = sup.wait_ready(Duration::from_millis(100)).unwrap_err();
        assert!(err.contains("при запуске с кодом 1: Не удалось открыть порт 1: занят"), "{err}");
        assert!(!err.contains("старая ошибка"), "{err}");

        let t = Instant::now();
        sup.shutdown();
        assert!(t.elapsed() < Duration::from_secs(1));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Мьютекс ядра занят другим Рупором: статус «уже запущен другой Рупор», новых запусков нет,
    /// пока тот работает; закрылся — ядро запускается снова.
    #[test]
    fn supervisor_waits_while_other_rupor_runs() {
        let cmd_exe =
            std::env::var("ComSpec").unwrap_or_else(|_| r"C:\Windows\System32\cmd.exe".into());
        let cmd = CoreCommand {
            program: PathBuf::from(cmd_exe),
            args: ["/c", "exit", "1"].map(String::from).to_vec(),
            cwd: None,
            source: "test",
        };
        let (host, restarts, statuses) = test_host(Ok(cmd));
        let other = Arc::clone(&host.other_core);
        other.store(true, Ordering::SeqCst);
        let sup = Arc::new(Supervisor::with_timing(fast_timing()));
        sup.start(host);

        wait_for(
            "статус «уже запущен другой Рупор»",
            Duration::from_secs(20),
            || statuses.lock().unwrap().contains(&CoreStatus::AlreadyRunning),
        );
        let err = sup.wait_ready(Duration::from_millis(100)).unwrap_err();
        assert!(err.contains("уже запущен другой Рупор"), "{err}");
        std::thread::sleep(Duration::from_millis(300));
        assert_eq!(
            restarts.load(Ordering::SeqCst),
            0,
            "пока другой Рупор работает — не перезапускать"
        );

        other.store(false, Ordering::SeqCst);
        wait_for(
            "перезапуск после закрытия другого Рупора",
            Duration::from_secs(20),
            || restarts.load(Ordering::SeqCst) >= 1,
        );
        let t = Instant::now();
        sup.shutdown();
        assert!(t.elapsed() < Duration::from_secs(3)); // запас: под нагрузкой CPU остановка ~1 с
    }

    #[test]
    fn last_error_line_from_core_log() {
        let log = "2026-01-01 10:00:00,000 INFO rupor: Рупор запущен\r\n\
                   2026-01-01 10:00:01,000 ERROR rupor: Первая ошибка\r\n\
                   2026-01-01 10:00:02,000 ERROR rupor.engine: Не удалось открыть порт 5: занят\r\n\
                   Traceback (most recent call last):\r\n\
                   OSError: [WinError 10048] ERROR xx: не строка журнала\r\n\
                   2026-01-01 10:00:03,000 INFO rupor: Ядро Рупора завершает работу\r\n";
        assert_eq!(last_error_line(log).as_deref(), Some("Не удалось открыть порт 5: занят"));
        assert_eq!(
            last_error_line("2026-01-01 10:00:00,000 CRITICAL rupor: всё плохо").as_deref(),
            Some("всё плохо")
        );
        assert_eq!(last_error_line("2026-01-01 10:00:00,000 INFO rupor: ок\n"), None);
        assert_eq!(last_error_line(""), None);
        let long = format!("2026-01-01 10:00:00,000 ERROR rupor: {}", "я".repeat(500));
        let short = last_error_line(&long).unwrap();
        assert_eq!(short.chars().count(), 301);
        assert!(short.ends_with('…'));
    }

    #[test]
    fn log_error_since_skips_old_lines() {
        let dir = temp_dir("log-since");
        let log = dir.join("rupor.log");
        std::fs::write(&log, "2026-01-01 10:00:00,000 ERROR rupor: старая\n").unwrap();
        let from = std::fs::metadata(&log).unwrap().len();
        assert_eq!(log_error_since(&log, from), None);
        let mut f = std::fs::OpenOptions::new().append(true).open(&log).unwrap();
        std::io::Write::write_all(
            &mut f,
            "2026-01-01 10:00:01,000 ERROR rupor: новая\n".as_bytes(),
        )
        .unwrap();
        drop(f);
        assert_eq!(log_error_since(&log, from).as_deref(), Some("новая"));
        // журнал сменился (ротация) и стал короче — читается с начала
        std::fs::write(&log, "2026-01-01 10:00:02,000 ERROR rupor: после ротации\n").unwrap();
        assert_eq!(log_error_since(&log, 10_000).as_deref(), Some("после ротации"));
        assert_eq!(log_error_since(&dir.join("нет.log"), 0), None);
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Имя мьютекса совпадает с ядром (core/rupor/__main__.py).
    #[test]
    fn core_mutex_matches_core() {
        let main = dev_root().map(|r| r.join("core").join("rupor").join("__main__.py"));
        let Some(src) = main.and_then(|p| std::fs::read_to_string(p).ok()) else {
            eprintln!("нет исходников ядра — тест пропущен");
            return;
        };
        let literal = format!("\"{}\"", CORE_MUTEX.replace('\\', "\\\\"));
        assert!(src.contains(&literal), "в __main__.py нет {literal}");
    }

    /// Настоящий процесс (поддельное ядро на Python из .venv): готовность, аргументы,
    /// перезапуск после падения с новыми портом/токеном, остановка всего дерева процессов.
    #[test]
    fn supervisor_restarts_crashed_core() {
        let Some(py) = dev_root()
            .map(|r| r.join(".venv").join("Scripts").join("python.exe"))
            .filter(|p| p.is_file())
        else {
            eprintln!("нет .venv — тест пропущен");
            return;
        };
        let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fake_core.py");
        let state = std::env::temp_dir().join(format!("rupor-fake-core-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&state);
        std::fs::create_dir_all(&state).unwrap();
        let cmd = CoreCommand {
            program: py,
            args: vec![script.display().to_string(), state.display().to_string()],
            cwd: None,
            source: "test",
        };
        let (host, restarts, statuses) = test_host(Ok(cmd));
        let sup = Arc::new(Supervisor::new());
        sup.start(host);

        let a = sup.wait_ready(Duration::from_secs(20)).expect("первое ядро готово");
        let run0 = std::fs::read_to_string(state.join("run-0.txt")).unwrap();
        let expected = core_args(a.port, &a.token, std::process::id());
        assert_eq!(run0.lines().collect::<Vec<_>>(), expected);

        // первое ядро «падает» через ~1 с, перезапуск через 1 с
        let t0 = Instant::now();
        while restarts.load(Ordering::SeqCst) == 0 {
            assert!(t0.elapsed() < Duration::from_secs(20), "ядро не перезапустилось");
            std::thread::sleep(Duration::from_millis(50));
        }
        let restart_after = t0.elapsed();
        let b = sup.wait_ready(Duration::from_secs(20)).expect("второе ядро готово");
        assert_ne!(a.token, b.token, "после перезапуска токен новый");
        assert!(
            restart_after >= Duration::from_millis(500),
            "пауза перед перезапуском соблюдается"
        );
        assert!(statuses.lock().unwrap().contains(&CoreStatus::Restarting));
        assert!(sup.lock().last_error.is_none());

        // выход: ядро (вместе с дочерним python venv-лаунчера) остановлено, порт закрыт
        sup.shutdown();
        let t1 = Instant::now();
        while probe(b.port) {
            assert!(t1.elapsed() < Duration::from_secs(5), "ядро не остановилось");
            std::thread::sleep(Duration::from_millis(100));
        }
        assert!(sup.wait_ready(Duration::from_millis(100)).is_err());
        assert_eq!(restarts.load(Ordering::SeqCst), 1, "после выхода перезапусков нет");
        let _ = std::fs::remove_dir_all(&state);
    }

    #[test]
    fn base64_and_ws_frame() {
        let cases = [
            ("", ""),
            ("f", "Zg=="),
            ("fo", "Zm8="),
            ("foo", "Zm9v"),
            ("foob", "Zm9vYg=="),
            ("foobar", "Zm9vYmFy"),
        ];
        for (raw, enc) in cases {
            assert_eq!(base64(raw.as_bytes()), enc);
        }
        assert_eq!(base64(&[0xff; 16]), "/////////////////////w==");
        let mask = [1, 2, 3, 4];
        let f = ws_frame(WS_TEXT, b"quit!", mask);
        assert_eq!(f[..6], [0x81, 0x85, 1, 2, 3, 4]);
        let payload: Vec<u8> = f[6..].iter().enumerate().map(|(i, b)| b ^ mask[i % 4]).collect();
        assert_eq!(payload, b"quit!");
        assert_eq!(
            ws_frame(WS_CLOSE, &1000u16.to_be_bytes(), [0; 4]),
            [0x88, 0x82, 0, 0, 0, 0, 3, 0xe8]
        );
        // кадры сервера: короткий, 16- и 64-битная длина
        let mut srv = vec![0x81, 2, b'h', b'i', 0x81, 126, 1, 0];
        srv.extend([b'x'; 256]);
        srv.extend([0x88, 127, 0, 0, 0, 0, 0, 0, 0, 2, 3, 0xe8]);
        let mut r = &srv[..];
        assert_eq!(read_frame(&mut r).unwrap(), (WS_TEXT, b"hi".to_vec()));
        assert_eq!(read_frame(&mut r).unwrap(), (WS_TEXT, vec![b'x'; 256]));
        assert_eq!(read_frame(&mut r).unwrap(), (WS_CLOSE, vec![3, 0xe8]));
        assert!(read_frame(&mut r).is_err());
    }

    /// Выход: готовое ядро получает WS `quit` (рукопожатие с токеном, маскированный кадр,
    /// после ответа — кадр закрытия) и завершается само, без `kill`, — успевает вернуть
    /// приглушённый звук. Поддельное ядро в режиме ws (файл `ws-mode`) проверяет токен и
    /// кадры, отвечает на рукопожатие, событием hello (длинным — 16-битная длина) и ответом.
    #[test]
    fn shutdown_asks_core_to_quit() {
        let Some(py) = venv_python() else {
            eprintln!("нет .venv — тест пропущен");
            return;
        };
        let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fake_core.py");
        let state = temp_dir("quit");
        std::fs::write(state.join("ws-mode"), b"").unwrap();
        let cmd = CoreCommand {
            program: py,
            args: vec![script.display().to_string(), state.display().to_string()],
            cwd: None,
            source: "test",
        };
        let (host, restarts, _statuses) = test_host(Ok(cmd));
        let sup = Arc::new(Supervisor::new());
        sup.start(host);
        let info = sup.wait_ready(Duration::from_secs(20)).expect("ядро готово");

        let t = Instant::now();
        sup.shutdown();
        let took = t.elapsed();
        let got =
            std::fs::read_to_string(state.join("quit-0.json")).expect("команда quit не дошла");
        assert_eq!(got, r#"{"id":1,"cmd":"quit","args":{}}"#);
        assert!(took < GRACEFUL_EXIT, "ядро не вышло само, остановлено через {took:?}");
        assert!(!probe(info.port), "порт ядра не закрыт");
        assert_eq!(restarts.load(Ordering::SeqCst), 0, "после выхода перезапусков нет");
        let _ = std::fs::remove_dir_all(&state);
    }

    /// Не WS-сервер на порту ядра (или ядро не отвечает на рукопожатие) — не ждём, а `kill`.
    #[test]
    fn send_quit_fails_fast_without_websocket() {
        let l = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = l.local_addr().unwrap().port();
        let srv = std::thread::spawn(move || {
            let (mut c, _) = l.accept().unwrap();
            let mut req = Vec::new();
            let mut b = [0u8; 1];
            while !req.ends_with(b"\r\n\r\n") && c.read(&mut b).unwrap_or(0) == 1 {
                req.push(b[0]);
            }
            c.write_all(b"HTTP/1.1 403 Forbidden\r\n\r\n").unwrap();
            let _ = c.read(&mut b); // ждать, пока клиент закроет соединение
            String::from_utf8(req).unwrap()
        });
        let err = send_quit(port, "00").unwrap_err();
        assert!(err.contains("403"), "{err}");
        let req = srv.join().unwrap();
        assert!(req.starts_with("GET /?token=00 HTTP/1.1\r\nHost: 127.0.0.1:"), "{req}");
        assert!(req.contains("\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"), "{req}");
        assert!(req.ends_with("\r\nSec-WebSocket-Version: 13\r\n\r\n"), "{req}");
    }

    /// Настоящее ядро из .venv в режиме `--sidecar` (без хука клавиатуры и мьютекса):
    /// порт открывается, после остановки закрывается. Требует ядро этапа 3, поэтому не по умолчанию:
    /// `cargo test -- --ignored real_core_smoke`.
    #[test]
    #[ignore = "нужно ядро с режимом --sidecar; запуск: cargo test -- --ignored real_core_smoke"]
    fn real_core_smoke() {
        let root = dev_root().expect("debug-сборка");
        let py = root.join(".venv").join("Scripts").join("python.exe");
        assert!(py.is_file(), "нет {}", py.display());
        let cmd = CoreCommand {
            program: py,
            args: ["-m", "rupor", "--no-hook", "--no-mutex"].map(String::from).to_vec(),
            cwd: Some(root.join("core")),
            source: "test",
        };
        let (host, restarts, _statuses) = test_host(Ok(cmd));
        let sup = Arc::new(Supervisor::new());
        sup.start(host);
        let info = sup.wait_ready(Duration::from_secs(60)).expect("ядро открыло WS-порт");
        assert_eq!(info.token.len(), 32);
        std::thread::sleep(Duration::from_secs(2));
        assert_eq!(restarts.load(Ordering::SeqCst), 0, "ядро не должно падать");
        sup.shutdown();
        let t = Instant::now();
        while probe(info.port) {
            assert!(t.elapsed() < Duration::from_secs(5), "ядро не остановилось");
            std::thread::sleep(Duration::from_millis(100));
        }
    }

    #[test]
    fn wait_ready_reports_missing_core() {
        let (host, _r, statuses) = test_host(Err("Не найдено ядро Рупора".into()));
        let sup = Arc::new(Supervisor::new());
        sup.start(host);
        let err = sup.wait_ready(Duration::from_millis(1500)).unwrap_err();
        assert!(err.contains("не запустилось за 1 с"), "{err}");
        assert!(err.contains("Не найдено ядро"), "{err}");
        assert!(statuses.lock().unwrap().contains(&CoreStatus::Failed));
        let t = Instant::now();
        sup.shutdown();
        assert!(t.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn resolve_order() {
        let tmp = std::env::temp_dir().join(format!("rupor-resolve-{}", std::process::id()));
        let res = tmp.join("res");
        let root = tmp.join("root");
        std::fs::create_dir_all(res.join("core")).unwrap();
        std::fs::create_dir_all(root.join(".venv").join("Scripts")).unwrap();
        std::fs::create_dir_all(root.join("core")).unwrap();
        std::fs::write(root.join(".venv").join("Scripts").join("python.exe"), b"").unwrap();

        // RUPOR_CORE побеждает всё
        let c = resolve_command_from(Some("py -m rupor --no-hook"), Some(&res), Some(root.clone()))
            .unwrap();
        assert_eq!(c.program, PathBuf::from("py"));
        assert_eq!(c.args, ["-m", "rupor", "--no-hook"]);
        assert_eq!(c.cwd, Some(root.join("core")));

        // нет exe в ресурсах → venv
        let c = resolve_command_from(None, Some(&res), Some(root.clone())).unwrap();
        assert_eq!(c.source, "venv (debug)");
        assert_eq!(c.args, ["-m", "rupor"]);
        assert_eq!(c.cwd, Some(root.join("core")));

        // exe в ресурсах → он
        std::fs::write(res.join("core").join("rupor-core.exe"), b"").unwrap();
        let c = resolve_command_from(Some("  "), Some(&res), Some(root.clone())).unwrap();
        assert_eq!(c.program, res.join("core").join("rupor-core.exe"));
        assert!(c.args.is_empty());

        // release без ресурсов → понятная ошибка
        std::fs::remove_file(res.join("core").join("rupor-core.exe")).unwrap();
        assert!(resolve_command_from(None, Some(&res), None)
            .unwrap_err()
            .contains("Не найдено ядро"));

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
