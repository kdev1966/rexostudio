"""Hardware probe and tier recommendation (EK-4)."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import asdict, dataclass, field

# RAM needed to run tier-1 models comfortably next to the application.
TIER1_MIN_RAM_GB = 8.0


@dataclass(frozen=True)
class HardwareProfile:
    os: str
    os_version: str
    arch: str
    cpu: str
    physical_cores: int
    logical_cores: int
    ram_gb: float
    avx2: bool
    accelerators: list[str] = field(
        default_factory=list
    )  # e.g. ["CUDAExecutionProvider"]
    recommended_tier: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _sysctl(name: str) -> str:
    try:
        out = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _linux_cpuinfo() -> dict[str, str]:
    info: dict[str, str] = {}
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition(":")
                info.setdefault(key.strip(), value.strip())
    except OSError:
        pass
    return info


def _ram_bytes() -> int:
    system = platform.system()
    if system == "Darwin":
        return int(_sysctl("hw.memsize") or 0)
    if system == "Linux":
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except OSError:
            return 0
    if system == "Windows":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return int(status.ullTotalPhys)
    return 0


def _cpu_and_avx2() -> tuple[str, bool, int]:
    """CPU name, AVX2 support and physical core count."""
    system = platform.system()
    logical = os.cpu_count() or 1
    if system == "Darwin":
        name = _sysctl("machdep.cpu.brand_string") or platform.processor()
        avx2 = "AVX2" in _sysctl("machdep.cpu.leaf7_features").split()
        physical = int(_sysctl("hw.physicalcpu") or logical)
        return name, avx2, physical
    if system == "Linux":
        info = _linux_cpuinfo()
        name = info.get("model name", platform.processor())
        avx2 = "avx2" in info.get("flags", "").split()
        cores = info.get(
            "cpu cores", ""
        )  # per socket; good enough for thread-count hints
        return name, avx2, int(cores) if cores.isdigit() else logical
    # Windows and others: no cheap reliable AVX2 probe without extra dependencies.
    return platform.processor() or platform.machine(), False, logical


def _accelerators() -> list[str]:
    """Non-CPU ONNX Runtime providers, if ONNX Runtime is installed."""
    try:
        import onnxruntime as ort
    except ImportError:
        return []
    return [p for p in ort.get_available_providers() if p != "CPUExecutionProvider"]


def recommend_tier(ram_gb: float, accelerators: list[str]) -> int:
    """Tier 2 needs an accelerator, tier 1 enough RAM; otherwise tier 0 (classical)."""
    if ram_gb < TIER1_MIN_RAM_GB:
        return 0
    if any(
        a in accelerators for a in ("CUDAExecutionProvider", "ROCMExecutionProvider")
    ):
        return 2
    return 1


def probe() -> HardwareProfile:
    """Describe the current machine."""
    cpu, avx2, physical = _cpu_and_avx2()
    ram_gb = round(_ram_bytes() / 2**30, 1)
    accel = _accelerators()
    system = platform.system()
    version = platform.mac_ver()[0] if system == "Darwin" else platform.release()
    return HardwareProfile(
        os=system,
        os_version=version,
        arch=platform.machine(),
        cpu=cpu,
        physical_cores=physical,
        logical_cores=os.cpu_count() or 1,
        ram_gb=ram_gb,
        avx2=avx2,
        accelerators=accel,
        recommended_tier=recommend_tier(ram_gb, accel),
    )
