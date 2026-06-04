from __future__ import annotations

from geonorge.models import AreaOption

from app.main_window import _merge_area_selection_with_visible_checks


def _area(code: str) -> AreaOption:
    return AreaOption(type="fylke", code=code, name=f"Name {code}")


def test_merge_preserves_hidden_selections() -> None:
    hidden = _area("hidden-1")
    visible = _area("visible-1")
    merged = _merge_area_selection_with_visible_checks(
        [hidden, visible],
        visible_codes={"visible-1", "visible-2"},
        visible_checked=[_area("visible-2")],
    )
    assert [a.code for a in merged] == ["hidden-1", "visible-2"]


def test_merge_replaces_visible_selection_state() -> None:
    merged = _merge_area_selection_with_visible_checks(
        [_area("a"), _area("b")],
        visible_codes={"a", "b"},
        visible_checked=[_area("a")],
    )
    assert [a.code for a in merged] == ["a"]
