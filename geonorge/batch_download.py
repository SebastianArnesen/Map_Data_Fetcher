"""Batch Geonorge order downloads with incremental file readiness."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from geonorge.client import DownloadCancelledError, HttpClient, NetworkError
from geonorge.compatibility import area_supports
from geonorge.constants import MAX_PARALLEL_DOWNLOADS, ORDER_POLL_INTERVAL_S
from geonorge.models import AreaOption, AreaType, OrderFile
from geonorge.nedlasting import NedlastingClient, all_packaging_complete

ItemCompletedCallback = Callable[[int], None]
ItemFailedCallback = Callable[[int, str, str], None]
SlotAcquireCallback = Callable[[], None]
SlotReleaseCallback = Callable[[], None]


class DownloadCancelled(Exception):
    """Raised when the user cancels a batch download job."""


class BatchDownloadPartialFailure(Exception):
    """Some files downloaded; others failed due to connection loss."""

    def __init__(
        self,
        successes: list[tuple[str, str]],
        failures: list[tuple[str, str]],
    ) -> None:
        self.successes = successes
        self.failures = failures
        failed = len(failures)
        super().__init__(f"{failed} file{'s' if failed != 1 else ''} failed due to connection loss.")


@dataclass(frozen=True)
class DownloadJobSpec:
    metadata_uuid: str
    area_type: AreaType | None
    format_name: str
    projection_code: str | None
    base_url: str | None
    output_dir: Path
    safe_title: str
    projection_part: str


@dataclass(frozen=True)
class DownloadTask:
    index: int
    area: AreaOption | None

    @property
    def area_label(self) -> str:
        return self.area.label if self.area else "Dataset"

    @property
    def area_code(self) -> str | None:
        return self.area.code if self.area else None


@dataclass(frozen=True)
class _DownloadResult:
    index: int
    area_label: str
    path: str


class DownloadProgressReporter(Protocol):
    def preparing(self, message: str) -> None: ...

    def packaging(self, ready: int, total: int) -> None: ...

    def downloading(self, index: int, label: str, size: int | None) -> None: ...

    def transfer(
        self,
        index: int,
        label: str,
        downloaded: int,
        total: int | None,
        *,
        force: bool = False,
    ) -> None: ...


def _absorb_in_flight_futures(in_flight: dict[int, Future[_DownloadResult]]) -> None:
    """Wait for parallel downloads to wind down without surfacing cancel tracebacks."""
    for future in list(in_flight.values()):
        try:
            future.result(timeout=60)
        except (DownloadCancelled, DownloadCancelledError):
            pass
        except Exception:
            pass
    in_flight.clear()


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise DownloadCancelled("Download cancelled.")


def build_target_path(spec: DownloadJobSpec, area: AreaOption | None, area_type: AreaType | None) -> Path:
    area_part = f"{area_type}_{area.code}" if area_type and area and area.code else "full"
    name = f"{spec.safe_title}_{area_part}_{spec.format_name}_{spec.projection_part}.zip"
    return spec.output_dir / name


def _validate_tasks(tasks: list[DownloadTask], spec: DownloadJobSpec, *, ned: NedlastingClient) -> None:
    for task in tasks:
        area = task.area
        area_label = task.area_label
        if area and not area_supports(
            area,
            projection_code=spec.projection_code,
            format_name=spec.format_name,
        ):
            raise RuntimeError(f"{area_label}: Not available with the selected projection and format.")
        ok, reason = ned.validate_area_format_projection(
            metadata_uuid=spec.metadata_uuid,
            area_type=spec.area_type,
            area_code=task.area_code,
            format_name=spec.format_name,
            projection_code=spec.projection_code,
            base_url=spec.base_url,
            area_option=area,
        )
        if not ok:
            raise RuntimeError(f"{area_label}: {reason or 'Not available.'}")


def _collect_order_files(ned: NedlastingClient, refs: list[str], *, base_url: str | None) -> list[OrderFile]:
    files: list[OrderFile] = []
    for ref in refs:
        files.extend(ned.poll_order_files(ref, base_url=base_url))
    return files


def _match_file_to_task(files: list[OrderFile], task: DownloadTask) -> OrderFile | None:
    code = task.area_code
    if code is None:
        for order_file in files:
            if order_file.is_downloadable:
                return order_file
        return None
    for order_file in files:
        if order_file.area_code == code and order_file.is_downloadable:
            return order_file
    for order_file in files:
        if order_file.name and code in order_file.name and order_file.is_downloadable:
            return order_file
    return None


class ThrottledTransferProgress:
    def __init__(self, reporter: DownloadProgressReporter, *, interval_s: float = 0.5) -> None:
        self._reporter = reporter
        self._interval_s = interval_s
        self._last_emit: dict[int, float] = {}

    def __call__(
        self,
        index: int,
        label: str,
        downloaded: int,
        total: int | None,
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        complete = bool(total) and downloaded >= total
        last = self._last_emit.get(index, 0.0)
        if not force and not complete and now - last < self._interval_s:
            return
        self._last_emit[index] = now
        self._reporter.transfer(index, label, downloaded, total, force=force)


def _download_task_file(
    task: DownloadTask,
    order_file: OrderFile,
    spec: DownloadJobSpec,
    *,
    http: HttpClient,
    reporter: DownloadProgressReporter,
    transfer_progress: ThrottledTransferProgress,
    cancel: threading.Event | None = None,
    acquire_transfer_slot: SlotAcquireCallback | None = None,
    release_transfer_slot: SlotReleaseCallback | None = None,
) -> _DownloadResult:
    if not order_file.download_url:
        raise RuntimeError(f"{task.area_label}: Missing download URL.")
    target = build_target_path(spec, task.area, spec.area_type)
    if acquire_transfer_slot is not None:
        acquire_transfer_slot()
    try:
        size = http.content_length(order_file.download_url)
        reporter.downloading(task.index, task.area_label, size)

        def on_chunk(downloaded: int, total: int | None) -> None:
            _check_cancel(cancel)
            transfer_progress(task.index, task.area_label, downloaded, total)

        def cancel_check() -> bool:
            return cancel is not None and cancel.is_set()

        try:
            http.download(
                order_file.download_url,
                str(target),
                progress=on_chunk,
                cancel=cancel_check if cancel is not None else None,
            )
        except DownloadCancelledError as exc:
            raise DownloadCancelled(str(exc)) from exc
        transfer_progress(task.index, task.area_label, size or 0, size, force=True)
        return _DownloadResult(task.index, task.area_label, str(target))
    finally:
        if release_transfer_slot is not None:
            release_transfer_slot()


def run_batch_order_download(
    tasks: list[DownloadTask],
    spec: DownloadJobSpec,
    *,
    ned: NedlastingClient,
    http: HttpClient,
    reporter: DownloadProgressReporter,
    on_item_completed: ItemCompletedCallback | None = None,
    on_item_failed: ItemFailedCallback | None = None,
    acquire_packaging_slot: SlotAcquireCallback | None = None,
    release_packaging_slot: SlotReleaseCallback | None = None,
    acquire_transfer_slot: SlotAcquireCallback | None = None,
    release_transfer_slot: SlotReleaseCallback | None = None,
    cancel: threading.Event | None = None,
    poll_interval_s: float = ORDER_POLL_INTERVAL_S,
    timeout_s: float = 60 * 30,
    max_parallel_downloads: int = MAX_PARALLEL_DOWNLOADS,
) -> list[tuple[str, str]]:
    if not tasks:
        return []

    _validate_tasks(tasks, spec, ned=ned)
    expected_codes = {t.area_code for t in tasks if t.area_code}
    if not expected_codes and len(tasks) == 1:
        expected_codes = set()

    areas_for_order: list[tuple[AreaType | None, str | None, AreaOption | None]] = [
        (spec.area_type, task.area_code, task.area) for task in tasks
    ]

    _check_cancel(cancel)

    if acquire_packaging_slot is not None:
        reporter.preparing("Waiting for packaging slot…")
        acquire_packaging_slot()

    slot_released = False

    def release_slot_once() -> None:
        nonlocal slot_released
        if slot_released or release_packaging_slot is None:
            return
        release_packaging_slot()
        slot_released = True

    network_failures: list[tuple[str, str]] = []

    try:
        reporter.preparing(f"Placing order for {len(tasks)} item{'s' if len(tasks) != 1 else ''}…")
        _check_cancel(cancel)
        refs = ned.place_batch_order(
            metadata_uuid=spec.metadata_uuid,
            areas=areas_for_order,
            format_name=spec.format_name,
            projection_code=spec.projection_code,
            base_url=spec.base_url,
        )
        order_summary = f"{len(refs)} order{'s' if len(refs) != 1 else ''}, {len(tasks)} item{'s' if len(tasks) != 1 else ''}"
        reporter.preparing(f"Order placed ({order_summary})…")

        completed_indices: set[int] = set()
        failed_indices: set[int] = set()
        results_by_index: dict[int, tuple[str, str]] = {}
        transfer_progress = ThrottledTransferProgress(reporter)
        start = time.monotonic()
        parallel = max(1, max_parallel_downloads)

        with ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="batch-dl") as pool:
            in_flight: dict[int, Future[_DownloadResult]] = {}
            packaging_done = False
            cached_files: list[OrderFile] = []

            try:
                while len(completed_indices) + len(failed_indices) < len(tasks) or in_flight:
                    _check_cancel(cancel)

                    if time.monotonic() - start > timeout_s:
                        pending = [
                            tasks[i].area_label
                            for i in range(len(tasks))
                            if i not in completed_indices and i not in failed_indices
                        ]
                        raise RuntimeError(f"Timed out waiting for files: {', '.join(pending)}")

                    if not packaging_done:
                        cached_files = _collect_order_files(ned, refs, base_url=spec.base_url)
                        ready_count = sum(
                            1 for task in tasks if _match_file_to_task(cached_files, task) is not None
                        )
                        reporter.packaging(ready_count, len(tasks))

                        if all_packaging_complete(cached_files, expected_area_codes=expected_codes):
                            packaging_done = True
                            release_slot_once()
                    files = cached_files

                    for task in tasks:
                        if task.index in completed_indices or task.index in failed_indices or task.index in in_flight:
                            continue
                        if len(in_flight) >= parallel:
                            break
                        _check_cancel(cancel)
                        order_file = _match_file_to_task(files, task)
                        if order_file is None or not order_file.download_url:
                            continue
                        in_flight[task.index] = pool.submit(
                            _download_task_file,
                            task,
                            order_file,
                            spec,
                            http=http,
                            reporter=reporter,
                            transfer_progress=transfer_progress,
                            cancel=cancel,
                            acquire_transfer_slot=acquire_transfer_slot,
                            release_transfer_slot=release_transfer_slot,
                        )

                    done_now, _ = wait(in_flight.values(), timeout=0.05, return_when="FIRST_COMPLETED")
                    for future in done_now:
                        for index, candidate in list(in_flight.items()):
                            if candidate is not future:
                                continue
                            del in_flight[index]
                            task = tasks[index]
                            try:
                                result = future.result()
                            except DownloadCancelled:
                                _absorb_in_flight_futures(in_flight)
                                raise
                            except NetworkError as exc:
                                reason = str(exc)
                                network_failures.append((task.area_label, reason))
                                failed_indices.add(index)
                                if on_item_failed is not None:
                                    on_item_failed(index, task.area_label, reason)
                                break
                            except Exception as exc:
                                raise RuntimeError(f"{task.area_label}: {exc}") from exc
                            results_by_index[result.index] = (result.area_label, result.path)
                            completed_indices.add(result.index)
                            if on_item_completed is not None:
                                on_item_completed(result.index)
                            break

                    if (
                        len(completed_indices) + len(failed_indices) < len(tasks)
                        and not in_flight
                        and not packaging_done
                    ):
                        time.sleep(poll_interval_s)
            except DownloadCancelled:
                _absorb_in_flight_futures(in_flight)
                raise

        successes = [results_by_index[i] for i in sorted(results_by_index)]
        if network_failures:
            raise BatchDownloadPartialFailure(successes, network_failures)
        return successes
    finally:
        release_slot_once()
