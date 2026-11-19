"""Phát hiện cấu hình pod (VRAM, RAM, GPU) để tự chọn model phù hợp.

Không khởi tạo CUDA trong tiến trình chính (ComfyUI đang giữ GPU): đọc qua nvidia-smi và
/proc/meminfo, giới hạn RAM của container lấy từ cgroup.
"""
import copy
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

_CACHE: Optional[Dict[str, Any]] = None


def _ram_gb() -> float:
    total = 0.0
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) / 1024 / 1024
                    break
    except OSError:
        pass
    # RunPod giới hạn RAM container bằng cgroup (free -g vẫn báo RAM của cả máy chủ).
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = open(path, encoding="utf-8").read().strip()
            if raw.isdigit() and int(raw) < (1 << 50):
                limit = int(raw) / 1024 ** 3
                total = min(total, limit) if total else limit
                break
        except OSError:
            continue
    return round(total, 1)


def detect(refresh: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    info: Dict[str, Any] = {"gpu": "", "vram_gb": 0.0, "ram_gb": _ram_gb()}
    override = os.environ.get("AI_STUDIO_VRAM_GB")
    if override:
        info["vram_gb"] = float(override)
    elif shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip().splitlines()
            if out:
                name, mem = [p.strip() for p in out[0].split(",")[:2]]
                info["gpu"], info["vram_gb"] = name, round(float(mem) / 1024, 1)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if os.environ.get("AI_STUDIO_RAM_GB"):
        info["ram_gb"] = float(os.environ["AI_STUDIO_RAM_GB"])
    _CACHE = info
    return info


def pick_motion(cfg: Dict[str, Any], hw: Dict[str, Any]) -> Dict[str, Any]:
    """Chọn model chuyển động/nhép miệng theo VRAM-RAM (motion.model: auto).

    Ngưỡng nằm trong settings.yaml > motion.auto. Trả về {"model", "lipsync", "reason"}.
    """
    rules = dict(cfg.get("auto", {}) or {})
    vram, ram = float(hw.get("vram_gb") or 0), float(hw.get("ram_gb") or 0)
    need14 = rules.get("wan14b_min", {"vram_gb": 20, "ram_gb": 40})
    need_s2v = rules.get("s2v_min", {"vram_gb": 24, "ram_gb": 40})
    use14 = vram >= float(need14.get("vram_gb", 20)) and ram >= float(need14.get("ram_gb", 40))
    lipsync = vram >= float(need_s2v.get("vram_gb", 24)) and ram >= float(need_s2v.get("ram_gb", 40))
    model = "wan22_14b" if use14 else "wan22_5b"
    reason = f"GPU {hw.get('gpu') or '?'} {vram:.0f} GB VRAM, RAM {ram:.0f} GB -> {model}" + (", nhép miệng S2V" if lipsync else ", không nhép miệng")
    return {"model": model, "lipsync": lipsync, "reason": reason}


def _meets(minimum: Dict[str, Any], hw: Dict[str, Any]) -> bool:
    return (float(hw.get("vram_gb") or 0) >= float(minimum.get("vram_gb", 0))
            and float(hw.get("ram_gb") or 0) >= float(minimum.get("ram_gb", 0)))


def pick_quality(cfg: Dict[str, Any], hw: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Mức chất lượng cao nhất pod đáp ứng (settings.yaml > quality.tiers, xếp từ thấp lên cao)."""
    quality = cfg.get("quality") or {}
    if not quality.get("auto", True):
        return "cố định (quality.auto: false)", {}
    name, changes = "mặc định", {}
    for tier in quality.get("tiers") or []:
        if _meets(tier.get("min") or {}, hw):
            name, changes = str(tier.get("name", "?")), dict(tier.get("set") or {})
    return name, changes


def _set_dotted(cfg: Dict[str, Any], key: str, value: Any) -> None:
    node = cfg
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def apply_quality(cfg: Dict[str, Any], hw: Dict[str, Any]) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    """Trả về (cfg đã nâng theo pod, tên mức, các thay đổi). Không sửa cfg gốc."""
    name, changes = pick_quality(cfg, hw)
    result = copy.deepcopy(cfg)
    for key, value in changes.items():
        _set_dotted(result, key, value)
    return result, name, changes


def ollama_models_wanted(cfg: Dict[str, Any], hw: Dict[str, Any]) -> List[str]:
    """Model Ollama cần có trên pod: bản mặc định (dự phòng) + bản của mức chất lượng hiện tại."""
    tuned, _, _ = apply_quality(cfg, hw)
    wanted: List[str] = []
    for source in (cfg.get("ollama") or {}, tuned.get("ollama") or {}):
        for key in ("model", "vision_model"):
            name = source.get(key)
            if name and name not in wanted:
                wanted.append(str(name))
    return wanted
