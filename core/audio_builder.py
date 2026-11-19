"""Sinh giọng đọc cả chương: cache theo nội dung, kiểm tra ASR, nhịp nghỉ theo dấu câu."""
import os
from typing import Any, Dict, List, Optional

import numpy as np

from core.asr_checker import ASRChecker, char_error_rate
from core.audio_utils import apply_fade, duration_ms, read_wav, resample, silence, trim_silence, write_wav
from core.tts_engine import TTSEngine
from core.utils import fingerprint, log, read_json, write_json
from core.vi_normalizer import speakable_length


class AudioBuilder:
    VERSION = 2

    def __init__(self, tts: TTSEngine, asr: ASRChecker, tts_cfg: Dict[str, Any], asr_cfg: Dict[str, Any], cache_dir: str):
        self.tts = tts
        self.asr = asr
        self.cfg = tts_cfg
        self.asr_cfg = asr_cfg
        self.cache_dir = os.path.join(cache_dir, "tts")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.force = False  # True: bỏ qua cache chunk, sinh lại toàn bộ giọng

    def _params_fp(self, voice_fp: str) -> str:
        keys = ("model_id", "num_step", "guidance_scale", "speed", "t_shift", "denoise", "seed")
        return fingerprint(self.VERSION, voice_fp, {k: self.cfg.get(k) for k in keys})

    def _check(self, text: str, samples: np.ndarray, sr: int) -> Dict[str, Any]:
        dur_s = samples.size / float(sr) if sr else 0.0
        cps = speakable_length(text) / dur_s if dur_s > 0 else 0.0
        result: Dict[str, Any] = {"duration_s": round(dur_s, 3), "cps": round(cps, 2), "cer": None, "asr": None}
        ok = dur_s > 0.25
        cps_min = float(self.asr_cfg.get("cps_min", 7))
        cps_max = float(self.asr_cfg.get("cps_max", 28))
        if speakable_length(text) >= 8 and not (cps_min <= cps <= cps_max):
            ok = False
        hyp = self.asr.transcribe(samples, sr) if self.asr.enabled else None
        if hyp is not None:
            cer = char_error_rate(text, hyp)
            result["cer"] = round(cer, 3)
            result["asr"] = hyp
            if cer > float(self.asr_cfg.get("max_cer", 0.15)):
                ok = False
        result["ok"] = ok
        return result

    def _score(self, check: Dict[str, Any]) -> float:
        cer = check.get("cer")
        return (0 if check.get("ok") else 10) + (cer if cer is not None else 0.5)

    def _render_chunk(self, chunk: Dict[str, Any], ref_audio: Optional[str], ref_text: Optional[str], params_fp: str) -> Dict[str, Any]:
        key = fingerprint(params_fp, chunk["tts"])
        wav_path = os.path.join(self.cache_dir, f"{key}.wav")
        meta_path = os.path.join(self.cache_dir, f"{key}.json")
        meta = None if self.force else read_json(meta_path)
        if meta and os.path.exists(wav_path):
            return {"path": wav_path, **meta}

        attempts = max(1, int(self.asr_cfg.get("max_attempts", 3)))
        base_seed = int(self.cfg.get("seed", 1234))
        best = None
        last_error = None
        for attempt in range(attempts):
            seed = base_seed + attempt * 7919
            try:
                samples, sr = self.tts.synthesize(chunk["tts"], ref_audio, ref_text, seed)
            except Exception as exc:
                last_error = exc
                log(f"Chunk {chunk['id']} lỗi lần {attempt + 1}: {exc}", "TTS")
                continue
            samples = trim_silence(
                samples,
                sr,
                threshold_db=float(self.cfg.get("trim_silence_db", -42)),
                lead_ms=int(self.cfg.get("lead_ms", 30)),
                tail_ms=int(self.cfg.get("tail_ms", 60)),
            )
            check = self._check(chunk["tts"], samples, sr)
            check.update({"attempt": attempt + 1, "seed": seed})
            if best is None or self._score(check) < self._score(best[2]):
                best = (samples, sr, check)
            if check["ok"]:
                break
            log(
                f"Chunk {chunk['id']} chưa đạt (CER={check.get('cer')}, {check['cps']} ký tự/s), "
                f"sinh lại lần {attempt + 2}...",
                "TTS",
            )
        if best is None:
            raise RuntimeError(f"Không sinh được audio cho chunk {chunk['id']}: {last_error}")
        samples, sr, check = best
        write_wav(wav_path, samples, sr)
        meta = {k: v for k, v in check.items()}
        meta["text"] = chunk["tts"]
        write_json(meta_path, meta)
        return {"path": wav_path, **meta}

    def build(
        self,
        chunks: List[Dict[str, Any]],
        ref_audio: Optional[str],
        ref_text: Optional[str],
        voice_fp: str,
        out_wav: str,
        timeline_path: str,
    ) -> Dict[str, Any]:
        params_fp = self._params_fp(voice_fp)
        audio_fp = fingerprint(params_fp, [(c["tts"], c["pause_after_ms"]) for c in chunks], self.cfg.get("fade_ms", 10))
        cached = read_json(timeline_path)
        if cached and cached.get("audio_fp") == audio_fp and os.path.exists(out_wav):
            log(f"Audio chương đã có ({cached['total_duration_sec']:.1f}s), dùng cache.", "TTS")
            return cached

        log(f"Sinh giọng đọc {len(chunks)} chunk...", "TTS")
        target_sr = int(self.tts.sample_rate)
        pieces: List[np.ndarray] = []
        entries: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        cursor = 0
        fade_ms = int(self.cfg.get("fade_ms", 10))
        for index, chunk in enumerate(chunks):
            info = self._render_chunk(chunk, ref_audio, ref_text, params_fp)
            samples, sr = read_wav(info["path"])
            if index == 0:
                target_sr = sr
            samples = apply_fade(resample(samples, sr, target_sr), target_sr, fade_ms)
            length = duration_ms(samples, target_sr)
            entries.append(
                {
                    "id": chunk["id"],
                    "para": chunk["para"],
                    "display": chunk["display"],
                    "start_ms": cursor,
                    "end_ms": cursor + length,
                }
            )
            if not info.get("ok", True):
                warnings.append({"id": chunk["id"], "text": chunk["display"], "cer": info.get("cer"), "asr": info.get("asr")})
            pieces.append(samples)
            pause = silence(int(chunk["pause_after_ms"]), target_sr)
            pieces.append(pause)
            cursor += length + duration_ms(pause, target_sr)
            if (index + 1) % 20 == 0:
                log(f"  {index + 1}/{len(chunks)} chunk", "TTS")

        full = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)
        write_wav(out_wav, full, target_sr)
        timeline = {
            "audio_fp": audio_fp,
            "sample_rate": target_sr,
            "total_duration_ms": duration_ms(full, target_sr),
            "total_duration_sec": full.size / float(target_sr),
            "chunks": entries,
            "warnings": warnings,
        }
        write_json(timeline_path, timeline)
        if warnings:
            log(f"{len(warnings)} chunk vẫn có dấu hiệu đọc sai sau khi thử lại (xem report).", "Cảnh báo")
        log(f"Audio chương: {timeline['total_duration_sec']:.1f}s", "TTS")
        return timeline
