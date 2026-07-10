from dataclasses import dataclass, field

from voice_lab.app.service import ApplicationService
from voice_lab.config import ConfigurationService
from voice_lab.controllers.hotkeys import HotkeyManager
from voice_lab.controllers.soundboard import SoundboardController
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io import AudioIO, Router
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginDiscovery, PluginManager
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
        self._record_telemetry(
            telemetry,
            "plugin.discovery_started",
            "info",
            "Plugin discovery started",
        )
        plugin_discovery = PluginDiscovery()
        discovery_result = plugin_discovery.discover()
        self._record_discovery_telemetry(telemetry, discovery_result)

        self._step("validate_plugins")
        plugins = PluginManager(discovery_result=discovery_result)
        self._record_plugin_startup_telemetry(telemetry, discovery_result, plugins)

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

    def _record_telemetry(self, telemetry, event_type, severity, message, **metadata):
        try:
            return telemetry.record_event(event_type, severity, message, **metadata)
        except Exception:
            return None

    def _record_discovery_telemetry(self, telemetry, discovery_result):
        for candidate in discovery_result.candidates:
            self._record_telemetry(
                telemetry,
                "plugin.candidate_discovered",
                "info",
                f"Plugin candidate discovered: {candidate.source}",
                source=candidate.source,
                candidate_type=candidate.candidate_type,
                origin=candidate.origin,
                candidate_order=candidate.discovery_order,
                manifest_path=str(candidate.manifest_path) if candidate.manifest_path else "",
                built_in=candidate.candidate_type == "builtin",
            )

        for failure in discovery_result.failures:
            self._record_telemetry(
                telemetry,
                "plugin.discovery_failed",
                failure.severity,
                failure.message,
                location_id=failure.location_id,
                path=str(failure.path) if failure.path else "",
                reason=failure.message,
            )

        self._record_telemetry(
            telemetry,
            "plugin.discovery_completed",
            "info",
            "Plugin discovery completed",
            candidate_count=len(discovery_result.candidates),
            failure_count=len(discovery_result.failures),
        )

    def _record_plugin_startup_telemetry(self, telemetry, discovery_result, plugins):
        load_results = plugins.manifest_load_results()
        registration_results = plugins.registration_results()

        for load_result in load_results:
            candidate = load_result.candidate
            if load_result.success:
                metadata = load_result.metadata
                self._record_telemetry(
                    telemetry,
                    "plugin.manifest_loaded",
                    "info",
                    f"Plugin metadata loaded: {metadata.plugin_id}",
                    plugin_id=metadata.plugin_id,
                    plugin_version=metadata.version,
                    effect_ids=tuple(effect.effect_id for effect in metadata.effects),
                    source=candidate.source,
                    origin=candidate.origin,
                    manifest_path=str(candidate.manifest_path) if candidate.manifest_path else "",
                    built_in=candidate.candidate_type == "builtin",
                    executable=candidate.candidate_type == "builtin",
                )
            else:
                self._record_telemetry(
                    telemetry,
                    "plugin.manifest_failed",
                    "warning",
                    f"Plugin manifest failed: {load_result.reason}",
                    source=candidate.source,
                    origin=candidate.origin,
                    manifest_path=str(candidate.manifest_path) if candidate.manifest_path else "",
                    reason=load_result.reason,
                    built_in=candidate.candidate_type == "builtin",
                )

        for result in registration_results:
            if result.success:
                metadata = result.metadata
                self._record_telemetry(
                    telemetry,
                    "plugin.compatible",
                    "info",
                    f"Plugin compatible: {metadata.plugin_id}",
                    plugin_id=metadata.plugin_id,
                    plugin_version=metadata.version,
                    min_api_version=metadata.compatibility.min_api_version,
                    max_api_version=metadata.compatibility.max_api_version or "",
                    current_api_version=plugins.api_version,
                    executable=metadata.plugin_id == "voicelab.builtin.effects",
                )
                self._record_telemetry(
                    telemetry,
                    "plugin.registered",
                    "info",
                    f"Plugin registered: {metadata.plugin_id}",
                    plugin_id=metadata.plugin_id,
                    effect_ids=tuple(effect.effect_id for effect in metadata.effects),
                    executable=metadata.plugin_id == "voicelab.builtin.effects",
                )
            else:
                event_type = (
                    "plugin.incompatible"
                    if "Plugin requires VoiceLab plugin API" in result.reason
                    else "plugin.registration_failed"
                )
                self._record_telemetry(
                    telemetry,
                    event_type,
                    "warning",
                    f"Plugin registration rejected: {result.reason}",
                    plugin_id=result.plugin_id,
                    reason=result.reason,
                    current_api_version=plugins.api_version,
                )

        registered_plugins = plugins.registered_plugins()
        registered_ids = tuple(plugin.plugin_id for plugin in registered_plugins)
        failures = plugins.registration_failures()
        external_registered = tuple(
            plugin.plugin_id
            for plugin in registered_plugins
            if plugin.plugin_id != "voicelab.builtin.effects"
        )
        incompatible_ids = tuple(
            failure.plugin_id
            for failure in failures
            if "Plugin requires VoiceLab plugin API" in failure.reason
        )
        status = {
            "discovered_candidate_count": len(discovery_result.candidates),
            "manifest_loaded_count": sum(1 for result in load_results if result.success),
            "registered_plugin_ids": registered_ids,
            "registered_plugin_count": len(registered_plugins),
            "rejected_plugin_count": len(failures),
            "incompatible_plugin_ids": incompatible_ids,
            "latest_plugin_failure": failures[-1].reason if failures else "",
            "built_in_plugin_available": "voicelab.builtin.effects" in registered_ids,
            "external_plugin_execution_supported": False,
            "external_registered_metadata_ids": external_registered,
        }
        try:
            telemetry.set_plugin_startup_status(status)
        except Exception:
            pass

        self._record_telemetry(
            telemetry,
            "plugin.startup_summary",
            "info",
            "Plugin startup summary",
            **status,
        )
