from dataclasses import dataclass, field

from voice_lab.app.service import ApplicationService
from voice_lab.config import ConfigurationService
from voice_lab.controllers.hotkeys import HotkeyManager
from voice_lab.controllers.soundboard import SoundboardController
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io import AudioIO, Router
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService


@dataclass
class LifecycleState:
    service: ApplicationService | None = None
    startup_steps: list[str] = field(default_factory=list)
    shutdown_steps: list[str] = field(default_factory=list)
    controllers_running: bool = False


class ApplicationLifecycle:
    def __init__(self):
        self.state = LifecycleState()

    def startup(self):
        if self.state.service is not None:
            return self.state.service

        self._step("load_configuration")
        config = ConfigurationService()

        self._step("initialize_telemetry")
        telemetry = TelemetryService()

        self._step("discover_plugins")
        plugins = PluginManager()

        self._step("validate_plugins")

        self._step("initialize_engine")
        engine = AudioEngine()

        self._step("initialize_mixer")
        mixer = Mixer()

        self._step("initialize_audio_io")
        audio_io = AudioIO()

        self._step("initialize_router")
        router = Router(audio_io)

        self._step("initialize_controllers")
        hotkeys = HotkeyManager()
        soundboard = SoundboardController()

        self._step("initialize_application_service")
        self.state.service = ApplicationService(
            telemetry=telemetry,
            config=config,
            plugins=plugins,
            engine=engine,
            mixer=mixer,
            audio_io=audio_io,
            router=router,
            hotkeys=hotkeys,
            soundboard=soundboard,
        )
        return self.state.service

    def start_controllers(self):
        service = self.startup()
        if self.state.controllers_running:
            return
        service.register_hotkeys()
        self.state.controllers_running = True

    def shutdown(self):
        service = self.state.service
        if service is None:
            return

        if self.state.controllers_running:
            self._shutdown_step("stop_controllers")
            service.unregister_hotkeys()
            self.state.controllers_running = False

        self._shutdown_step("stop_audio")
        service.stop_audio()

        self._shutdown_step("flush_telemetry")
        service.telemetry_snapshot()

        self._shutdown_step("close_devices")
        service.router.stop()

        self._shutdown_step("unload_plugins")

        self._shutdown_step("save_configuration")

    def _step(self, name):
        self.state.startup_steps.append(name)

    def _shutdown_step(self, name):
        self.state.shutdown_steps.append(name)
