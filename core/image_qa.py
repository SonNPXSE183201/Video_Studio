"""Kiểm tra ảnh tự động bằng model thị giác (Ollama): đúng số người, đúng thời đại, khớp cảnh."""
from typing import Any, Dict

from core.ollama_client import OllamaClient

EXPECTED_PEOPLE = {"none": (0, 0), "single": (1, 1), "pair": (2, 2), "group": (3, 12), "crowd": (3, 99)}


class ImageQA:
    def __init__(self, ollama: OllamaClient, cfg: Dict[str, Any], style: Dict[str, Any], series: Dict[str, Any]):
        self.ollama = ollama
        self.cfg = cfg
        self.style = style
        self.series = series
        self.enabled = bool(cfg.get("enabled", True))
        self.min_score = int(cfg.get("min_score", 6))

    def available(self) -> bool:
        return self.enabled and self.ollama.has_model(self.ollama.vision_model)

    def review(self, image_path: str, scene: Dict[str, Any]) -> Dict[str, Any]:
        meta = scene["meta"]
        world = self.series.get("setting_en") or self.style.get("world_en", "")
        era = self.series.get("era_en") or ""
        system = (
            "You are a strict film continuity supervisor checking AI-generated stills. "
            "Look only at the image. Return strict JSON only."
        )
        prompt = (
            f"Intended world: {world}. Era: {era}.\n"
            f"Must avoid: {self.style.get('negative', '')}\n"
            f"Intended shot: {meta.get('subject_en', '')}. {meta.get('action_en', '')}\n"
            f"Intended number of people: {meta.get('population_mode')}\n\n"
            "Answer:\n"
            '{"people_count":0,"matches_scene":0,"anachronism":false,"anachronism_items":[],'
            '"deformed":false,"has_text":false,"issue_vi":"mô tả ngắn lỗi nếu có"}\n'
            "matches_scene is 0-10. anachronism = objects/clothing/buildings that do not belong "
            "to the intended world and era. deformed = broken anatomy, extra limbs, melted faces. "
            "has_text = visible letters, captions or watermark."
        )
        result = self.ollama.generate_json(
            prompt, system_prompt=system, images=[image_path], model=self.ollama.vision_model, temperature=0.1
        )
        if not isinstance(result, dict):
            return {"ok": True, "skipped": True, "reason": "VLM không trả lời"}
        reasons = []
        try:
            people = int(result.get("people_count", -1))
        except (TypeError, ValueError):
            people = -1
        low, high = EXPECTED_PEOPLE.get(meta.get("population_mode", "single"), (0, 99))
        if people >= 0 and not (low <= people <= high):
            reasons.append(f"số người {people} (cần {low}-{high})")
        try:
            score = float(result.get("matches_scene", 10))
        except (TypeError, ValueError):
            score = 10.0
        if score < self.min_score:
            reasons.append(f"không khớp cảnh ({score:.0f}/10)")
        if result.get("anachronism"):
            reasons.append("sai thời đại: " + ", ".join(map(str, result.get("anachronism_items", [])))[:120])
        if result.get("deformed"):
            reasons.append("dị dạng")
        if result.get("has_text") and self.cfg.get("reject_text", True):
            reasons.append("có chữ trong ảnh")
        return {
            "ok": not reasons,
            "score": score,
            "people": people,
            "reasons": reasons,
            "note": str(result.get("issue_vi", ""))[:200],
        }
