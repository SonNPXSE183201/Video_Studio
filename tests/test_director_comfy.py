import json
import os
import tempfile
import unittest

from core.character_registry import CharacterRegistry
from core.comfy_client import ComfyClient, ImageGenerator
from core.location_registry import LocationRegistry
from core.motion_client import MotionGenerator
from core.scene_director import SceneDirector
from core.series_analyzer import heuristic_genre
from core.style import list_styles, load_art_style, load_style
from core.utils import read_yaml


class FakeOllama:
    model = "fake"

    def __init__(self, responses=None):
        self.responses = list(responses or [])

    def generate_json(self, prompt, system_prompt="", **kwargs):
        return self.responses.pop(0) if self.responses else None


class StyleTests(unittest.TestCase):
    def test_all_presets_load_and_inherit_base(self):
        ids = [s[0] for s in list_styles()]
        for required in ("tien_hiep", "do_thi_tq_1990s", "do_thi_tq_2000s", "do_thi_tq_2010s", "linh_di", "mat_the"):
            self.assertIn(required, ids)
        for style_id in ids:
            style = load_style(style_id)
            self.assertIn("single", style["population_negative"], style_id)
            self.assertTrue(style.get("world_en"), style_id)
            load_art_style(style["default_art_style"])

    def test_themes_add_rules_without_changing_era(self):
        from core.style import apply_themes, list_themes

        self.assertEqual({"kinh_doanh", "quan_truong", "dau_tri"}, {t[0] for t in list_themes()})
        style = apply_themes(load_style("do_thi_tq_1980s"), ["quan_truong", "kinh_doanh", "khong_co"])
        self.assertEqual(["quan_truong", "kinh_doanh"], style["themes"])
        self.assertIn("1980s", style["director_rules_en"])          # thời đại giữ nguyên
        self.assertIn("officialdom", style["director_rules_en"])     # luật quan trường được cộng thêm
        self.assertIn("readable slogans", style["negative"])
        patterns = " ".join(g["pattern"] for g in style["context_guards"])
        self.assertIn("thường vụ", patterns)
        self.assertIn("hợp đồng", patterns)
        self.assertIn("tem phiếu", patterns)                        # guard gốc của preset vẫn còn

    def test_genre_by_chapter_and_era_detection(self):
        from core.style import detect_era_genre, genre_for_chapter

        series = {"genre": "do_thi_tq_1990s", "genre_by_chapter": {"1-150": "do_thi_tq_1990s", "151-": "do_thi_tq_2000s"}}
        self.assertEqual("do_thi_tq_1990s", genre_for_chapter(series, 150))
        self.assertEqual("do_thi_tq_2000s", genre_for_chapter(series, 151))
        self.assertEqual("do_thi_tq_1990s", genre_for_chapter({"genre": "do_thi_tq_1990s"}, 999))
        text = "Năm 2003, công ty lên sàn. Đến năm 2005 doanh thu gấp đôi, cuối năm 2006 mở chi nhánh."
        self.assertEqual("do_thi_tq_2000s", detect_era_genre(text, "do_thi_tq_1990s")[0])
        # một lần nhắc hồi tưởng không đủ để đổi thời đại
        self.assertEqual("", detect_era_genre("Hắn nhớ lại năm 2010 kiếp trước.", "do_thi_tq_1990s")[0])
        # thể loại không có mốc năm (tiên hiệp) không bị ảnh hưởng
        self.assertEqual("", detect_era_genre(text, "tien_hiep")[0])

    def test_heuristic_themes(self):
        from core.series_analyzer import heuristic_themes

        text = "Bí thư huyện ủy triệu tập họp thường vụ. Huyện trưởng phản đối. Kỷ ủy vào cuộc. " * 2
        self.assertIn("quan_truong", heuristic_themes(text))
        self.assertEqual("do_thi_tq_1980s", heuristic_genre("Năm 1984, hắn cầm tem phiếu, phiếu gạo ra công xã"))

    def test_heuristic_genre(self):
        self.assertEqual("tien_hiep", heuristic_genre("Hắn Luyện Khí tầng hai, có ba khối linh thạch, tông môn"))
        self.assertEqual("do_thi_tq_1990s", heuristic_genre("Năm 1996, hắn cầm máy nhắn tin, đại ca đại"))


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bible = os.path.join(self.tmp.name, "bible")
        self.chars = CharacterRegistry(os.path.join(bible, "characters.json"))
        self.locs = LocationRegistry(os.path.join(bible, "locations.json"))
        self.a = self.chars.upsert_from_analysis(
            {"canonical_name": "Lâm Phong", "gender": "male", "role": "main",
             "appearance_en": "solo, 1man, short black hair, sharp eyes", "outfit_en": "white shirt, grey trousers"}, 1)
        self.b = self.chars.upsert_from_analysis(
            {"canonical_name": "Tô Tình", "gender": "female", "appearance_en": "long hair, gentle face"}, 1)
        self.home = self.locs.upsert({"name": "Khu tập thể nhà máy dệt", "description_en": "grey five-storey danwei apartment block, laundry on bamboo poles"}, 1)

    def tearDown(self):
        self.tmp.cleanup()

    def director(self, style_id="do_thi_tq_1990s", responses=None):
        style = load_style(style_id)
        return SceneDirector(FakeOllama(responses), self.chars, self.locs, style,
                             load_art_style(style["default_art_style"]), {"era_en": "mainland China, 1995"},
                             {"batch_size": 6, "max_visible_characters": 2})

    def test_population_tags_removed_from_bible(self):
        self.assertNotIn("1man", self.chars.get_character_prompt(self.a, 1))
        self.assertIn("white shirt", self.chars.get_character_prompt(self.a, 5))  # trang phục chương gần nhất

    def test_group_scenes_respects_paragraphs_and_limits(self):
        chunks = [{"id": i, "para": i // 2, "display": "x" * 100, "is_title": i == 0} for i in range(12)]
        scenes = SceneDirector.group_scenes(chunks, target_chars=230, max_chars=360)
        flat = [cid for s in scenes for cid in s["chunk_ids"]]
        self.assertEqual(list(range(12)), flat)
        self.assertTrue(all(len(s["text"]) <= 360 + 3 for s in scenes))

    def test_urban_prompt_has_no_xianxia_and_keeps_location(self):
        response = {"scenes": [
            {"scene_index": 1, "visual_type": "dialogue", "population_mode": "pair",
             "visible_character_ids": [self.a, self.b], "focus_character_id": self.a,
             "subject_en": "a young man talks to a woman in a corridor", "location_id": self.home,
             "time_of_day": "dusk", "shot_type": "medium_shot", "motion_priority": 2},
            {"scene_index": 2, "visual_type": "character", "visible_character_ids": [self.a],
             "subject_en": "the man lights a cigarette", "shot_type": "close_up"},
        ]}
        director = self.director(responses=[response])
        directed = director.direct([
            {"index": 1, "text": "Lâm Phong nói với Tô Tình.", "chunk_ids": [0]},
            {"index": 2, "text": "Hắn châm điếu thuốc.", "chunk_ids": [1]},
        ], 1)
        compiled = director.compile(directed, 1)
        first, second = compiled
        self.assertEqual("pair", first["meta"]["population_mode"])
        self.assertIn("exactly two different people", first["positive"])
        self.assertIn("danwei apartment block", first["positive"])
        self.assertNotIn("xianxia", first["positive"].lower())
        self.assertIn("smartphone", first["negative"])
        # cảnh 2 không nêu địa điểm -> kế thừa cảnh 1 (liên tục bối cảnh)
        self.assertEqual(self.home, second["meta"]["location_id"])
        self.assertEqual("dusk", second["meta"]["time_of_day"])
        self.assertNotIn("two people", first["negative"])  # cảnh 2 người không được cấm "two people"

    def test_failed_llm_falls_back_to_one_named_character(self):
        director = self.director(responses=[None, None, None])
        directed = director.direct([{"index": 1, "text": "Lâm Phong nhìn Tô Tình.", "chunk_ids": [0]}], 1)
        self.assertTrue(directed[0]["meta"]["fallback"])
        self.assertEqual([self.a], directed[0]["meta"]["visible_character_ids"])

    def test_overrides_apply_without_llm(self):
        director = self.director(responses=[{"scenes": [{"scene_index": 1, "visual_type": "environment"}]}])
        directed = director.direct([{"index": 1, "text": "Trời mưa.", "chunk_ids": [0]}], 1)
        compiled = director.compile(directed, 1, lambda idx: {"characters": ["Lâm Phong"], "extra_en": "neon rain"})
        self.assertEqual([self.a], compiled[0]["meta"]["visible_character_ids"])
        self.assertIn("neon rain", compiled[0]["positive"])

    def test_people_guards_do_not_conflict_with_population(self):
        from core.style import apply_themes

        style = apply_themes(load_style("do_thi_tq_1990s"), ["quan_truong", "dau_tri"])
        responses = [{"scenes": [
            {"scene_index": 1, "visual_type": "character", "visible_character_ids": [self.a], "subject_en": "a man stands"},
            {"scene_index": 2, "visual_type": "dialogue", "visible_character_ids": [self.a, self.b], "subject_en": "two talk"},
            {"scene_index": 3, "visual_type": "environment", "subject_en": "an empty hall"},
        ]}]
        director = SceneDirector(FakeOllama(responses), self.chars, self.locs, style, load_art_style("cinematic_realistic"), {}, {})
        text = "Cuộc họp thường vụ, bí thư tính toán mưu kế."
        compiled = director.compile(director.direct([{"index": i, "text": text, "chunk_ids": [i]} for i in (1, 2, 3)], 1), 1)
        single, pair, empty = (c["positive"] for c in compiled)
        self.assertNotIn("meeting table", single)
        self.assertIn("calculating eyes", single)
        self.assertIn("meeting table", pair)
        self.assertNotIn("calculating eyes", empty)
        self.assertNotIn("official in a dark jacket", empty)

    def test_xianxia_guards(self):
        director = self.director("tien_hiep", [{"scenes": [{"scene_index": 1, "visual_type": "environment", "subject_en": "a fish pond"}]}])
        directed = director.direct([{"index": 1, "text": "Hệ thống nâng cấp ao cá.", "chunk_ids": [0]}], 1)
        positive = director.compile(directed, 1)[0]["positive"]
        self.assertIn("no interface", positive)
        self.assertIn("homestead", positive)


class FakeComfy(ComfyClient):
    def __init__(self, info):
        super().__init__("http://fake")
        self._object_info = info


def node(required):
    return {"input": {"required": required}}


class ComfyTests(unittest.TestCase):
    def test_template_optional_nodes_are_bypassed(self):
        template = ComfyClient.load_template("qwen_image_edit")
        graph = ComfyClient.fill_template(template, {
            "positive": "p", "negative": "n", "seed": 5, "width": 64, "height": 64, "unet": "u", "clip": "c",
            "vae": "v", "lora": "", "lora_strength": 1, "shift": 3, "steps": 8, "cfg": 1, "sampler": "euler",
            "scheduler": "simple", "ref_image_1": "a.png", "ref_image_2": "",
        })
        self.assertNotIn("4", graph)                       # LoRA rỗng bị gỡ
        self.assertEqual(["1", 0], graph["5"]["inputs"]["model"])  # nối thẳng UNET
        self.assertNotIn("21", graph)                      # ảnh mẫu 2 rỗng bị gỡ
        self.assertNotIn("image2", graph["6"]["inputs"])
        self.assertEqual(5, graph["9"]["inputs"]["seed"])
        self.assertTrue(all("_optional" not in n for n in graph.values()))
        json.dumps(graph)

    def test_falls_back_to_sdxl_when_qwen_models_missing(self):
        info = {
            "UNETLoader": node({"unet_name": [["other.safetensors"]]}),
            "CLIPLoader": node({"clip_name": [["x"]]}), "VAELoader": node({"vae_name": [["x"]]}),
            "LoraLoaderModelOnly": node({"lora_name": [["x"]]}), "ModelSamplingAuraFlow": node({}),
            "CLIPTextEncode": node({}), "EmptySD3LatentImage": node({}), "KSampler": node({}),
            "VAEDecode": node({}), "SaveImage": node({}),
            "CheckpointLoaderSimple": node({"ckpt_name": [["sd_xl_base_1.0.safetensors"]]}),
            "LoraLoader": node({"lora_name": [["3d_render_style_xl.safetensors"]]}),
            "EmptyLatentImage": node({}), "CLIPTextEncodeSDXL": node({}),
        }
        cfg = read_yaml(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml"))["image"]
        gen = ImageGenerator(FakeComfy(info), cfg, load_art_style("3d_donghua"))
        gen.prepare()
        self.assertEqual("sdxl", gen.active_workflow)
        self.assertFalse(gen.edit_enabled)
        graph = gen._sdxl_graph({"positive": "a man in a 1990s street", "negative": "n", "seed": 1})
        # Nội dung cảnh phải nằm ở cả text_g (encoder mạnh) chứ không chỉ text_l
        self.assertIn("1990s street", graph["6"]["inputs"]["text_g"])
        self.assertEqual(["10", 0], graph["3"]["inputs"]["model"])

    def test_motion_graphs_are_valid_links(self):
        cfg = read_yaml(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml"))["motion"]
        for model in ("wan22_5b", "wan22_14b"):
            gen = MotionGenerator(FakeComfy({}), {**cfg, "model": model})
            graph = gen.build("img.png", "p", "n", 7)
            for node_id, nd in graph.items():
                for value in nd["inputs"].values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                        self.assertIn(str(value[0]), graph, f"{model}: node {node_id} trỏ tới node không tồn tại {value}")
            length = graph["7" if model == "wan22_5b" else "16"]["inputs"]["length"]
            self.assertEqual(0, (length - 1) % 4)

    def test_s2v_graph_chains_chunks(self):
        cfg = read_yaml(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml"))["motion"]
        gen = MotionGenerator(FakeComfy({}), cfg)
        graph = gen.build_s2v("img.png", "a.wav", "p", "n", 7, 3)
        for node_id, nd in graph.items():
            for value in nd["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                    self.assertIn(str(value[0]), graph, f"S2V: node {node_id} trỏ tới node không tồn tại {value}")
        kinds = [nd["class_type"] for nd in graph.values()]
        self.assertEqual(1, kinds.count("WanSoundImageToVideo"))
        self.assertEqual(2, kinds.count("WanSoundImageToVideoExtend"))
        self.assertEqual(3, kinds.count("KSampler"))
        # Như template: nhân đôi latent đầu, bỏ 3 ảnh đầu sau khi giải mã.
        self.assertEqual(3, graph["23"]["inputs"]["batch_index"])

    def test_chain_clip_count(self):
        cfg = read_yaml(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml"))["motion"]
        gen = MotionGenerator(FakeComfy({}), cfg)
        clip = gen.clip_seconds()
        self.assertAlmostEqual(81 / 16, clip, places=3)
        self.assertEqual(1, gen.clips_needed(5.5))
        self.assertEqual(2, gen.clips_needed(9.0))
        self.assertEqual(4, gen.clips_needed(60.0))


if __name__ == "__main__":
    unittest.main()
