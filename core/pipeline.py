"""Điều phối toàn bộ quy trình: chương truyện -> video hoàn chỉnh, tự động, có cache."""
import os
import shutil
import subprocess
import time
import traceback

import numpy as np
from typing import Any, Dict, List, Optional, Set

from core.asr_checker import ASRChecker
from core.audio_builder import AudioBuilder
from core.character_registry import CharacterRegistry
from core.comfy_client import ComfyClient, ImageGenerator
from core.drive_sync import DriveSync
from core.image_qa import ImageQA
from core.location_registry import LocationRegistry
from core.motion_client import MotionGenerator
from core.ollama_client import OllamaClient
from core.project import Project
from core.scene_director import SceneDirector
from core.series_analyzer import analyze_series, heuristic_genre, heuristic_themes
from core.storyboard import contact_sheet, thumbnail, write_report
from core.style import (
    apply_themes,
    detect_era_genre,
    genre_for_chapter,
    list_styles,
    list_themes,
    load_art_style,
    load_style,
)
from core.subtitle import SubtitleGenerator
from core.text_processor import build_chunks, chapter_title, clean_paragraphs, extract_standardization_table
from core.tts_engine import TTSEngine
from core.utils import file_fingerprint, fingerprint, format_duration, log, read_json, set_log_file, write_json
from core.video_renderer import VideoRenderer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = ("direct", "audio", "images", "motion", "render")


def resolve_path(path: str, project: Optional[Project] = None) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    for base in ((project.root if project else None), ROOT, os.getcwd()):
        if base and os.path.exists(os.path.join(base, path)):
            return os.path.join(base, path)
    return os.path.join(ROOT, path)


