"""Папка моделей (настройка model_dir) и подбор модели под компьютер.

- проверка настройки (кириллица, переменные окружения, относительный путь — ошибка);
- поиск и загрузка модели идут в папку model_dir;
- fetch.move_model / remove_model на настоящем (маленьком) кэше HuggingFace во временной
  папке: настоящий кэш пользователя не трогается, в сеть тесты не ходят;
- команды model_dir_set и model_recommend через настоящий WS-сервер (фикстура env из
  test_api: движок без модели, без хука и без микрофона)."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from rupor import asr, config, engine, fetch, i18n, recommend
from rupor.engine import Engine
from rupor.storage import Storage
from test_api import Env, FakeRecognizer, FakeRecorder, _wait_for, env  # noqa: F401 — фикстура env

REPO = "org/m"
FOLDER = "models--org--m"
REV = "0123456789abcdef0123456789abcdef01234567"
FILES: dict[str, bytes] = {
    "config.json": b'{"alignment_heads": []}',
    "preprocessor_config.json": b'{"feature_size": 128}',
    "model.bin": bytes(range(256)) * 12_000,          # ≈3 МБ — несколько событий прогресса
    "tokenizer.json": b'{"model": {"type": "BPE"}}',
    "vocabulary.json": b'["a", "b"]',
}
TOTAL = sum(len(v) for v in FILES.values())


def blob(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def can_symlink(where: Path) -> bool:
    probe = where / "probe-link"
    try:
        os.symlink("nowhere", probe)
    except OSError:
        return False
    probe.unlink()
    return True


def make_cache(cache: Path, links: bool = True) -> Path:
    """Кэш HuggingFace с моделью org/m: blobs + snapshots (относительные ссылки или сами
    файлы) + refs/main + trees + .locks — как его оставляет huggingface_hub."""
    folder = cache / FOLDER
    snap = folder / "snapshots" / REV
    (folder / "blobs").mkdir(parents=True)
    snap.mkdir(parents=True)
    for name, data in FILES.items():
        (folder / "blobs" / blob(data)).write_bytes(data)
        if links:
            os.symlink(os.path.join("..", "..", "blobs", blob(data)), snap / name)
        else:
            (snap / name).write_bytes(data)
    (folder / "refs").mkdir()
    (folder / "refs" / "main").write_text(REV, encoding="utf-8")
    (folder / "trees").mkdir()
    (folder / "trees" / "listing.txt").write_text("config.json\n", encoding="utf-8")
    locks = cache / ".locks" / FOLDER
    locks.mkdir(parents=True)
    (locks / (blob(FILES["model.bin"]) + ".lock")).write_text("", encoding="utf-8")
    return folder


@pytest.fixture
def links_ok(tmp_path: Path) -> None:
    if not can_symlink(tmp_path):
        pytest.skip("в этой системе нельзя создавать символьные ссылки")


@pytest.fixture(autouse=True)
def _fast_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "PROGRESS_INTERVAL_S", 0.0)
    monkeypatch.setattr(fetch, "_REPLACE_PAUSES_S", (0.0,))


def progress_log() -> tuple[list[tuple[float, str]], Callable[[float, str], None]]:
    events: list[tuple[float, str]] = []
    return events, lambda p, t: events.append((p, t))


def snapshot_files(folder: Path) -> dict[str, bytes]:
    snap = folder / "snapshots" / REV
    return {p.name: p.read_bytes() for p in snap.iterdir()}


# ---------------------------- настройка ----------------------------

def test_model_dir_default_and_valid_paths() -> None:
    assert config.Settings().model_dir == ""
    assert "model_dir" in config.MODEL_FIELDS
    norm = config.normalize_model_dir
    assert norm("") == "" and norm("   ") == ""
    assert norm(r"D:\Модели\whisper-models") == r"D:\Модели\whisper-models"
    assert norm("D:/Модели/whisper models/") == r"D:\Модели\whisper models"
    assert norm(r'  "D:\Мои модели\whisper"  ') == r"D:\Мои модели\whisper"   # из проводника
    assert norm(r"D:\a\..\b\.\c") == r"D:\b\c"
    assert norm(r"\\nas\share\Модели") == r"\\nas\share\Модели"
    assert norm("D:\\") == "D:\\"


def test_model_dir_expands_env_and_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUPOR_TEST_TECH", r"D:\Модели")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Тест")
    norm = config.normalize_model_dir
    assert norm(r"%RUPOR_TEST_TECH%\whisper-models") == r"D:\Модели\whisper-models"
    assert norm(r"~\models") == r"C:\Users\Тест\models"


@pytest.mark.parametrize("value,text", [
    ("models", "полный путь"),
    (r"whisper\models", "полный путь"),
    ("D:models", "полный путь"),
    (r"\models", "полный путь"),
    ("./models", "полный путь"),
    (r"D:\a|b", "недопустимые символы"),
    (r"D:\a?b", "недопустимые символы"),
    (r"D:\a:b", "недопустимые символы"),
    (r"%RUPOR_NO_SUCH_VAR%\models", "RUPOR_NO_SUCH_VAR"),
    (5, "строка"),
    (None, "строка"),
])
def test_model_dir_rejects(value: Any, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUPOR_NO_SUCH_VAR", raising=False)
    with pytest.raises(ValueError, match=text):
        config.normalize_model_dir(value)


def test_model_dir_patch_error_names_setting() -> None:
    s = config.Settings()
    with pytest.raises(ValueError) as ei:
        config.apply_patch(s, {"model_dir": "models"})
    assert str(ei.value).startswith("Папка модели: ")
    assert s.model_dir == ""
    assert config.apply_patch(s, {"model_dir": r"D:\Модели\whisper-models\\"}) == ["model_dir"]
    assert s.model_dir == r"D:\Модели\whisper-models"
    i18n.set_language("en")
    with pytest.raises(ValueError, match="^Model folder: a full folder path"):
        config.apply_patch(s, {"model_dir": "models"})


def test_model_dir_soft_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    p = config.settings_path()
    p.write_text(json.dumps({"model_dir": "relative\\models"}), encoding="utf-8")
    assert config.load().model_dir == ""          # неверное → по умолчанию, Рупор стартует
    p.write_text(json.dumps({"model_dir": "D:/Модели/whisper-models"}, ensure_ascii=False),
                 encoding="utf-8")
    assert config.load().model_dir == r"D:\Модели\whisper-models"
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["model_dir"] == r"D:\Модели\whisper-models"


def test_model_cache_dir() -> None:
    from huggingface_hub import constants
    default = Path(os.path.abspath(constants.HF_HUB_CACHE))
    assert fetch.model_cache_dir("") == default and fetch.model_cache_dir(None) == default
    assert default.is_absolute()
    assert fetch.model_cache_dir(r"D:\Модели\whisper-models") == \
        Path(r"D:\Модели\whisper-models")
    assert fetch.same_dir(r"D:\Models\x", "d:/models/X/")
    assert not fetch.same_dir(r"D:\Models\x", r"D:\Models\y")


# ---------------------------- поиск модели в папке ----------------------------

def test_model_path_looks_only_in_given_folder(tmp_path: Path) -> None:
    make_cache(tmp_path / "Модели whisper", links=False)
    found = fetch.model_path(REPO, tmp_path / "Модели whisper")
    assert found == tmp_path / "Модели whisper" / FOLDER / "snapshots" / REV
    assert fetch.model_path(REPO, tmp_path / "другая") is None


def test_recognizer_loads_from_model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def fake_path(model: str, cache_dir: Any = None) -> Path:
        seen.append(cache_dir)
        return tmp_path

    monkeypatch.setattr(fetch, "model_path", fake_path)
    monkeypatch.setattr(asr, "WhisperModel", lambda path, **kw: SimpleNamespace(path=path))
    rec = asr.Recognizer(config.Settings(model_dir=r"D:\Модели\whisper-models"))
    assert rec._create("cpu", "int8").path == str(tmp_path)
    rec2 = asr.Recognizer(config.Settings())
    rec2._create("cpu", "int8")
    assert seen == [r"D:\Модели\whisper-models", None]


def test_engine_lookups_and_download_use_model_dir(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    folder = str(tmp_path / "Модели" / "whisper-models")
    ready_calls: list[tuple[str, Any]] = []
    downloads: list[tuple[str, Any]] = []

    def fake_ready(model: str, cache_dir: Any = None) -> bool:
        ready_calls.append((model, cache_dir))
        return False

    def fake_download(model: str, cb: Callable[[float, str], None], cache_dir: Any = None) -> str:
        downloads.append((model, cache_dir))
        return "x"

    monkeypatch.setattr(fetch, "model_ready", fake_ready)
    monkeypatch.setattr(fetch, "cuda_ready", lambda dirs=None: True)
    monkeypatch.setattr(fetch, "download_model", fake_download)
    rec = FakeRecognizer()
    rec._loaded = False
    storage = Storage(tmp_path / "rupor.db")
    eng = Engine(config.Settings(sounds=False, first_run_done=True, model_dir=folder), storage,
                 recognizer=rec, recorder_factory=lambda dev, cb: FakeRecorder(),
                 field_reader=lambda: None)
    try:
        st = eng.setup_status()
        assert st["model_ready"] is False
        assert st["model_dir"] == folder
        assert st["model_dir_default"] == str(fetch.model_cache_dir(""))
        assert ready_calls[-1] == ("large-v3-turbo", folder)
        eng._load_model()                     # модели нет — качается в model_dir
        _wait_for(lambda: bool(downloads))
        assert downloads == [("large-v3-turbo", folder)]
        assert ready_calls[-1] == ("large-v3-turbo", folder)
    finally:
        eng.shutdown()
        storage.close()


# ---------------------------- перенос модели ----------------------------

def test_move_when_destination_already_has_model(tmp_path: Path) -> None:
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    make_cache(dst, links=False)
    events, cb = progress_log()
    path = fetch.move_model(REPO, src, dst, cb)
    assert Path(path) == dst / FOLDER / "snapshots" / REV
    assert fetch.model_path(REPO, src) is not None     # исходная копия не тронута
    assert events == [(100.0, f"Модель {REPO} уже есть в {dst}")]


def test_move_same_volume_renames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                  links_ok: None) -> None:
    src, dst = tmp_path / "old", tmp_path / "Модели" / "whisper-models"
    make_cache(src)

    def no_copy(*a: Any, **kw: Any) -> None:
        raise AssertionError("на том же томе копировать не нужно")

    monkeypatch.setattr(fetch, "_copy_file", no_copy)
    events, cb = progress_log()
    path = fetch.move_model(REPO, src, dst, cb)
    assert Path(path) == dst / FOLDER / "snapshots" / REV
    assert not (src / FOLDER).exists()                  # переименование, не копия
    assert (dst / ".locks" / FOLDER).is_dir() and not (src / ".locks" / FOLDER).exists()
    snap = dst / FOLDER / "snapshots" / REV
    assert all(os.path.islink(snap / name) for name in FILES)
    assert snapshot_files(dst / FOLDER) == FILES
    assert events[0] == (0.0, f"Переношу модель {REPO}…")
    assert events[-1] == (100.0, f"Модель {REPO} перенесена")


def test_move_cross_volume_copies_with_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             links_ok: None) -> None:
    src, dst = tmp_path / "old", tmp_path / "Модели" / "whisper-models"
    make_cache(src)
    (src / FOLDER / "blobs" / "deadbeef.incomplete").write_bytes(b"\0" * 1000)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)
    events, cb = progress_log()
    path = fetch.move_model(REPO, src, dst, cb)
    folder = dst / FOLDER
    assert Path(path) == folder / "snapshots" / REV
    assert fetch.model_path(REPO, src) is not None      # исходная копия на месте
    snap = folder / "snapshots" / REV
    for name, data in FILES.items():
        assert os.path.islink(snap / name)
        assert os.readlink(snap / name) == os.path.join("..", "..", "blobs", blob(data))
        assert (folder / "blobs" / blob(data)).read_bytes() == data
    assert snapshot_files(folder) == FILES
    assert (folder / "refs" / "main").read_text(encoding="utf-8") == REV
    assert (folder / "trees" / "listing.txt").is_file()
    assert (dst / ".locks" / FOLDER).is_dir()
    assert not (folder / "blobs" / "deadbeef.incomplete").exists()   # недокачанное не берём
    assert not (dst / (FOLDER + ".rupor-tmp")).exists()
    pcts = [p for p, _ in events]
    assert pcts[0] == 0.0 and pcts[-1] == 100.0 and pcts == sorted(pcts)
    mid = [t for p, t in events if 0 < p < 100]
    assert mid and all(t.startswith(f"Переношу модель {REPO}: ") and t.endswith(" МБ")
                       for t in mid)


def test_move_without_symlink_privilege_writes_files_once(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch,
                                                          links_ok: None) -> None:
    """Ссылки создавать нельзя (нет привилегии): на месте ссылки — сам файл, а его блоб
    отдельно не копируется (место на диске не удваивается)."""
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)

    def no_links(*a: Any, **kw: Any) -> None:
        raise OSError(errno.EPERM, "A required privilege is not held by the client")

    monkeypatch.setattr(os, "symlink", no_links)
    fetch.move_model(REPO, src, dst, lambda p, t: None)
    folder = dst / FOLDER
    snap = folder / "snapshots" / REV
    assert not any(os.path.islink(snap / n) for n in FILES)
    assert snapshot_files(folder) == FILES
    blobs = list((folder / "blobs").iterdir()) if (folder / "blobs").exists() else []
    assert blobs == []
    used = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    assert used < TOTAL + 1000                          # без второй копии model.bin
    assert fetch.model_path(REPO, dst) == snap


def test_move_regular_snapshot_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кэш без ссылок (так huggingface_hub пишет без права на ссылки) копируется как есть."""
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)
    fetch.move_model(REPO, src, dst, lambda p, t: None)
    assert snapshot_files(dst / FOLDER) == FILES
    assert fetch.model_path(REPO, src) is not None


