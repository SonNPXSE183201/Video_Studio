"""Ollama client: JSON có retry, context đủ dài, hỗ trợ model thị giác, giải phóng VRAM."""
import base64
import io
import json
import re
import time
from typing import Any, Dict, List, Optional

import requests

from core.utils import log


class OllamaClient:
    def __init__(self, cfg: Dict[str, Any]):
        self.host = str(cfg.get("host", "http://127.0.0.1:11434")).rstrip("/")
        self.model = cfg.get("model", "qwen2.5:14b")
        self.vision_model = cfg.get("vision_model", "qwen2.5vl:7b")
        self.timeout = int(cfg.get("timeout_seconds", 300))
        self.retries = max(0, int(cfg.get("retries", 2)))
        self.temperature = float(cfg.get("temperature", 0.2))
        # Mặc định Ollama chỉ 2048-4096 token -> prompt dài bị cắt cụt âm thầm.
        self.num_ctx = int(cfg.get("num_ctx", 16384))

    def health(self) -> bool:
        try:
            return requests.get(f"{self.host}/api/version", timeout=5).status_code == 200
        except Exception:
            return False

    def installed_models(self) -> List[str]:
        try:
            data = requests.get(f"{self.host}/api/tags", timeout=10).json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def has_model(self, name: str) -> bool:
        names = self.installed_models()
        return name in names or f"{name}:latest" in names

    def unload_all(self) -> None:
        try:
            loaded = requests.get(f"{self.host}/api/ps", timeout=10).json().get("models", [])
        except Exception:
            loaded = [{"name": self.model}, {"name": self.vision_model}]
        for item in loaded:
            name = item.get("name") or item.get("model")
            if not name:
                continue
            try:
                requests.post(
                    f"{self.host}/api/generate",
                    json={"model": name, "keep_alive": 0},
                    timeout=60,
                )
            except Exception:
                pass

    @staticmethod
    def _parse_json(text: str) -> Optional[Any]:
        text = (text or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
        return None

    @staticmethod
    def encode_image(path: str, max_side: int = 896) -> str:
        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=88)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        images: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Optional[Any]:
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "top_p": 0.9,
                "num_ctx": self.num_ctx,
            },
            "keep_alive": "10m",
        }
        if images:
            payload["images"] = [self.encode_image(p) for p in images]

        for attempt in range(self.retries + 1):
            try:
                res = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
                if res.status_code != 200:
                    log(f"Ollama HTTP {res.status_code}: {res.text[:200]}", "LLM")
                else:
                    parsed = self._parse_json(res.json().get("response", ""))
                    if parsed is not None:
                        return parsed
                    log("Ollama trả JSON hỏng.", "LLM")
            except Exception as exc:
                log(f"Ollama lỗi: {exc}", "LLM")
            if attempt < self.retries:
                payload["options"]["temperature"] = min(0.7, payload["options"]["temperature"] + 0.15)
                time.sleep(2 + attempt * 3)
        return None
