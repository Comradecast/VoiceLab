from pathlib import Path
import os
import platform
import shutil
import sys

try:
    from setuptools import Extension, setup
    from setuptools.command.build_ext import build_ext
except ImportError as exc:
    raise SystemExit("setuptools is required to build the Signalsmith backend") from exc

try:
    import pybind11
except ImportError as exc:
    raise SystemExit("pybind11 is required to build the Signalsmith backend") from exc


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "voice_lab" / "effects"
MODULE_STEM = "_signalsmith_pitch"
SOURCE = PACKAGE_DIR / "native" / "signalsmith_pitch_backend.cpp"


def _module_binaries():
    return sorted(PACKAGE_DIR.glob(f"{MODULE_STEM}*.pyd")) + sorted(
        PACKAGE_DIR.glob(f"{MODULE_STEM}*.so")
    )


def _clean_existing_binaries():
    for binary in _module_binaries():
        try:
            binary.unlink()
        except PermissionError as exc:
            raise SystemExit(
                "Cannot replace the existing Signalsmith native module because Windows "
                f"has it locked: {binary}. Stop any running VoiceLab/Python process that "
                "has imported voice_lab.effects._signalsmith_pitch, then rerun this build."
            ) from exc


class VoiceLabBuildExt(build_ext):
    def run(self):
        if os.name == "nt" and platform.machine().lower() not in {"amd64", "x86_64"}:
            raise SystemExit(
                "Signalsmith backend build supports 64-bit Windows Python only for RC1; "
                f"detected architecture: {platform.machine()}"
            )
        if not SOURCE.exists():
            raise SystemExit(f"Signalsmith backend source is missing: {SOURCE}")
        _clean_existing_binaries()
        try:
            super().run()
        except Exception as exc:
            raise SystemExit(
                "Signalsmith backend build failed. On Windows, install Microsoft C++ Build "
                "Tools with the MSVC compiler, run this script with the intended Python or "
                f"virtual environment, and ensure pybind11 is installed. Error: {exc}"
            ) from exc
        binaries = _module_binaries()
        if len(binaries) != 1:
            raise SystemExit(
                "Signalsmith backend build did not leave exactly one canonical native module "
                f"in {PACKAGE_DIR}; found: {[str(path) for path in binaries]}"
            )
        shutil.rmtree(ROOT / "build", ignore_errors=True)


extension = Extension(
    "voice_lab.effects._signalsmith_pitch",
    sources=[str(SOURCE)],
    include_dirs=[
        pybind11.get_include(),
        str(ROOT / "third_party" / "signalsmith-stretch" / "include"),
        str(ROOT / "third_party" / "signalsmith-linear" / "include"),
    ],
    language="c++",
    extra_compile_args=["/std:c++17", "/O2"] if __import__("os").name == "nt" else ["-std=c++17", "-O3"],
)


setup(
    name="voicelab-signalsmith-backend",
    version="0.0.0",
    ext_modules=[extension],
    script_args=sys.argv[1:] or ["build_ext", "--inplace"],
    cmdclass={"build_ext": VoiceLabBuildExt},
)
