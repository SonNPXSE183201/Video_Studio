"""Chuyển động bằng Wan 2.2 qua ComfyUI.

- I2V: 14B (high/low noise + LightX2V 4 bước) hoặc 5B TI2V. Thiếu model 14B thì tự dùng 5B.
- Nối clip: clip sau bắt đầu từ khung cuối của clip trước -> phủ kín cảnh dài, hành động liên tục.
- S2V: Wan 2.2 S2V 14B, nhân vật nhép miệng theo audio thoại (graph theo template chính thức
  video_wan2_2_14B_s2v của ComfyUI: WanSoundImageToVideo + WanSoundImageToVideoExtend).
"""
import math
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from core.comfy_client import ComfyClient, ComfyError
from core.utils import log


class MotionGenerator:
    MODELS = ("wan22_14b", "wan22_5b")

    def __init__(self, comfy: ComfyClient, cfg: Dict[str, Any]):
        self.comfy = comfy
        self.cfg = cfg
        self.model = str(cfg.get("model", "auto"))
        self.lipsync = bool(cfg.get("lipsync", True))
        if self.model == "auto":
            from core.hardware import detect, pick_motion

            choice = pick_motion(cfg, detect())
            self.model = choice["model"]
            self.lipsync = self.lipsync and choice["lipsync"]
            log(f"Tự chọn theo cấu hình pod: {choice['reason']}", "Motion")
        self.ready: bool = False
        self.s2v_ready: bool = False
        self.problems: List[str] = []
        self.ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    # ------------------------------------------------------------ settings
    def _section(self, model: Optional[str] = None) -> Dict[str, Any]:
        return dict(self.cfg.get(model or self.model, {}) or {})

    def fps(self, model: Optional[str] = None) -> float:
        return float(self._section(model).get("fps", self.cfg.get("fps", 16)))

    def settings_fingerprint(self) -> Dict[str, Any]:
        return {"model": self.model, "cfg": self._section(), "frames": self.cfg.get("frames"), "fps": self.fps()}

    def s2v_fingerprint(self) -> Dict[str, Any]:
        return {"s2v": self.cfg.get("s2v", {}), "fps": self.cfg.get("s2v", {}).get("fps", 16)}

    def _dims(self, model: Optional[str] = None) -> Dict[str, int]:
        section = self._section(model)
        width = max(320, int(section.get("width", 832)) // 32 * 32)
        height = max(320, int(section.get("height", 480)) // 32 * 32)
        frames = max(17, int(section.get("frames", self.cfg.get("frames", 81))))
        return {"width": width, "height": height, "length": ((frames - 1) // 4) * 4 + 1}

    def clip_seconds(self) -> float:
        return self._dims()["length"] / self.fps()

    # -------------------------------------------------------------- graphs
    def build(self, image_name: str, prompt: str, negative: str, seed: int, model: Optional[str] = None) -> Dict[str, Any]:
        model = model or self.model
        if model == "wan22_14b":
            return self._wan14b(image_name, prompt, negative, seed)
        return self._wan5b(image_name, prompt, negative, seed)

    def _common(self, image_name: str, prompt: str, negative: str, section: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": section.get("text_encoder", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"), "type": "wan", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": section.get("vae")}},
            "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        }

    def _tail(self, samples_ref: List[Any], fps: float, vae_ref: Optional[List[Any]] = None) -> Dict[str, Any]:
        return {
            "30": {"class_type": "VAEDecode", "inputs": {"samples": samples_ref, "vae": vae_ref or ["3", 0]}},
            "31": {"class_type": "CreateVideo", "inputs": {"images": ["30", 0], "fps": float(fps)}},
            "32": {"class_type": "SaveVideo", "inputs": {"video": ["31", 0], "filename_prefix": "video/AIStudio", "format": "mp4", "codec": "h264"}},
        }

    def _wan5b(self, image_name: str, prompt: str, negative: str, seed: int) -> Dict[str, Any]:
        s = self._section("wan22_5b")
        d = self._dims("wan22_5b")
        graph = self._common(image_name, prompt, negative, {"vae": s.get("vae", "wan2.2_vae.safetensors"), **s})
        graph.update(
            {
                "1": {"class_type": "UNETLoader", "inputs": {"unet_name": s.get("diffusion_model", "wan2.2_ti2v_5B_fp16.safetensors"), "weight_dtype": "default"}},
                "7": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["3", 0], "start_image": ["4", 0], "batch_size": 1, **d}},
                "8": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": float(s.get("shift", 8.0))}},
                "9": {
                    "class_type": "KSampler",
                    "inputs": {
                        "model": ["8", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
                        "seed": int(seed), "steps": int(s.get("steps", 20)), "cfg": float(s.get("cfg", 5.0)),
                        "sampler_name": s.get("sampler", "uni_pc"), "scheduler": s.get("scheduler", "simple"), "denoise": 1.0,
                    },
                },
            }
        )
        graph.update(self._tail(["9", 0], self.fps("wan22_5b")))
        return graph

    def _wan14b(self, image_name: str, prompt: str, negative: str, seed: int) -> Dict[str, Any]:
        s = self._section("wan22_14b")
        d = self._dims("wan22_14b")
        steps = int(s.get("steps", 4))
        split = int(s.get("split_step", steps // 2))
        graph = self._common(image_name, prompt, negative, {"vae": s.get("vae", "wan_2.1_vae.safetensors"), **s})
        graph.update(
            {
                "10": {"class_type": "UNETLoader", "inputs": {"unet_name": s.get("high_noise_model"), "weight_dtype": "default"}},
                "11": {"class_type": "UNETLoader", "inputs": {"unet_name": s.get("low_noise_model"), "weight_dtype": "default"}},
                "12": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["10", 0], "lora_name": s.get("high_noise_lora"), "strength_model": 1.0}},
                "13": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["11", 0], "lora_name": s.get("low_noise_lora"), "strength_model": 1.0}},
                "14": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["12", 0], "shift": float(s.get("shift", 5.0))}},
                "15": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["13", 0], "shift": float(s.get("shift", 5.0))}},
                "16": {
                    "class_type": "WanImageToVideo",
                    "inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["3", 0], "start_image": ["4", 0], "batch_size": 1, **d},
                },
                "17": {
                    "class_type": "KSamplerAdvanced",
                    "inputs": {
                        "model": ["14", 0], "add_noise": "enable", "noise_seed": int(seed), "steps": steps,
                        "cfg": float(s.get("cfg", 1.0)), "sampler_name": s.get("sampler", "euler"), "scheduler": s.get("scheduler", "simple"),
                        "positive": ["16", 0], "negative": ["16", 1], "latent_image": ["16", 2],
                        "start_at_step": 0, "end_at_step": split, "return_with_leftover_noise": "enable",
                    },
                },
                "18": {
                    "class_type": "KSamplerAdvanced",
                    "inputs": {
                        "model": ["15", 0], "add_noise": "disable", "noise_seed": int(seed), "steps": steps,
                        "cfg": float(s.get("cfg", 1.0)), "sampler_name": s.get("sampler", "euler"), "scheduler": s.get("scheduler", "simple"),
                        "positive": ["16", 0], "negative": ["16", 1], "latent_image": ["17", 0],
                        "start_at_step": split, "end_at_step": 10000, "return_with_leftover_noise": "disable",
                    },
                },
            }
        )
        graph.update(self._tail(["18", 0], self.fps("wan22_14b")))
        return graph

    def build_s2v(self, image_name: str, audio_name: str, prompt: str, negative: str, seed: int, chunks: int) -> Dict[str, Any]:
        """Wan 2.2 S2V: đoạn đầu 'chunk_frames' khung, mỗi đoạn nối thêm cùng độ dài (nhép miệng theo audio)."""
        s = dict(self.cfg.get("s2v", {}) or {})
        chunk = int(s.get("chunk_frames", 77))
        width = max(320, int(s.get("width", 832)) // 32 * 32)
        height = max(320, int(s.get("height", 480)) // 32 * 32)
        sampler = {
            "steps": int(s.get("steps", 4)), "cfg": float(s.get("cfg", 1.0)),
            "sampler_name": s.get("sampler", "uni_pc"), "scheduler": s.get("scheduler", "simple"), "denoise": 1.0,
        }
        model_ref: List[Any] = ["1", 0]
        graph: Dict[str, Any] = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": s.get("model", "wan2.2_s2v_14B_fp8_scaled.safetensors"), "weight_dtype": "default"}},
        }
        if s.get("lora"):
            graph["2"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": s["lora"], "strength_model": float(s.get("lora_strength", 1.0))}}
            model_ref = ["2", 0]
        graph.update(
            {
                "3": {"class_type": "ModelSamplingSD3", "inputs": {"model": model_ref, "shift": float(s.get("shift", 8.0))}},
                "4": {"class_type": "CLIPLoader", "inputs": {"clip_name": s.get("text_encoder", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"), "type": "wan", "device": "default"}},
                "5": {"class_type": "VAELoader", "inputs": {"vae_name": s.get("vae", "wan_2.1_vae.safetensors")}},
                "6": {"class_type": "AudioEncoderLoader", "inputs": {"audio_encoder_name": s.get("audio_encoder", "wav2vec2_large_english_fp16.safetensors")}},
                "7": {"class_type": "LoadAudio", "inputs": {"audio": audio_name}},
                "8": {"class_type": "AudioEncoderEncode", "inputs": {"audio_encoder": ["6", 0], "audio": ["7", 0]}},
                "9": {"class_type": "LoadImage", "inputs": {"image": image_name}},
                "10": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": prompt}},
                "11": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": negative}},
                "12": {
                    "class_type": "WanSoundImageToVideo",
                    "inputs": {
                        "positive": ["10", 0], "negative": ["11", 0], "vae": ["5", 0], "audio_encoder_output": ["8", 0],
                        "ref_image": ["9", 0], "width": width, "height": height, "length": chunk, "batch_size": 1,
                    },
                },
                "13": {
                    "class_type": "KSampler",
                    "inputs": {"model": ["3", 0], "positive": ["12", 0], "negative": ["12", 1], "latent_image": ["12", 2], "seed": int(seed), **sampler},
                },
            }
        )
        latent: List[Any] = ["13", 0]
        for k in range(1, max(1, chunks)):
            ext, smp, cat = str(100 + 3 * k), str(101 + 3 * k), str(102 + 3 * k)
            graph[ext] = {
                "class_type": "WanSoundImageToVideoExtend",
                "inputs": {
                    "positive": ["10", 0], "negative": ["11", 0], "vae": ["5", 0], "video_latent": latent,
                    "audio_encoder_output": ["8", 0], "ref_image": ["9", 0], "length": chunk,
                },
            }
            graph[smp] = {
                "class_type": "KSampler",
                "inputs": {"model": ["3", 0], "positive": [ext, 0], "negative": [ext, 1], "latent_image": [ext, 2], "seed": int(seed), **sampler},
            }
            graph[cat] = {"class_type": "LatentConcat", "inputs": {"samples1": latent, "samples2": [smp, 0], "dim": "t"}}
            latent = [cat, 0]
        # Như template: nhân đôi latent đầu rồi bỏ 3 ảnh đầu sau khi giải mã (VAE nhân quả).
        graph["20"] = {"class_type": "LatentCut", "inputs": {"samples": latent, "dim": "t", "index": 0, "amount": 1}}
        graph["21"] = {"class_type": "LatentConcat", "inputs": {"samples1": ["20", 0], "samples2": latent, "dim": "t"}}
        graph["22"] = {"class_type": "VAEDecode", "inputs": {"samples": ["21", 0], "vae": ["5", 0]}}
        graph["23"] = {"class_type": "ImageFromBatch", "inputs": {"image": ["22", 0], "batch_index": 3, "length": 4096}}
        graph["24"] = {"class_type": "CreateVideo", "inputs": {"images": ["23", 0], "fps": float(s.get("fps", 16))}}
        graph["25"] = {"class_type": "SaveVideo", "inputs": {"video": ["24", 0], "filename_prefix": "video/AIStudioS2V", "format": "mp4", "codec": "h264"}}
        return graph

    # ------------------------------------------------------------- prepare
    def prepare(self) -> bool:
        order = [self.model] + [m for m in self.MODELS if m != self.model]
        self.problems = []
        for model in order:
            try:
                problems = self.comfy.missing_requirements(self.build("x.png", "t", "t", 1, model))
            except Exception as exc:
                problems = [str(exc)]
            if not problems:
                if model != self.model:
                    log(f"Motion '{self.model}' thiếu model, dùng '{model}'.", "Motion")
                self.model = model
                self.ready = True
                break
            self.problems.extend(problems)
            log(f"Motion '{model}' chưa dùng được: {'; '.join(problems[:3])}", "Motion")
        if not self.ready:
            log("Không có model chuyển động nào dùng được: toàn bộ cảnh dùng Ken Burns.", "Motion")
        if (self.cfg.get("s2v") or {}).get("enabled", True) and self.lipsync:
            try:
                problems = self.comfy.missing_requirements(self.build_s2v("x.png", "a.wav", "t", "t", 1, 2))
                problems = [p for p in problems if "LoadImage" not in p and "LoadAudio" not in p]
            except Exception as exc:
                problems = [str(exc)]
            self.s2v_ready = not problems
            if problems:
                log(f"Nhép miệng (S2V) chưa dùng được: {'; '.join(problems[:3])}. Cảnh thoại dùng I2V.", "Motion")
        return self.ready

    # ------------------------------------------------------------ generate
    def _ff(self, args: List[str]) -> None:
        res = subprocess.run([self.ffmpeg, "-y", "-v", "error"] + args, capture_output=True, text=True)
        if res.returncode != 0:
            raise ComfyError(f"ffmpeg lỗi: {res.stderr[-300:]}")

    def _last_frame(self, clip: str, out_png: str) -> str:
        self._ff(["-sseof", "-0.2", "-i", clip, "-update", "1", "-frames:v", "1", out_png])
        return out_png

    def _concat(self, parts: List[str], out: str) -> None:
        """Nối các clip, bỏ khung đầu của clip sau (trùng khung cuối clip trước)."""
        if len(parts) == 1:
            shutil.copyfile(parts[0], out)
            return
        args: List[str] = []
        chains = []
        for i, part in enumerate(parts):
            args += ["-i", part]
            start = 0 if i == 0 else 1
            chains.append(f"[{i}:v]trim=start_frame={start},setpts=PTS-STARTPTS[v{i}]")
        graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
        self._ff(args + ["-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p", out])

    def generate(self, image_path: str, prompt: str, negative: str, seed: int, output_path: str) -> bool:
        """Một clip từ một ảnh (tương thích cách gọi cũ)."""
        if not self.ready:
            return False
        try:
            name = self.comfy.upload_image(image_path)
            graph = self.build(name, prompt, negative, seed)
            self.comfy.run(graph, output_path, timeout=int(self.cfg.get("timeout_seconds", 1500)))
            return True
        except (ComfyError, Exception) as exc:
            log(f"Không tạo được clip: {exc}", "Motion")
            return False

    def clips_needed(self, seconds: float) -> int:
        slow = float(self.cfg.get("max_slowdown", 1.2))
        cap = int(self.cfg.get("max_clips_per_scene", 4))
        return max(1, min(cap, math.ceil(seconds / (self.clip_seconds() * slow) - 1e-6)))

    def generate_chain(self, image_path: str, prompts: List[str], negative: str, seed: int, seconds: float, output_path: str) -> bool:
        """Nhiều clip nối tiếp (clip sau bắt đầu từ khung cuối clip trước) đủ phủ 'seconds'."""
        if not self.ready:
            return False
        prompts = [p for p in prompts if p] or ["subtle natural movement"]
        count = self.clips_needed(seconds) if self.cfg.get("chain", True) else 1
        work = output_path + ".parts"
        os.makedirs(work, exist_ok=True)
        parts: List[str] = []
        start = image_path
        for k in range(count):
            part = os.path.join(work, f"part_{k}.mp4")
            if not self.generate(start, prompts[min(k, len(prompts) - 1)], negative, seed + k * 7919, part):
                break
            parts.append(part)
            if k + 1 < count:
                try:
                    start = self._last_frame(part, os.path.join(work, f"last_{k}.png"))
                except ComfyError as exc:
                    log(f"Không lấy được khung cuối: {exc}", "Motion")
                    break
        if not parts:
            return False
        try:
            self._concat(parts, output_path)
        except ComfyError as exc:
            log(f"Không nối được clip: {exc}", "Motion")
            shutil.copyfile(parts[0], output_path)
        shutil.rmtree(work, ignore_errors=True)
        return True

    def generate_s2v(self, image_path: str, audio_path: str, prompt: str, negative: str, seed: int, output_path: str) -> bool:
        """Nhân vật nhép miệng theo audio (audio đã tắt tiếng các đoạn dẫn truyện)."""
        if not self.s2v_ready:
            return False
        try:
            import soundfile as sf

            info = sf.info(audio_path)
            seconds = info.frames / float(info.samplerate)
            s = self.cfg.get("s2v", {}) or {}
            chunk = int(s.get("chunk_frames", 77))
            chunks = max(1, min(int(s.get("max_chunks", 8)), math.ceil(seconds * float(s.get("fps", 16)) / chunk)))
            image_name = self.comfy.upload_image(image_path)
            audio_name = self.comfy.upload_image(audio_path)
            graph = self.build_s2v(image_name, audio_name, prompt, negative, seed, chunks)
            self.comfy.run(graph, output_path, timeout=int(self.cfg.get("timeout_seconds", 1500)) * chunks)
            return True
        except Exception as exc:
            log(f"Không tạo được clip nhép miệng: {exc}", "Motion")
            return False
