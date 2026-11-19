"""Đạo diễn hình ảnh: Story Bible, chia cảnh, phân tích cảnh bằng LLM, ghép prompt.

Kết quả LLM (meta) được cache; prompt được ghép lại mỗi lần chạy từ meta + Bible +
overrides, nên sửa Bible/overrides có hiệu lực ngay mà không phải gọi lại LLM.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional

from core.character_registry import CharacterRegistry
from core.location_registry import LocationRegistry
from core.ollama_client import OllamaClient
from core.utils import fingerprint, log


class SceneDirector:
    VERSION = 6
    VALID_SHOTS = {"close_up", "medium_shot", "wide_shot", "action_shot", "over_shoulder", "insert"}
    VALID_POPULATIONS = {"none", "single", "pair", "group", "crowd"}
    VALID_TIMES = {"day", "night", "dawn", "dusk", "indoor"}

    def __init__(
        self,
        ollama: OllamaClient,
        characters: CharacterRegistry,
        locations: LocationRegistry,
        style: Dict[str, Any],
        art: Dict[str, Any],
        series: Dict[str, Any],
        cfg: Dict[str, Any],
    ):
        self.ollama = ollama
        self.chars = characters
        self.locs = locations
        self.style = style
        self.art = art
        self.series = series
        self.cfg = cfg
        self.batch_size = max(1, int(cfg.get("batch_size", 6)))
        self.max_visible = max(1, int(cfg.get("max_visible_characters", 2)))
        self.allow_crowds = bool(cfg.get("allow_crowds", False))

    # ----------------------------------------------------------- fingerprint
    def fingerprint(self, chapter_text: str) -> str:
        return fingerprint(
            self.VERSION,
            chapter_text,
            {k: self.style.get(k) for k in ("id", "world_en", "director_rules_en", "props_en", "location_rules_en")},
            self.series.get("era_en"),
            self.series.get("setting_en"),
            {k: self.cfg.get(k) for k in ("batch_size", "scene_target_chars", "scene_max_chars", "max_visible_characters", "allow_crowds")},
            self.ollama.model,
        )

    def _world_brief(self) -> str:
        parts = [
            f"World: {self.series.get('setting_en') or self.style.get('world_en', '')}",
            f"Era: {self.series.get('era_en') or 'as implied by the genre'}",
            f"Rules: {self.style.get('director_rules_en', '')}",
            f"Typical props: {self.style.get('props_en', '')}",
            f"Clothing: {self.style.get('character_rules_en', '')}",
            f"Places: {self.style.get('location_rules_en', '')}",
        ]
        return "\n".join(p for p in parts if p.split(":", 1)[1].strip())

    # --------------------------------------------------------- story bible
    @staticmethod
    def _windows(paragraphs: List[str], max_chars: int) -> List[str]:
        windows, current = [], ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 1 > max_chars:
                windows.append(current)
                current = ""
            current = f"{current}\n{paragraph}".strip()
        if current:
            windows.append(current)
        return windows

    def discover_bible(self, paragraphs: List[str], chapter: int) -> None:
        system = (
            "You are the continuity editor of a film adaptation of a Vietnamese web novel. "
            "Build a persistent bible of people and places. Reuse an existing id when a name or "
            "alias matches; resolve titles and nicknames to one identity. Do not invent facts the "
            "text contradicts, but when appearance is unstated, propose a plausible look that "
            "fits the role, age and world, then keep it stable. Ignore animals and objects. "
            "Write visual descriptions in concise concrete English. Return strict JSON only.\n"
            + self._world_brief()
        )
        scan_chars = max(2000, int(self.cfg.get("character_scan_chars", 9000)))
        touched_chars, touched_locs = set(), set()
        for index, window in enumerate(self._windows(paragraphs, scan_chars), start=1):
            prompt = (
                f"CHAPTER {chapter}, PART {index}\n"
                f"KNOWN CHARACTERS:\n{self.chars.build_llm_context(80) or '(none)'}\n\n"
                f"KNOWN LOCATIONS:\n{self.locs.build_llm_context(40) or '(none)'}\n\n"
                f"STORY TEXT:\n{window}\n\n"
                "Return:\n"
                '{"characters":[{"id":"existing_id_or_empty","canonical_name":"Vietnamese name",'
                '"aliases":["other names/titles"],"gender":"male|female|unknown",'
                '"role":"main|supporting|minor","age_en":"e.g. early 20s",'
                '"appearance_en":"permanent face, hair, build, skin, distinctive marks",'
                '"outfit_en":"clothes in this part, matching the world and era"}],'
                '"locations":[{"id":"existing_id_or_empty","name":"Vietnamese place name",'
                '"aliases":[],"description_en":"stable visual description: architecture, '
                'materials, layout, light"}]}'
            )
            result = self.ollama.generate_json(prompt, system_prompt=system)
            if not isinstance(result, dict):
                log(f"Không quét được Bible phần {index}.", "Cảnh báo")
                continue
            for profile in result.get("characters") or []:
                if isinstance(profile, dict):
                    char_id = self.chars.upsert_from_analysis(profile, chapter)
                    if char_id:
                        touched_chars.add(char_id)
            for profile in result.get("locations") or []:
                if isinstance(profile, dict):
                    loc_id = self.locs.upsert(profile, chapter)
                    if loc_id:
                        touched_locs.add(loc_id)
        self.chars.save()
        self.locs.save()
        log(f"Bible chương {chapter}: {len(touched_chars)} nhân vật, {len(touched_locs)} địa điểm.", "Đạo diễn")

    # ---------------------------------------------------------- scene split
    @staticmethod
    def group_scenes(chunks: List[Dict[str, Any]], target_chars: int = 230, max_chars: int = 360) -> List[Dict[str, Any]]:
        scenes: List[Dict[str, Any]] = []
        current: List[Dict[str, Any]] = []
        length = 0

        def close() -> None:
            nonlocal current, length
            if current:
                scenes.append(
                    {
                        "index": len(scenes) + 1,
                        "chunk_ids": [c["id"] for c in current],
                        "text": " ".join(c["display"] for c in current),
                    }
                )
            current, length = [], 0

        for chunk in chunks:
            size = len(chunk["display"])
            new_paragraph = bool(current) and chunk["para"] != current[-1]["para"]
            title_only = bool(current) and all(c.get("is_title") for c in current)
            if current and not title_only and (
                length + size > max_chars or (new_paragraph and length >= target_chars)
            ):
                close()
            current.append(chunk)
            length += size
        close()
        return scenes

    # ------------------------------------------------------------ directing
    def _system_prompt(self) -> str:
        crowd_rule = (
            "Crowds are allowed when essential."
            if self.allow_crowds
            else "Avoid crowds: show one representative subject or a wide environment shot."
        )
        return (
            "You are the director of photography adapting a Vietnamese web novel into a film. "
            "For each scene decide what the camera actually shows, grounded in the text and the "
            "world rules below.\n" + self._world_brief() + "\n"
            "Rules: identify the acting character from grammar, dialogue attribution and context. "
            "Show the person speaking or acting, not everyone mentioned. Prefer one focal character; "
            f"at most {self.max_visible} named characters. {crowd_rule} Places, objects and "
            "establishing shots use population_mode=none. Keep continuity: if the text does not "
            "change place, reuse the previous location_id and time_of_day. Use only character ids "
            "and location ids from the bible; for a new place leave location_id empty and describe "
            "it in location_en. Every *_en field must be concrete visible description (people, "
            "pose, expression, objects, materials, light), never style words, never abstract plot. "
            "motion_en: subtle 4-second movement (breathing, hair, cloth, smoke, water, light); "
            "camera_motion_en: one slow camera move. motion_priority 0-3: 3 = action or strong "
            "emotion that benefits from animation, 0 = static. Return strict JSON only."
        )

    def _relevant_character_ids(self, text: str, recent: List[str]) -> List[str]:
        ids = self.chars.identify_characters_in_text(text)
        for char_id in recent:
            if char_id not in ids:
                ids.append(char_id)
        mains = [
            k for k, v in self.chars.characters.items()
            if any(t in str(v.get("vai_tro", "")).casefold() for t in ("main", "chính"))
        ]
        for char_id in mains:
            if char_id not in ids:
                ids.append(char_id)
        return ids[:25]

    def _ask_batch(self, batch: List[Dict[str, Any]], chapter: int, history: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        text = " ".join(s["text"] for s in batch)
        recent_ids = [h["focus"] for h in history[-3:] if h.get("focus")]
        char_ids = self._relevant_character_ids(text, recent_ids)
        payload = [{"scene_index": s["index"], "text": s["text"]} for s in batch]
        prompt = (
            f"CHAPTER {chapter}\n"
            f"CHARACTER BIBLE:\n{self.chars.build_llm_context(25, char_ids) or '(none)'}\n\n"
            f"LOCATION BIBLE:\n{self.locs.build_llm_context(60) or '(none)'}\n\n"
            f"PREVIOUS SCENES: {json.dumps(history[-2:], ensure_ascii=False) if history else 'none'}\n\n"
            f"SCENES:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "Return one result per scene:\n"
            '{"scenes":[{"scene_index":1,"visual_type":"character|dialogue|action|environment|object|creature",'
            '"population_mode":"none|single|pair|group|crowd","visible_character_ids":["id"],'
            '"focus_character_id":"id or empty","subject_en":"who/what is seen and composition",'
            '"action_en":"visible action","expression_en":"facial expression or empty",'
            '"location_id":"bible id or empty","location_en":"visible environment",'
            '"time_of_day":"day|night|dawn|dusk|indoor","mood_en":"lighting mood",'
            '"shot_type":"close_up|medium_shot|wide_shot|action_shot|over_shoulder|insert",'
            '"motion_en":"subtle movement","camera_motion_en":"slow camera move","motion_priority":0}]}'
        )
        response = self.ollama.generate_json(prompt, system_prompt=self._system_prompt())
        parsed: Dict[int, Dict[str, Any]] = {}
        if isinstance(response, dict) and isinstance(response.get("scenes"), list):
            for item in response["scenes"]:
                if isinstance(item, dict):
                    try:
                        parsed[int(item.get("scene_index"))] = item
                    except (TypeError, ValueError):
                        continue
        return parsed

    def direct(self, scenes: List[Dict[str, Any]], chapter: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        history: List[Dict[str, Any]] = []
        previous: Dict[str, Any] = {}
        total = len(scenes)
        for start in range(0, total, self.batch_size):
            batch = scenes[start : start + self.batch_size]
            parsed = self._ask_batch(batch, chapter, history)
            missing = [s for s in batch if s["index"] not in parsed]
            if missing and len(batch) > 1:
                # Thử lại từng nửa nhỏ hơn trước khi chấp nhận fallback.
                half = max(1, len(missing) // 2)
                for part in (missing[:half], missing[half:]):
                    if part:
                        parsed.update(self._ask_batch(part, chapter, history))
            for scene in batch:
                raw = parsed.get(scene["index"])
                meta = self._validate(scene, raw or {}, previous)
                meta["fallback"] = raw is None
                if raw is None:
                    log(f"Cảnh {scene['index']}: LLM không trả kết quả, dùng suy luận dự phòng.", "Cảnh báo")
                results.append({**scene, "meta": meta})
                previous = meta
                history.append(
                    {
                        "scene_index": scene["index"],
                        "focus": meta.get("focus_character_id"),
                        "location_id": meta.get("location_id"),
                        "subject": meta.get("subject_en", "")[:120],
                    }
                )
            log(f"Đã đạo diễn {min(start + self.batch_size, total)}/{total} cảnh", "Đạo diễn")
        return results

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _validate(self, scene: Dict[str, Any], ai: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
        visual_type = str(ai.get("visual_type") or "").lower()
        population = str(ai.get("population_mode") or "").lower()
        population = population if population in self.VALID_POPULATIONS else ""

        visible: List[str] = []
        for raw in self._as_list(ai.get("visible_character_ids")):
            if isinstance(raw, dict):
                raw = raw.get("id") or raw.get("name")
            char_id = self.chars.resolve_character(raw)
            if char_id and char_id not in visible:
                visible.append(char_id)
        focus = self.chars.resolve_character(ai.get("focus_character_id"))
        if focus and focus not in visible:
            visible.insert(0, focus)
        if not visible and (not ai or visual_type in {"character", "dialogue", "action"}):
            visible = self.chars.identify_characters_in_text(scene["text"])[:1]

        if population == "none" or visual_type in {"environment", "object", "creature"}:
            visible, population = [], "none"
        elif population in {"group", "crowd"} and self.allow_crowds:
            visible = visible[: self.max_visible]
        else:
            visible = visible[: self.max_visible]
            population = {0: "none", 1: "single"}.get(len(visible), "pair")
            if population == "none" and ai.get("population_mode") == "single":
                population = "single"  # người không tên nhưng có mặt
        if focus not in visible:
            focus = visible[0] if visible else None

        loc_id = self.locs.resolve(ai.get("location_id"))
        location_en = str(ai.get("location_en") or "").strip()
        if not loc_id and not location_en:
            loc_id = previous.get("location_id")
            location_en = previous.get("location_en", "")
        time_of_day = str(ai.get("time_of_day") or "").lower()
        if time_of_day not in self.VALID_TIMES:
            time_of_day = previous.get("time_of_day", "day")
        shot = str(ai.get("shot_type") or "medium_shot")
        shot = shot if shot in self.VALID_SHOTS else "medium_shot"
        try:
            priority = max(0, min(3, int(ai.get("motion_priority", 1))))
        except (TypeError, ValueError):
            priority = 1

        return {
            "visual_type": visual_type or "story_moment",
            "population_mode": population,
            "visible_character_ids": visible,
            "focus_character_id": focus,
            "subject_en": str(ai.get("subject_en") or "").strip(),
            "action_en": str(ai.get("action_en") or "").strip(),
            "expression_en": str(ai.get("expression_en") or "").strip(),
            "location_id": loc_id,
            "location_en": location_en,
            "time_of_day": time_of_day,
            "mood_en": str(ai.get("mood_en") or "").strip(),
            "shot_type": shot,
            "motion_en": str(ai.get("motion_en") or "").strip(),
            "camera_motion_en": str(ai.get("camera_motion_en") or "").strip(),
            "motion_priority": priority,
        }

    # ------------------------------------------------------- prompt compile
    def _guards(self, text: str) -> List[str]:
        lowered = text.casefold()
        found = []
        for guard in self.style.get("context_guards") or []:
            try:
                if re.search(str(guard.get("pattern", "")), lowered):
                    found.append(str(guard.get("en", "")).strip())
            except re.error:
                continue
        return [g for g in found if g]

    def _population_phrase(self, population: str, ids: List[str]) -> str:
        if population == "none":
            return "no people, environment or object focus"
        if population == "single":
            gender = self.chars.get_gender(ids[0]) if ids else "unknown"
            noun = {"male": "man", "female": "woman"}.get(gender, "person")
            return f"exactly one {noun}, single subject"
        if population == "pair":
            return "exactly two different people, clearly separated, distinct faces"
        return "a small group of distinct people"

    def compile(
        self,
        directed: List[Dict[str, Any]],
        chapter: int,
        override_for: Optional[Callable[[int], Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        compiled = []
        for scene in directed:
            meta = dict(scene["meta"])
            override = override_for(scene["index"]) if override_for else {}
            if override.get("characters") is not None:
                ids = [cid for cid in (self.chars.resolve_character(c) for c in override["characters"]) if cid]
                meta["visible_character_ids"] = ids
                meta["population_mode"] = {0: "none", 1: "single"}.get(len(ids), "pair")
                meta["focus_character_id"] = ids[0] if ids else None
            for key in ("subject_en", "action_en", "location_en", "shot_type", "time_of_day", "mood_en", "motion_en"):
                if override.get(key):
                    meta[key] = override[key]
            if override.get("location_id"):
                meta["location_id"] = self.locs.resolve(override["location_id"]) or meta.get("location_id")

            ids = meta["visible_character_ids"]
            parts: List[str] = [self._population_phrase(meta["population_mode"], ids)]
            subject = meta.get("subject_en") or "a cinematic moment from the story"
            parts.append(subject)
            for key in ("action_en", "expression_en"):
                value = meta.get(key)
                if value and value.casefold() not in subject.casefold():
                    parts.append(value)
            positions = ["on the left", "on the right"] if len(ids) == 2 else [""]
            for index, char_id in enumerate(ids):
                identity = self.chars.get_character_prompt(char_id, chapter)
                if identity:
                    where = positions[index] if index < len(positions) else ""
                    parts.append(f"{('person ' + where).strip()}: {identity}")
            location = self.locs.description(meta.get("location_id")) or meta.get("location_en", "")
            if location:
                parts.append(f"setting: {location}")
            light = f"{meta.get('time_of_day', 'day')} lighting"
            if meta.get("mood_en"):
                light += f", {meta['mood_en']}"
            parts.append(light)
            parts.extend(self._guards(scene["text"]))
            framing = (self.style.get("shot_framing") or {}).get(meta["shot_type"], "")
            if framing:
                parts.append(framing)
            parts.append(self.series.get("era_en") or self.style.get("world_en", ""))
            if override.get("extra_en"):
                parts.append(str(override["extra_en"]))
            parts.append(self.art.get("positive", ""))
            positive = override.get("prompt") or ", ".join(p.strip() for p in parts if p and p.strip())

            negative = ", ".join(
                p.strip()
                for p in (
                    self.art.get("negative", ""),
                    self.style.get("negative", ""),
                    self.style.get("anatomy_negative", ""),
                    (self.style.get("population_negative") or {}).get(meta["population_mode"], ""),
                )
                if p and p.strip()
            )
            motion_parts = [
                self.art.get("motion_style", ""),
                self.style.get("motion_prefix_en", ""),
                subject,
                meta.get("action_en", ""),
                meta.get("motion_en") or "subtle natural movement, breathing, hair and cloth moving slightly",
                meta.get("camera_motion_en") or "slow cinematic push-in",
                "keep the exact faces, clothing, colors and composition of the first frame, no new people",
            ]
            motion_prompt = ". ".join(p.strip(" .") for p in motion_parts if p and p.strip())
            motion_negative = ", ".join(
                p for p in (
                    self.style.get("motion_negative", ""),
                    (self.style.get("population_negative") or {}).get(meta["population_mode"], ""),
                ) if p
            )
            refs = [self.chars.get_reference_image(cid) for cid in ids]
            refs = [r for r in refs if r][:2] if len([r for r in refs if r]) == len(ids) else []
            compiled.append(
                {
                    **scene,
                    "meta": meta,
                    "positive": positive,
                    "negative": negative,
                    "motion_prompt": motion_prompt,
                    "motion_negative": motion_negative,
                    "reference_images": refs,
                    "motion_override": override.get("motion"),
                    "seed": int(fingerprint(chapter, scene["index"]), 16) % 2_147_483_000 + 1,
                }
            )
        return compiled
