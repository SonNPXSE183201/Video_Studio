import hashlib
import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional


class CharacterRegistry:
    """Persistent character bible populated from the story, not from Python rules."""

    def __init__(self, filepath: str = "data/characters.json"):
        self.filepath = filepath
        self.characters: Dict[str, Dict[str, Any]] = {}
        self.alias_map: Dict[str, str] = {}
        self.load()

    @staticmethod
    def _normalise(value: str) -> str:
        value = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
        return re.sub(r"\s+", " ", value)

    @classmethod
    def make_character_id(cls, name: str) -> str:
        ascii_name = unicodedata.normalize("NFKD", str(name or ""))
        ascii_name = "".join(c for c in ascii_name if not unicodedata.combining(c))
        slug = re.sub(r"[^a-z0-9]+", "", ascii_name.casefold())
        if not slug:
            slug = "character"
        return slug[:48]

    POPULATION_TOKENS = {
        "solo", "1man", "1woman", "1girl", "1boy", "2men", "2women",
        "single male focus", "single female focus", "single person",
    }

    @classmethod
    def clean_visual(cls, text: str) -> str:
        """Bỏ tag số người (solo, 1man...) khỏi mô tả để prompt ghép không mâu thuẫn."""
        parts = [p.strip() for p in str(text or "").split(",")]
        return ", ".join(p for p in parts if p and p.casefold() not in cls.POPULATION_TOKENS)

    @staticmethod
    def _stable_seed(value: str) -> int:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return int(digest[:12], 16) % 999_999_937 + 1

    def load(self) -> None:
        if not os.path.exists(self.filepath):
            self.characters = {}
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.characters = loaded if isinstance(loaded, dict) else {}
            self._migrate_records()
            self._rebuild_alias_map()
        except Exception as exc:
            print(f"[Cảnh báo] Không thể tải {self.filepath}: {exc}")
            self.characters = {}

    def _migrate_records(self) -> None:
        for char_id, data in self.characters.items():
            if not isinstance(data, dict):
                self.characters[char_id] = data = {}
            data.setdefault("ten_chuan", char_id)
            data.setdefault("vai_tro", "phụ")
            data.setdefault("gioi_tinh", "unknown")
            data.setdefault("ten_goi_khac", [])
            data.setdefault("ngoai_hinh_en", "")
            data.setdefault("trang_phuc_theo_giai_doan", {})
            data.setdefault("anh_tham_chieu", "")
            data.setdefault("seed", self._stable_seed(char_id))
            data.setdefault("first_seen_chapter", None)
            data.setdefault("last_seen_chapter", None)
            data.setdefault("mentions", 0)
            data["ngoai_hinh_en"] = self.clean_visual(data.get("ngoai_hinh_en", ""))
            data["trang_phuc_theo_giai_doan"] = {
                k: self.clean_visual(v) for k, v in (data.get("trang_phuc_theo_giai_doan") or {}).items()
            }

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        tmp_path = f"{self.filepath}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.characters, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.filepath)

    def _rebuild_alias_map(self) -> None:
        self.alias_map = {}
        # Canonical names win over aliases when bad source data contains collisions.
        for char_id, data in self.characters.items():
            name = self._normalise(data.get("ten_chuan", ""))
            if name:
                self.alias_map[name] = char_id
        for char_id, data in self.characters.items():
            for alias in data.get("ten_goi_khac", []):
                normalised = self._normalise(alias)
                # Lower-case descriptive phrases (for example a generic old man,
                # disciple or guard) are context labels, not globally unique names.
                # Keeping them in the bible helps the LLM, but deterministic fallback
                # must not bind every future person with that description to one ID.
                looks_unique = any(c.isupper() or c.isdigit() for c in str(alias))
                if normalised and looks_unique and normalised not in self.alias_map:
                    self.alias_map[normalised] = char_id

    def resolve_character(self, value: Any) -> Optional[str]:
        if not value:
            return None
        raw = str(value).strip()
        if raw in self.characters:
            return raw
        return self.alias_map.get(self._normalise(raw))

    def upsert_from_analysis(
        self, profile: Dict[str, Any], chapter_num: int
    ) -> Optional[str]:
        """Merge an AI-discovered identity while preserving established visual traits."""
        name = str(
            profile.get("canonical_name")
            or profile.get("ten_chuan")
            or profile.get("name")
            or ""
        ).strip()
        if not name:
            return None

        aliases = [
            str(a).strip()
            for a in profile.get("aliases", profile.get("ten_goi_khac", []))
            if str(a).strip()
        ]
        char_id = self.resolve_character(profile.get("id")) or self.resolve_character(name)
        if not char_id:
            for alias in aliases:
                char_id = self.resolve_character(alias)
                if char_id:
                    break

        if not char_id:
            base_id = self.make_character_id(name)
            char_id = base_id
            suffix = 2
            while char_id in self.characters:
                char_id = f"{base_id}{suffix}"
                suffix += 1
            self.characters[char_id] = {
                "ten_chuan": name,
                "vai_tro": str(profile.get("role") or "phụ"),
                "gioi_tinh": str(profile.get("gender") or "unknown").lower(),
                "ten_goi_khac": [],
                "ngoai_hinh_en": "",
                "trang_phuc_theo_giai_doan": {},
                "anh_tham_chieu": "",
                "seed": self._stable_seed(char_id),
                "first_seen_chapter": chapter_num,
                "last_seen_chapter": chapter_num,
                "mentions": 0,
            }

        record = self.characters[char_id]
        record["mentions"] = int(record.get("mentions", 0)) + 1
        known_names = {
            self._normalise(record.get("ten_chuan", "")),
            *(self._normalise(a) for a in record.get("ten_goi_khac", [])),
        }
        for alias in [name, *aliases]:
            norm = self._normalise(alias)
            if norm and norm not in known_names and alias != record.get("ten_chuan"):
                record.setdefault("ten_goi_khac", []).append(alias)
                known_names.add(norm)

        appearance = self.clean_visual(
            profile.get("appearance_en") or profile.get("ngoai_hinh_en") or ""
        )
        # Identity is immutable once useful traits exist; this prevents chapter drift.
        if appearance and len(str(record.get("ngoai_hinh_en", ""))) < 20:
            record["ngoai_hinh_en"] = appearance

        gender = str(profile.get("gender") or "").strip().lower()
        if gender in {"male", "female", "nonbinary", "unknown"} and record.get(
            "gioi_tinh", "unknown"
        ) == "unknown":
            record["gioi_tinh"] = gender

        role = str(profile.get("role") or "").strip()
        if role and record.get("vai_tro", "phụ") == "phụ":
            record["vai_tro"] = role

        age = str(profile.get("age_en") or "").strip()
        if age and not record.get("tuoi_en"):
            record["tuoi_en"] = age

        outfit = self.clean_visual(profile.get("outfit_en") or "")
        if outfit:
            record.setdefault("trang_phuc_theo_giai_doan", {})[
                f"ch{chapter_num}-{chapter_num}"
            ] = outfit

        source_description = str(profile.get("description_source") or "").strip()
        if source_description:
            record["mo_ta_nguon"] = source_description

        first_seen = record.get("first_seen_chapter")
        if first_seen is None or chapter_num < first_seen:
            record["first_seen_chapter"] = chapter_num
        record["last_seen_chapter"] = chapter_num
        self._rebuild_alias_map()
        return char_id

    def identify_characters_in_text(self, text: str) -> List[str]:
        """Return IDs in mention order; deterministic ordering avoids random focus drift."""
        normalised_text = self._normalise(text)
        hits: List[tuple] = []
        for alias, char_id in self.alias_map.items():
            pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
            match = re.search(pattern, normalised_text)
            if match:
                hits.append((match.start(), -len(alias), char_id))
        result: List[str] = []
        for _, _, char_id in sorted(hits):
            if char_id not in result:
                result.append(char_id)
        return result

    def get_outfit(self, char_id: str, chapter_num: int) -> str:
        """Trang phục của chương này; nếu chưa có thì lấy chương gần nhất trước đó."""
        best_outfit, best_start, default_outfit = "", -1, ""
        for range_str, value in self.characters.get(char_id, {}).get("trang_phuc_theo_giai_doan", {}).items():
            match = re.search(r"(\d+)\s*-\s*(\d+)", range_str)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
                if start <= chapter_num <= end:
                    return value
                if end < chapter_num and start > best_start:
                    best_outfit, best_start = value, start
            elif "default" in range_str.lower():
                default_outfit = value
        return best_outfit or default_outfit

    def get_character_prompt(self, char_id: str, chapter_num: int = 1) -> str:
        if char_id not in self.characters:
            return ""
        char = self.characters[char_id]
        appearance = str(char.get("ngoai_hinh_en", "")).strip()
        age = str(char.get("tuoi_en", "")).strip()
        if age and age.casefold() in appearance.casefold():
            age = ""
        outfit = self.get_outfit(char_id, chapter_num)
        return ", ".join(p for p in (age, appearance, outfit) if p)

    def set_reference_image(self, char_id: str, path: str) -> None:
        if char_id in self.characters:
            self.characters[char_id]["anh_tham_chieu"] = path

    def casting_candidates(self, ids: List[str], min_mentions: int = 2) -> List[str]:
        """Nhân vật cần ảnh mẫu: vai chính/phụ quan trọng, chưa có ảnh tham chiếu."""
        result = []
        for char_id in ids:
            data = self.characters.get(char_id, {})
            if self.get_reference_image(char_id):
                continue
            role = str(data.get("vai_tro", "")).casefold()
            important = any(k in role for k in ("main", "chính", "supporting"))
            if important or int(data.get("mentions", 0)) >= min_mentions:
                result.append(char_id)
        return result

    def get_gender(self, char_id: str) -> str:
        data = self.characters.get(char_id, {})
        gender = str(data.get("gioi_tinh", "unknown")).lower()
        if gender in {"male", "female"}:
            return gender
        appearance = str(data.get("ngoai_hinh_en", "")).lower()
        if any(token in appearance for token in ("woman", "female", "girl")):
            return "female"
        if any(token in appearance for token in ("man", "male", "boy")):
            return "male"
        return "unknown"

    def get_seed(self, char_id: str) -> int:
        data = self.characters.get(char_id, {})
        try:
            seed = int(data.get("seed", -1))
        except (TypeError, ValueError):
            seed = -1
        return seed if seed > 0 else self._stable_seed(char_id)

    def get_reference_image(self, char_id: str) -> Optional[str]:
        """Đường dẫn ảnh mẫu (lưu tương đối theo thư mục dự án để chạy được ở mọi máy)."""
        ref = str(self.characters.get(char_id, {}).get("anh_tham_chieu", ""))
        if not ref:
            return None
        if not os.path.isabs(ref):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(self.filepath)))
            candidate = os.path.join(project_root, ref)
            if os.path.exists(candidate):
                return candidate
        return ref if os.path.exists(ref) else None

    def build_llm_context(self, max_characters: int = 100, only_ids: Optional[List[str]] = None) -> str:
        items = self.characters.items()
        if only_ids is not None:
            wanted = set(only_ids)
            items = [(k, v) for k, v in items if k in wanted]
        ordered = sorted(
            items,
            key=lambda item: (
                item[1].get("last_seen_chapter") is None,
                -(item[1].get("last_seen_chapter") or 0),
                item[1].get("ten_chuan", ""),
            ),
        )[:max_characters]
        lines = []
        for char_id, data in ordered:
            aliases = ", ".join(data.get("ten_goi_khac", [])) or "none"
            appearance = data.get("ngoai_hinh_en", "") or "not established yet"
            lines.append(
                f"- id={char_id}; name={data.get('ten_chuan')}; aliases={aliases}; "
                f"gender={data.get('gioi_tinh', 'unknown')}; identity={appearance}"
            )
        return "\n".join(lines)
