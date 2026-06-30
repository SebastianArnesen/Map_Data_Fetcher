from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from app.dialogs import apply_destructive_button, build_message_box_stylesheet


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_apply_destructive_button_sets_object_name(qapp) -> None:
    button = QPushButton("Quit")
    apply_destructive_button(button)
    assert button.objectName() == "messageBoxDestructiveButton"


def test_build_message_box_stylesheet_includes_destructive_block() -> None:
    stylesheet = build_message_box_stylesheet(light_mode=True)
    assert "messageBoxDestructiveButton" in stylesheet

    dark_stylesheet = build_message_box_stylesheet(light_mode=False)
    assert "messageBoxDestructiveButton" in dark_stylesheet
