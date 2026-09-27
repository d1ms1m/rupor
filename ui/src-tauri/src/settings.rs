//! Чтение нужных оболочке ключей из `%APPDATA%\Rupor\settings.json`.
//!
//! Файлом владеет ядро (пишет атомарно через .tmp → replace); оболочка его только читает
//! при старте: показать ли главное окно (мастер первого запуска), где поставить пилюлю и на
//! каком языке подписать трей и окна, пока интерфейс не подключился.

use serde_json::Value;

#[derive(Debug, Clone, PartialEq)]
pub struct UiSettings {
    /// `first_run_done` — мастер первого запуска пройден. Нет файла/ключа → `false`.
    pub first_run_done: bool,
    /// `pill_enabled` — показывать пилюлю. По умолчанию `true`.
    pub pill_enabled: bool,
    /// `pill_position` — `[x, y]` в физических пикселях или `null` (снизу по центру).
    pub pill_position: Option<(i32, i32)>,
    /// `autostart` — запускать с Windows. По умолчанию `true`.
    pub autostart: bool,
    /// `language` — язык интерфейса `system` | `ru` | `en`, как записан (разбирает
    /// `i18n::resolve`). Нет ключа — `None`, как `system`.
    pub language: Option<String>,
}

impl Default for UiSettings {
    fn default() -> Self {
        Self {
            first_run_done: false,
            pill_enabled: true,
            pill_position: None,
            autostart: true,
            language: None,
        }
    }
}

pub fn load() -> UiSettings {
    let Some(path) = crate::logger::app_dir().map(|d| d.join("settings.json")) else {
        return UiSettings::default();
    };
    match std::fs::read_to_string(&path) {
        Ok(text) => parse(&text),
        Err(_) => UiSettings::default(), // файла нет — первый запуск
    }
}

pub fn parse(text: &str) -> UiSettings {
    let Ok(v) = serde_json::from_str::<Value>(text.trim_start_matches('\u{feff}')) else {
        crate::log_warn!("settings.json не читается как JSON — беру значения по умолчанию");
        return UiSettings::default();
    };
    let d = UiSettings::default();
    UiSettings {
        first_run_done: v
            .get("first_run_done")
            .and_then(Value::as_bool)
            .unwrap_or(d.first_run_done),
        pill_enabled: v.get("pill_enabled").and_then(Value::as_bool).unwrap_or(d.pill_enabled),
        pill_position: v.get("pill_position").and_then(parse_position),
        autostart: v.get("autostart").and_then(Value::as_bool).unwrap_or(d.autostart),
        language: v.get("language").and_then(Value::as_str).map(str::to_string),
    }
}

fn parse_position(v: &Value) -> Option<(i32, i32)> {
    let arr = v.as_array()?;
    if arr.len() != 2 {
        return None;
    }
    let coord = |x: &Value| -> Option<i32> {
        let f = x.as_f64()?;
        (f.is_finite() && f.abs() < 1_000_000.0).then(|| f.round() as i32)
    };
    Some((coord(&arr[0])?, coord(&arr[1])?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_when_keys_missing() {
        let s = parse(r#"{"ptt_key": "rctrl"}"#);
        assert_eq!(s, UiSettings::default());
        assert!(!s.first_run_done);
        assert!(s.pill_enabled);
    }

    #[test]
    fn reads_keys() {
        let s = parse(
            r#"{"first_run_done": true, "pill_enabled": false, "pill_position": [100, -20.6]}"#,
        );
        assert!(s.first_run_done);
        assert!(!s.pill_enabled);
        assert_eq!(s.pill_position, Some((100, -21)));
    }

    #[test]
    fn bad_position_is_ignored() {
        assert_eq!(parse(r#"{"pill_position": null}"#).pill_position, None);
        assert_eq!(parse(r#"{"pill_position": [1]}"#).pill_position, None);
        assert_eq!(parse(r#"{"pill_position": ["a", 2]}"#).pill_position, None);
        assert_eq!(parse(r#"{"pill_position": {"x": 1}}"#).pill_position, None);
    }

    #[test]
    fn language_key() {
        assert_eq!(parse(r#"{"language": "en"}"#).language.as_deref(), Some("en"));
        assert_eq!(parse(r#"{"language": "system"}"#).language.as_deref(), Some("system"));
        assert_eq!(parse(r#"{"language": 1}"#).language, None);
        assert_eq!(parse("{}").language, None);
    }

    #[test]
    fn broken_json_and_bom() {
        assert_eq!(parse("{не json"), UiSettings::default());
        assert!(parse("\u{feff}{\"first_run_done\": true}").first_run_done);
    }
}
