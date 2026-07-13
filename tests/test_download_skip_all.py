from __future__ import annotations

from app.main_window import MainWindow


def test_download_error_key_strips_whitespace() -> None:
    assert MainWindow._download_error_key(RuntimeError("  boom  ")) == "boom"


def test_dataset_wide_download_error_detects_restricted_role() -> None:
    error = (
        'Failed to place order (500): "Order contains restricted datasets, '
        'but user does not have required role for 41c4c637-cc05-4e07-bdfe-c630abbc6635"'
    )
    assert MainWindow._is_dataset_wide_download_error(error) is True


def test_dataset_wide_download_error_ignores_area_specific_failures() -> None:
    assert MainWindow._is_dataset_wide_download_error("Area too large for clipping.") is False
