use std::path::{Path, PathBuf};

/// Выпускная сборка без ядра разрешена только явно (например, проверка сборки оболочки).
const ALLOW_NO_CORE: &str = "RUPOR_ALLOW_NO_CORE";

fn main() {
    let manifest =
        PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let release = std::env::var("PROFILE").is_ok_and(|p| p == "release");
    // `resources/core/` — сюда build.cmd кладёт собранное PyInstaller-ядро (rupor-core).
    let core_dir = manifest.join("resources").join("core");
    println!("cargo:rerun-if-changed=resources/core");
    println!("cargo:rerun-if-env-changed={ALLOW_NO_CORE}");

    if release && std::env::var_os(ALLOW_NO_CORE).is_none() {
        // Без ядра установщик собрался бы «успешно», но установленный Рупор не нашёл бы ядро
        // (запасной вариант с .venv есть только в debug, см. sidecar.rs).
        let exe = core_dir.join("rupor-core.exe");
        if !exe.is_file() {
            panic!(
                "\n\nНет ядра Рупора: {}\n\
                 Установщик без ядра не работает. Собирайте через build.cmd в корне проекта \
                 (он собирает ядро PyInstaller, копирует его в resources\\core и запускает \
                 `npm run tauri build`) или сначала выполните `build.cmd core`.\n\
                 Если ядро действительно не нужно (проверка сборки оболочки), задайте {ALLOW_NO_CORE}=1.\n",
                exe.display()
            );
        }
    } else {
        // При разработке ядра в ресурсах нет (оно берётся из .venv), а tauri-build падает
        // на отсутствующем ресурсе, поэтому создаём папку с поясняющим файлом.
        ensure_dev_core_dir(&core_dir);
    }

    check_versions(&manifest, release);
    tauri_build::build()
}

fn ensure_dev_core_dir(core_dir: &Path) {
    if !core_dir.exists() {
        std::fs::create_dir_all(core_dir).expect("не удалось создать resources/core");
    }
    let readme = core_dir.join("README.txt");
    if !readme.exists() {
        std::fs::write(
            &readme,
            "Сюда build.cmd копирует собранное ядро Рупора (PyInstaller onedir rupor-core).\r\n\
             Файл создан автоматически debug-сборкой (build.rs), его можно не трогать.\r\n",
        )
        .expect("не удалось записать resources/core/README.txt");
    }
}

/// Версия записана в четырёх местах, а установщик той же версии ставится поверх без удаления
/// прежней — расхождение легко пропустить. В release — ошибка сборки, в debug — предупреждение.
fn check_versions(manifest: &Path, release: bool) {
    let cargo = env!("CARGO_PKG_VERSION");
    let ui = manifest.parent().expect("ui/");
    let sources = [
        ("tauri.conf.json", manifest.join("tauri.conf.json"), Kind::Json),
        ("ui/package.json", ui.join("package.json"), Kind::Json),
        ("pyproject.toml", ui.join("..").join("pyproject.toml"), Kind::Pyproject),
    ];
    let mut mismatches = Vec::new();
    for (name, path, kind) in &sources {
        println!("cargo:rerun-if-changed={}", path.display());
        // Файла может не быть (собирается только оболочка) — тогда сверять не с чем.
        let Ok(text) = std::fs::read_to_string(path) else { continue };
        match kind.version(&text) {
            Some(v) if v == cargo => {}
            Some(v) => mismatches.push(format!("{name} {v}")),
            None => mismatches.push(format!("{name} — версия не найдена")),
        }
    }
    if mismatches.is_empty() {
        return;
    }
    let msg = format!(
        "Версии Рупора расходятся: Cargo.toml {cargo}, {}. Поднимите версию во всех файлах сразу.",
        mismatches.join(", ")
    );
    if release {
        panic!("\n\n{msg}\n");
    }
    println!("cargo:warning={msg}");
}

enum Kind {
    Json,
    Pyproject,
}

impl Kind {
    fn version(&self, text: &str) -> Option<String> {
        match self {
            Kind::Json => serde_json::from_str::<serde_json::Value>(text)
                .ok()?
                .get("version")?
                .as_str()
                .map(str::to_string),
            Kind::Pyproject => pyproject_version(text),
        }
    }
}

/// `version = "x.y.z"` из секции `[project]` pyproject.toml.
fn pyproject_version(text: &str) -> Option<String> {
    let mut in_project = false;
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_project = line == "[project]";
            continue;
        }
        if !in_project {
            continue;
        }
        let Some(rest) = line.strip_prefix("version") else { continue };
        let Some(value) = rest.trim_start().strip_prefix('=') else { continue };
        return Some(value.trim().trim_matches(|c| c == '"' || c == '\'').to_string());
    }
    None
}