@pytest.mark.parametrize("exc,text", [
    (OSError(errno.EIO, "Ошибка ввода-вывода"), "Не удалось перенести модель"),
    (OSError(errno.ENOSPC, "No space left on device"), "закончилось место"),
])
def test_move_failure_removes_partial_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           exc: OSError, text: str) -> None:
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)
    real = fetch._copy_file
    n = [0]

    def flaky(s: Path, d: Path, report: Callable[[int], None]) -> None:
        n[0] += 1
        if n[0] == 3:
            raise exc
        real(s, d, report)

    monkeypatch.setattr(fetch, "_copy_file", flaky)
    with pytest.raises(fetch.FetchError, match=text):
        fetch.move_model(REPO, src, dst, lambda p, t: None)
    assert not (dst / FOLDER).exists()
    assert not (dst / (FOLDER + ".rupor-tmp")).exists()   # прерванная копия не осталась
    assert fetch.model_path(REPO, src) is not None


def test_move_checks_free_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: SimpleNamespace(total=1 << 40, used=0, free=10_000))

    def no_copy(*a: Any, **kw: Any) -> None:
        raise AssertionError("места нет — копировать нельзя")

    monkeypatch.setattr(fetch, "_copy_file", no_copy)
    with pytest.raises(fetch.FetchError, match="Недостаточно места на диске для модели"):
        fetch.move_model(REPO, src, dst, lambda p, t: None)
    assert not (dst / FOLDER).exists() and not (dst / (FOLDER + ".rupor-tmp")).exists()


