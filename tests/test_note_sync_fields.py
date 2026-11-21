"""The sync fields in ``notes.json`` (sync spec §3.2).

Two properties matter and pull in opposite directions:

* a deck that never enabled sync must keep writing exactly the v1 file, so
  nobody's ``notes.json`` changes because a feature they do not use exists;
* once sync is on, the file carries ``position``, ``server_updated_at`` and
  ``synced``, and ``position`` is what defines deck order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lurkn.notes import Note
from lurkn.store import Store


def test_an_offline_note_writes_only_the_v1_keys() -> None:
    note = Note.create("Groceries", now=10.0)

    assert note.to_dict() == {
        "id": note.id,
        "text": "Groceries",
        "created": 10.0,
        "updated": 10.0,
    }


def test_sync_fields_round_trip_through_the_file(tmp_path: Path) -> None:
    store = Store(tmp_path / "notes.json")
    note = Note.create("Groceries", now=10.0)
    note.position = 3
    note.server_updated_at = "2026-11-21T09:15:01.002331Z"
    note.synced = False

    store.save([note])
    loaded = store.load().notes[0]

    assert loaded.position == 3
    assert loaded.server_updated_at == "2026-11-21T09:15:01.002331Z"
    assert loaded.synced is False


def test_a_v1_file_without_position_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "notes": [
                    {"id": "a", "text": "first", "created": 1.0, "updated": 1.0},
                    {"id": "b", "text": "second", "created": 2.0, "updated": 2.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    notes = Store(path).load().notes

    # Absent position means "the array index is the order", per the spec.
    assert [note.position for note in notes] == [None, None]
    assert [note.synced for note in notes] == [True, True]


def test_a_bad_position_is_rejected_rather_than_silently_coerced() -> None:
    with pytest.raises(ValueError):
        Note.from_dict(
            {"id": "a", "text": "x", "created": 1.0, "updated": 1.0, "position": "1"}
        )


def test_a_non_boolean_synced_flag_is_rejected() -> None:
    with pytest.raises(ValueError):
        Note.from_dict(
            {"id": "a", "text": "x", "created": 1.0, "updated": 1.0, "synced": 1}
        )


def test_saving_an_offline_deck_does_not_add_sort_keys(tmp_path: Path) -> None:
    # The whole point: enabling sync must be the reason the format changes.
    store = Store(tmp_path / "notes.json")
    store.save([Note.create("Groceries", now=10.0)])

    document = json.loads((tmp_path / "notes.json").read_text(encoding="utf-8"))

    assert set(document["notes"][0]) == {"id", "text", "created", "updated"}
