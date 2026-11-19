"""Xử lý audio bằng numpy (không phụ thuộc pydub/audioop)."""
import os
import wave
from typing import Tuple

import numpy as np


def to_mono_float(samples) -> np.ndarray:
    if hasattr(samples, "detach"):
        samples = samples.detach().float().cpu().numpy()
    data = np.asarray(samples, dtype=np.float32)
    data = np.squeeze(data)
    if data.ndim == 2:
        # (channels, n) hoặc (n, channels)
        data = data.mean(axis=0 if data.shape[0] < data.shape[1] else 1)
    if data.dtype != np.float32:
        data = data.astype(np.float32)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 1.5:  # int16 range
        data = data / 32768.0
    return data


def read_wav(path: str) -> Tuple[np.ndarray, int]:
    try:
        import soundfile as sf

        data, sr = sf.read(path, dtype="float32", always_2d=False)
        return to_mono_float(data), int(sr)
    except ImportError:
        pass
    with wave.open(path, "rb") as handle:
        sr = handle.getframerate()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"Chỉ hỗ trợ WAV 16-bit khi thiếu soundfile: {path}")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, sr


def write_wav(path: str, samples: np.ndarray, sr: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = np.clip(to_mono_float(samples), -1.0, 1.0)
    pcm = (data * 32767.0).astype(np.int16)
    tmp = f"{path}.tmp.wav"
    with wave.open(tmp, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sr))
        handle.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def resample(samples: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or samples.size == 0:
        return samples
    duration = samples.size / float(src_sr)
    target_len = max(1, int(round(duration * dst_sr)))
    src_t = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    dst_t = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(dst_t, src_t, samples).astype(np.float32)


def silence(ms: int, sr: int) -> np.ndarray:
    return np.zeros(max(0, int(sr * ms / 1000.0)), dtype=np.float32)


def _frame_db(samples: np.ndarray, sr: int, frame_ms: int = 10) -> np.ndarray:
    frame = max(1, int(sr * frame_ms / 1000))
    count = samples.size // frame
    if count == 0:
        return np.array([-120.0])
    frames = samples[: count * frame].reshape(count, frame)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    return 20.0 * np.log10(rms + 1e-12)


def trim_silence(
    samples: np.ndarray,
    sr: int,
    threshold_db: float = -42.0,
    lead_ms: int = 30,
    tail_ms: int = 60,
) -> np.ndarray:
    """Cắt khoảng lặng đầu/cuối do TTS tự sinh để nhịp nghỉ do tool kiểm soát."""
    if samples.size == 0:
        return samples
    peak = float(np.max(np.abs(samples)))
    if peak <= 1e-6:
        return samples[:0]
    db = _frame_db(samples, sr) - 20.0 * np.log10(peak)  # tương đối so với đỉnh
    voiced = np.where(db > threshold_db)[0]
    if voiced.size == 0:
        return samples
    frame = max(1, int(sr * 10 / 1000))
    start = max(0, voiced[0] * frame - int(sr * lead_ms / 1000))
    end = min(samples.size, (voiced[-1] + 1) * frame + int(sr * tail_ms / 1000))
    return samples[start:end]


def apply_fade(samples: np.ndarray, sr: int, fade_ms: int = 10) -> np.ndarray:
    length = min(samples.size // 2, int(sr * fade_ms / 1000))
    if length <= 1:
        return samples
    out = samples.copy()
    ramp = np.linspace(0.0, 1.0, length, dtype=np.float32)
    out[:length] *= ramp
    out[-length:] *= ramp[::-1]
    return out


def normalize_rms(samples: np.ndarray, target_db: float = -20.0, max_peak: float = 0.95) -> np.ndarray:
    if samples.size == 0:
        return samples
    rms = float(np.sqrt(np.mean(samples ** 2) + 1e-12))
    gain = (10 ** (target_db / 20.0)) / max(rms, 1e-6)
    out = samples * gain
    peak = float(np.max(np.abs(out)))
    if peak > max_peak:
        out *= max_peak / peak
    return out.astype(np.float32)


def duration_ms(samples: np.ndarray, sr: int) -> int:
    return int(round(samples.size * 1000.0 / sr))