@pytest.mark.parametrize("same_volume", [False, True])
def test_move_verification_failure_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             same_volume: bool) -> None:
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: same_volume)
    real = fetch.model_path

    def blind(model: str, cache_dir: Any = None) -> Path | None:
        if cache_dir is not None and fetch.same_dir(cache_dir, dst):
            return None                     # «после переноса модель не находится»
        return real(model, cache_dir)

    monkeypatch.setattr(fetch, "model_path", blind)
    with pytest.raises(fetch.FetchError, match="не находится"):
        fetch.move_model(REPO, src, dst, lambda p, t: None)
    assert not (dst / FOLDER).exists()
    assert not (dst / (FOLDER + ".rupor-tmp")).exists()
    assert real(REPO, src) is not None      # переименованная — возвращена на место


def test_move_replaces_stale_temp_and_merges_partial(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """След прерванной прошлой попытки удаляется; неполная папка модели в новом месте
    (прерванная загрузка) дополняется, недокачанный файл в ней не мешает."""
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    stale = dst / (FOLDER + ".rupor-tmp")
    (stale / "blobs").mkdir(parents=True)
    (stale / "blobs" / "junk").write_bytes(b"junk")
    (dst / FOLDER / "blobs").mkdir(parents=True)
    (dst / FOLDER / "blobs" / "cafe.incomplete").write_bytes(b"\0" * 10)
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)
    path = fetch.move_model(REPO, src, dst, lambda p, t: None)
    assert Path(path) == dst / FOLDER / "snapshots" / REV
    assert not stale.exists()
    assert snapshot_files(dst / FOLDER) == FILES
    assert (dst / FOLDER / "blobs" / "cafe.incomplete").exists()   # чужое не удаляем


