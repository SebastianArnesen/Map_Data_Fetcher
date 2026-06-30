from __future__ import annotations

from unittest.mock import MagicMock

from geonorge.models import OrderFile
from geonorge.nedlasting import NedlastingClient, all_packaging_complete, parse_order_files


def test_parse_order_files_reads_multi_file_response() -> None:
    raw = [
        {
            "fileId": "f1",
            "area": "T32VLN",
            "downloadUrl": "https://example/a.zip",
            "status": "ReadyForDownload",
            "name": "cell_a.zip",
            "format": "GeoTIFF",
            "projection": "25833",
        },
        {
            "fileId": "f2",
            "area": "T32VMQ",
            "status": "WaitingForProcessing",
            "name": "cell_b.zip",
        },
    ]
    files = parse_order_files(raw)
    assert len(files) == 2
    assert files[0].area_code == "T32VLN"
    assert files[0].is_downloadable
    assert not files[1].is_downloadable


def test_all_packaging_complete_when_all_areas_ready() -> None:
    files = [
        OrderFile("f1", "A", "https://x/a", "ReadyForDownload", "a.zip", None, None),
        OrderFile("f2", "B", "https://x/b", "ReadyForDownload", "b.zip", None, None),
    ]
    assert all_packaging_complete(files, expected_area_codes={"A", "B"})


def test_all_packaging_complete_false_while_waiting() -> None:
    files = [
        OrderFile("f1", "A", "https://x/a", "ReadyForDownload", "a.zip", None, None),
        OrderFile("f2", "B", None, "WaitingForProcessing", "b.zip", None, None),
    ]
    assert not all_packaging_complete(files, expected_area_codes={"A", "B"})


def test_place_batch_order_builds_multiple_order_lines() -> None:
    http = MagicMock()
    http.post_json.return_value = MagicMock(
        status_code=201,
        json={"referenceNumber": "order-1"},
        text="",
    )
    ned = NedlastingClient(http)
    ned._resolve_order_area_type = MagicMock(return_value="celle")  # type: ignore[method-assign]

    refs = ned.place_batch_order(
        metadata_uuid="uuid-1",
        areas=[("celle", "A", None), ("celle", "B", None)],
        format_name="GeoTIFF",
        projection_code="25833",
    )

    assert refs == ["order-1"]
    payload = http.post_json.call_args[0][1]
    assert len(payload["orderLines"]) == 2
    assert payload["orderLines"][0]["areas"][0]["code"] == "A"
    assert payload["orderLines"][1]["areas"][0]["code"] == "B"


def test_place_batch_order_chunks_on_failure() -> None:
    http = MagicMock()
    responses = [
        MagicMock(status_code=400, json=None, text="too large"),
        MagicMock(status_code=201, json={"referenceNumber": "order-a"}, text=""),
        MagicMock(status_code=201, json={"referenceNumber": "order-b"}, text=""),
    ]
    http.post_json.side_effect = responses
    ned = NedlastingClient(http)
    ned._resolve_order_area_type = MagicMock(return_value="celle")  # type: ignore[method-assign]

    refs = ned.place_batch_order(
        metadata_uuid="uuid-1",
        areas=[("celle", "A", None), ("celle", "B", None)],
        format_name="GeoTIFF",
        projection_code="25833",
    )

    assert refs == ["order-a", "order-b"]
    assert http.post_json.call_count == 3
