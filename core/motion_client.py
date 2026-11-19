"""Image-to-video bằng Wan 2.2 qua ComfyUI (5B TI2V hoặc 14B I2V + LightX2V)."""
from typing import Any, Dict, List

from core.comfy_client import ComfyClient, ComfyError
from core.utils import log


class MotionGenerator:
    def __init__(self, comfy: ComfyClient, cfg: Dict[str, Any]):
        self.comfy = comfy
        self.cfg = cfg
        self.model = str(cfg.get("model", "wan22_5b"))
        self.ready: bool = False
        self.problems: List[str] = []

    def settings_fingerprint(self) -> Dict[str, Any]:
        return {"model": self.model, "cfg": self.cfg.get(self.model, {}), "frames": self.cfg.get("frames"), "fps": self.cfg.get("fps")}

    def _dims(self) -> Dict[str, int]:
        section = self.cfg.get(self.model, {}) or {}
        width = max(320, int(section.get("width", 1024)) // 32 * 32)
        height = max(320, int(section.get("height", 576)) // 32 * 32)
        frames = max(17, int(self.cfg.get("frames", 97)))
        return {"width": width, "height": height, "length": ((frames - 1) // 4) * 4 + 1}

    def build(self, image_name: str, prompt: str, negative: str, seed: int) -> Dict[str, Any]:
        return self._wan14b(image_name, prompt, negative, seed) if self.model == "wan22_14b" else self._wan5b(image_name, prompt, negative, seed)

    def _common(self, image_name: str, prompt: str, negative: str, section: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": section.get("text_encoder", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"), "type": "wan", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": section.get("vae")}},
            "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
            "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        }

    def _tail(self, samples_ref: List[Any]) -> Dict[str, Any]:
        return {
            "30": {"class_type": "VAEDecode", "inputs": {"samples": samples_ref, "vae": ["3", 0]}},
            "31": {"class_type": "CreateVideo", "inputs": {"images": ["30", 0], "fps": float(self.cfg.get("fps", 24))}},
            "32": {"class_type": "SaveVideo", "inputs": {"video": ["31", 0], "filename_prefix": "video/AIStudio", "format": "mp4", "codec": "h264"}},
        }

    def _wan5b(self, image_name: str, prompt: str, negative: str, seed: int) -> Dict[str, Any]:
        s = self.cfg.get("wan22_5b", {}) or {}
        d = self._dims()
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
        graph.update(self._tail(["9", 0]))
        return graph

    def _wan14b(self, image_name: str, prompt: str, negative: str, seed: int) -> Dict[str, Any]:
        s = self.cfg.get("wan22_14b", {}) or {}
        d = self._dims()
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
        graph.update(self._tail(["18", 0]))
        return graph

    def prepare(self) -> bool:
        try:
            problems = self.comfy.missing_requirements(self.build("x.png", "t", "t", 1))
        except Exception as exc:
            problems = [str(exc)]
        self.problems = problems
        self.ready = not problems
        if problems:
            log(f"Motion '{self.model}' chưa dùng được: {'; '.join(problems[:4])}. Dùng Ken Burns.", "Motion")
        return self.ready

    def generate(self, image_path: str, prompt: str, negative: str, seed: int, output_path: str) -> bool:
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