def test_move_errors(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(fetch.FetchError, match="нет в папке"):
        fetch.move_model(REPO, tmp_path / "empty", tmp_path / "new", lambda p, t: None)
    make_cache(tmp_path / "old", links=False)
    (tmp_path / "file").write_text("x", encoding="utf-8")
    with pytest.raises(fetch.FetchError, match="Не удалось создать папку"):
        fetch.move_model(REPO, tmp_path / "old", tmp_path / "file" / "models",
                         lambda p, t: None)
    with pytest.raises(fetch.FetchError, match="Неизвестная модель"):
        fetch.move_model("нет-такой-модели", tmp_path / "old", tmp_path / "new",
                         lambda p, t: None)


def junction(target: Path, link: Path) -> None:
    """Junction link → target (как mklink /J: прав администратора не нужно)."""
    import _winapi
    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def test_same_dir_sees_same_folder_under_other_path(tmp_path: Path) -> None:
    real = tmp_path / "real models"
    real.mkdir()
    (tmp_path / "other").mkdir()
    junction(real, tmp_path / "alias")
    assert fetch.same_dir(real, tmp_path / "alias")
    assert fetch.same_dir(str(real).upper(), tmp_path / "alias" / ".")
    # папки ещё нет — по настоящему пути (junction выше раскрывается)
    assert fetch.same_dir(real / "hub", tmp_path / "alias" / "hub")
    assert not fetch.same_dir(real, tmp_path / "other")
    assert not fetch.same_dir(real / "hub", tmp_path / "other" / "hub")


@pytest.mark.parametrize("level", ["cache", "model"])
def test_move_to_same_physical_copy_never_deletes_it(tmp_path: Path, level: str) -> None:
    """Новая папка — та же старая под другим путём (junction на весь кэш или на саму
    models--org--name): «уже там», и удаление «старой» копии стёрло бы единственную —
    shares_files это видит."""
    real = tmp_path / "real"
    make_cache(real, links=False)
    if level == "cache":
        new = tmp_path / "alias"
        junction(real, new)
    else:
        new = tmp_path / "new"
        junction(real / FOLDER, new / FOLDER)
    events, cb = progress_log()
    path = fetch.move_model(REPO, real, new, cb)
    assert events == [(100.0, f"Модель {REPO} уже есть в {new}")]
    assert fetch.same_dir(path, new / FOLDER / "snapshots" / REV)   # путь — какой даст hub
    assert fetch.shares_files(REPO, real, new) is True
    assert fetch.model_path(REPO, real) is not None and fetch.model_path(REPO, new) is not None


def test_shares_files_separate_copy_and_hardlinks(tmp_path: Path) -> None:
    old, new, linked = tmp_path / "old", tmp_path / "new", tmp_path / "linked"
    make_cache(old, links=False)
    make_cache(new, links=False)
    assert fetch.shares_files(REPO, old, new) is False         # честная вторая копия
    assert fetch.shares_files(REPO, old, tmp_path / "empty") is False   # копии нет
    # копия из жёстких ссылок на файлы старой: удалить старую — значит удалить и эти файлы
    shutil.copytree(old, linked, copy_function=os.link)
    assert fetch.shares_files(REPO, old, linked) is True
    # копия внутри удаляемых папок старой
    nested = old / FOLDER
    shutil.copytree(old / FOLDER, tmp_path / "stage")
    os.replace(tmp_path / "stage", nested / FOLDER)
    assert fetch.model_path(REPO, nested) is not None
    assert fetch.shares_files(REPO, old, nested) is True


@pytest.mark.parametrize("sub", [FOLDER, FOLDER + "/blobs", FOLDER + "/snapshots/" + REV,
                                 ".locks", ".locks/" + FOLDER])
def test_move_refuses_target_inside_model_folder(tmp_path: Path, sub: str) -> None:
    """Новая папка внутри папки самой модели или .locks: копия легла бы в то, что удаляет
    remove_model, — пропали бы обе. Отказ до любой работы с диском."""
    old = tmp_path / "old"
    make_cache(old, links=False)
    before = sorted(str(p) for p in old.rglob("*"))
    target = old / sub
    with pytest.raises(fetch.FetchError, match="внутри служебной папки модели"):
        fetch.move_model(REPO, old, target, lambda p, t: None)
    with pytest.raises(fetch.FetchError, match="Выберите другую папку"):
        fetch.check_move_target(REPO, old, target)
    assert sorted(str(p) for p in old.rglob("*")) == before    # ничего не создано
    assert fetch.model_path(REPO, old) is not None
    fetch.check_move_target(REPO, old, tmp_path / "new")         # рядом — можно
    fetch.check_move_target(REPO, old, old / "sub")              # внутри кэша, не модели — можно
    fetch.check_move_target("нет-такой-модели", old, target)     # папки такой модели нет


def test_move_refuses_target_inside_model_folder_via_unc_loopback(tmp_path: Path) -> None:
    """Папка модели под UNC-путём на эту же машину (\\\\localhost\\C$\\…): realpath его не
    сводит к локальному, но это та же папка — перенос внутрь неё запрещён, копии целы."""
    old = tmp_path / "old"
    make_cache(old, links=False)

    def unc(p: Path) -> str:
        s = str(p)
        return "\\\\localhost\\" + s[0] + "$" + s[2:]

    try:
        os.stat(unc(old))
    except OSError as e:
        pytest.skip(f"нет доступа к административной шаре: {e}")
    for target in (unc(old / FOLDER), unc(old / FOLDER / "sub"), unc(old / ".locks" / "x")):
        with pytest.raises(fetch.FetchError, match="Выберите другую папку"):
            fetch.check_move_target(REPO, old, target)
    assert fetch.model_path(REPO, old) is not None
    fetch.check_move_target(REPO, old, unc(tmp_path / "new"))   # рядом — можно


def test_move_completes_partial_destination_copy(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """В новой папке модель «есть», но без файла, который есть в исходной (старый
    huggingface_hub не докачал preprocessor_config.json, списка файлов trees нет): это не
    «уже там» — копия дополняется, иначе удалилась бы полная исходная."""
    src, dst = tmp_path / "old", tmp_path / "new"
    make_cache(src, links=False)
    make_cache(dst, links=False)
    (dst / FOLDER / "snapshots" / REV / "preprocessor_config.json").unlink()
    assert fetch.model_path(REPO, dst) is not None      # для model_path копия «полная»
    monkeypatch.setattr(fetch, "_same_volume", lambda a, b: False)
    events, cb = progress_log()
    path = fetch.move_model(REPO, src, dst, cb)
    assert Path(path) == dst / FOLDER / "snapshots" / REV
    assert snapshot_files(dst / FOLDER) == FILES
    assert not any("уже есть" in t for _p, t in events)
    assert fetch.model_path(REPO, src) is not None


# ---------------------------- удаление модели ----------------------------

def test_remove_model_only_its_folders(tmp_path: Path) -> None:
    cache = tmp_path / "hub"
    make_cache(cache, links=can_symlink(tmp_path))
    other = cache / "models--org--other"
    (other / "blobs").mkdir(parents=True)
    (other / "blobs" / "x").write_bytes(b"x")
    (cache / ".locks" / "models--org--other").mkdir(parents=True)
    (cache / "CACHEDIR.TAG").write_text("tag", encoding="utf-8")
    assert fetch.remove_model(REPO, cache) is True
    assert not (cache / FOLDER).exists() and not (cache / ".locks" / FOLDER).exists()
    assert (other / "blobs" / "x").exists() and (cache / ".locks" / "models--org--other").exists()
    assert (cache / "CACHEDIR.TAG").exists()
    assert fetch.remove_model(REPO, cache) is True          # уже нет — не ошибка


def test_remove_model_refuses_paths_and_bad_names(tmp_path: Path) -> None:
    own = tmp_path / "моя модель"
    own.mkdir()
    (own / "model.bin").write_bytes(b"x")
    assert fetch.remove_model(str(own), tmp_path) is False
    assert (own / "model.bin").exists()
    (tmp_path / "victim").mkdir()
    for bad in ("org/..", "../victim", "a/b\\..\\..\\victim", "нет-такой-модели"):
        assert fetch.remove_model(bad, tmp_path / "hub") is False
    assert (tmp_path / "victim").exists()


def test_remove_model_reports_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_cache(tmp_path, links=False)

    def locked(*a: Any, **kw: Any) -> None:
        raise PermissionError(13, "Файл занят")

    monkeypatch.setattr(shutil, "rmtree", locked)
    assert fetch.remove_model(REPO, tmp_path) is False
    assert (tmp_path / FOLDER).exists()


# ---------------------------- команда model_dir_set ----------------------------

MODEL = "large-v3-turbo"          # модель движка по умолчанию


class FakeModels:
    """Где «лежит» модель (папки — как их передаёт движок: None — кэш по умолчанию) и что
    движок просил сделать с папками. Кэш по умолчанию — во временной папке теста (настоящий
    кэш пользователя не трогается даже чтением)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, env: Env) -> None:
        from huggingface_hub import constants
        monkeypatch.setattr(constants, "HF_HUB_CACHE", str(env.tmp / "hf" / "hub"))
        self.ready: set[str | None] = {None}          # где лежит MODEL
        self.others: dict[str, set[str | None]] = {}  # где лежат другие модели
        self.moves: list[tuple[str, Any, Any]] = []
        self.removed: list[tuple[str, Any]] = []
        self.downloads: list[tuple[str, Any]] = []
        self.order: list[str] = []
        self.gate = threading.Event()
        self.gate.set()
        self.move_error: Exception | None = None
        self.remove_ok = True
        self.remove_gate = threading.Event()   # снять — удаление старой копии «идёт»
        self.remove_gate.set()
        self.download_gate = threading.Event()   # снять — загрузка «идёт»
        self.download_gate.set()
        self.rename = False           # перенос «переименованием»: в старой папке модели нет
        self.vanish = False           # после переноса новая папка «пропала» (флешка вынута)
        self.load_error: Exception | None = None   # rec.load падает (файл не читается)
        monkeypatch.setattr(fetch, "model_ready", self.model_ready)
        monkeypatch.setattr(fetch, "move_model", self.move_model)
        monkeypatch.setattr(fetch, "remove_model", self.remove_model)
        monkeypatch.setattr(fetch, "download_model", self.download_model)
        monkeypatch.setattr(fetch, "shares_files", lambda model, old, new: False)
        rec = env.rec
        real_load, real_unload = rec.load, rec.unload

        def load() -> None:
            self.order.append("load")
            if self.load_error is not None:
                raise self.load_error
            real_load()

        def unload() -> None:
            self.order.append("unload")
            real_unload()

        rec.load = load  # type: ignore[method-assign]
        rec.unload = unload  # type: ignore[method-assign]

    def where(self, model: str) -> set[str | None]:
        return self.ready if model == MODEL else self.others.setdefault(model, set())

    def model_ready(self, model: str, cache_dir: Any = None) -> bool:
        return cache_dir in self.where(model)

    def move_model(self, model: str, src: Any, dst: Any, cb: Callable[[float, str], None]) -> str:
        self.moves.append((model, src, dst))
        self.order.append("move")
        cb(10.0, f"Переношу модель {model}: 1 из 10 МБ")
        assert self.gate.wait(10)
        if self.move_error is not None:
            raise self.move_error
        cb(60.0, f"Переношу модель {model}: 6 из 10 МБ")
        if self.rename:
            self.where(model).discard(src)
        if not self.vanish:
            self.where(model).add(dst)
        return "x"

    def remove_model(self, model: str, cache_dir: Any) -> bool:
        self.removed.append((model, cache_dir))
        self.order.append("remove")
        assert self.remove_gate.wait(10)
        if self.remove_ok:
            self.where(model).discard(cache_dir)
        return self.remove_ok

    def download_model(self, model: str, cb: Callable[[float, str], None],
                       cache_dir: Any = None) -> str:
        self.downloads.append((model, cache_dir))
        cb(50.0, "половина")
        assert self.download_gate.wait(10)
        self.where(model).add(cache_dir)
        return "x"


def new_folder(env: Env) -> str:
    return config.normalize_model_dir(str(env.tmp / "Модели" / "whisper-models"))


def saved_settings(env: Env) -> dict[str, Any]:
    """settings.json движка теста ({} — ещё ни разу не сохранялся)."""
    p = env.tmp / "Rupor" / "settings.json"
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return data


def test_model_dir_set_move_flow(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    fm = FakeModels(monkeypatch, env)
    fm.gate.clear()
    new = new_folder(env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new + "\\", "move": True}) == {"ok": True,
                                                                          "moving": True}
    c.wait_event("progress", lambda d: d["what"] == "model" and d["pct"] == 10.0)
    # пока идёт перенос: диктовка работает на загруженной модели, настройка прежняя
    env.dictate("диктовка во время переноса")
    c.wait_event("history")
    assert env.calls.delivered == [("диктовка во время переноса ", False)]
    assert c.call("get_settings")["model_dir"] == ""
    assert "переносится" in c.error("model_dir_set", {"path": str(env.tmp / "x"), "move": True})
    assert "переносится" in c.error("model_dir_set", {"path": str(env.tmp / "y"), "move": False})
    fm.gate.set()
    done = c.wait_event("progress", lambda d: d["done"])
    assert done == {"what": "model", "pct": 100.0, "text": "Модель перенесена", "done": True,
                    "error": None}
    st = c.wait_event("settings", lambda d: d["model_dir"] == new, fresh=False)
    assert st["model_dir"] == new and saved_settings(env)["model_dir"] == new
    n = c.wait_event("notice", lambda d: "перенесена в" in d["text"], fresh=False)
    assert n["text"] == f"Модель перенесена в {new}" and n["level"] == "info" and n["toast"]
    assert fm.moves == [("large-v3-turbo", None, new)]
    assert fm.removed == [("large-v3-turbo", None)]
    # модель перезагружена из новой папки, старая копия удалена уже после этого
    assert fm.order == ["move", "unload", "load", "remove"]
    assert env.rec.loaded
    assert c.call("setup_status")["model_dir"] == new
    c.close()


@pytest.mark.parametrize("move,ready_old", [(False, True), (True, False)])
def test_model_dir_set_switch_downloads_into_new_folder(env: Env, monkeypatch: pytest.MonkeyPatch,
                                                        move: bool, ready_old: bool) -> None:
    """Без переноса (или переносить нечего) — только смена папки: модели там нет —
    качается туда, прежняя распознаёт; ничего не переносится и не удаляется."""
    fm = FakeModels(monkeypatch, env)
    if not ready_old:
        fm.ready = set()
    new = new_folder(env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new, "move": move}) == {"ok": True, "moving": False}
    assert c.wait_event("settings", fresh=False)["model_dir"] == new
    c.wait_event("progress", lambda d: d["done"] is True)
    _wait_for(lambda: "load" in fm.order)
    assert fm.downloads == [("large-v3-turbo", new)]
    assert fm.moves == [] and fm.removed == []
    assert env.rec.loaded
    c.close()


def test_model_dir_set_switch_to_folder_with_model_reloads(env: Env,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    fm = FakeModels(monkeypatch, env)
    new = new_folder(env)
    fm.ready.add(new)
    c = env.client()
    assert c.call("model_dir_set", {"path": new, "move": False})["moving"] is False
    _wait_for(lambda: fm.order == ["unload", "load"])
    assert fm.downloads == [] and fm.moves == []
    c.close()


def test_model_dir_set_same_folder_is_noop(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    fm = FakeModels(monkeypatch, env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": "", "move": True}) == {"ok": True, "moving": False}
    assert c.call("model_dir_set", {"path": ' "" ', "move": False})["moving"] is False
    assert c.call("get_settings")["model_dir"] == ""
    assert c.events("settings") == [] and fm.moves == [] and fm.order == []
    c.close()


def test_model_dir_set_same_folder_other_spelling_is_saved(env: Env,
                                                           monkeypatch: pytest.MonkeyPatch
                                                           ) -> None:
    """Та же папка, записанная иначе (явный путь кэша по умолчанию и "", другой регистр):
    запись сохраняется — без переноса и без удаления «старой» копии. Иначе кнопка «По
    умолчанию» после явного пути кэша ничего бы не делала (а перенос стёр бы модель)."""
    fm = FakeModels(monkeypatch, env)
    default = str(fetch.model_cache_dir(""))
    fm.ready |= {default, default.upper()}     # та же папка — модель и там «есть»
    c = env.client()
    assert c.call("model_dir_set", {"path": default, "move": True}) == {"ok": True,
                                                                       "moving": False}
    assert c.call("get_settings")["model_dir"] == default
    assert saved_settings(env)["model_dir"] == default
    assert c.call("model_dir_set", {"path": default.upper(), "move": True})["moving"] is False
    assert c.call("get_settings")["model_dir"] == default.upper()
    # «По умолчанию» после явного пути — снова "" (кэш по HF_HOME / HF_HUB_CACHE)
    assert c.call("model_dir_set", {"path": "", "move": True}) == {"ok": True, "moving": False}
    assert c.call("get_settings")["model_dir"] == "" and saved_settings(env)["model_dir"] == ""
    assert fm.moves == [] and fm.removed == [] and fm.downloads == []
    c.close()


def test_model_dir_set_invalid(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    fm = FakeModels(monkeypatch, env)
    (env.tmp / "файл").write_text("x", encoding="utf-8")
    c = env.client()
    assert c.error("model_dir_set", {"path": "models", "move": True}).startswith(
        "Папка модели: нужен полный путь")
    assert "Не удалось создать папку" in c.error(
        "model_dir_set", {"path": str(env.tmp / "файл" / "models"), "move": False})
    assert "move" in c.error("model_dir_set", {"path": str(env.tmp / "a"), "move": "да"})
    assert "path" in c.error("model_dir_set", {"move": True})
    assert c.call("get_settings")["model_dir"] == ""
    assert fm.moves == [] and fm.order == []
    c.close()


def test_model_dir_set_move_failure_keeps_settings(env: Env,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    fm = FakeModels(monkeypatch, env)
    fm.move_error = fetch.FetchError("Недостаточно места на диске для модели large-v3-turbo")
    new = new_folder(env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new, "move": True})["moving"] is True
    err = c.wait_event("progress", lambda d: d["done"])
    assert err["error"] == "Недостаточно места на диске для модели large-v3-turbo"
    assert err["what"] == "model" and err["pct"] == 10.0
    assert c.call("get_settings")["model_dir"] == "" and saved_settings(env).get(
        "model_dir", "") == ""
    assert env.rec.loaded and fm.removed == [] and "unload" not in fm.order
    env.dictate("модель работает")
    c.wait_event("history")
    assert env.calls.delivered == [("модель работает ", False)]
    # слот освобождён — можно повторить
    fm.move_error = None
    assert c.call("model_dir_set", {"path": new, "move": True})["moving"] is True
    c.wait_event("notice", lambda d: "перенесена в" in d["text"])
    c.close()


def test_model_dir_set_busy_until_old_copy_removed(env: Env,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Перенос закончен, а старая копия ещё удаляется: новый model_dir_set — «переносится».
    Иначе перенос обратно нашёл бы старую копию целой («уже там»), а потом удалились бы обе."""
    from huggingface_hub import constants
    default = env.tmp / "hf" / "hub"     # перенос обратно — не в настоящий кэш пользователя
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(default))
    fm = FakeModels(monkeypatch, env)
    fm.remove_gate.clear()
    new = new_folder(env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new, "move": True})["moving"] is True
    assert c.wait_event("progress", lambda d: d["done"])["error"] is None
    _wait_for(lambda: fm.removed == [("large-v3-turbo", None)])
    assert "переносится" in c.error("model_dir_set", {"path": "", "move": True})
    assert "переносится" in c.error("model_dir_set", {"path": "", "move": False})
    assert c.call("get_settings")["model_dir"] == new
    # загрузки модели это не держит: слот «model» уже свободен
    assert "model" not in env.eng._downloading
    fm.remove_gate.set()
    c.wait_event("notice", lambda d: "перенесена в" in d["text"])
    _wait_for(lambda: not env.eng._moving)
    # теперь обратно — старой копии уже нет, переносится честно
    assert c.call("model_dir_set", {"path": "", "move": True})["moving"] is True
    n = c.wait_event("notice", lambda d: d["text"] != f"Модель перенесена в {new}")
    assert n["text"] == f"Модель перенесена в {default}"
    assert fm.moves == [("large-v3-turbo", None, new), ("large-v3-turbo", new, None)]
    assert fm.removed == [("large-v3-turbo", None), ("large-v3-turbo", new)]
    assert fm.ready == {None}
    c.close()