class Studio:
    def __init__(self, cfg: Dict[str, Any], project: Project, options: Optional[Dict[str, Any]] = None):
        self.cfg = cfg
        self.project = project
        self.opt = options or {}
        self.force: Set[str] = set(self.opt.get("force") or [])
        self.until: Optional[str] = self.opt.get("until")
        self.redo_scenes: Dict[int, Set[int]] = self.opt.get("redo_scenes") or {}
        project.ensure_dirs()
        set_log_file(os.path.join(project.logs_dir, "studio.log"))

        self.ollama = OllamaClient(cfg.get("ollama", {}))
        self.comfy = ComfyClient(cfg.get("comfyui", {}).get("host", "http://127.0.0.1:8188"),
                                 int(cfg.get("comfyui", {}).get("timeout_seconds", 600)))
        self.tts = TTSEngine(cfg.get("tts", {}))
        self.asr = ASRChecker(cfg.get("asr", {}))
        self.audio = AudioBuilder(self.tts, self.asr, cfg.get("tts", {}), cfg.get("asr", {}), project.cache_dir)
        self.chars = CharacterRegistry(project.characters_path)
        self.locs = LocationRegistry(project.locations_path)
        self.drive = DriveSync(cfg.get("upload", {}), os.path.join(project.logs_dir, "upload.log"))
        self.series: Dict[str, Any] = {}
        self.style: Dict[str, Any] = {}
        self.art: Dict[str, Any] = {}
        self._images: Optional[ImageGenerator] = None
        self._motion: Optional[MotionGenerator] = None
        self._renderer: Optional[VideoRenderer] = None

    # ============================================================ services
    def renderer(self) -> VideoRenderer:
        if self._renderer is None:
            self._renderer = VideoRenderer(self.cfg.get("video", {}))
        return self._renderer

    def images(self) -> ImageGenerator:
        if self._images is None:
            self._images = ImageGenerator(self.comfy, self.cfg.get("image", {}), self.art)
            self._images.prepare()
        return self._images

    def motion(self) -> MotionGenerator:
        if self._motion is None:
            self._motion = MotionGenerator(self.comfy, self.cfg.get("motion", {}))
            self._motion.prepare()
        return self._motion

    def free_gpu(self, keep: str) -> None:
        """Chỉ giữ một nhóm model trên GPU để không tràn VRAM."""
        if keep != "ollama" and self.ollama.health():
            self.ollama.unload_all()
        if keep != "tts":
            self.tts.unload()
            self.asr.unload()
        if keep != "comfy" and self.comfy.health():
            self.comfy.free_memory()

    def require(self, service: str) -> None:
        ok = self.ollama.health() if service == "ollama" else self.comfy.health()
        if not ok:
            host = self.ollama.host if service == "ollama" else self.comfy.host
            raise RuntimeError(f"{service} không chạy ở {host}. Chạy `AUTO_RUN=0 bash setup.sh` để bật lại dịch vụ.")

    # ============================================================== series
    def ensure_series(self) -> None:
        series = self.project.load_series()
        valid = {s[0] for s in list_styles()}
        need_analysis = any(series.get(k) in (None, "", "auto") for k in ("genre", "art_style", "themes"))
        if need_analysis or "analyze" in self.force:
            chapters = self.project.chapter_files()
            if not chapters:
                raise RuntimeError(f"Chưa có chương nào trong {self.project.chapters_dir}")
            director_cfg = self.cfg.get("director", {})
            sample_chars = int(director_cfg.get("analysis_sample_chars", 6000))
            samples = []
            for _, path in chapters[: int(director_cfg.get("analysis_chapters", 3))]:
                with open(path, "r", encoding="utf-8") as handle:
                    samples.append("\n".join(clean_paragraphs(handle.read()))[:sample_chars])
            if self.ollama.health():
                log("Phân tích thể loại / thời đại bộ truyện...", "Phân tích")
                result = analyze_series(self.ollama, samples, series.get("title", ""))
                self.ollama.unload_all()
            else:
                genre = heuristic_genre("\n".join(samples))
                result = {"genre": genre, "themes": heuristic_themes("\n".join(samples)),
                          "art_style": load_style(genre).get("default_art_style"), "analysis_note": "heuristic (Ollama không chạy)"}
            for key, value in result.items():
                if key in ("genre", "art_style", "themes"):
                    if series.get(key) in (None, "", "auto") or "analyze" in self.force:
                        series[key] = value
                elif value and (not series.get(key) or "analyze" in self.force):
                    series[key] = value
            self.project.save_series(series)
            log(f"Thể loại: {series['genre']} | Chủ đề: {series.get('themes') or 'không'} | "
                f"Phong cách vẽ: {series['art_style']} | {series.get('era_en', '')}", "Phân tích")
            if series.get("analysis_note"):
                log(f"Lý do: {series['analysis_note']}", "Phân tích")
        if not isinstance(series.get("themes"), list):
            series["themes"] = [t.strip() for t in str(series.get("themes") or "").split(",") if t.strip() and t.strip() != "auto"]
        known_themes = {t[0] for t in list_themes()}
        unknown = [t for t in series["themes"] if t not in known_themes]
        if unknown:
            log(f"Bỏ qua chủ đề không tồn tại: {unknown}. Có: {', '.join(sorted(known_themes))}", "Cảnh báo")
        for genre in [series["genre"], *(series.get("genre_by_chapter") or {}).values()]:
            if genre not in valid:
                raise RuntimeError(f"genre '{genre}' không hợp lệ. Có: {', '.join(sorted(valid))}")
        self.series = series
        self.style = apply_themes(load_style(series["genre"]), series["themes"])
        self.art = load_art_style(series["art_style"])

    def _chapter_style(self, number: int, text: str) -> List[str]:
        """Chọn preset cho chương (genre_by_chapter / tự nhận thời đại) và cộng chủ đề."""
        notes: List[str] = []
        genre = genre_for_chapter(self.series, number)
        suggestion, counts = detect_era_genre(text, genre)
        if suggestion:
            auto = bool(self.cfg.get("director", {}).get("auto_era", True)) and not self.series.get("genre_by_chapter")
            msg = (f"Chương {number} nhắc nhiều năm thuộc '{suggestion}' ({counts}) nhưng đang dùng '{genre}'.")
            if auto:
                genre = suggestion
                msg += f" Tự chuyển sang '{suggestion}' cho chương này."
            else:
                msg += " Nếu truyện đã sang thời kỳ mới, thêm genre_by_chapter trong series.yaml."
            log(msg, "Thời đại")
            notes.append(msg)
        self.style = apply_themes(load_style(genre), self.series.get("themes") or [])
        return notes

    def director(self) -> SceneDirector:
        return SceneDirector(self.ollama, self.chars, self.locs, self.style, self.art, self.series, self.cfg.get("director", {}))

    def voice(self) -> Dict[str, Any]:
        voice = self.series.get("voice") or {}
        ref_audio = resolve_path(str(voice.get("ref_audio") or ""), self.project)
        ref_text_path = resolve_path(str(voice.get("ref_text") or ""), self.project)
        if not ref_audio or not os.path.exists(ref_audio):
            log("Không có giọng mẫu, OmniVoice sẽ dùng giọng mặc định.", "Cảnh báo")
            return {"ref_audio": None, "ref_text": None, "fp": "default"}
        ref_text = ""
        if os.path.exists(ref_text_path):
            with open(ref_text_path, "r", encoding="utf-8") as handle:
                ref_text = handle.read().strip()
        else:
            log(f"Thiếu file lời giọng mẫu {ref_text_path}; OmniVoice sẽ tự nhận dạng.", "Cảnh báo")
        fp = fingerprint(file_fingerprint(ref_audio), ref_text)
        prepared = os.path.join(self.project.cache_dir, f"voice_ref_{fp}.wav")
        if not os.path.exists(prepared):
            TTSEngine.prepare_reference(ref_audio, prepared)
        return {"ref_audio": prepared, "ref_text": ref_text or None, "fp": fp}

    # ================================================================= run
    def _acquire_lock(self) -> str:
        lock = os.path.join(self.project.work_dir, ".lock")
        if os.path.exists(lock):
            try:
                pid = int(open(lock).read().strip())
                os.kill(pid, 0)
                raise RuntimeError(f"Dự án đang được xử lý bởi tiến trình {pid}.")
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                pass
        with open(lock, "w") as handle:
            handle.write(str(os.getpid()))
        return lock

    def run(self, chapter_filter: Optional[Set[int]] = None, finish: bool = False) -> bool:
        lock = self._acquire_lock()
        started = time.time()
        failures: List[int] = []
        try:
            self.ensure_series()
            chapters = [(n, p) for n, p in self.project.chapter_files() if chapter_filter is None or n in chapter_filter]
            if not chapters:
                log("Không có chương nào khớp để xử lý.", "Studio")
                return False
            log(f"Dự án '{self.project.slug}': {len(chapters)} chương cần kiểm tra.", "Studio")
            for number, path in chapters:
                try:
                    self.process_chapter(number, path)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    failures.append(number)
                    log(f"CHƯƠNG {number} LỖI: {exc}", "LỖI")
                    log(traceback.format_exc()[-2000:], "LỖI")
            if self.until in (None, "render"):
                self.build_episodes(finish)
        finally:
            self.free_gpu(keep="none")
            if os.path.exists(lock):
                os.remove(lock)
        log(f"Hoàn tất sau {format_duration(time.time() - started)}. Lỗi: {failures or 'không'}", "Studio")
        if self.opt.get("stop_pod") or self.cfg.get("runpod", {}).get("stop_pod_when_done"):
            self.stop_pod()
        return not failures

    def stop_pod(self) -> None:
        pod_id = os.environ.get("RUNPOD_POD_ID")
        if pod_id and shutil.which("runpodctl"):
            log(f"Tắt pod {pod_id} để ngừng tính tiền...", "Studio")
            subprocess.run(["runpodctl", "stop", "pod", pod_id])
        else:
            log("Không tìm thấy RUNPOD_POD_ID/runpodctl, không tự tắt pod.", "Studio")

    # ============================================================ chapter
    def process_chapter(self, number: int, path: str) -> None:
        work = self.project.chapter_dir(number)
        state = self.project.load_chapter_state(number)
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        paragraphs = clean_paragraphs(raw)
        if not paragraphs:
            raise RuntimeError("Chương rỗng sau khi làm sạch.")
        title = chapter_title(paragraphs) or f"Chương {number}"
        log(f"===== CHƯƠNG {number}: {title} =====", "Studio")
        self.chapter_notes = self._chapter_style(number, "\n".join(paragraphs))
        log(f"Preset: {self.style['id']}" + (f" + chủ đề {self.style.get('themes')}" if self.style.get("themes") else ""), "Studio")

        for item in extract_standardization_table(raw):
            self.chars.upsert_from_analysis({"canonical_name": item["name"], "description_source": item["description"]}, number)

        tts_cfg = self.cfg.get("tts", {})
        chunks = build_chunks(
            paragraphs,
            max_chars=int(tts_cfg.get("max_chars", 160)),
            merge_sentences=bool(tts_cfg.get("merge_sentences", True)),
            pauses=tts_cfg.get("pauses_ms"),
            glossary=self.project.load_glossary(),
        )

        # ---------------- 1. đạo diễn
        director = self.director()
        dcfg = self.cfg.get("director", {})
        direct_fp = fingerprint(director.fingerprint("\n".join(paragraphs)), [c["display"] for c in chunks])
        scenes_path = os.path.join(work, "scenes.json")
        cached = read_json(scenes_path)
        if "direct" in self.force or not cached or cached.get("fp") != direct_fp:
            self.require("ollama")
            self.free_gpu(keep="ollama")
            log("Quét Story Bible (nhân vật, địa điểm)...", "Đạo diễn")
            director.discover_bible(paragraphs, number)
            scenes = SceneDirector.group_scenes(
                chunks, int(dcfg.get("scene_target_chars", 230)), int(dcfg.get("scene_max_chars", 360))
            )
            log(f"Phân {len(scenes)} cảnh, đạo diễn bằng {self.ollama.model}...", "Đạo diễn")
            directed = director.direct(scenes, number)
            write_json(scenes_path, {"fp": direct_fp, "scenes": directed})
            self.ollama.unload_all()
            state.pop("render_fp", None)
        else:
            directed = cached["scenes"]
            log(f"Dùng phân cảnh đã có ({len(directed)} cảnh).", "Đạo diễn")
        self.project.save_chapter_state(number, state)
        if self.until == "direct":
            return
        compiled = director.compile(directed, number, lambda idx: self.project.scene_override(number, idx))
        write_json(os.path.join(work, "prompts.json"), [
            {k: s.get(k) for k in ("index", "text", "positive", "negative", "motion_prompt", "reference_images", "seed")}
            for s in compiled
        ])

        # ---------------- 2. giọng đọc
        voice = self.voice()
        audio_wav = os.path.join(work, "audio", "chapter.wav")
        timeline_path = os.path.join(work, "audio", "timeline.json")
        if "audio" in self.force and os.path.exists(timeline_path):
            os.remove(timeline_path)
        self.free_gpu(keep="tts")
        self.audio.force = "audio" in self.force
        timeline = self.audio.build(chunks, voice["ref_audio"], voice["ref_text"], voice["fp"], audio_wav, timeline_path)
        self.tts.unload()
        self.asr.unload()
        ass_path = None
        subtitle_cfg = self.cfg.get("video", {}).get("subtitle", {})
        if subtitle_cfg.get("enabled", True):
            ass_path = SubtitleGenerator(subtitle_cfg, tuple(self.cfg.get("video", {}).get("resolution", [1920, 1080]))).generate(
                timeline, os.path.join(work, "render", "subs.ass")
            )
        durations = self._scene_durations(compiled, timeline)
        if self.until == "audio":
            return

        # ---------------- 3. ảnh + casting + QA
        self.require("comfy")
        self.free_gpu(keep="comfy")
        self._casting(compiled, number)
        compiled = director.compile(directed, number, lambda idx: self.project.scene_override(number, idx))
        self._render_images(compiled, number, work, state)
        if self.until == "images":
            self._outputs(number, title, compiled, durations, timeline, state, work)
            return

        # ---------------- 4. chuyển động
        clips: Dict[int, str] = {}
        if self.cfg.get("motion", {}).get("enabled", True):
            clips = self._render_motion(compiled, durations, number, work, state,
                                        timeline=timeline, chunks=chunks, audio_wav=audio_wav)
        if self.until == "motion":
            self._outputs(number, title, compiled, durations, timeline, state, work, clips)
            return

        # ---------------- 5. dựng phim
        self.free_gpu(keep="none")
        out = self.project.chapter_video_path(number)
        bgm = self._pick_bgm(number)
        render_fp = fingerprint(
            timeline.get("audio_fp"),
            [state.get("images", {}).get(str(s["index"]), {}).get("fp") for s in compiled],
            {str(k): state.get("motion", {}).get(str(k)) for k in clips},
            durations,
            self.cfg.get("video", {}),
            file_fingerprint(ass_path),
            self.series.get("watermark"),
            file_fingerprint(bgm),
        )
        if "render" not in self.force and state.get("render_fp") == render_fp and os.path.exists(out):
            log(f"Video chương đã mới nhất: {out}", "Render")
        else:
            renderer = self.renderer()
            visual = []
            for scene in compiled:
                visual.append(
                    {
                        "image": os.path.join(work, "images", f"scene_{scene['index']:04d}.png"),
                        "clip": clips.get(scene["index"]),
                        "duration": durations[scene["index"]],
                        "kb_mode": renderer.pick_kb_mode(scene["seed"], scene["meta"].get("shot_type", "")),
                    }
                )
            log(f"Dựng video {format_duration(timeline['total_duration_sec'])} ({len(visual)} cảnh)...", "Render")
            renderer.render_chapter(
                visual, audio_wav, ass_path, out, os.path.join(work, "render"),
                timeline["total_duration_sec"], self.series.get("watermark", ""), bgm,
            )
            state["render_fp"] = render_fp
            state.pop("chapter_uploaded", None)
            self.project.save_chapter_state(number, state)
            log(f"XONG: {out}", "Render")
        self._outputs(number, title, compiled, durations, timeline, state, work, clips)
        if self.cfg.get("upload", {}).get("upload_chapters", False) and not state.get("chapter_uploaded"):
            if self.drive.upload(out, f"{self.project.slug}/chapters"):
                state["chapter_uploaded"] = True
                self.project.save_chapter_state(number, state)

    @staticmethod
    def _scene_windows(compiled: List[Dict[str, Any]], timeline: Dict[str, Any]) -> Dict[int, tuple]:
        """Mốc (bắt đầu, kết thúc) ms của từng cảnh trên trục thời gian audio chương."""
        durations = Studio._scene_durations(compiled, timeline)
        windows: Dict[int, tuple] = {}
        cursor = 0.0
        for scene in compiled:
            length = durations[scene["index"]] * 1000.0
            windows[scene["index"]] = (cursor, cursor + length)
            cursor += length
        return windows

    @staticmethod
    def _scene_durations(compiled: List[Dict[str, Any]], timeline: Dict[str, Any]) -> Dict[int, float]:
        starts = {c["id"]: c["start_ms"] for c in timeline["chunks"]}
        total_ms = timeline["total_duration_ms"]
        scene_starts = []
        for scene in compiled:
            ids = [i for i in scene["chunk_ids"] if i in starts]
            scene_starts.append(starts[ids[0]] if ids else None)
        # Cảnh thiếu chunk (hiếm) mượn mốc của cảnh trước.
        for i, value in enumerate(scene_starts):
            if value is None:
                scene_starts[i] = scene_starts[i - 1] if i else 0
        scene_starts[0] = 0
        durations: Dict[int, float] = {}
        for i, scene in enumerate(compiled):
            end = scene_starts[i + 1] if i + 1 < len(compiled) else total_ms
            durations[scene["index"]] = max(0.6, (end - scene_starts[i]) / 1000.0)
        return durations

    # ============================================================ casting
    def _casting(self, compiled: List[Dict[str, Any]], number: int) -> None:
        ccfg = self.cfg.get("casting", {})
        if not ccfg.get("enabled", True):
            return
        counts: Dict[str, int] = {}
        for scene in compiled:
            for cid in scene["meta"]["visible_character_ids"]:
                counts[cid] = counts.get(cid, 0) + 1
        ordered = sorted(counts, key=lambda c: -counts[c])
        targets = [
            c for c in self.chars.casting_candidates(ordered, int(ccfg.get("min_mentions", 2)))
            if counts.get(c, 0) >= int(ccfg.get("min_scenes", 2))
        ][: int(ccfg.get("max_per_chapter", 6))]
        if not targets:
            return
        log(f"Casting ảnh mẫu cho {len(targets)} nhân vật: {', '.join(targets)}", "Casting")
        images = self.images()
        candidates: Dict[str, List[str]] = {}
        for cid in targets:
            identity = self.chars.get_character_prompt(cid, number)
            positive = ", ".join(p for p in (
                "character reference portrait, single person, front view, head and shoulders, looking at camera, "
                "neutral expression, plain soft studio background, even lighting",
                identity,
                self.series.get("era_en") or self.style.get("world_en", ""),
                self.art.get("positive", ""),
            ) if p)
            negative = ", ".join(p for p in (
                self.art.get("negative", ""), self.style.get("negative", ""), self.style.get("anatomy_negative", ""),
                (self.style.get("population_negative") or {}).get("single", ""), "profile view, back view, hands covering face",
            ) if p)
            folder = os.path.join(self.project.refs_dir, cid)
            paths = []
            for k in range(max(1, int(ccfg.get("candidates", 3)))):
                out = os.path.join(folder, f"candidate_{k + 1}.png")
                seed = self.chars.get_seed(cid) + k * 101
                try:
                    images.generate(positive, negative, seed, out)
                    paths.append(out)
                except Exception as exc:
                    log(f"Casting {cid} ứng viên {k + 1} lỗi: {exc}", "Casting")
            if paths:
                candidates[cid] = paths
        qa = ImageQA(self.ollama, self.cfg.get("qa", {}), self.style, self.series)
        use_qa = qa.available()
        if use_qa:
            self.free_gpu(keep="ollama")
        for cid, paths in candidates.items():
            best = paths[0]
            if use_qa and len(paths) > 1:
                best_score = -1.0
                fake_scene = {"meta": {"population_mode": "single", "subject_en": "portrait of " + self.chars.get_character_prompt(cid, number)}}
                for p in paths:
                    review = qa.review(p, fake_scene)
                    score = review.get("score", 0) - (5 if not review.get("ok", True) else 0)
                    if score > best_score:
                        best, best_score = p, score
            ref = os.path.join(self.project.refs_dir, cid, "ref.png")
            shutil.copyfile(best, ref)
            self.chars.set_reference_image(cid, os.path.relpath(ref, self.project.root).replace(os.sep, "/"))
            log(f"Ảnh mẫu {cid}: {ref}", "Casting")
        self.chars.save()
        if use_qa:
            self.ollama.unload_all()

    # ============================================================== images
    def _render_images(self, compiled: List[Dict[str, Any]], number: int, work: str, state: Dict[str, Any]) -> None:
        images = self.images()
        qa_cfg = self.cfg.get("qa", {})
        records: Dict[str, Any] = state.setdefault("images", {})
        redo = self.redo_scenes.get(number, set())
        settings = images.settings_fingerprint()

        def image_path(scene: Dict[str, Any]) -> str:
            return os.path.join(work, "images", f"scene_{scene['index']:04d}.png")

        def scene_fp(scene: Dict[str, Any]) -> str:
            return fingerprint(scene["positive"], scene["negative"], scene["seed"],
                               [file_fingerprint(r) for r in scene["reference_images"]], settings)

        def draw(scene: Dict[str, Any], attempt: int) -> None:
            seed = scene["seed"] + attempt * 1009
            images.generate(scene["positive"], scene["negative"], seed, image_path(scene), scene["reference_images"])

        todo = []
        fps: Dict[str, str] = {}
        for scene in compiled:
            key = str(scene["index"])
            rec = records.get(key)
            fp = fps[key] = scene_fp(scene)
            if "images" in self.force or scene["index"] in redo or not rec or rec.get("fp") != fp or not os.path.exists(image_path(scene)):
                todo.append(scene)
                records.pop(key, None)   # chỉ ghi lại sau khi vẽ xong (dừng giữa chừng không bị coi là đã vẽ)

        # Gom cảnh theo model: Qwen-Image (không ảnh mẫu, đang nóng sau casting) trước, Qwen-Image-Edit sau.
        # Xen kẽ hai model 20 GB buộc ComfyUI nạp lại từ ổ mỗi lần đổi (đo: vài phút/lần trên volume mạng).
        def model_order(scene: Dict[str, Any]) -> tuple:
            return (bool(images.edit_enabled and scene["reference_images"]), scene["index"])

        todo.sort(key=model_order)
        if todo:
            log(f"Vẽ {len(todo)}/{len(compiled)} ảnh ({images.active_workflow})...", "Ảnh")
        for n, scene in enumerate(todo, start=1):
            try:
                draw(scene, 0)
            except Exception as exc:
                self.project.save_chapter_state(number, state)
                raise RuntimeError(f"Vẽ cảnh {scene['index']} thất bại: {exc}")
            records[str(scene["index"])] = {"fp": fps[str(scene["index"])], "attempt": 0, "qa": None}
            self.project.save_chapter_state(number, state)   # lưu từng ảnh: dừng giữa chừng không mất ảnh đã vẽ
            if n % 5 == 0:
                log(f"  {n}/{len(todo)} ảnh", "Ảnh")
        self.project.save_chapter_state(number, state)

        qa = ImageQA(self.ollama, qa_cfg, self.style, self.series)
        if not qa.enabled:
            return
        if not qa.available():
            log(f"Bỏ qua QA ảnh: chưa có model thị giác {self.ollama.vision_model} trong Ollama.", "QA")
            return
        max_rounds = int(qa_cfg.get("max_rounds", 2))
        for round_no in range(max_rounds + 1):
            pending = [s for s in compiled if records.get(str(s["index"]), {}).get("qa") is None]
            if not pending:
                break
            self.free_gpu(keep="ollama")
            log(f"QA ảnh vòng {round_no + 1}: kiểm {len(pending)} ảnh...", "QA")
            failed = []
            for scene in pending:
                rec = records[str(scene["index"])]
                review = qa.review(image_path(scene), scene)
                rec["qa"] = review
                if not review.get("ok", True):
                    failed.append(scene)
            self.project.save_chapter_state(number, state)
            retry = sorted((s for s in failed if records[str(s["index"])]["attempt"] < max_rounds), key=model_order)
            if not retry or round_no == max_rounds:
                break
            self.ollama.unload_all()
            self.free_gpu(keep="comfy")
            log(f"Vẽ lại {len(retry)} ảnh chưa đạt: {[s['index'] for s in retry]}", "QA")
            for scene in retry:
                rec = records[str(scene["index"])]
                rec["attempt"] += 1
                try:
                    draw(scene, rec["attempt"])
                    rec["qa"] = None
                except Exception as exc:
                    log(f"Vẽ lại cảnh {scene['index']} lỗi: {exc}", "QA")
            self.project.save_chapter_state(number, state)
        self.ollama.unload_all()

    # ============================================================== motion
    def _choose_motion(self, compiled: List[Dict[str, Any]], durations: Dict[int, float]) -> List[int]:
        mcfg = self.cfg.get("motion", {})
        ratio = float(mcfg.get("ratio", 0.25))
        forced_on = {s["index"] for s in compiled if s.get("motion_override") is True}
        forced_off = {s["index"] for s in compiled if s.get("motion_override") is False}
        quota = max(0, int(round(len(compiled) * ratio)))
        ranked = sorted(
            (s for s in compiled if s["index"] not in forced_off and s["index"] not in forced_on),
            key=lambda s: (-(3 if s["index"] == 1 else s["meta"].get("motion_priority", 1)), durations[s["index"]]),
        )
        chosen = list(forced_on)
        for scene in ranked:
            if len(chosen) >= quota:
                break
            if scene["meta"].get("motion_priority", 1) >= int(mcfg.get("min_priority", 1)) or scene["index"] == 1:
                chosen.append(scene["index"])
        return sorted(set(chosen))

    @staticmethod
    def _speech_track(audio_wav: str, window: tuple, speech: List[tuple], out: str, pad_ms: int = 80) -> str:
        """Cắt audio của cảnh, chỉ giữ các đoạn thoại (dẫn truyện -> im lặng để miệng không mấp máy)."""
        import soundfile as sf

        samples, sr = sf.read(audio_wav, dtype="float32", always_2d=False)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        start = int(window[0] * sr / 1000)
        end = max(start + 1, int(window[1] * sr / 1000))
        clip = samples[start:end].copy()
        mask = np.zeros(clip.shape[0], dtype=bool)
        for s_ms, e_ms in speech:
            a = max(0, int((s_ms - window[0] - pad_ms) * sr / 1000))
            b = min(clip.shape[0], int((e_ms - window[0] + pad_ms) * sr / 1000))
            if b > a:
                mask[a:b] = True
        clip[~mask] = 0.0
        os.makedirs(os.path.dirname(out), exist_ok=True)
        sf.write(out, clip, sr)
        return out

    def _render_motion(self, compiled, durations, number: int, work: str, state: Dict[str, Any],
                       timeline: Optional[Dict[str, Any]] = None, chunks: Optional[List[Dict[str, Any]]] = None,
                       audio_wav: Optional[str] = None) -> Dict[int, str]:
        motion = self.motion()
        mcfg = self.cfg.get("motion", {})
        records: Dict[str, Any] = state.setdefault("motion", {})
        clips: Dict[int, str] = {}
        by_index = {s["index"]: s for s in compiled}
        redo = self.redo_scenes.get(number, set())
        if not motion.ready:
            return clips
        if str(mcfg.get("coverage", "all")) == "all":
            chosen = [s["index"] for s in compiled if s.get("motion_override") is not False]
        else:
            chosen = self._choose_motion(compiled, durations)

        # Thoại: cảnh có người nói đang ở một mình trong khung -> S2V nhép miệng.
        lipsync = bool(mcfg.get("lipsync", True)) and motion.s2v_ready and timeline and chunks and audio_wav
        windows = self._scene_windows(compiled, timeline) if timeline else {}
        dialogue_ids = {c["id"] for c in (chunks or []) if c.get("dialogue")}
        times = {c["id"]: (c["start_ms"], c["end_ms"]) for c in (timeline or {}).get("chunks", [])}

        self.free_gpu(keep="comfy")
        todo = []
        for index in chosen:
            scene = by_index[index]
            seconds = durations[index]
            speech: List[tuple] = []
            if lipsync and scene.get("speaker_id") and scene["meta"].get("population_mode") == "single":
                speech = [times[i] for i in scene["chunk_ids"] if i in dialogue_ids and i in times]
            mode = "s2v" if speech else "i2v"
            clip = os.path.join(work, "motion", f"scene_{index:04d}.mp4")
            img = state.get("images", {}).get(str(index), {})
            if mode == "s2v":
                fp = fingerprint(img.get("fp"), img.get("attempt"), mode, scene.get("speech_prompt"), speech,
                                 windows.get(index), timeline.get("audio_fp"), motion.s2v_fingerprint())
            else:
                fp = fingerprint(img.get("fp"), img.get("attempt"), mode, scene.get("motion_beats") or scene["motion_prompt"],
                                 motion.clips_needed(seconds), motion.settings_fingerprint())
            if "motion" in self.force or index in redo or records.get(str(index)) != fp or not os.path.exists(clip):
                todo.append({"scene": scene, "clip": clip, "fp": fp, "mode": mode, "speech": speech, "seconds": seconds})
            else:
                clips[index] = clip
        # Gom theo model: I2V trước, S2V sau (mỗi lần đổi model 14B phải nạp lại hàng chục GB).
        todo.sort(key=lambda t: (t["mode"] != "i2v", t["scene"]["index"]))
        if todo:
            n_s2v = sum(1 for t in todo if t["mode"] == "s2v")
            n_clips = sum(motion.clips_needed(t["seconds"]) for t in todo if t["mode"] == "i2v")
            log(f"Chuyển động {len(todo)} cảnh ({motion.model}: {len(todo) - n_s2v} cảnh / {n_clips} clip; "
                f"nhép miệng S2V: {n_s2v} cảnh)...", "Motion")
        started = time.time()
        for n, task in enumerate(todo, start=1):
            scene, clip = task["scene"], task["clip"]
            image = os.path.join(work, "images", f"scene_{scene['index']:04d}.png")
            negative = scene.get("motion_negative", "")
            ok = False
            if task["mode"] == "s2v":
                wav = self._speech_track(audio_wav, windows[scene["index"]], task["speech"],
                                         os.path.join(work, "motion", f"speech_{scene['index']:04d}.wav"))
                ok = motion.generate_s2v(image, wav, scene.get("speech_prompt") or scene["motion_prompt"], negative, scene["seed"], clip)
            if not ok:
                ok = motion.generate_chain(image, scene.get("motion_beats") or [scene["motion_prompt"]], negative,
                                           scene["seed"], task["seconds"], clip)
            if ok:
                records[str(scene["index"])] = task["fp"]
                clips[scene["index"]] = clip
            else:
                records.pop(str(scene["index"]), None)
            self.project.save_chapter_state(number, state)
            per = (time.time() - started) / n
            log(f"  cảnh {n}/{len(todo)} ({task['mode']}, {task['seconds']:.0f}s) - còn ~{per * (len(todo) - n) / 60:.0f} phút", "Motion")
        self.comfy.free_memory()
        return clips

    # ============================================================= outputs
    def _pick_bgm(self, number: int) -> Optional[str]:
        bcfg = self.cfg.get("video", {}).get("bgm", {})
        if not bcfg.get("enabled", True):
            return None
        base = resolve_path(bcfg.get("dir", "assets/bgm"))
        mood = self.style.get("bgm_mood", "")
        files: List[str] = []
        for folder in (os.path.join(base, mood), base):
            if os.path.isdir(folder):
                files = sorted(
                    os.path.join(folder, f) for f in os.listdir(folder)
                    if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg", ".flac"))
                )
                if files:
                    break
        return files[number % len(files)] if files else None

    def _outputs(self, number, title, compiled, durations, timeline, state, work, clips=None) -> None:
        clips = clips or {}
        records = state.get("images", {})
        rows = []
        for scene in compiled:
            rec = records.get(str(scene["index"]), {})
            qa = rec.get("qa") or {}
            rows.append(
                {
                    "index": scene["index"],
                    "text": scene["text"],
                    "image": os.path.join(work, "images", f"scene_{scene['index']:04d}.png"),
                    "duration": durations.get(scene["index"], 0),
                    "clip": clips.get(scene["index"]),
                    "fallback": scene["meta"].get("fallback"),
                    "qa_failed": qa.get("ok") is False,
                    "qa_reasons": qa.get("reasons", []),
                }
            )
        out = self.project.output_dir
        sheet = contact_sheet(rows, os.path.join(out, "storyboards", f"Chuong_{number:04d}.jpg"))
        cover = next((r["image"] for r in rows if r["image"] and os.path.exists(r["image"]) and not r["qa_failed"]
                      and any(s["index"] == r["index"] and s["meta"]["population_mode"] == "single" for s in compiled)), None)
        thumbnail(cover or (rows[0]["image"] if rows else ""), title, os.path.join(out, "thumbnails", f"Chuong_{number:04d}.jpg"))
        report = write_report(os.path.join(out, "reports", f"Chuong_{number:04d}.md"), number, title, timeline, rows,
                              getattr(self, "chapter_notes", []))
        if self.cfg.get("upload", {}).get("upload_storyboards", True):
            for path in (sheet, report):
                if path and os.path.exists(path):
                    marker = f"{path}.uploaded"
                    if os.path.exists(marker):
                        os.remove(marker)  # luôn cập nhật bản mới
                    self.drive.upload(path, f"{self.project.slug}/review")

    # ============================================================ episodes
    def build_episodes(self, finish: bool = False) -> None:
        per = int(self.series.get("chapters_per_episode") or self.cfg.get("episodes", {}).get("chapters_per_episode", 10))
        chapters = self.project.chapter_files()
        if per <= 0 or not chapters:
            return
        state = read_json(self.project.episodes_state_path, {}) or {}
        ucfg = self.cfg.get("upload", {})
        for start in range(0, len(chapters), per):
            group = chapters[start : start + per]
            episode_no = start // per + 1
            videos = [self.project.chapter_video_path(n) for n, _ in group]
            if not all(os.path.exists(v) for v in videos):
                continue
            if len(group) < per and not finish:
                log(f"Tập {episode_no} mới có {len(group)}/{per} chương; thêm chương hoặc chạy --finish.", "Tập")
                continue
            first, last = group[0][0], group[-1][0]
            name = f"{self.project.slug}_Tap{episode_no:03d}_Chuong{first:04d}-{last:04d}.mp4"
            out = os.path.join(self.project.output_dir, "episodes", name)
            fp = fingerprint([(v, os.path.getsize(v), int(os.path.getmtime(v))) for v in videos])
            record = state.get(str(episode_no), {})
            if record.get("fp") == fp and (os.path.exists(out) or record.get("uploaded")):
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            log(f"Ghép tập {episode_no}: chương {first}-{last}", "Tập")
            self.renderer().concat_videos(videos, out)
            record = {"fp": fp, "file": name, "uploaded": False}
            if ucfg.get("enabled", True):
                marker = f"{out}.uploaded"
                if os.path.exists(marker):
                    os.remove(marker)
                record["uploaded"] = self.drive.upload(out, self.project.slug, delete_after=bool(ucfg.get("delete_local_episode", True)))
            state[str(episode_no)] = record
            write_json(self.project.episodes_state_path, state)
