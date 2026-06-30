from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from geonorge.batch_download import (
    BatchDownloadPartialFailure,
    DownloadCancelled,
    DownloadJobSpec,
    DownloadTask,
    run_batch_order_download,
)
from geonorge.client import NetworkError
from geonorge.models import AreaOption, OrderFile


@pytest.fixture
def job_spec(tmp_path: Path) -> DownloadJobSpec:
    return DownloadJobSpec(
        metadata_uuid="60ecee84-bd74-430c-92dc-a1a01a05df9e",
        area_type="celle",
        format_name="GeoTIFF",
        projection_code="25833",
        base_url="https://nedlasting.geonorge.no/api",
        output_dir=tmp_path,
        safe_title="Sentinel2",
        projection_part="25833",
    )


def test_run_batch_order_download_single_post_multiple_files(job_spec: DownloadJobSpec) -> None:
    areas = [
        AreaOption(type="celle", code="A", name="Cell A"),
        AreaOption(type="celle", code="B", name="Cell B"),
    ]
    tasks = [DownloadTask(index=i, area=a) for i, a in enumerate(areas)]

    poll_state = {"calls": 0}

    def poll_files(ref: str, *, base_url=None):
        poll_state["calls"] += 1
        if poll_state["calls"] == 1:
            return [
                OrderFile("f1", "A", "https://example/a.zip", "ReadyForDownload", "a.zip", None, None),
                OrderFile("f2", "B", None, "WaitingForProcessing", "b.zip", None, None),
            ]
        return [
            OrderFile("f1", "A", "https://example/a.zip", "ReadyForDownload", "a.zip", None, None),
            OrderFile("f2", "B", "https://example/b.zip", "ReadyForDownload", "b.zip", None, None),
        ]

    ned = MagicMock()
    ned.validate_area_format_projection.return_value = (True, None)
    ned.place_batch_order.return_value = ["order-1"]
    ned.poll_order_files.side_effect = poll_files

    http = MagicMock()
    http.content_length.return_value = 100
    http.download.side_effect = (
        lambda url, target, progress=None, cancel=None: progress(100, 100) if progress else None
    )

    reporter = MagicMock()
    slot_acquired = []
    slot_released = []

    results = run_batch_order_download(
        tasks,
        job_spec,
        ned=ned,
        http=http,
        reporter=reporter,
        acquire_packaging_slot=lambda: slot_acquired.append(1),
        release_packaging_slot=lambda: slot_released.append(1),
        poll_interval_s=0.01,
    )

    assert len(results) == 2
    ned.place_batch_order.assert_called_once()
    assert slot_acquired and slot_released
    assert http.download.call_count == 2


def test_cancel_event_stops_before_order(job_spec: DownloadJobSpec) -> None:
    areas = [AreaOption(type="celle", code="A", name="Cell A")]
    tasks = [DownloadTask(index=0, area=areas[0])]
    cancel = threading.Event()
    cancel.set()

    ned = MagicMock()
    ned.validate_area_format_projection.return_value = (True, None)
    http = MagicMock()
    reporter = MagicMock()
    slot_released: list[int] = []

    with pytest.raises(DownloadCancelled):
        run_batch_order_download(
            tasks,
            job_spec,
            ned=ned,
            http=http,
            reporter=reporter,
            release_packaging_slot=lambda: slot_released.append(1),
            cancel=cancel,
            poll_interval_s=0.01,
        )

    ned.place_batch_order.assert_not_called()
    assert slot_released == []


def test_cancel_event_releases_packaging_slot(job_spec: DownloadJobSpec) -> None:
    areas = [AreaOption(type="celle", code="A", name="Cell A")]
    tasks = [DownloadTask(index=0, area=areas[0])]
    cancel = threading.Event()

    ned = MagicMock()
    ned.validate_area_format_projection.return_value = (True, None)

    def place_and_cancel(*args, **kwargs):
        cancel.set()
        return ["order-1"]

    ned.place_batch_order.side_effect = place_and_cancel
    http = MagicMock()
    reporter = MagicMock()
    slot_acquired: list[int] = []
    slot_released: list[int] = []

    with pytest.raises(DownloadCancelled):
        run_batch_order_download(
            tasks,
            job_spec,
            ned=ned,
            http=http,
            reporter=reporter,
            acquire_packaging_slot=lambda: slot_acquired.append(1),
            release_packaging_slot=lambda: slot_released.append(1),
            cancel=cancel,
            poll_interval_s=0.01,
        )

    assert slot_acquired == [1]
    assert slot_released == [1]


def test_network_failure_continues_batch(job_spec: DownloadJobSpec) -> None:
    areas = [
        AreaOption(type="celle", code="A", name="Cell A"),
        AreaOption(type="celle", code="B", name="Cell B"),
    ]
    tasks = [DownloadTask(index=i, area=a) for i, a in enumerate(areas)]

    ned = MagicMock()
    ned.validate_area_format_projection.return_value = (True, None)
    ned.place_batch_order.return_value = ["order-1"]
    ned.poll_order_files.return_value = [
        OrderFile("f1", "A", "https://example/a.zip", "ReadyForDownload", "a.zip", None, None),
        OrderFile("f2", "B", "https://example/b.zip", "ReadyForDownload", "b.zip", None, None),
    ]

    def download_side_effect(url, target, progress=None, cancel=None):
        if "a.zip" in url:
            raise NetworkError("connection lost")
        if progress:
            progress(100, 100)

    http = MagicMock()
    http.content_length.return_value = 100
    http.download.side_effect = download_side_effect

    reporter = MagicMock()
    failed_items: list[tuple[int, str, str]] = []

    with pytest.raises(BatchDownloadPartialFailure) as exc_info:
        run_batch_order_download(
            tasks,
            job_spec,
            ned=ned,
            http=http,
            reporter=reporter,
            on_item_failed=lambda index, label, reason: failed_items.append((index, label, reason)),
            poll_interval_s=0.01,
        )

    exc = exc_info.value
    assert len(exc.successes) == 1
    assert exc.successes[0][0] == "B — Cell B"
    assert len(exc.failures) == 1
    assert exc.failures[0][0] == "A — Cell A"
    assert failed_items == [(0, "A — Cell A", "connection lost")]
    assert http.download.call_count == 2
