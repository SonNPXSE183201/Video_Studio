"""Nghe lại audio TTS bằng ASR (PhoWhisper) để phát hiện vấp, nuốt chữ, đọc sượt."""
import re
import unicodedata
from typing import Any, Dict, Optional

import numpy as np

from core.audio_utils import resample
from core.utils import log


def normalize_compare(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", "", text)


def char_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize_compare(reference)
    hyp = normalize_compare(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, hc in enumerate(hyp, start=1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (rc != hc),
            )
        previous = current
    return previous[-1] / float(len(ref))


class ASRChecker:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.enabled = bool(cfg.get("enabled", True))
        self.model_id = cfg.get("model_id", "vinai/PhoWhisper-large")
        self.pipe = None
        self._failed = False

    def load(self) -> bool:
        if not self.enabled or self._failed:
            return False
        if self.pipe is not None:
            return True
        try:
            import torch
            from transformers import pipeline

            device = 0 if torch.cuda.is_available() else -1
            dtype = torch.float16 if device == 0 else torch.float32
            log(f"Nạp ASR '{self.model_id}' để kiểm tra giọng đọc...", "ASR")
            self.pipe = pipeline(
                "automatic-speech-recognition",
                model=self.model_id,
                device=device,
                torch_dtype=dtype,
            )
            return True
        except Exception as exc:
            self._failed = True
            log(f"Không nạp được ASR ({exc}). Bỏ qua bước kiểm tra giọng.", "Cảnh báo")
            return False

    def transcribe(self, samples: np.ndarray, sr: int) -> Optional[str]:
        if not self.load():
            return None
        audio = resample(samples, sr, 16000)
        try:
            result = self.pipe({"raw": audio, "sampling_rate": 16000})
            return str(result.get("text", "")).strip()
        except Exception as exc:
            log(f"ASR lỗi: {exc}", "Cảnh báo")
            return None

    def unload(self) -> None:
        if self.pipe is None:
            return
        import torch

        del self.pipe
        self.pipe = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
