"""Chạy trọn pipeline (chương thật -> MP4 thật) với model AI giả lập.

Kiểm chứng phần điều phối, cache, đồng bộ hình-tiếng, QA vẽ lại, TTS sinh lại, render
FFmpeg. Model AI thật (OmniVoice/Ollama/ComfyUI) chỉ kiểm được trên GPU pod bằng
`python studio.py check` và `run --until ...`.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from core.pipeline import Studio
from core.project import Project
from core.utils import read_json, read_yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAPTER = os.path.join(ROOT, "projects", "thu_nghiem", "chapters", "Chuong_0001.txt")


class FakeOllama:
    model, vision_model, host = "fake-llm", "fake-vlm", "fake"

    def __init__(self):
        self.qa_calls = 0

    def health(self):
        return True

    def has_model(self, name):
        return True

    def unload_all(self):
        pass

    def generate_json(self, prompt, system_prompt="", images=None, model=None, temperature=None):
        if "GENRE PRESETS" in prompt:
            return {"genre": "tien_hiep", "art_style": "3d_donghua", "era_en": "ancient", "setting_en": "a cultivation world", "reason_vi": "tu tiên"}
        if "KNOWN CHARACTERS" in prompt:
            return {
                "characters": [
                    {"id": "", "canonical_name": "Kế Duyên", "gender": "male", "role": "main", "appearance_en": "young man, black hair, thin face", "outfit_en": "grey robe"},
                    {"id": "", "canonical_name": "Hoàng lão đầu", "aliases": ["Hoàng lão"], "gender": "male", "role": "supporting", "appearance_en": "old bald man with a pipe"},
                ],
                "locations": [{"name": "Tằng Đầu Thị", "description_en": "lakeside market town with wooden houses"}],
            }
        if images:
            self.qa_calls += 1
            is_scene = "portrait of" not in prompt and "people: single" in prompt
            if is_scene and not getattr(self, "failed_once", False):  # một ảnh cảnh bị chê -> phải vẽ lại
                self.failed_once = True
                return {"people_count": 3, "matches_scene": 2, "anachronism": True, "anachronism_items": ["car"]}
            people = 0 if "Intended number of people: none" in prompt else 1
            return {"people_count": people, "matches_scene": 8, "anachronism": False, "deformed": False, "has_text": False}
        if "SCENES:" in prompt:
            payload = json.loads(prompt.split("SCENES:\n", 1)[1].split("\n\nReturn", 1)[0])
            scenes = []
            for item in payload:
                has_hero = "Kế Duyên" in item["text"]
                scenes.append({
                    "scene_index": item["scene_index"],
                    "visual_type": "character" if has_hero else "environment",
                    "population_mode": "single" if has_hero else "none",
                    "visible_character_ids": ["keduyen"] if has_hero else [],
                    "focus_character_id": "keduyen" if has_hero else "",
                    "subject_en": "a young cultivator" if has_hero else "a quiet courtyard",
                    "location_id": "tangdauthi",
                    "shot_type": "medium_shot",
                    "motion_priority": 3 if item["scene_index"] % 4 == 0 else 1,
                    "speaker_id": "keduyen" if has_hero and "“" in item["text"] else "",
                    "action_beats_en": ["he picks up a cup", "he drinks slowly"] if has_hero else [],
                    "props_en": "a tea cup",
                })
            return {"scenes": scenes}
        return None


class FakeComfy:
    host = "fake"

    def health(self):
        return True

    def free_memory(self):
        pass


class FakeImages:
    active_workflow, edit_enabled = "fake", False

    def __init__(self):
        self.calls = []

    def settings_fingerprint(self):
        return {"fake": 1}

    def generate(self, positive, negative, seed, output_path, refs=None):
        from PIL import Image, ImageDraw

        self.calls.append(output_path)
        rng = np.random.default_rng(seed % (2**32))
        color = tuple(int(c) for c in rng.integers(40, 220, 3))
        img = Image.new("RGB", (832, 464), color)
        ImageDraw.Draw(img).ellipse((300, 100, 530, 360), fill=(255, 255, 255))
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
        return output_path


class FakeMotion:
    ready, s2v_ready, model = True, True, "fake"

    def __init__(self):
        self.calls = 0
        self.s2v_calls = []

    def settings_fingerprint(self):
        return {"fake": 1}

    def s2v_fingerprint(self):
        return {"fake_s2v": 1}

    def clips_needed(self, seconds):
        return max(1, min(4, int(seconds // 2.4) + 1))

    def _clip(self, image_path, seconds, output_path):
        subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", image_path, "-t", f"{seconds:.2f}",
                        "-vf", "scale=416:232,zoompan=z='1+0.002*on':d=48:s=416x232:fps=16",
                        "-pix_fmt", "yuv420p", output_path], capture_output=True, check=True)

    def generate_chain(self, image_path, prompts, negative, seed, seconds, output_path):
        self.calls += 1
        self.last_prompts = prompts
        self._clip(image_path, 2.0 * self.clips_needed(seconds), output_path)
        return True

    def generate_s2v(self, image_path, audio_path, prompt, negative, seed, output_path):
        import soundfile as sf

        data, sr = sf.read(audio_path)
        self.s2v_calls.append({"prompt": prompt, "seconds": len(data) / sr, "voiced": float((abs(data) > 0).mean())})
        self._clip(image_path, len(data) / sr + 0.3, output_path)
        return True


class FakeASR:
    enabled = True

    def __init__(self, tts):
        self.tts = tts

    def transcribe(self, samples, sr):
        text, attempt = self.tts.last
        if "Biết" in text and attempt == 1:
            return "xyz"  # lần đầu "đọc vấp" -> phải sinh lại
        return text

    def unload(self):
        pass


class FakeTTS:
    sample_rate = 24000

    def __init__(self):
        self.attempts = {}
        self.last = ("", 0)

    def synthesize(self, text, ref_audio, ref_text, seed):
        self.attempts[text] = self.attempts.get(text, 0) + 1
        self.last = (text, self.attempts[text])
        sr = self.sample_rate
        seconds = max(0.4, len(re.sub(r"\W", "", text)) / 15.0)
        t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
        voice = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        pad = np.zeros(int(sr * 0.4), dtype=np.float32)  # TTS tự chèn lặng -> phải bị cắt
        return np.concatenate([pad, voice, pad]), sr

    def unload(self):
        pass


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}


@unittest.skipUnless(shutil.which("ffmpeg") and os.path.exists(CHAPTER), "cần ffmpeg và chương mẫu")
class EndToEndTests(unittest.TestCase):
    def test_full_pipeline_with_fake_models(self):
        cfg = copy.deepcopy(read_yaml(os.path.join(ROOT, "config", "settings.yaml")))
        cfg["video"].update({"resolution": [640, 360], "fps": 12, "encoder": "libx264", "x264_preset": "ultrafast",
                             "ken_burns": {"zoom": 1.1, "supersample": 1}})
        cfg["video"]["bgm"]["enabled"] = False
        cfg["upload"]["enabled"] = False
        cfg["motion"]["ratio"] = 0.2
        from core.utils import set_log_file

        self.addCleanup(set_log_file, None)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project = Project(tmp, "E2E Test")
            project.create("E2E Test")
            with open(CHAPTER, encoding="utf-8") as handle:
                paragraphs = [p for p in handle.read().split("\n") if p.strip()][:40]
            with open(os.path.join(project.chapters_dir, "Chuong_0001.txt"), "w", encoding="utf-8") as handle:
                handle.write("\n\n".join(paragraphs))
            series = project.load_series()
            series["watermark"] = "Kênh Thử"
            series["voice"]["ref_audio"] = os.path.join(ROOT, "assets", "voices", "default.wav")
            series["voice"]["ref_text"] = os.path.join(ROOT, "assets", "voices", "default.txt")
            project.save_series(series)

            def make_studio():
                studio = Studio(copy.deepcopy(cfg), project, {})
                tts = FakeTTS()
                studio.ollama, studio.comfy = FakeOllama(), FakeComfy()
                studio._images, studio._motion = FakeImages(), FakeMotion()
                studio.tts.synthesize = tts.synthesize
                studio.audio.asr = studio.asr = FakeASR(tts)
                return studio, tts

            studio, tts = make_studio()
            self.assertTrue(studio.run(finish=True))

            video = project.chapter_video_path(1)
            timeline = read_json(os.path.join(project.work_dir, "ch0001", "audio", "timeline.json"))
            streams = probe(video)
            # Đồng bộ: hình và tiếng dài bằng nhau và bằng timeline lời đọc.
            self.assertAlmostEqual(timeline["total_duration_sec"], streams["video"], delta=0.25)
            self.assertAlmostEqual(streams["audio"], streams["video"], delta=0.25)
            # TTS: chunk "Biết." bị ASR báo vấp lần đầu -> được sinh lại, không còn cảnh báo.
            self.assertEqual(2, tts.attempts["Biết."])
            self.assertEqual([], timeline["warnings"])
            # Khoảng lặng TTS tự chèn (0.4s mỗi đầu) đã bị cắt trước khi ghép.
            first = timeline["chunks"][0]
            self.assertLess(first["end_ms"] - first["start_ms"], 3000)
            # Ảnh: 1 ảnh bị QA chê -> vẽ lại; casting tạo ảnh mẫu cho nhân vật chính.
            scenes = read_json(os.path.join(project.work_dir, "ch0001", "scenes.json"))["scenes"]
            draws = studio._images.calls
            scene_draws = [c for c in draws if "scene_" in c]
            self.assertEqual(len(scenes) + 1, len(scene_draws))
            self.assertTrue(any("candidate_" in c for c in draws))
            self.assertTrue(studio.chars.get_reference_image("keduyen"))
            self.assertGreater(studio._motion.calls, 0)
            # Phim: mọi cảnh đều có chuyển động; cảnh thoại của nhân vật một mình -> nhép miệng S2V
            # với audio chỉ giữ phần thoại (dẫn truyện bị tắt tiếng).
            self.assertEqual(len(scenes), studio._motion.calls + len(studio._motion.s2v_calls))
            self.assertTrue(studio._motion.s2v_calls)
            self.assertTrue(all("speaking" in c["prompt"] for c in studio._motion.s2v_calls))
            self.assertTrue(all(0 < c["voiced"] <= 1 for c in studio._motion.s2v_calls))
            series = project.load_series()
            self.assertEqual("tien_hiep", series["genre"])
            for sub in ("storyboards", "thumbnails", "reports"):
                self.assertTrue(os.path.exists(os.path.join(project.output_dir, sub, "Chuong_0001." + ("md" if sub == "reports" else "jpg"))))
            episodes = read_json(project.episodes_state_path)
            self.assertIn("1", episodes)

            # Chạy lại: mọi thứ lấy từ cache, không vẽ/không đọc/không render lại.
            mtime = os.path.getmtime(video)
            studio2, tts2 = make_studio()
            self.assertTrue(studio2.run(finish=True))
            self.assertEqual([], studio2._images.calls)
            self.assertEqual({}, tts2.attempts)
            self.assertEqual(0, studio2._motion.calls)
            self.assertEqual([], studio2._motion.s2v_calls)
            self.assertEqual(mtime, os.path.getmtime(video))

            # Đã lên Drive -> .done, xóa file nặng; lần chạy sau bỏ qua chương này.
            freed = project.mark_done(1, {"episode": 1})
            self.assertGreater(freed, 0)
            self.assertFalse(os.path.exists(video))
            self.assertFalse(os.path.exists(os.path.join(project.work_dir, "ch0001", "images")))
            self.assertTrue(os.path.exists(os.path.join(project.work_dir, "ch0001", "scenes.json")))
            studio3, tts3 = make_studio()
            self.assertFalse(studio3.run(finish=True))   # không còn chương nào cần làm
            self.assertEqual([], studio3._images.calls)
            self.assertEqual({}, tts3.attempts)


if __name__ == "__main__":
    unittest.main()
