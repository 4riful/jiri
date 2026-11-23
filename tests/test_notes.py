from __future__ import annotations

import pytest

from jiri import notes


def test_add_and_list_notes(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    note = notes.add_note("Shared", "Remember the tiny robot.", tags="desk,robot", db_path=db_path)
    assert note.id == 1
    assert note.title == "Shared"
    listed = notes.list_notes(db_path=db_path)
    assert len(listed) == 1
    assert listed[0].body == "Remember the tiny robot."


def test_note_title_and_body_required(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    with pytest.raises(ValueError, match="title"):
        notes.add_note(" ", "Body", db_path=db_path)
    with pytest.raises(ValueError, match="body"):
        notes.add_note("Title", " ", db_path=db_path)
