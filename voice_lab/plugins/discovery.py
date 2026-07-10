from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any


BUILTIN_PLUGIN_SOURCE = "voicelab:builtin"
PLUGIN_MANIFEST_NAME = "plugin.json"


@dataclass(frozen=True)
class DiscoveryLocation:
    location_id: str
    kind: str
    path: Path | None = None
    required: bool = False

    def __post_init__(self):
        if not self.location_id:
            raise ValueError("DiscoveryLocation location_id is required")
        if self.kind not in {"builtin", "directory"}:
            raise ValueError("DiscoveryLocation kind must be builtin or directory")
        if self.kind == "directory" and self.path is None:
            raise ValueError("Directory discovery locations require a path")


@dataclass(frozen=True)
class PluginCandidate:
    source: str
    candidate_type: str
    origin: str
    discovery_order: int
    path: Path | None = None
    manifest_path: Path | None = None
    manifest: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        if self.candidate_type not in {"builtin", "manifest"}:
            raise ValueError("PluginCandidate candidate_type must be builtin or manifest")
        if self.discovery_order < 0:
            raise ValueError("PluginCandidate discovery_order must be non-negative")
        object.__setattr__(self, "manifest", MappingProxyType(dict(self.manifest)))


@dataclass(frozen=True)
class DiscoveryFailure:
    location_id: str
    message: str
    severity: str = "warning"
    path: Path | None = None


@dataclass(frozen=True)
class PluginDiscoveryResult:
    candidates: tuple[PluginCandidate, ...] = field(default_factory=tuple)
    failures: tuple[DiscoveryFailure, ...] = field(default_factory=tuple)


class PluginDiscovery:
    def __init__(self, locations=None):
        self.locations = tuple(locations) if locations is not None else default_discovery_locations()

    def discover(self):
        candidates = []
        failures = []
        seen_paths = set()

        for location in self.locations:
            try:
                if location.kind == "builtin":
                    candidates.append(
                        PluginCandidate(
                            source=BUILTIN_PLUGIN_SOURCE,
                            candidate_type="builtin",
                            origin=location.location_id,
                            discovery_order=len(candidates),
                        )
                    )
                    continue

                location_candidates, location_failures = self._discover_directory(
                    location,
                    seen_paths,
                    len(candidates),
                )
                candidates.extend(location_candidates)
                failures.extend(location_failures)
            except Exception as exc:
                failures.append(
                    DiscoveryFailure(
                        location_id=location.location_id,
                        path=location.path,
                        severity="error" if location.required else "warning",
                        message=f"Plugin discovery failed: {exc}",
                    )
                )

        return PluginDiscoveryResult(candidates=tuple(candidates), failures=tuple(failures))

    def _discover_directory(self, location, seen_paths, start_order):
        path = location.path
        failures = []
        candidates = []

        if not path.exists():
            failures.append(
                DiscoveryFailure(
                    location_id=location.location_id,
                    path=path,
                    severity="error" if location.required else "info",
                    message=(
                        "Required plugin directory is missing"
                        if location.required
                        else "Optional plugin directory is missing"
                    ),
                )
            )
            return candidates, failures

        if not path.is_dir():
            failures.append(
                DiscoveryFailure(
                    location_id=location.location_id,
                    path=path,
                    severity="error",
                    message="Plugin discovery location is not a directory",
                )
            )
            return candidates, failures

        try:
            entries = sorted(path.iterdir(), key=lambda item: str(item.name).lower())
        except Exception as exc:
            failures.append(
                DiscoveryFailure(
                    location_id=location.location_id,
                    path=path,
                    severity="error",
                    message=f"Plugin directory is not readable: {exc}",
                )
            )
            return candidates, failures

        for entry in entries:
            manifest_path = self._candidate_manifest_path(entry)
            if manifest_path is None:
                continue
            resolved = manifest_path.resolve()
            if resolved in seen_paths:
                failures.append(
                    DiscoveryFailure(
                        location_id=location.location_id,
                        path=manifest_path,
                        message="Duplicate plugin candidate path ignored",
                    )
                )
                continue
            seen_paths.add(resolved)
            candidates.append(
                PluginCandidate(
                    source=str(manifest_path),
                    candidate_type="manifest",
                    origin=location.location_id,
                    discovery_order=start_order + len(candidates),
                    path=entry,
                    manifest_path=manifest_path,
                )
            )

        return candidates, failures

    def _candidate_manifest_path(self, entry):
        if entry.is_file() and entry.name == PLUGIN_MANIFEST_NAME:
            return entry
        if entry.is_dir():
            manifest_path = entry / PLUGIN_MANIFEST_NAME
            if manifest_path.is_file():
                return manifest_path
        return None

def default_discovery_locations(base_path=None, home_path=None):
    base = Path(base_path) if base_path is not None else Path.cwd()
    home = Path(home_path) if home_path is not None else Path.home()
    return (
        DiscoveryLocation("builtin", "builtin", required=True),
        DiscoveryLocation("application_plugins", "directory", base / "plugins"),
        DiscoveryLocation("user_plugins", "directory", home / "VoiceLab" / "plugins"),
    )