def test_model_dir_set_old_copy_not_removed_warns(env: Env,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    fm = FakeModels(monkeypatch, env)
    fm.remove_ok = False
    c = env.client()
    c.mark()
    c.call("model_dir_set", {"path": new_folder(env), "move": True})
    n = c.wait_event("notice", lambda d: d["level"] == "warn")
    assert n["text"].startswith("Старую копию удалить не удалось: ")
    assert n["text"].endswith("models--mobiuslabsgmbh--faster-whisper-large-v3-turbo")
    c.close()


def test_model_dir_set_save_failure_moves_model_back(env: Env,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Перенос прошёл переименованием, а настройки не записались (файл занят) — модель
    возвращается в прежнюю папку, настройка не меняется."""
    fm = FakeModels(monkeypatch, env)
    fm.rename = True

    def locked_save(s: config.Settings) -> None:
        raise PermissionError(13, "Файл занят другим процессом")

    monkeypatch.setattr(config, "save", locked_save)
    new = new_folder(env)
    c = env.client()
    c.mark()
    c.call("model_dir_set", {"path": new, "move": True})
    err = c.wait_event("progress", lambda d: d["done"])
    assert err["error"] and "PermissionError" in err["error"]
    assert fm.moves == [("large-v3-turbo", None, new), ("large-v3-turbo", new, None)]
    assert None in fm.ready and fm.removed == []
    assert c.call("get_settings")["model_dir"] == ""
    c.close()


def test_set_settings_model_dir_switches_folder(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """model_dir через обычную смену настроек — как смена модели: перезагрузка/загрузка."""
    fm = FakeModels(monkeypatch, env)
    new = new_folder(env)
    c = env.client()
    assert c.call("set_settings", {"patch": {"model_dir": new}})["model_dir"] == new
    _wait_for(lambda: fm.downloads == [("large-v3-turbo", new)] and "load" in fm.order)
    assert "Папка модели" in c.error("set_settings", {"patch": {"model_dir": "rel"}})
    c.close()


def test_model_dir_set_refuses_target_inside_model_folder(env: Env,
                                                          monkeypatch: pytest.MonkeyPatch
                                                          ) -> None:
    """Папка внутри папки самой модели или .locks — ошибка сразу: поток переноса не
    запускается, папка не создаётся, настройка прежняя."""
    fm = FakeModels(monkeypatch, env)
    default = fetch.model_cache_dir("")
    folder = fetch.model_folder(MODEL, None)
    c = env.client()
    for target in (folder, folder / "snapshots", default / ".locks"):
        for move in (True, False):
            err = c.error("model_dir_set", {"path": str(target), "move": move})
            assert "внутри служебной папки модели" in err, err
    assert not folder.exists() and not (default / ".locks").exists()
    assert c.call("get_settings")["model_dir"] == "" and fm.moves == [] and fm.order == []
    assert not env.eng._moving and "model" not in env.eng._downloading
    c.close()


def test_model_dir_set_reload_failure_keeps_old_copy(env: Env,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """Копия проверена, а из новой папки модель не загрузилась (флешка отвалилась, файл не
    читается): старая копия — единственная рабочая, её не удалять."""
    fm = FakeModels(monkeypatch, env)
    fm.load_error = RuntimeError("model.bin не читается")
    new = new_folder(env)
    old_folder = fetch.model_folder(MODEL, None)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new, "move": True})["moving"] is True
    n = c.wait_event("notice", lambda d: d["level"] == "warn")
    assert n["text"] == f"Модель не загрузилась из новой папки — старая копия оставлена: {old_folder}"
    assert fm.removed == [] and None in fm.ready
    assert fm.order == ["move", "unload", "load"]
    assert c.call("get_settings")["model_dir"] == new
    _wait_for(lambda: not env.eng._moving)
    c.close()


def test_model_dir_set_new_folder_gone_before_reload_keeps_old_copy(
        env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """После переноса модели в новой папке не стало (вынута флешка): прежняя модель в памяти
    продолжает работать и качается заново — старую копию не удалять."""
    fm = FakeModels(monkeypatch, env)
    fm.vanish = True
    fm.download_gate.clear()
    new = new_folder(env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new, "move": True})["moving"] is True
    n = c.wait_event("notice", lambda d: d["level"] == "warn")
    assert n["text"].startswith("Модель не загрузилась из новой папки — старая копия оставлена")
    assert fm.removed == [] and env.rec.loaded
    fm.download_gate.set()
    _wait_for(lambda: new in fm.ready and not env.eng._swap_pending)
    assert fm.downloads == [(MODEL, new)] and fm.removed == []
    c.close()


@pytest.mark.parametrize("fail", [False, True])
def test_model_change_during_move_is_downloaded_after(env: Env, monkeypatch: pytest.MonkeyPatch,
                                                      fail: bool) -> None:
    """Модель сменили во время переноса: её загрузка ждёт слот «model» и начинается, когда
    перенос его освобождает, — в новую папку после удачного переноса, в прежнюю после
    неудачного. Перезагрузка из новой папки не прошла (распознаёт прежняя модель) — старая
    копия перенесённой модели остаётся."""
    fm = FakeModels(monkeypatch, env)
    fm.gate.clear()
    if fail:
        fm.move_error = fetch.FetchError("Недостаточно места на диске для модели large-v3-turbo")
    new = new_folder(env)
    c = env.client()
    c.mark()
    assert c.call("model_dir_set", {"path": new, "move": True})["moving"] is True
    c.wait_event("progress", lambda d: d["pct"] == 10.0)
    c.call("set_settings", {"patch": {"model": "small"}})
    _wait_for(lambda: env.eng._swap_pending)
    assert fm.downloads == []            # слот «model» занят переносом
    fm.gate.set()
    where = None if fail else new
    _wait_for(lambda: fm.downloads == [("small", where)])
    _wait_for(lambda: not env.eng._swap_pending and where in fm.where("small")
              and env.rec.loaded and env.eng._model_phase == "ready")
    _wait_for(lambda: not env.eng._moving)
    assert c.wait_event("notice", lambda d: "Скачиваю модель small" in d["text"],
                        fresh=False)["toast"]
    assert fm.downloads == [("small", where)] and fm.removed == []
    assert c.call("get_settings")["model_dir"] == ("" if fail else new)
    if not fail:
        c.wait_event("notice", lambda d: "старая копия оставлена" in d["text"], fresh=False)
    c.close()


def real_model_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Настоящий поиск модели (фикстура env подменяет его на «всегда есть»); сеть — нельзя."""
    monkeypatch.setattr(fetch, "model_ready",
                        lambda model, cache_dir=None: fetch.model_path(model, cache_dir) is not None)

    def no_download(*a: Any, **kw: Any) -> str:
        raise AssertionError("модель уже есть — качать нечего")

    monkeypatch.setattr(fetch, "download_model", no_download)


def use_model_folder(env: Env, c: Any, folder: Path) -> None:
    c.call("set_settings", {"patch": {"model": REPO, "model_dir": str(folder)}})
    _wait_for(lambda: env.eng._model_phase == "ready" and env.rec.loaded)


def test_model_dir_set_same_folder_via_junction_is_plain_switch(env: Env,
                                                                monkeypatch: pytest.MonkeyPatch
                                                                ) -> None:
    """Новая папка — та же нынешняя под другим путём (junction): не перенос (он удалил бы
    единственную копию), а смена записи."""
    real_model_ready(monkeypatch)
    real = env.tmp / "real models"
    make_cache(real, links=False)
    alias = env.tmp / "alias"
    junction(real, alias)
    c = env.client()
    use_model_folder(env, c, real)
    assert c.call("model_dir_set", {"path": str(alias), "move": True}) == {"ok": True,
                                                                          "moving": False}
    assert c.call("get_settings")["model_dir"] == str(alias)
    assert not env.eng._moving
    assert fetch.model_path(REPO, real) is not None and fetch.model_path(REPO, alias) is not None
    c.close()


def test_model_dir_set_into_junction_of_model_folder_keeps_only_copy(
        env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """В новой папке models--org--name — junction на папку модели в нынешней: «уже там»,
    а старая копия — это она же: не удаляется, перенос считается удачным."""
    real_model_ready(monkeypatch)
    real, new = env.tmp / "real", env.tmp / "new"
    make_cache(real, links=False)
    junction(real / FOLDER, new / FOLDER)
    c = env.client()
    use_model_folder(env, c, real)
    c.mark()
    assert c.call("model_dir_set", {"path": str(new), "move": True})["moving"] is True
    n = c.wait_event("notice", lambda d: "перенесена в" in d["text"] or d["level"] != "info")
    assert n["text"] == f"Модель перенесена в {new}" and n["level"] == "info"
    _wait_for(lambda: not env.eng._moving)
    assert c.call("get_settings")["model_dir"] == str(new)
    assert snapshot_files(real / FOLDER) == FILES
    assert fetch.model_path(REPO, real) is not None and fetch.model_path(REPO, new) is not None
    c.close()


# ---------------------------- подбор модели ----------------------------

def hw(gpu: str | None, vram: int | None, cuda: int, ram: float, threads: int,
       types: frozenset[str] | None = None) -> recommend.Hardware:
    return recommend.Hardware(gpu, vram, cuda, ram, threads, types)


# Что CTranslate2 умеет на картах (get_supported_compute_types("cuda"))
AMPERE = frozenset({"float32", "int8", "int8_float32", "int8_float16", "float16", "bfloat16",
                    "int8_bfloat16"})
TURING = frozenset({"float32", "int8", "int8_float32", "int8_float16", "float16"})
PASCAL = frozenset({"float32", "int8", "int8_float32"})       # GTX 10xx, GT 1030 (CC 6.1)
MAXWELL = frozenset({"float32"})                              # GTX 9xx, GT 710 (Kepler)


@pytest.mark.parametrize("h,want,reason", [
    (hw("NVIDIA GeForce RTX 3060 Ti", 8192, 1, 31.9, 16), ("large-v3-turbo", "cuda", "float16"),
     "Видеокарта RTX 3060 Ti, 8 ГБ — лучшая модель для русского работает быстро"),
    (hw("NVIDIA GeForce RTX 3060 Ti", 8192, 1, 31.9, 16, AMPERE),
     ("large-v3-turbo", "cuda", "float16"), "RTX 3060 Ti, 8 ГБ"),
    (hw("NVIDIA GeForce GTX 1650", 4096, 1, 16, 8, TURING), ("large-v3-turbo", "cuda", "float16"),
     "GTX 1650, 4 ГБ"),
    (hw("NVIDIA GeForce GTX 1650", 3910, 1, 16, 8), ("large-v3-turbo", "cuda", "float16"),
     "GTX 1650, 3,8 ГБ"),
    (hw("NVIDIA GeForce GTX 1650", 3072, 1, 16, 8, TURING),
     ("large-v3-turbo", "cuda", "int8_float16"), "экономном режиме"),
    (hw("NVIDIA GeForce MX450", 1536, 1, 8, 4, TURING), ("small", "cuda", "int8_float16"),
     "видеопамяти мало"),
    # Pascal: float16 и int8_float16 CTranslate2 на них не берёт (не подменяет, а падает) —
    # int8 на той же карте
    (hw("NVIDIA GeForce GTX 1060 6GB", 6144, 1, 16, 8, PASCAL), ("large-v3-turbo", "cuda", "int8"),
     "Видеокарта GTX 1060 6GB не поддерживает половинную точность (float16) — модель "
     "large-v3-turbo работает на ней в режиме int8"),
    (hw("NVIDIA GeForce GTX 1060 3GB", 3072, 1, 16, 8, PASCAL),
     ("large-v3-turbo", "cuda", "int8"), "режиме int8"),
    (hw("NVIDIA GeForce GT 1030", 2048, 1, 8, 4, PASCAL), ("large-v3-turbo", "cuda", "int8"),
     "GT 1030"),
    (hw("NVIDIA Quadro P400", 1024, 1, 8, 4, PASCAL), ("small", "cuda", "int8"), "Quadro P400"),
    (hw(None, None, 1, 16, 8, PASCAL), ("large-v3-turbo", "cuda", "int8"), "режиме int8"),
    # ни float16, ни int8 (Maxwell, Kepler) — правила для процессора, с честной причиной
    (hw("NVIDIA GeForce GT 710", 1024, 1, 8, 4, MAXWELL), ("base", "cpu", "int8"),
     "Видеокарта GT 710 для распознавания не подходит (слишком старая для CTranslate2), "
     "компьютер скромный (4 потока, 8 ГБ памяти)"),
    (hw("NVIDIA GeForce GTX 970", 4096, 1, 16, 16, MAXWELL), ("small", "cpu", "int8"),
     "GTX 970 для распознавания не подходит"),
    # драйвер (NVML) карту видит, а CUDA — нет (драйвер слишком старый для CUDA 12): на ней
    # модель не запустится — правила для процессора (cuBLAS тут ни при чём)
    (hw("NVIDIA GeForce RTX 4070", 12282, 0, 32, 20), ("small", "cpu", "int8"),
     "Видеокарта RTX 4070 для распознавания не подходит (CUDA её не видит: возможно, устарел "
     "драйвер NVIDIA) — на процессоре (20 потоков, 32 ГБ памяти)"),
    (hw("NVIDIA GeForce GTX 760", 2048, 0, 8, 4), ("base", "cpu", "int8"), "CUDA её не видит"),
    # CUDA видит карту, а NVML — нет: объём неизвестен
    (hw(None, None, 1, 16, 8), ("large-v3-turbo", "cuda", "int8_float16"),
     "Видеокарта NVIDIA, объём видеопамяти не определён"),
    (hw(None, None, 0, 16, 16), ("small", "cpu", "int8"), "16 потоков, 16 ГБ памяти"),
    (hw(None, None, 0, 7.8, 8), ("small", "cpu", "int8"), "8 потоков, 7,8 ГБ памяти"),
    (hw(None, None, 0, 8, 12), ("small", "cpu", "int8"), "12 потоков, 8 ГБ памяти"),
    (hw(None, None, 0, 0, 8), ("small", "cpu", "int8"), "объём памяти не определён"),
    (hw(None, None, 0, 16, 4), ("base", "cpu", "int8"), "4 потока"),
    (hw(None, None, 0, 4, 12), ("base", "cpu", "int8"), "компьютер скромный"),
    (hw(None, None, 0, 6, 1), ("base", "cpu", "int8"), "1 поток, 6 ГБ памяти"),
])
def test_recommend_rules(h: recommend.Hardware, want: tuple[str, str, str], reason: str) -> None:
    c = recommend.choose(h)
    assert (c.model, c.device, c.compute_type) == want
    assert reason in c.reason


def test_recommend_reason_in_english() -> None:
    i18n.set_language("en")
    c = recommend.choose(hw("NVIDIA GeForce RTX 3060 Ti", 8192, 1, 32, 16))
    assert c.reason == ("RTX 3060 Ti graphics card with 8 GB — the best model for Russian and "
                        "English runs fast")
    assert "16 threads, 4 GB of RAM" in recommend.choose(hw(None, None, 0, 4, 16)).reason
    assert "1 thread," in recommend.choose(hw(None, None, 0, 4, 1)).reason
    assert recommend.choose(hw("NVIDIA GeForce GTX 1060 6GB", 6144, 1, 16, 8, PASCAL)).reason == (
        "GTX 1060 6GB graphics card does not support half precision (float16) — the "
        "large-v3-turbo model runs on it in int8 mode")
    assert recommend.choose(hw("NVIDIA GeForce RTX 4070", 12282, 0, 32, 20)).reason.startswith(
        "The RTX 4070 graphics card cannot be used for recognition (CUDA does not see it")


def test_ram_gb_prefers_installed_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Память — установленная: у 8-гигабайтного ноутбука со встроенной графикой Windows видит
    ≈7,35 ГБ, а это всё-таки «8 ГБ» (small, а не base)."""
    usable = int(7.35 * 2**30)
    monkeypatch.setattr(recommend, "_installed_ram_kb", lambda: 8 * 1048576)
    monkeypatch.setattr(recommend, "_usable_ram_bytes", lambda: usable)
    assert recommend.ram_gb() == 8.0
    c = recommend.choose(hw(None, None, 0, recommend.ram_gb(), 12))
    assert (c.model, c.device) == ("small", "cpu") and "8 ГБ памяти" in c.reason
    # установленную не узнать (виртуальная машина) — та, что видит Windows
    monkeypatch.setattr(recommend, "_installed_ram_kb", lambda: None)
    assert recommend.ram_gb() == 7.3 or recommend.ram_gb() == 7.4
    monkeypatch.setattr(recommend, "_usable_ram_bytes", lambda: None)
    assert recommend.ram_gb() == 0.0


def test_ram_readers_on_this_windows() -> None:
    installed, usable = recommend._installed_ram_kb(), recommend._usable_ram_bytes()
    assert usable is not None and usable > 2**29
    if installed is not None:                  # в виртуальной машине бывает None
        assert installed * 1024 >= usable * 0.9


def test_cuda_compute_types() -> None:
    types = asr.cuda_compute_types()
    if asr.cuda_device_count() < 1:
        assert types is None
    else:
        assert types is not None and "float32" in types


def test_model_recommend_uses_card_compute_types(env: Env,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "gpu_info", lambda: ("NVIDIA GeForce GTX 1060 6GB", 6144))
    monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)
    monkeypatch.setattr(engine, "cuda_compute_types", lambda: PASCAL)
    monkeypatch.setattr(fetch, "model_sizes", lambda repos, budget_s=4.0: {})
    c = env.client()
    assert c.call("model_recommend")["recommended"] == {"model": "large-v3-turbo",
                                                        "device": "cuda", "compute_type": "int8"}
    c.close()


def test_progress_sizes_match_model_list() -> None:
    """Размер модели в списке мастера (size_mb, МБ по 10⁶ байт) и в прогрессе загрузки или
    переноса — одно и то же число."""
    for exact in (75_538_270, 486_212_372, 1_621_806_436, 3_087_284_237):
        assert fetch._mb(exact) == i18n.fmt_num(round(exact / 1_000_000))
    assert fetch._mb(486_212_372) == "486"
    assert fetch._gb(1_621_806_436) == "1,6"
    i18n.set_language("en")
    assert fetch._mb(1_546_000_000) == "1,546"


@pytest.fixture
def no_size_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "_SIZES", {})
    monkeypatch.setattr(fetch, "_SIZES_FAILED", {})
    monkeypatch.setattr(fetch, "_SIZE_THREADS", {})


def test_recommend_options_sizes_from_hub_and_fallback(monkeypatch: pytest.MonkeyPatch,
                                                       no_size_cache: None) -> None:
    exact = {"Systran/faster-whisper-small": 483_546_902,
             "mobiuslabsgmbh/faster-whisper-large-v3-turbo": 1_621_806_436}
    asked: list[tuple[str, float]] = []

    def fake_size(repo: str, timeout: float = 10) -> int:
        asked.append((repo, timeout))
        return exact.get(repo, 0)

    monkeypatch.setattr(fetch, "_expected_model_size", fake_size)
    r = recommend.recommend(hw("NVIDIA GeForce RTX 3060 Ti", 8192, 1, 31.94, 16), budget_s=2)
    assert {k: r[k] for k in ("gpu_name", "vram_mb", "cuda_ok", "ram_gb", "cpu_threads")} == {
        "gpu_name": "NVIDIA GeForce RTX 3060 Ti", "vram_mb": 8192, "cuda_ok": True,
        "ram_gb": 31.9, "cpu_threads": 16}
    assert r["recommended"] == {"model": "large-v3-turbo", "device": "cuda",
                                "compute_type": "float16"}
    opts = {o["model"]: o for o in r["options"]}
    assert list(opts) == ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
    assert opts["small"]["size_mb"] == 484 and opts["large-v3-turbo"]["size_mb"] == 1622
    assert opts["tiny"]["size_mb"] == 75 and opts["medium"]["size_mb"] == 1530   # запасные
    assert opts["large-v3"]["size_mb"] == 3090 and opts["base"]["size_mb"] == 145
    assert [o["model"] for o in r["options"] if o["recommended"]] == ["large-v3-turbo"]
    for o in r["options"]:
        assert o["repo"] == fetch.repo_id(o["model"]) and "distil" not in o["repo"]
        assert 1 <= o["quality"] <= 5 and 1 <= o["speed"] <= 5
        assert isinstance(o["note"], str) and o["note"]
    assert sorted(a for a, _t in asked) == sorted(fetch.repo_id(m) for m in recommend.MODELS)
    # удачные размеры запомнены на процесс, неудачные не переспрашиваются сразу же
    asked.clear()
    recommend.options("small", budget_s=2)
    assert asked == []


def test_recommend_does_not_wait_for_slow_hub(monkeypatch: pytest.MonkeyPatch,
                                              no_size_cache: None) -> None:
    release = threading.Event()
    calls: list[str] = []

    def slow(repo: str, timeout: float = 10) -> int:
        calls.append(repo)
        release.wait(10)
        return 1_000_000

    monkeypatch.setattr(fetch, "_expected_model_size", slow)
    try:
        t0 = time.monotonic()
        opts = recommend.options("small", budget_s=0.2)
        assert time.monotonic() - t0 < 2
        assert [o["size_mb"] for o in opts] == [recommend.FALLBACK_MB[m] for m in recommend.MODELS]
        recommend.options("small", budget_s=0.1)   # запросы ещё идут — новых не начинаем
        assert len(calls) == len(recommend.MODELS)
    finally:
        release.set()
        for t in list(fetch._SIZE_THREADS.values()):   # дописать в кэш этого теста, не в общий
            t.join(5)


def test_recommend_catalog_texts() -> None:
    for lang in i18n.UI_LANGS:
        cat = i18n.catalog(lang)
        for key in recommend.NOTE_KEYS.values():
            assert cat.get(key), (lang, key)
    assert [i18n.tp("rec.threads", n) for n in (1, 2, 5, 21)] == [
        "1 поток", "2 потока", "5 потоков", "21 поток"]
    assert [i18n.tp_in("en", "rec.threads", n) for n in (1, 8)] == ["1 thread", "8 threads"]


def test_ram_gb_reads_windows() -> None:
    assert recommend.ram_gb() > 0.5


def test_model_recommend_ws(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "gpu_info", lambda: ("NVIDIA GeForce RTX 3060 Ti", 8192))
    monkeypatch.setattr(engine, "cuda_device_count", lambda: 1)
    monkeypatch.setattr(engine, "cuda_compute_types", lambda: None)
    monkeypatch.setattr(recommend, "ram_gb", lambda: 31.9)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    monkeypatch.setattr(fetch, "model_sizes", lambda repos, budget_s=4.0: {})
    c = env.client()
    r = c.call("model_recommend")
    assert set(r) == {"gpu_name", "vram_mb", "cuda_ok", "ram_gb", "cpu_threads", "recommended",
                      "reason", "options"}
    assert r["recommended"] == {"model": "large-v3-turbo", "device": "cuda",
                                "compute_type": "float16"}
    assert r["reason"] == "Видеокарта RTX 3060 Ti, 8 ГБ — лучшая модель для русского работает быстро"
    assert r["cpu_threads"] == 16 and r["ram_gb"] == 31.9 and r["cuda_ok"] is True
    assert len(r["options"]) == 6
    assert set(r["options"][0]) == {"model", "repo", "size_mb", "quality", "speed",
                                    "recommended", "note"}
    c.call("set_settings", {"patch": {"language": "en"}})
    assert c.call("model_recommend")["reason"].startswith("RTX 3060 Ti graphics card with 8 GB")
    c.close()


def test_long_commands_include_recommend_and_model_dir_set() -> None:
    """model_recommend ждёт сеть и NVML, model_dir_set — диск (недоступный сетевой путь —
    десятки секунд): очередь команд соединения они не держат."""
    from rupor import server
    assert {"model_recommend", "model_dir_set"} <= server.LONG_COMMANDS
