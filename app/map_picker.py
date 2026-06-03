from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.paths import app_data_dir
from geonorge.map_selection import normalize_grid_coordinates

logger = logging.getLogger(__name__)


DEFAULT_TILE_URL = "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
_HTTP_HEADERS = {
    "Accept": "application/json,image/png,*/*",
    "User-Agent": "GeonorgeDatasets",
}
_MAX_TILE_INFLIGHT = 8


def _tile_url_template() -> str:
    return (os.environ.get("GEONORGE_BASEMAP_TILE_URL") or DEFAULT_TILE_URL).strip()


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def lonlat_to_global_px(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    lat = _clamp(lat, -85.05112878, 85.05112878)
    n = 2.0**zoom
    x = (lon + 180.0) / 360.0 * n * 256.0
    lat_rad = math.radians(lat)
    y = (1.0 - (math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi)) / 2.0 * n * 256.0
    return x, y


def global_px_to_lonlat(x: float, y: float, zoom: int) -> tuple[float, float]:
    n = 2.0**zoom
    lon = x / (n * 256.0) * 360.0 - 180.0
    t = math.pi * (1.0 - 2.0 * y / (n * 256.0))
    lat = math.degrees(math.atan(math.sinh(t)))
    return lon, lat


def _tile_xy_for_global_px(x: float, y: float) -> tuple[int, int]:
    return int(math.floor(x / 256.0)), int(math.floor(y / 256.0))


def _wrap_tile_x(x: int, zoom: int) -> int:
    n = 2**zoom
    return x % n


def _clamp_tile_y(y: int, zoom: int) -> int:
    n = 2**zoom
    return 0 if y < 0 else n - 1 if y >= n else y


def _tile_cache_dir() -> Path:
    root = app_data_dir() / "tile_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _tile_cache_path(z: int, x: int, y: int) -> Path:
    return _tile_cache_dir() / str(z) / str(x) / f"{y}.png"


class _TileFetchSignals(QObject):
    tile_ready = Signal(int, int, int, int, QImage)  # epoch,z,x,y,img


def _requests_verify() -> str | bool:
    from app.ssl_bundle import ca_bundle_path

    return ca_bundle_path()


def _fetch_tile_image(z: int, x: int, y: int, url_template: str, timeout_s: float = 10.0) -> QImage | None:
    url = url_template.format(z=z, x=x, y=y)
    try:
        resp = requests.get(
            url,
            timeout=timeout_s,
            headers={**_HTTP_HEADERS, "Accept": "image/png,*/*"},
            verify=_requests_verify(),
        )
        if resp.status_code != 200 or not resp.content:
            logger.debug("Basemap tile HTTP %s for %s", resp.status_code, url)
            return None
        img = QImage.fromData(resp.content)
        if img.isNull():
            logger.debug("Basemap tile decode failed for %s", url)
            return None
        return img
    except Exception:
        logger.debug("Basemap tile fetch failed for %s", url, exc_info=True)
        return None


def _extract_feature_code(props: dict[str, Any]) -> str | None:
    for k in ("code", "Code", "n", "id", "ID", "name", "Name", "bladnr", "bladNr", "sheet", "Sheet"):
        v = props.get(k)
        if isinstance(v, (str, int)):
            s = str(v).strip()
            if s:
                return s
    return None


def _iter_polygon_rings(geom: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """
    Return rings as lists of (lon,lat). Supports Polygon and MultiPolygon.
    """
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    rings: list[list[tuple[float, float]]] = []
    if gtype == "Polygon" and isinstance(coords, list):
        for ring in coords:
            if not isinstance(ring, list):
                continue
            pts: list[tuple[float, float]] = []
            for p in ring:
                if (
                    isinstance(p, (list, tuple))
                    and len(p) >= 2
                    and isinstance(p[0], (int, float))
                    and isinstance(p[1], (int, float))
                ):
                    pts.append((float(p[0]), float(p[1])))
            if pts:
                rings.append(pts)
    elif gtype == "MultiPolygon" and isinstance(coords, list):
        for poly in coords:
            if not isinstance(poly, list):
                continue
            for ring in poly:
                if not isinstance(ring, list):
                    continue
                pts: list[tuple[float, float]] = []
                for p in ring:
                    if (
                        isinstance(p, (list, tuple))
                        and len(p) >= 2
                        and isinstance(p[0], (int, float))
                        and isinstance(p[1], (int, float))
                    ):
                        pts.append((float(p[0]), float(p[1])))
                if pts:
                    rings.append(pts)
    return rings


def _rings_look_projected(rings: list[list[tuple[float, float]]]) -> bool:
    for ring in rings:
        for x, y in ring:
            if abs(x) > 180.0 or abs(y) > 90.0:
                return True
    return False


def _reproject_rings_to_wgs84(
    rings: list[list[tuple[float, float]]], *, source_epsg: int
) -> list[list[tuple[float, float]]]:
    from pyproj import Transformer

    transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)
    out: list[list[tuple[float, float]]] = []
    for ring in rings:
        pts: list[tuple[float, float]] = []
        for x, y in ring:
            nx, ny = normalize_grid_coordinates(x, y, source_epsg=source_epsg)
            lon, lat = transformer.transform(nx, ny)
            pts.append((float(lon), float(lat)))
        if pts:
            out.append(pts)
    return out


@dataclass(frozen=True)
class GridCellShape:
    code: str
    path_lonlat: QPainterPath
    bbox_lonlat: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat


def _lonlat_path_to_screen(
    path_lonlat: QPainterPath,
    *,
    zoom: int,
    top_left: tuple[float, float],
) -> QPainterPath:
    """Map a lon/lat path to screen space, honouring MoveTo subpath boundaries."""
    mapped = QPainterPath()
    for i in range(path_lonlat.elementCount()):
        e = path_lonlat.elementAt(i)
        gx, gy = lonlat_to_global_px(e.x, e.y, zoom)
        sx = gx - top_left[0]
        sy = gy - top_left[1]
        if e.type == QPainterPath.ElementType.MoveToElement:
            mapped.moveTo(sx, sy)
        elif e.type == QPainterPath.ElementType.LineToElement:
            mapped.lineTo(sx, sy)
        elif e.type == QPainterPath.ElementType.CurveToElement:
            mapped.cubicTo(sx, sy, sx, sy, sx, sy)
    mapped.setFillRule(Qt.FillRule.WindingFill)
    return mapped


def _build_path_for_rings(rings: list[list[tuple[float, float]]]) -> tuple[QPainterPath, tuple[float, float, float, float]] | None:
    if not rings:
        return None
    min_lon = 180.0
    max_lon = -180.0
    min_lat = 90.0
    max_lat = -90.0
    path = QPainterPath()
    for ring in rings:
        if len(ring) < 3:
            continue
        first = True
        for lon, lat in ring:
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            if first:
                path.moveTo(lon, lat)
                first = False
            else:
                path.lineTo(lon, lat)
        path.closeSubpath()
    if path.isEmpty():
        return None
    path.setFillRule(Qt.FillRule.WindingFill)
    return path, (min_lon, min_lat, max_lon, max_lat)


@dataclass(frozen=True)
class ParsedGridCell:
    code: str
    rings: tuple[tuple[tuple[float, float], ...], ...]


def parse_geojson_grid_cells(
    geojson_text: str,
    *,
    allowed_codes: set[str] | None = None,
    source_epsg: int | None = None,
) -> list[ParsedGridCell]:
    """Parse GeoJSON on a worker thread (no Qt widgets)."""
    try:
        data = json.loads(geojson_text)
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return []
    features = data.get("features")
    if not isinstance(features, list):
        return []

    allowed = set(allowed_codes or [])
    out: list[ParsedGridCell] = []
    for f in features:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        geom = f.get("geometry") if isinstance(f.get("geometry"), dict) else None
        if not geom:
            continue
        code = _extract_feature_code(props)
        if not code:
            continue
        if allowed and code not in allowed:
            continue
        rings = _iter_polygon_rings(geom)
        if rings and source_epsg and _rings_look_projected(rings):
            rings = _reproject_rings_to_wgs84(rings, source_epsg=source_epsg)
        if not rings:
            continue
        frozen_rings = tuple(tuple(ring) for ring in rings)
        out.append(ParsedGridCell(code=code, rings=frozen_rings))
    return out


def build_grid_cell_shapes(parsed: list[ParsedGridCell]) -> list[GridCellShape]:
    out: list[GridCellShape] = []
    for item in parsed:
        rings = [list(ring) for ring in item.rings]
        built = _build_path_for_rings(rings)
        if not built:
            continue
        path, bbox = built
        out.append(GridCellShape(code=item.code, path_lonlat=path, bbox_lonlat=bbox))
    return out


class MapCanvas(QWidget):
    toggled = Signal(str, bool)  # code, selected

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mapCanvas")
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, False)

        self._zoom = 5
        self._wheel_delta_accum = 0
        self._dark_basemap = False
        self._defer_basemap = False
        self._center_lon = 11.0
        self._center_lat = 64.0
        self._drag_last: QPoint | None = None
        self._hover_code: str | None = None

        self._tile_pix: dict[tuple[int, int, int], QPixmap] = {}
        self._tile_pix_dark: dict[tuple[int, int, int], QPixmap] = {}
        self._tile_inflight: set[tuple[int, int, int]] = set()
        self._tile_epoch = 0
        self._tile_url_template = _tile_url_template()

        self._grid_cells: dict[str, GridCellShape] = {}
        self._selected_codes: set[str] = set()

        self._signals = _TileFetchSignals(self)
        self._signals.tile_ready.connect(self._on_tile_ready, Qt.ConnectionType.QueuedConnection)

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.timeout.connect(self.update)

    def set_center(self, *, lon: float, lat: float, zoom: int | None = None) -> None:
        self._center_lon = float(lon)
        self._center_lat = float(lat)
        if zoom is not None:
            self._zoom = int(zoom)
        self.update()

    def clear_basemap_tiles(self) -> None:
        self._tile_epoch += 1
        self._tile_pix.clear()
        self._tile_pix_dark.clear()
        self._tile_inflight.clear()

    def set_grid_cells(self, cells: list[GridCellShape]) -> None:
        self._grid_cells = {c.code: c for c in cells}
        self.update()

    def set_selected_codes(self, codes: set[str]) -> None:
        self._selected_codes = set(codes)
        self.update()

    def set_basemap_deferred(self, deferred: bool) -> None:
        """When True, skip basemap tile fetches until the grid overlay is ready."""
        self._defer_basemap = bool(deferred)
        if not deferred:
            self.update()

    def set_dark_basemap(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._dark_basemap == enabled:
            return
        self._dark_basemap = enabled
        bg = QColor(28, 30, 34) if self._dark_basemap else QColor(245, 246, 248)
        self.setStyleSheet(f"QWidget#mapCanvas {{ background-color: {bg.name()}; }}")
        self._rebuild_dark_tile_cache()
        self.update()

    def _rebuild_dark_tile_cache(self) -> None:
        self._tile_pix_dark.clear()
        if not self._dark_basemap:
            return
        for key, pix in self._tile_pix.items():
            if pix.isNull():
                self._tile_pix_dark[key] = pix
                continue
            img = pix.toImage()
            if img.isNull():
                self._tile_pix_dark[key] = QPixmap()
                continue
            img = img.copy()
            img.invertPixels(QImage.InvertMode.InvertRgb)
            self._tile_pix_dark[key] = QPixmap.fromImage(img)

    def _basemap_pixmap(self, key: tuple[int, int, int]) -> QPixmap | None:
        if self._dark_basemap:
            return self._tile_pix_dark.get(key) or self._tile_pix.get(key)
        return self._tile_pix.get(key)

    def _remember_tile(self, key: tuple[int, int, int], img: QImage) -> None:
        if img.isNull():
            # Remember failure so paint does not re-request the same tile forever.
            self._tile_pix[key] = QPixmap()
            self._tile_pix_dark[key] = QPixmap()
            return
        pix = QPixmap.fromImage(img)
        self._tile_pix[key] = pix
        if self._dark_basemap:
            inv = img.copy()
            inv.invertPixels(QImage.InvertMode.InvertRgb)
            self._tile_pix_dark[key] = QPixmap.fromImage(inv)
        else:
            self._tile_pix_dark.pop(key, None)

    def _background_color(self) -> QColor:
        return QColor(28, 30, 34) if self._dark_basemap else QColor(245, 246, 248)

    def _schedule_repaint(self) -> None:
        if not self._repaint_timer.isActive():
            self._repaint_timer.start(0)

    def _fetch_tile(self, z: int, x: int, y: int) -> None:
        key = (z, x, y)
        if key in self._tile_pix or key in self._tile_inflight:
            return
        if len(self._tile_inflight) >= _MAX_TILE_INFLIGHT:
            self._schedule_repaint()
            return
        self._tile_inflight.add(key)
        epoch = self._tile_epoch

        cache_path = _tile_cache_path(z, x, y)
        if cache_path.exists():
            try:
                img = QImage(str(cache_path))
                if not img.isNull() and epoch == self._tile_epoch:
                    self._remember_tile(key, img)
                    self._tile_inflight.discard(key)
                    self._schedule_repaint()
                    return
            except Exception:
                pass

        def work() -> None:
            # Network + disk only — no Qt GUI access on this thread.
            img = _fetch_tile_image(z, x, y, self._tile_url_template)
            if img is None:
                self._signals.tile_ready.emit(epoch, z, x, y, QImage())
                return
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(cache_path), "PNG")
            except Exception:
                pass
            self._signals.tile_ready.emit(epoch, z, x, y, img)

        from PySide6.QtCore import QRunnable, QThreadPool

        class _Run(QRunnable):
            def run(self) -> None:  # type: ignore[override]
                work()

        QThreadPool.globalInstance().start(_Run())

    def _on_tile_ready(self, epoch: int, z: int, x: int, y: int, img: QImage) -> None:
        if epoch != self._tile_epoch:
            return
        key = (z, x, y)
        self._tile_inflight.discard(key)
        self._remember_tile(key, img)
        self._schedule_repaint()

    def _screen_to_lonlat(self, pt: QPoint) -> tuple[float, float]:
        w = max(1, self.width())
        h = max(1, self.height())
        cx, cy = lonlat_to_global_px(self._center_lon, self._center_lat, self._zoom)
        gx = cx + (pt.x() - w / 2.0)
        gy = cy + (pt.y() - h / 2.0)
        return global_px_to_lonlat(gx, gy, self._zoom)

    def _grid_hit_test(self, lon: float, lat: float) -> str | None:
        # Quick bbox prune, then path.contains.
        for code, shape in self._grid_cells.items():
            min_lon, min_lat, max_lon, max_lat = shape.bbox_lonlat
            if lon < min_lon or lon > max_lon or lat < min_lat or lat > max_lat:
                continue
            try:
                if shape.path_lonlat.contains(QPointF(lon, lat)):
                    return code
            except Exception:
                continue
        return None

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if not delta:
            return
        # Accumulate trackpad deltas; require ~one mouse-notch before zooming.
        self._wheel_delta_accum += delta
        if abs(self._wheel_delta_accum) < 120:
            return
        steps = int(self._wheel_delta_accum / 120)
        self._wheel_delta_accum -= steps * 120
        steps = max(-1, min(1, steps))
        if not steps:
            return
        before_lon, before_lat = self._screen_to_lonlat(event.position().toPoint())
        self._zoom = int(_clamp(self._zoom + steps, 2, 18))
        after_px = lonlat_to_global_px(before_lon, before_lat, self._zoom)
        w = max(1, self.width())
        h = max(1, self.height())
        cx, cy = after_px[0] - (event.position().x() - w / 2.0), after_px[1] - (event.position().y() - h / 2.0)
        self._center_lon, self._center_lat = global_px_to_lonlat(cx, cy, self._zoom)
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._drag_last = event.pos()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_last is not None and (event.buttons() & Qt.LeftButton):
            dx = event.pos().x() - self._drag_last.x()
            dy = event.pos().y() - self._drag_last.y()
            self._drag_last = event.pos()
            cx, cy = lonlat_to_global_px(self._center_lon, self._center_lat, self._zoom)
            cx -= dx
            cy -= dy
            self._center_lon, self._center_lat = global_px_to_lonlat(cx, cy, self._zoom)
            self.update()
            return

        lon, lat = self._screen_to_lonlat(event.pos())
        code = self._grid_hit_test(lon, lat)
        if code != self._hover_code:
            self._hover_code = code
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        was_drag = False
        if self._drag_last is not None:
            # If the mouse moved significantly, treat as pan.
            was_drag = (event.pos() - self._drag_last).manhattanLength() > 4
        self._drag_last = None
        if was_drag:
            return
        lon, lat = self._screen_to_lonlat(event.pos())
        code = self._grid_hit_test(lon, lat)
        if not code:
            return
        selected = code not in self._selected_codes
        if selected:
            self._selected_codes.add(code)
        else:
            self._selected_codes.discard(code)
        self.toggled.emit(code, selected)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), self._background_color())
            painter.setRenderHint(QPainter.Antialiasing, True)
            self._paint_map_content(painter)
        except Exception:
            logger.exception("Map canvas paint failed")
        finally:
            painter.end()

    def _paint_map_content(self, painter: QPainter) -> None:

        w = max(1, self.width())
        h = max(1, self.height())
        center_px = lonlat_to_global_px(self._center_lon, self._center_lat, self._zoom)
        top_left = (center_px[0] - w / 2.0, center_px[1] - h / 2.0)
        bottom_right = (center_px[0] + w / 2.0, center_px[1] + h / 2.0)

        tx0, ty0 = _tile_xy_for_global_px(top_left[0], top_left[1])
        tx1, ty1 = _tile_xy_for_global_px(bottom_right[0], bottom_right[1])

        if not self._defer_basemap:
            for ty in range(ty0, ty1 + 1):
                y = _clamp_tile_y(ty, self._zoom)
                for tx in range(tx0, tx1 + 1):
                    x = _wrap_tile_x(tx, self._zoom)
                    key = (self._zoom, x, y)
                    sx = int(tx * 256 - top_left[0])
                    sy = int(ty * 256 - top_left[1])
                    if pix := self._basemap_pixmap(key):
                        if pix.isNull():
                            continue
                        rect = QRect(sx, sy, 256, 256)
                        painter.drawPixmap(rect, pix)
                    else:
                        self._fetch_tile(self._zoom, x, y)

        # Grid overlay
        if self._grid_cells:
            selected_fill = QColor(0, 120, 215, 110) if not self._dark_basemap else QColor(111, 150, 255, 130)
            hover_fill = QColor(255, 165, 0, 90) if not self._dark_basemap else QColor(255, 214, 120, 110)
            stroke_color = QColor(0, 0, 0, 180) if not self._dark_basemap else QColor(255, 255, 255, 210)
            stroke = QPen(stroke_color, 1.0)
            stroke.setCosmetic(True)
            painter.setPen(stroke)

            for code, shape in self._grid_cells.items():
                if shape.path_lonlat.elementCount() == 0:
                    continue
                min_lon, min_lat, max_lon, max_lat = shape.bbox_lonlat
                if not all(math.isfinite(v) for v in shape.bbox_lonlat):
                    continue
                if min_lon >= max_lon or min_lat >= max_lat:
                    continue
                mapped = _lonlat_path_to_screen(
                    shape.path_lonlat,
                    zoom=self._zoom,
                    top_left=top_left,
                )
                if mapped.isEmpty():
                    continue

                if code in self._selected_codes:
                    painter.fillPath(mapped, selected_fill)
                elif code == self._hover_code:
                    painter.fillPath(mapped, hover_fill)
                painter.drawPath(mapped)

        # Attribution
        painter.setPen(QColor(220, 220, 220, 180) if self._dark_basemap else QColor(0, 0, 0, 160))
        painter.drawText(QRect(8, h - 22, w - 16, 16), Qt.AlignLeft | Qt.AlignVCenter, "© Kartverket")


