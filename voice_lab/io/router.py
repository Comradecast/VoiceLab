import queue

from voice_lab.io.capture import Capture
from voice_lab.io.device_errors import DeviceFailure, DeviceFailureError


class Router:
    def __init__(self, audio_io, capture=None):
        self.audio_io = audio_io
        self.capture = capture or Capture()
        self.monitor_queue = queue.Queue(maxsize=1)

    def validate_route(self, input_id, virtual_mic_id, monitor_id=None):
        devices = self.audio_io.query_devices()
        self._require_device(devices, input_id, "input", "max_input_channels")
        self._require_device(devices, virtual_mic_id, "virtual mic output", "max_output_channels")
        if monitor_id is not None:
            self._require_device(devices, monitor_id, "monitor output", "max_output_channels")

    def start(self, engine, mixer, input_id, virtual_mic_id, monitor_id=None, monitor_enabled=None):
        self.stop()
        try:
            self.validate_route(input_id, virtual_mic_id, monitor_id)
            self.monitor_queue = queue.Queue(maxsize=1)

            def main_callback(indata, outdata, frames, time_info, status):
                input_frame = self.capture.capture_block(indata, frames)
                voice_frame = engine.process_voice(input_frame)
                buses = mixer.mix(voice_frame)

                self.audio_io.write_frame(outdata, buses.main_bus)

                if monitor_enabled and monitor_enabled() and monitor_id is not None:
                    self._drop_stale_monitor_frame()
                    try:
                        self.monitor_queue.put_nowait(buses.monitor_bus)
                    except queue.Full:
                        pass

            def monitor_callback(outdata, frames, time_info, status):
                try:
                    frame = self.monitor_queue.get_nowait()
                    self.audio_io.write_frame(outdata, frame)
                except queue.Empty:
                    outdata[:] = 0

            if monitor_id is not None:
                self.audio_io.open_output_stream(monitor_id, monitor_callback)

            self.audio_io.open_duplex_stream(input_id, virtual_mic_id, main_callback)
        except Exception as start_exc:
            try:
                self.stop()
            except Exception as cleanup_exc:
                raise DeviceFailureError(
                    DeviceFailure(
                        category="partial_start_cleanup_failed",
                        role="route",
                        technical_detail=(
                            f"startup failure: {start_exc}; cleanup failure: {cleanup_exc}"
                        ),
                    )
                ) from cleanup_exc
            raise

    def stop(self):
        self.audio_io.close()
        self.monitor_queue = queue.Queue(maxsize=1)

    def _drop_stale_monitor_frame(self):
        try:
            self.monitor_queue.get_nowait()
        except queue.Empty:
            pass

    def _require_device(self, devices, device_id, label, channel_key):
        if device_id is None:
            raise DeviceFailureError(
                DeviceFailure(
                    category="missing_selection",
                    role=self._role_for_label(label),
                    technical_detail=f"Missing {label} device",
                )
            )
        try:
            device = devices[device_id]
        except Exception as exc:
            raise DeviceFailureError(
                DeviceFailure(
                    category="device_not_found",
                    role=self._role_for_label(label),
                    selected_device_id=device_id,
                    technical_detail=f"Invalid {label} device: {device_id}",
                )
            ) from exc
        if device[channel_key] <= 0:
            raise DeviceFailureError(
                DeviceFailure(
                    category="unsupported_configuration",
                    role=self._role_for_label(label),
                    selected_device_id=device_id,
                    technical_detail=f"Device {device_id} is not a valid {label} device",
                )
            )

    def _role_for_label(self, label):
        if label == "input":
            return "input"
        if label == "virtual mic output":
            return "virtual_output"
        if label == "monitor output":
            return "monitor_output"
        return "route"
