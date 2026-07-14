import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


BAND_COLORS = {
    "low_shelf": QColor("#4f9dff"),
    "low_mid": QColor("#42b883"),
    "mid": QColor("#f2b84b"),
    "presence": QColor("#ee6c8a"),
    "high_shelf": QColor("#a06cff"),
}


def frequency_to_x(frequency_hz, rect, minimum_hz=20.0, maximum_hz=20000.0):
    low = math.log10(float(minimum_hz))
    high = math.log10(float(maximum_hz))
    value = min(float(maximum_hz), max(float(minimum_hz), float(frequency_hz)))
    ratio = (math.log10(value) - low) / (high - low)
    return float(rect.left() + ratio * rect.width())


def x_to_frequency(x, rect, minimum_hz=20.0, maximum_hz=20000.0):
    ratio = (float(x) - float(rect.left())) / max(float(rect.width()), 1.0)
    ratio = min(1.0, max(0.0, ratio))
    low = math.log10(float(minimum_hz))
    high = math.log10(float(maximum_hz))
    return float(10.0 ** (low + ratio * (high - low)))


def gain_to_y(gain_db, rect, minimum_db=-12.0, maximum_db=12.0):
    value = min(float(maximum_db), max(float(minimum_db), float(gain_db)))
    ratio = (float(maximum_db) - value) / (float(maximum_db) - float(minimum_db))
    return float(rect.top() + ratio * rect.height())


def y_to_gain(y, rect, minimum_db=-12.0, maximum_db=12.0):
    ratio = (float(y) - float(rect.top())) / max(float(rect.height()), 1.0)
    ratio = min(1.0, max(0.0, ratio))
    return float(float(maximum_db) - ratio * (float(maximum_db) - float(minimum_db)))


def adjusted_q_from_wheel(q, wheel_delta, fine=False, minimum=0.3, maximum=6.0):
    step = 0.03 if fine else 0.15
    notches = float(wheel_delta) / 120.0
    return min(float(maximum), max(float(minimum), float(q) + notches * step))


class ParametricEqGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("parametric_eq_graph")
        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        self.visualization = None
        self.spectrum = None
        self.bands = ()
        self.selected_band_id = "mid"
        self.hover_band_id = None
        self.on_select = None
        self.on_drag = None
        self.on_q_change = None
        self.on_reset = None
        self._dragging = False
        self._plot_rect = QRectF()

    def node_count(self):
        return len(self.bands)

    def set_snapshots(self, visualization, application_snapshot, spectrum=None):
        self.visualization = visualization
        self.spectrum = spectrum
        self.bands = tuple(application_snapshot.applied_plan.bands) if application_snapshot is not None else ()
        if visualization is not None:
            self.selected_band_id = visualization.selected_band_id
        self.update()

    def plot_rect(self):
        return QRectF(self._plot_rect)

    def node_position(self, band):
        rect = self._current_plot_rect()
        return QPointF(
            frequency_to_x(band.applied_frequency_hz, rect),
            gain_to_y(band.applied_gain_db, rect),
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#111417"))
        rect = self._current_plot_rect()
        self._plot_rect = QRectF(rect)
        self._draw_grid(painter, rect)
        self._draw_spectrum(painter, rect)
        self._draw_response(painter, rect)
        self._draw_nodes(painter, rect)
        self._draw_state_label(painter, rect)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        band = self._nearest_band(event.position())
        if band is None:
            return
        self.selected_band_id = band.band_id
        self._dragging = True
        if self.on_select is not None:
            self.on_select(band.band_id)
        self.update()

    def mouseMoveEvent(self, event):
        if self._dragging and self.selected_band_id:
            rect = self._current_plot_rect()
            frequency = x_to_frequency(event.position().x(), rect)
            gain = y_to_gain(event.position().y(), rect)
            if event.modifiers() & Qt.ShiftModifier:
                current = self._band(self.selected_band_id)
                if current is not None:
                    frequency = current.requested_frequency_hz + (frequency - current.requested_frequency_hz) * 0.25
                    gain = current.requested_gain_db + (gain - current.requested_gain_db) * 0.25
            if self.on_drag is not None:
                self.on_drag(self.selected_band_id, frequency, gain)
            return
        band = self._nearest_band(event.position())
        self.hover_band_id = None if band is None else band.band_id
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False

    def mouseDoubleClickEvent(self, event):
        band = self._nearest_band(event.position())
        if band is not None and self.on_reset is not None:
            self.on_reset(band.band_id)

    def wheelEvent(self, event):
        band = self._band(self.selected_band_id)
        if band is None or band.filter_type != "peaking":
            return
        fine = bool(event.modifiers() & Qt.ShiftModifier)
        q = adjusted_q_from_wheel(band.requested_q, event.angleDelta().y(), fine=fine)
        if self.on_q_change is not None:
            self.on_q_change(band.band_id, q)
        event.accept()

    def keyPressEvent(self, event):
        band = self._band(self.selected_band_id)
        if band is None or self.on_drag is None:
            return
        step_gain = 0.1 if event.modifiers() & Qt.ShiftModifier else 0.5
        step_freq = 1.01 if event.modifiers() & Qt.ShiftModifier else 1.05
        if event.key() == Qt.Key_Up:
            self.on_drag(band.band_id, band.requested_frequency_hz, band.requested_gain_db + step_gain)
        elif event.key() == Qt.Key_Down:
            self.on_drag(band.band_id, band.requested_frequency_hz, band.requested_gain_db - step_gain)
        elif event.key() == Qt.Key_Left:
            self.on_drag(band.band_id, band.requested_frequency_hz / step_freq, band.requested_gain_db)
        elif event.key() == Qt.Key_Right:
            self.on_drag(band.band_id, band.requested_frequency_hz * step_freq, band.requested_gain_db)

    def _current_plot_rect(self):
        return QRectF(56, 18, max(120, self.width() - 82), max(120, self.height() - 56))

    def _draw_grid(self, painter, rect):
        painter.setPen(QPen(QColor("#30363c"), 1))
        for hz in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
            x = frequency_to_x(hz, rect)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for db in (-12, -6, 0, 6, 12):
            y = gain_to_y(db, rect)
            painter.setPen(QPen(QColor("#5a626b") if db == 0 else QColor("#30363c"), 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(QColor("#aeb7c2"))
        painter.setFont(QFont("Segoe UI", 8))
        for hz, label in ((20, "20"), (100, "100"), (1000, "1k"), (10000, "10k"), (20000, "20k")):
            painter.drawText(QPointF(frequency_to_x(hz, rect) - 10, rect.bottom() + 16), label)
        for db in (-12, -6, 0, 6, 12):
            painter.drawText(QPointF(8, gain_to_y(db, rect) + 4), f"{db:+d}")

    def _draw_spectrum(self, painter, rect):
        if self.spectrum is None or not self.spectrum.active or not self.spectrum.output_magnitude_db:
            return
        path = QPainterPath()
        started = False
        for hz, db in zip(self.spectrum.frequency_hz, self.spectrum.output_magnitude_db):
            if hz < 20.0 or hz > 20000.0:
                continue
            x = frequency_to_x(hz, rect)
            y = gain_to_y(max(-12.0, min(0.0, db / 10.0)), rect)
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor(95, 120, 150, 80), 1))
        painter.drawPath(path)

    def _draw_response(self, painter, rect):
        if self.visualization is None:
            return
        path = QPainterPath()
        fill = QPainterPath()
        baseline = gain_to_y(0.0, rect)
        started = False
        for hz, db in zip(self.visualization.frequency_hz, self.visualization.response_db):
            x = frequency_to_x(hz, rect)
            y = gain_to_y(db, rect, self.visualization.graph_min_gain_db, self.visualization.graph_max_gain_db)
            if not started:
                path.moveTo(x, y)
                fill.moveTo(x, baseline)
                fill.lineTo(x, y)
                started = True
            else:
                path.lineTo(x, y)
                fill.lineTo(x, y)
        fill.lineTo(rect.right(), baseline)
        fill.closeSubpath()
        disabled = self.visualization.local_bypass or self.visualization.global_bypass or self.visualization.backend_status == "failed"
        painter.fillPath(fill, QColor(79, 157, 255, 25 if not disabled else 10))
        painter.setPen(QPen(QColor("#76c7ff") if not disabled else QColor("#78808a"), 3 if not disabled else 2, Qt.SolidLine if not disabled else Qt.DashLine))
        painter.drawPath(path)

    def _draw_nodes(self, painter, rect):
        for band in self.bands:
            pos = self.node_position(band)
            selected = band.band_id == self.selected_band_id
            hover = band.band_id == self.hover_band_id
            color = BAND_COLORS.get(band.band_id, QColor("#dddddd"))
            radius = 8 if selected else 6
            if abs(band.applied_gain_db) <= 1.0e-6:
                color = QColor(color.red(), color.green(), color.blue(), 115)
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#ffffff") if selected else QColor("#202428"), 3 if selected else 1))
            painter.drawEllipse(pos, radius + (2 if hover else 0), radius + (2 if hover else 0))
            if band.frequency_clamped or band.gain_clamped or band.q_clamped:
                painter.setPen(QPen(QColor("#ffcc66"), 2))
                painter.drawEllipse(pos, radius + 5, radius + 5)

    def _draw_state_label(self, painter, rect):
        if self.visualization is None:
            return
        labels = []
        if self.visualization.global_bypass:
            labels.append("Global bypass")
        if self.visualization.local_bypass:
            labels.append("Bypassed")
        if self.visualization.flat:
            labels.append("Flat")
        if self.visualization.transition_active:
            labels.append(f"Transition {self.visualization.transition_progress:.2f}")
        if self.visualization.transition_pending:
            labels.append("Transition pending")
        if self.visualization.backend_status == "failed":
            labels.append("Backend failed")
        painter.setPen(QColor("#d8dee9"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QPointF(rect.left(), rect.top() - 4), " | ".join(labels))

    def _nearest_band(self, position):
        nearest = None
        nearest_distance = 999999.0
        for band in self.bands:
            node = self.node_position(band)
            distance = math.hypot(position.x() - node.x(), position.y() - node.y())
            if distance < nearest_distance:
                nearest = band
                nearest_distance = distance
        return nearest if nearest_distance <= 18.0 else None

    def _band(self, band_id):
        for band in self.bands:
            if band.band_id == band_id:
                return band
        return None
