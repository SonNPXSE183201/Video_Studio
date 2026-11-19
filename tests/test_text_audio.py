import os
import tempfile
import unittest

import numpy as np

from core.asr_checker import char_error_rate
from core.audio_utils import read_wav, trim_silence, write_wav
from core.subtitle import SubtitleGenerator, split_caption
from core.text_processor import DEFAULT_PAUSES, build_chunks, clean_paragraphs
from core.vi_normalizer import normalize_for_tts, number_to_words


class NormalizerTests(unittest.TestCase):
    def test_numbers(self):
        cases = {
            15: "mười lăm", 21: "hai mươi mốt", 24: "hai mươi tư", 105: "một trăm linh năm",
            1005: "một nghìn không trăm linh năm", 1998: "một nghìn chín trăm chín mươi tám",
            2500000000: "hai tỷ năm trăm triệu",
        }
        for number, words in cases.items():
            self.assertEqual(words, number_to_words(number))

    def test_system_panel_is_speakable(self):
        text = normalize_for_tts("【LV1: Tốc độ sinh trưởng +20% ×50, lv0】")
        self.assertNotRegex(text, r"[\d【】%×]")
        self.assertIn("cấp một", text)
        self.assertIn("tăng hai mươi phần trăm", text)
        self.assertIn("nhân năm mươi", text)

    def test_vietnamese_number_formats(self):
        self.assertIn("một nghìn năm trăm", normalize_for_tts("1.500 linh thạch"))
        self.assertIn("ba phẩy năm", normalize_for_tts("3,5 cân"))
        self.assertIn("ba đến năm", normalize_for_tts("3-5 ngày"))
        self.assertIn("vi ai pi", normalize_for_tts("thẻ VIP"))
        self.assertIn("box hai", normalize_for_tts("box2"))


class ChunkTests(unittest.TestCase):
    def setUp(self):
        raw = (
            "Chương 7: Trở về năm 1998\n\n"
            "“Ngày mai ta lại tới.”\n\n“......”\n\n"
            "Hắn đứng dậy, " + "rất lâu rất lâu, " * 20 + "rồi đi ra cửa. Trời mưa.\n\n"
            "Cô ấy hỏi: “Anh đi đâu?”"
        )
        self.paragraphs = clean_paragraphs(raw)
        self.chunks = build_chunks(self.paragraphs, max_chars=120)

    def test_chunks_respect_max_length(self):
        self.assertTrue(all(len(c["display"]) <= 120 for c in self.chunks))

    def test_title_and_dialogue_pauses(self):
        self.assertTrue(self.chunks[0]["is_title"])
        self.assertEqual(DEFAULT_PAUSES["title"], self.chunks[0]["pause_after_ms"])
        self.assertIn("một nghìn chín trăm chín mươi tám", self.chunks[0]["tts"])
        # "......" không đọc mà thành nhịp nghỉ dài sau câu thoại trước nó
        self.assertGreaterEqual(self.chunks[1]["pause_after_ms"], DEFAULT_PAUSES["paragraph"] + DEFAULT_PAUSES["ellipsis"])
        self.assertFalse(any(c["display"].strip("“”. …") == "" for c in self.chunks))

    def test_comma_split_keeps_rising_intonation(self):
        comma_chunks = [c for c in self.chunks if c["display"].rstrip().endswith(",")]
        self.assertTrue(comma_chunks)
        for chunk in comma_chunks:
            self.assertEqual(DEFAULT_PAUSES["comma"], chunk["pause_after_ms"])
            self.assertTrue(chunk["tts"].endswith(","))

    def test_ids_are_sequential(self):
        self.assertEqual(list(range(len(self.chunks))), [c["id"] for c in self.chunks])


class AudioTests(unittest.TestCase):
    def test_trim_silence_keeps_padding(self):
        sr = 24000
        tone = 0.5 * np.sin(np.linspace(0, 440 * 2 * np.pi, sr)).astype(np.float32)
        padded = np.concatenate([np.zeros(sr), tone, np.zeros(sr)])
        trimmed = trim_silence(padded, sr, lead_ms=30, tail_ms=60)
        self.assertAlmostEqual(1.09, trimmed.size / sr, delta=0.03)

    def test_wav_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.wav")
            write_wav(path, np.zeros(2400, dtype=np.float32), 24000)
            data, sr = read_wav(path)
            self.assertEqual((2400, 24000), (data.size, sr))

    def test_cer(self):
        self.assertEqual(0.0, char_error_rate("Ngày mai, ta lại tới.", "ngày mai ta lại tới"))
        self.assertGreater(char_error_rate("Ngày mai ta lại tới", "ngày tới"), 0.3)


class SubtitleTests(unittest.TestCase):
    def test_long_lines_are_split(self):
        text = "Kế Duyên nhìn xem cái này hắc bào nam tử chậm rãi từng bước đạp bên bờ, vừa mới chuẩn bị đóng lại viện môn, chưa từng nghĩ sát vách viện tử lại đi ra một người."
        parts = split_caption(text, 84)
        self.assertTrue(all(len(p) <= 84 for p in parts))
        self.assertEqual(text.split(), " ".join(parts).split())
        with tempfile.TemporaryDirectory() as tmp:
            path = SubtitleGenerator({}).generate(
                {"chunks": [{"display": text + " {x}", "start_ms": 0, "end_ms": 9000}]}, os.path.join(tmp, "s.ass")
            )
            content = open(path, encoding="utf-8").read()
        self.assertGreaterEqual(content.count("Dialogue:"), 2)
        self.assertNotIn("{x}", content)
        self.assertIn("0:00:09.00", content)


if __name__ == "__main__":
    unittest.main()
