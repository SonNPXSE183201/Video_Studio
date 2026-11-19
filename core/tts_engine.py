"""OmniVoice TTS: clone giọng, seed cố định, tham số sinh cấu hình được."""
import os
from typing import Any, Dict, Optional, Tuple

import numpy as np

from core.audio_utils import normalize_rms, read_wav, to_mono_float, trim_silence, write_wav
from core.utils import log


def _install_torch_accelerator_polyfill(torch) -> None:
    """transformers mới gọi torch.accelerator; PyTorch < 2.6 không có."""
    if hasattr(torch, "accelerator"):
        return

    class _PolyfillAccelerator:
        @staticmethod
        def current_accelerator():
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")

        @staticmethod
        def is_available():
            return torch.cuda.is_available()

        @staticmethod
        def device_count():
            return torch.cuda.device_count()

    torch.accelerator = _PolyfillAccelerator()


class TTSEngine:
    OPTIONAL_KWARGS = ("num_step", "guidance_scale", "speed", "t_shift", "denoise")

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.model_id = cfg.get("model_id", "k2-fsa/OmniVoice")
        self.sample_rate = int(cfg.get("sample_rate", 24000))
        self.model = None
        self._unsupported: set = set()

    def load(self) -> None:
        if self.model is not None:
            return
        import torch

        _install_torch_accelerator_polyfill(torch)
        from omnivoice import OmniVoice

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32
        log(f"Nạp OmniVoice '{self.model_id}' trên {device.upper()}...", "TTS")
        self.model = OmniVoice.from_pretrained(self.model_id, device_map=device, dtype=dtype)
        model_sr = getattr(self.model, "sampling_rate", None) or getattr(self.model, "sample_rate", None)
        if model_sr:
            self.sample_rate = int(model_sr)

    def unload(self) -> None:
        if self.model is None:
            return
        import torch

        del self.model
        self.model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        log("Đã giải phóng OmniVoice khỏi VRAM.", "TTS")

    def _gen_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        for key in self.OPTIONAL_KWARGS:
            value = self.cfg.get(key)
            if value is not None and key not in self._unsupported:
                kwargs[key] = value
        return kwargs

    def synthesize(
        self,
        text: str,
        ref_audio: Optional[str],
        ref_text: Optional[str],
        seed: int,
    ) -> Tuple[np.ndarray, int]:
        self.load()
        import torch

        torch.manual_seed(int(seed))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(seed))

        kwargs: Dict[str, Any] = {"text": text}
        if ref_audio and os.path.exists(ref_audio):
            kwargs["ref_audio"] = ref_audio
            if ref_text:
                kwargs["ref_text"] = ref_text
        kwargs.update(self._gen_kwargs())

        while True:
            try:
                audio = self.model.generate(**kwargs)
                break
            except TypeError as exc:
                # Phiên bản OmniVoice khác có thể không nhận một số tham số.
                bad = next((k for k in self.OPTIONAL_KWARGS if k in kwargs and k in str(exc)), None)
                if not bad:
                    raise
                log(f"OmniVoice không hỗ trợ tham số '{bad}', bỏ qua.", "TTS")
                self._unsupported.add(bad)
                kwargs.pop(bad, None)

        samples = audio[0] if isinstance(audio, (list, tuple)) else audio
        return to_mono_float(samples), self.sample_rate

    @staticmethod
    def prepare_reference(src_wav: str, dst_wav: str, max_seconds: float = 12.0) -> str:
        """Cắt lặng, chuẩn hóa âm lượng, giới hạn độ dài giọng mẫu."""
        samples, sr = read_wav(src_wav)
        samples = trim_silence(samples, sr, threshold_db=-45, lead_ms=50, tail_ms=120)
        if samples.size > sr * max_seconds:
            log(
                f"Giọng mẫu dài {samples.size / sr:.1f}s > {max_seconds}s; nên dùng mẫu 6-10s "
                "và sửa file .txt cho khớp.",
                "Cảnh báo",
            )
        samples = normalize_rms(samples, -20.0)
        write_wav(dst_wav, samples, sr)
        return dst_wav