class MapPickerWidget(QWidget):
    toggled = Signal(str, bool)  # code, selected

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = MapCanvas(self)
        self.canvas.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, False)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.canvas, 1)

        self.canvas.toggled.connect(self.toggled)

    def apply_parsed_grid(self, parsed: list[ParsedGridCell]) -> None:
        canvas = self.canvas
        canvas.setUpdatesEnabled(False)
        try:
            try:
                shapes = build_grid_cell_shapes(parsed)
            except Exception:
                logger.exception("Failed to build map grid shapes")
                shapes = []
            canvas.set_grid_cells(shapes)
            canvas.set_basemap_deferred(False)
            self.fit_to_grid()
        finally:
            canvas.setUpdatesEnabled(True)
            canvas.update()

    def set_grid_from_geojson(
        self,
        *,
        geojson_text: str,
        allowed_codes: set[str] | None = None,
        source_epsg: int | None = None,
    ) -> None:
        parsed = parse_geojson_grid_cells(
            geojson_text,
            allowed_codes=allowed_codes,
            source_epsg=source_epsg,
        )
        self.apply_parsed_grid(parsed)

    def fit_to_grid(self) -> None:
        cells = list(self.canvas._grid_cells.values())
        if not cells:
            return
        min_lon = min(c.bbox_lonlat[0] for c in cells)
        min_lat = min(c.bbox_lonlat[1] for c in cells)
        max_lon = max(c.bbox_lonlat[2] for c in cells)
        max_lat = max(c.bbox_lonlat[3] for c in cells)
        if not all(math.isfinite(v) for v in (min_lon, min_lat, max_lon, max_lat)):
            return
        if min_lon >= max_lon or min_lat >= max_lat:
            return
        lon = (min_lon + max_lon) / 2.0
        lat = (min_lat + max_lat) / 2.0
        lon_span = max(max_lon - min_lon, 1e-6)
        lat_span = max(max_lat - min_lat, 1e-6)
        lat_rad = math.radians(lat)
        span = max(lon_span, lat_span * max(math.cos(lat_rad), 0.2))
        zoom = int(_clamp(math.log2(360.0 / span) - 0.5, 4.0, 14.0))
        self.canvas.set_center(lon=lon, lat=lat, zoom=zoom)


def fetch_text(url: str, *, timeout_s: float = 12.0) -> str:
    resp = requests.get(
        url,
        timeout=timeout_s,
        headers=_HTTP_HEADERS,
        verify=_requests_verify(),
    )
    resp.raise_for_status()
    return resp.text

