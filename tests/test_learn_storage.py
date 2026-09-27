"""Storage: обучение словаря — dict_learn_add и одноразовая отмена dict_learn_undo по журналу
(kv «learn_journal»). Регрессии: «Отменить» не должно удалять то, что добавлено позже
(другой выученный вариант, ручные правки), и не должно срабатывать второй раз."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from rupor.storage import Storage


@pytest.fixture
def st(tmp_path: Path) -> Iterator[Storage]:
    s = Storage(tmp_path / "rupor.db")
    yield s
    s.close()


def terms(st: Storage) -> list[tuple[str, list[str]]]:
    return [(d["term"], d["variants"]) for d in st.dict_list()]


def test_undo_created_term(st: Storage) -> None:
    item, created = st.dict_learn_add("Metabase", "метабейс")
    assert created
    assert st.dict_learn_undo("Metabase", "метабейс", item["id"], True) is True
    assert st.dict_list() == []


def test_undo_first_of_two_learned_variants_keeps_second(st: Storage) -> None:
    """Находки 10 и 13: вторая правка того же термина (её уведомление ещё висит) не пропадает
    вместе с первой; отмена второй затем убирает термин целиком."""
    a, ca = st.dict_learn_add("Metabase", "метабейс")
    b, cb = st.dict_learn_add("Metabase", "мета бейз")
    assert (ca, cb) == (True, False) and a["id"] == b["id"]
    st.dict_learn_undo("Metabase", "метабейс", a["id"], True)
    assert terms(st) == [("Metabase", ["мета бейз"])]
    st.dict_learn_undo("Metabase", "мета бейз", b["id"], False)
    assert st.dict_list() == []


def test_undo_created_keeps_manual_variants(st: Storage) -> None:
    """Находка 10: пока уведомление висит, пользователь дописал вариант на странице «Словарь»."""
    item, _ = st.dict_learn_add("Metabase", "метабейс")
    st.dict_upsert(item["id"], "Metabase", ["метабейс", "метабас"])
    st.dict_learn_undo("Metabase", "метабейс", item["id"], True)
    assert terms(st) == [("Metabase", ["метабас"])]


def test_undo_created_term_only_keeps_manual_variant(st: Storage) -> None:
    item, _ = st.dict_learn_add("ClickHouse", "")
    st.dict_upsert(item["id"], "ClickHouse", ["клик хаус"])
    assert st.dict_learn_undo("ClickHouse", "", item["id"], True) is False
    assert terms(st) == [("ClickHouse", ["клик хаус"])]


def test_undo_created_keeps_renamed_term(st: Storage) -> None:
    item, _ = st.dict_learn_add("Metabase", "метабейс")
    st.dict_upsert(item["id"], "MetaBase", ["метабейс"])       # пользователь поправил написание
    st.dict_learn_undo("Metabase", "метабейс", item["id"], True)
    assert terms(st) == [("MetaBase", [])]


def test_undo_is_one_shot_and_id_reuse_is_safe(st: Storage) -> None:
    """Находка 12: отменили, пользователь сам завёл тот же термин (SQLite отдал тот же id),
    повторная «Отменить» (второе окно, перезагрузка) ничего не трогает."""
    item, _ = st.dict_learn_add("Metabase", "метабейс")
    st.dict_learn_undo("Metabase", "метабейс", item["id"], True)
    manual = st.dict_upsert(None, "Metabase", ["мета бейз"])
    assert manual["id"] == item["id"]                          # id переиспользован
    assert st.dict_learn_undo("Metabase", "метабейс", item["id"], True) is False
    assert terms(st) == [("Metabase", ["мета бейз"])]
    # created=false: вариант, который пользователь вернул вручную, тоже не снимается
    st.dict_learn_add("Metabase", "метабейс")
    st.dict_learn_undo("Metabase", "метабейс", item["id"], False)
    st.dict_upsert(item["id"], "Metabase", ["мета бейз", "метабейс"])
    assert st.dict_learn_undo("Metabase", "метабейс", item["id"], False) is False
    assert terms(st) == [("Metabase", ["мета бейз", "метабейс"])]


def test_undo_after_manual_delete_and_recreate(st: Storage) -> None:
    item, _ = st.dict_learn_add("Metabase", "метабейс")
    st.dict_delete(item["id"])                                  # журнал этой записи забыт
    again = st.dict_upsert(None, "Metabase", ["метабейс"])
    assert again["id"] == item["id"]
    assert st.dict_learn_undo("Metabase", "метабейс", item["id"], True) is False
    assert terms(st) == [("Metabase", ["метабейс"])]


def test_add_without_change_is_not_undoable(st: Storage) -> None:
    """Вариант уже был (добавлен вручную) — правка ничего не меняла, отменять нечего."""
    st.dict_upsert(None, "Metabase", ["метабейс"])
    item, created = st.dict_learn_add("metabase", "Метабейс")
    assert created is False and item["variants"] == ["метабейс"]
    assert st.dict_learn_undo("metabase", "Метабейс", item["id"], False) is False
    assert terms(st) == [("Metabase", ["метабейс"])]


def test_undo_variant_added_to_manual_term(st: Storage) -> None:
    base = st.dict_upsert(None, "Metabase", ["мета бейс"])
    item, created = st.dict_learn_add("Metabase", "метабейс")
    assert not created and item["id"] == base["id"]
    assert st.dict_learn_undo("metabase", "МЕТАБЕЙС", None, False) is True
    assert terms(st) == [("Metabase", ["мета бейс"])]


def test_import_replace_forgets_journal(st: Storage) -> None:
    item, _ = st.dict_learn_add("Metabase", "метабейс")
    st.import_data({"version": 1, "dictionary": [{"term": "Metabase",
                                                  "variants": ["метабейс"]}],
                    "snippets": []}, replace=True)
    assert st.dict_learn_undo("Metabase", "метабейс", item["id"], True) is False
    assert terms(st) == [("Metabase", ["метабейс"])]


def test_journal_is_bounded_and_survives_garbage(st: Storage) -> None:
    st.kv_set("learn_journal", "{битый json")
    item, _ = st.dict_learn_add("Grafana", "графана")
    assert st.dict_learn_undo("Grafana", "графана", item["id"], True) is True
    for i in range(320):
        st.dict_learn_add(f"Term{i}", f"вариант{i}")
    assert len(json.loads(st.kv_get("learn_journal"))) == 300
