# 🎬 AI Video Studio

Biến chương truyện chữ tiếng Việt thành video hoàn chỉnh như một bộ phim:
- giọng đọc AI clone, nhân vật nhép miệng khi thoại;
- ảnh đúng nhân vật, bối cảnh và sự kiện của chương;
- mọi cảnh đều chuyển động;
- phụ đề và nhạc nền;
- ghép tập và đẩy lên Google Drive.

Chạy hoàn toàn bằng terminal trên RunPod.

**Bạn chỉ cần thả file chương `.txt` vào, tool tự làm phần còn lại.**

## Quy trình tự động

| Bước | Tool làm gì | Tự kiểm tra |
|---|---|---|
| Phân tích bộ truyện | LLM đọc 3 chương đầu, chọn **thể loại + chủ đề + thời đại + phong cách vẽ**, ghi vào `series.yaml` | dùng từ khóa nếu LLM lỗi |
| Story Bible | Quét **nhân vật** (ngoại hình cố định, trang phục theo chương) và **địa điểm** | gộp bí danh, không ghi đè ngoại hình đã ổn định |
| Đạo diễn | Chia cảnh khoảng 10 giây như phim. LLM mô tả **sự kiện, đồ vật, tương tác** trong chương, 2–4 nhịp hành động mỗi cảnh, ai đang nói, góc máy đa dạng | thử lại lô nhỏ hơn; cảnh lỗi được ghi trong báo cáo |
| Giọng đọc | Chuẩn hóa văn bản (số, %, Lv, 【】, từ mượn), chia đoạn ≤160 ký tự, OmniVoice seed cố định, nhịp nghỉ theo dấu câu | **PhoWhisper nghe lại**; sai > 15% thì đọc lại (tối đa 3 lần) |
| Casting | Vẽ 3 ảnh chân dung cho nhân vật quan trọng; model thị giác chọn ảnh tốt nhất làm ảnh mẫu | — |
| Vẽ ảnh | **Qwen-Image-Edit** vẽ mọi cảnh (một model, không phải nạp lại), giữ mặt nhân vật theo ảnh mẫu. Qwen-Image và SDXL làm dự phòng | **model thị giác kiểm** số người, sai thời đại, dị dạng, chữ; lỗi thì vẽ lại |
| Chuyển động | **Mọi cảnh** đều chuyển động bằng Wan 2.2: nhiều clip nối tiếp theo các nhịp hành động. Cảnh nhân vật nói thoại dùng **Wan 2.2 S2V nhép miệng**. Model tự chọn theo VRAM/RAM của pod | clip lỗi thì lùi về I2V, cuối cùng là Ken Burns |
| Dựng phim | Crossfade, phụ đề 2 dòng, watermark, nhạc nền tự nhỏ đi khi có lời, chuẩn âm lượng −16 LUFS | hình và tiếng khớp tuyệt đối theo timeline |
| Đóng gói | Ghép tập (mặc định 10 chương), upload vào thư mục Drive riêng của từng bộ truyện, đánh dấu `.done` và dọn file | upload lỗi thì giữ file, lần sau thử lại |

Mỗi bước có cache riêng: chạy lại chỉ làm phần đã thay đổi. Pod tắt giữa chừng thì lần chạy sau làm tiếp từ chỗ dừng.

## Thể loại có sẵn

```
tien_hiep          Tiên hiệp / tu tiên cổ đại           (mặc định vẽ: hoạt hình 3D)
huyen_huyen        Huyền huyễn / đấu khí                (3D)
lich_su_co_dai     Lịch sử / cung đấu / ngôn tình cổ    (điện ảnh)
do_thi_tq_1980s    Trung Quốc thập niên 1980 (niên đại) (điện ảnh)
do_thi_tq_1990s    Đô thị Trung Quốc thập niên 1990     (điện ảnh)
do_thi_tq_2000s    Đô thị Trung Quốc thập niên 2000     (điện ảnh)
do_thi_tq_2010s    Đô thị Trung Quốc 2010-2015          (điện ảnh)
do_thi_hien_dai    Đô thị hiện đại                      (điện ảnh)
mat_the            Mạt thế / zombie                     (điện ảnh)
linh_di            Linh dị / kinh dị                    (điện ảnh)
khoa_huyen         Khoa huyễn / tương lai               (3D)
```

**Chủ đề cộng thêm** (`themes` trong `series.yaml`, chọn nhiều được, tool tự nhận diện):

```
kinh_doanh    Kinh doanh / trọng sinh làm giàu / thương chiến
quan_truong   Quan trường / chính trường
dau_tri       Đấu trí / mưu lược / trinh thám
```

**Truyện kéo dài nhiều thập kỷ:** tool đếm các năm được nhắc trong từng chương. Nếu chương đã sang thập kỷ khác, tool tự dùng preset đúng thời đại cho chương đó. Muốn cố định thì khai báo trong `series.yaml`:

```yaml
genre_by_chapter:
  "1-150": do_thi_tq_1990s
  "151-400": do_thi_tq_2000s
  "401-": do_thi_tq_2010s
```

## Sử dụng trên RunPod

> Hướng dẫn đầy đủ (chọn GPU, tài khoản mới, Stop/Start, sự cố, số đo thực tế): **[docs/HUONG_DAN_RUNPOD.md](docs/HUONG_DAN_RUNPOD.md)**

### 1. Tạo pod
- Template **PyTorch 2.8, CUDA 12.8.1**.
- **Container disk 200 GB**: setup chép model hay dùng sang ổ này để đọc nhanh.
- Volume gắn tại `/workspace`. Volume Global hoặc Network đều được.
- GPU có NVENC, **RAM ≥ 40 GB** để dùng Wan 14B + nhép miệng. Gợi ý: A40 (rẻ nhất), RTX PRO 4500 SE, L40S (tự lên mức "cao"), RTX PRO 6000 (mức "tối đa"). Bảng chi tiết: mục 2 trong hướng dẫn.
- Tool **tự phát hiện VRAM/RAM** rồi chọn model: pod mạnh dùng Wan 14B + nhép miệng; pod yếu tự lùi về Wan 5B và bỏ nhép miệng.

### 2. Cài đặt: chạy lại đúng lệnh này sau mỗi lần Start pod
```bash
curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
cd /root/AI_Video_Studio
bash run.sh check
```
- Lần đầu khoảng 40–60 phút, chủ yếu để tải khoảng 150 GB model vào volume.
- Những lần sau khoảng 10–20 phút: không tải lại, chỉ cài Python và chép model sang ổ nhanh.

### 3. Google Drive
1. Đặt `rclone.conf` (remote tên `gdrive`) vào `/workspace/rclone.conf`.
2. Mọi thứ được upload vào thư mục Drive có ID ghi trong `config/settings.yaml > upload.root_folder_id`.
3. Mỗi bộ truyện tự có một thư mục con mang tên truyện:
   - `<Tên truyện>/`: video tập (ghép 10 chương).
   - `<Tên truyện>/review/`: storyboard và báo cáo lỗi từng chương.
   - `<Tên truyện>/chapters/`: video từng chương (chỉ khi bật `upload_chapters`).
4. Thử kết nối: `bash run.sh drive <du_an>`.
5. Tập đã lên Drive thì các chương của tập được đánh dấu **`.done`**, file nặng bị xóa (~1 GB/chương), và lần chạy sau tự bỏ qua. Muốn làm lại: `--force done`.

### 4. Làm phim
```bash
bash run.sh new "Ten Bo Truyen" --from /workspace/upload     # tạo dự án, nhập các file chương .txt
bash run.sh run ten_bo_truyen --chapters 1 --until images     # xem thử ảnh chương 1 trước
nohup bash run.sh run ten_bo_truyen --stop-pod > /workspace/run.log 2>&1 &   # chạy hết, xong tự tắt pod (qua RunPod API)
tail -f /workspace/run.log
```

### Xem tool đang làm gì
Mở **Jupyter Lab** của pod → `workspace/video_studio_projects/<du_an>/`. Nháy đúp để xem ảnh, clip và nghe giọng đọc ngay trong trình duyệt:
- `work/ch0001/images/`: ảnh từng cảnh.
- `work/ch0001/motion/`: clip chuyển động.
- `work/ch0001/audio/chapter.wav`: giọng đọc.
- `output/`: video hoàn chỉnh, storyboard, báo cáo.

Tiến độ: `bash run.sh status <du_an>` hoặc `tail -f /workspace/run.log`. Chi tiết: mục 6b trong [hướng dẫn](docs/HUONG_DAN_RUNPOD.md).

**Thêm chương:** kéo file `.txt` vào `workspace/video_studio_projects/<du_an>/chapters/`. Lần chạy `run` sau tự làm các chương chưa xong.

### Lệnh thường dùng
```bash
bash run.sh status ten_bo_truyen                          # tiến độ từng chương (XONG = đã .done)
bash run.sh run ten_bo_truyen --chapters 1-3              # chỉ chạy chương 1-3
bash run.sh run ten_bo_truyen --finish                    # ghép cả tập cuối chưa đủ chương
bash run.sh run ten_bo_truyen --force audio               # làm lại một bước: direct,audio,images,motion,render,analyze,done
bash run.sh redo ten_bo_truyen --ch 3 --scene 12 --stage image   # vẽ lại 1 cảnh
bash run.sh voice ten_bo_truyen giong_moi.wav             # đổi giọng clone (kèm giong_moi.txt)
bash run.sh drive ten_bo_truyen                           # thử upload Drive
bash run.sh analyze ten_bo_truyen                         # nhận diện lại thể loại
bash run.sh styles                                        # danh sách thể loại / chủ đề / phong cách vẽ
bash run.sh check                                         # kiểm tra Ollama, ComfyUI, model, GPU
```

## Cấu trúc thư mục

### Mã nguồn (trên GitHub)
```
AI_Video_Studio/
├── studio.py                 CLI: new, voice, run, redo, analyze, status, styles, check, drive
├── run.sh                    Chạy studio.py bằng đúng Python của pod (kiểm tra Ollama/ComfyUI đang chạy)
├── setup.sh                  Gọi pod/setup_pod.sh; AUTO_RUN=1 PROJECT=<du_an> thì cài xong tự chạy
├── requirements.txt          Thư viện Python của tool (requests, numpy, soundfile, Pillow, PyYAML...)
├── README.md                 File này
├── .gitignore                Không đưa lên git: rclone.conf, *.conf, projects/, file nhạc/font tự thêm
├── .gitattributes            Giữ xuống dòng kiểu Linux (LF) cho script chạy trên pod
│
├── pod/
│   ├── bootstrap.sh          MỘT LỆNH cho pod mới / vừa Start: clone hoặc cập nhật code vào /root, chạy setup
│   └── setup_pod.sh          Cài gói hệ thống, venv, Ollama, ComfyUI; tải model; chép model sang ổ nhanh;
│                             khởi động dịch vụ; chạy check. Biến INSTALL_* bật/tắt từng nhóm model
│
├── config/
│   ├── settings.yaml         Cấu hình chung: LLM, TTS, ASR, ảnh, QA, casting, chuyển động (auto/14B/5B/S2V),
│   │                         dựng phim, phụ đề, nhạc nền, số chương/tập, Google Drive
│   ├── art_styles.yaml       Phong cách vẽ: 3d_donghua, cinematic_realistic, anime_cn, ink_painting
│   ├── styles/               Preset thể loại (thế giới, thời đại, trang phục, đồ vật, luật đạo diễn, negative)
│   │   ├── _base.yaml        Phần chung mọi thể loại kế thừa (khung hình, negative, số người)
│   │   └── tien_hiep.yaml, huyen_huyen.yaml, lich_su_co_dai.yaml, do_thi_tq_1980s/1990s/2000s/2010s.yaml,
│   │       do_thi_hien_dai.yaml, mat_the.yaml, linh_di.yaml, khoa_huyen.yaml
│   └── themes/               Chủ đề cộng thêm vào thể loại: kinh_doanh.yaml, quan_truong.yaml, dau_tri.yaml
│
├── workflows/                Workflow ComfyUI dạng template {{placeholder}}
│   ├── qwen_image.json       Qwen-Image + LoRA Lightning (dự phòng)
│   └── qwen_image_edit.json  Qwen-Image-Edit 2509: vẽ mọi cảnh, giữ mặt nhân vật từ ảnh mẫu
│
├── core/
│   ├── pipeline.py           Điều phối toàn bộ: phân tích -> đạo diễn -> giọng -> ảnh -> chuyển động -> dựng
│   │                         -> ghép tập -> upload -> .done. Cache từng bước, giải phóng VRAM giữa các bước
│   ├── project.py            Cấu trúc thư mục dự án, series.yaml, overrides, trạng thái chương, .done
│   ├── series_analyzer.py    Đọc 3 chương đầu, chọn thể loại / chủ đề / thời đại / phong cách vẽ
│   ├── style.py              Nạp preset thể loại + chủ đề, đổi thời đại theo chương
│   ├── scene_director.py     Story Bible, chia cảnh, LLM đạo diễn (sự kiện, đồ vật, nhịp hành động,
│   │                         người nói), ghép prompt ảnh / chuyển động / nhép miệng
│   ├── character_registry.py Nhân vật: tên, bí danh, ngoại hình cố định, trang phục theo chương, ảnh mẫu
│   ├── location_registry.py  Địa điểm và mô tả cố định
│   ├── ollama_client.py      Gọi LLM / model thị giác (Ollama), trả JSON, giải phóng VRAM
│   ├── text_processor.py     Làm sạch chương, chia đoạn đọc, đánh dấu thoại, nhịp nghỉ theo dấu câu
│   ├── vi_normalizer.py      Chuẩn hóa tiếng Việt cho TTS: số, %, đơn vị, Lv, 【】, từ mượn (hack, game...)
│   ├── tts_engine.py         OmniVoice clone giọng
│   ├── asr_checker.py        PhoWhisper nghe lại, tính tỷ lệ sai để đọc lại đoạn vấp
│   ├── audio_builder.py      Sinh giọng từng đoạn, cache, ghép audio chương + timeline thời gian
│   ├── audio_utils.py        Đọc/ghi wav, cắt lặng, fade, resample (numpy)
│   ├── comfy_client.py       Gọi ComfyUI, điền template, kiểm tra thiếu model, chọn workflow ảnh,
│   │                         tự bỏ LoRA thiếu
│   ├── image_qa.py           Model thị giác chấm ảnh: số người, sai thời đại, dị dạng, chữ
│   ├── hardware.py           Phát hiện GPU/VRAM/RAM của pod để tự chọn model chuyển động
│   ├── motion_client.py      Wan 2.2 14B/5B I2V (nối clip từ khung cuối), Wan 2.2 S2V nhép miệng
│   ├── video_renderer.py     FFmpeg: clip/Ken Burns, crossfade, phụ đề, watermark, nhạc nền, chuẩn âm lượng
│   ├── subtitle.py           Phụ đề ASS 2 dòng theo timeline
│   ├── storyboard.py         Bảng ảnh các cảnh, thumbnail, báo cáo .md mỗi chương
│   ├── drive_sync.py         Upload rclone theo ID thư mục Drive, mỗi bộ truyện một thư mục con
│   └── utils.py              Log, fingerprint cache, đọc/ghi json-yaml, font
│
├── assets/
│   ├── voices/default.wav    Giọng mẫu mặc định (clone_voice_clean) + default.txt: lời đúng từng chữ
│   ├── bgm/                  Nhạc nền tự thêm: assets/bgm/<mood>/*.mp3 (không đưa lên git)
│   └── fonts/                Font phụ đề tự thêm (không đưa lên git)
│
├── docs/HUONG_DAN_RUNPOD.md  Hướng dẫn RunPod: GPU, tài khoản mới, Stop/Start, đo hiệu năng, sự cố
└── tests/                    Test chạy không cần GPU: python -m unittest discover -s tests -t .
    ├── test_text_audio.py    Chuẩn hóa tiếng Việt, chia đoạn, audio, phụ đề
    ├── test_director_comfy.py Đạo diễn, ghép prompt, workflow ComfyUI, graph Wan/S2V, tự chọn model
    └── test_e2e.py           Chạy trọn pipeline với model giả lập + FFmpeg thật (đồng bộ hình-tiếng, cache, .done)
```

### Trên pod
```
/root/AI_Video_Studio/                 Code (mất khi Stop pod, bootstrap tự clone lại)
│   └── projects -> /workspace/video_studio_projects   (liên kết để dữ liệu nằm trên volume)
/opt/ai-video-studio-runtime/          Ổ container nhanh (mất khi Stop): venv Python, ComfyUI, Ollama,
                                       bản chép model hay dùng (models/comfyui/), cache TTS
/workspace/                            Volume (giữ nguyên khi Stop)
├── rclone.conf                        Kết nối Google Drive (bạn tự đặt vào)
├── setup.log, bootstrap.out           Log cài đặt lần gần nhất
├── ai-video-studio-runtime/
│   ├── models/comfyui/                Toàn bộ model ảnh/video (~130 GB): diffusion_models, text_encoders,
│   │                                  vae, loras, audio_encoders, checkpoints
│   ├── models/ollama-cache.tar        Bản nén model Ollama (LLM + model thị giác)
│   ├── cache/huggingface-cache.tar    Bản nén model giọng (OmniVoice, PhoWhisper)
│   ├── config/extra_model_paths.yaml  ComfyUI đọc model từ đâu
│   ├── env.sh                         Biến môi trường cho run.sh
│   └── logs/                          comfyui.log, ollama.log
└── video_studio_projects/<du_an>/     Dữ liệu từng bộ truyện (xem dưới)
```

### Một dự án (bộ truyện): `projects/<du_an>/`
```
chapters/Chuong_0001.txt ...     Chương đầu vào (UTF-8, tên có số chương)
series.yaml                      Hồ sơ truyện: title, drive_folder, thể loại, chủ đề, thời đại theo chương,
                                 phong cách vẽ, giọng đọc, watermark, số chương/tập (tool tự điền lần đầu)
overrides.yaml                   Sửa tay từng cảnh: nhân vật, bối cảnh, prompt, bật/tắt chuyển động
voice/voice.wav, voice.txt       Giọng clone riêng của bộ truyện (nếu tạo bằng --voice)
bible/characters.json            Nhân vật: ngoại hình cố định, trang phục theo chương, ảnh mẫu (sửa được)
bible/locations.json             Địa điểm và mô tả
bible/glossary.json              Cách đọc riêng cho TTS, ví dụ {"Lv": "cấp"}
refs/<nhan_vat>/ref.png          Ảnh mẫu khuôn mặt (candidate_*.png là các ảnh casting)
work/_cache/                     Cache giọng đọc từng đoạn (đổi chương không phải đọc lại đoạn trùng)
work/episodes.json               Tập đã ghép / đã upload
work/ch0001/
├── state.json                   Trạng thái và fingerprint từng ảnh / clip (để chạy tiếp, không làm lại)
├── scenes.json, prompts.json    Kết quả đạo diễn và prompt từng cảnh
├── audio/chapter.wav, timeline.json   Giọng đọc cả chương và mốc thời gian từng đoạn
├── images/scene_0001.png ...    Ảnh từng cảnh
├── motion/scene_0001.mp4 ...    Clip chuyển động; speech_*.wav là audio thoại cho nhép miệng
├── render/                      Đoạn video trung gian, phụ đề subs.ass
└── .done                        Đã lên Drive: thư mục images/motion/audio/render đã bị xóa, lần sau bỏ qua
output/
├── chapters/Chuong_0001.mp4     Video từng chương
├── episodes/<du_an>_Tap001_Chuong0001-0010.mp4   Video tập (xóa sau khi upload)
├── storyboards/Chuong_0001.jpg  Bảng ảnh các cảnh để duyệt nhanh
├── thumbnails/Chuong_0001.jpg   Ảnh bìa
└── reports/Chuong_0001.md       Báo cáo: đoạn đọc có thể sai, ảnh không đạt QA
logs/studio.log, upload.log      Log chạy và log upload
```

## Tự nâng chất lượng theo cấu hình pod

Mỗi lần chạy, tool đo VRAM/RAM của pod và áp **mức chất lượng cao nhất** pod đáp ứng (`settings.yaml > quality`). Setup tự tải thêm model cho mức đó, vẫn giữ bản mặc định làm dự phòng. Nếu model của mức cao chưa tải được, tool tự dùng lại bản mặc định.

| Mức | Điều kiện | Ví dụ máy | Thay đổi |
|---|---|---|---|
| thường | mọi pod | A40, RTX PRO 4500 (SE), RTX 4090 | Video 480p→1080p, LLM đạo diễn 14B |
| cao | VRAM ≥ 44 GB, RAM ≥ 60 GB | L40S, RTX 6000 Ada | Video **720p**, nhép miệng 576p, **LLM 32B** (tải thêm ~20 GB) |
| tối đa | VRAM ≥ 80 GB, RAM ≥ 120 GB | RTX PRO 6000, H100/A100 80 GB | Video 720p, nhép miệng 720p, **LLM 72B + VLM 32B** (tải thêm ~70 GB), QA chặt hơn |

Model chuyển động cũng tự chọn theo pod (`motion.model: auto`):
- VRAM ≥ 24 GB và RAM ≥ 40 GB: Wan 14B + nhép miệng.
- Yếu hơn: Wan 5B, không nhép miệng.

Muốn cố định cấu hình thì đặt `quality.auto: false`. Các ngưỡng và giá trị đều sửa được trong `settings.yaml`.

## Tùy chỉnh thường gặp

- **Giọng đọc:** file wav 6–10 giây, sạch, không nhạc nền, kèm file `.txt` ghi đúng từng chữ. Dùng `new --voice` hoặc lệnh `voice`.
- **Nhạc nền:** chép mp3 vào `assets/bgm/<mood>/`. Các mood theo thể loại: `epic_chinese`, `nostalgic`, `modern_drama`, `guzheng_drama`, `dark_tension`, `horror`, `electronic_epic`.
- **Nhân vật vẽ sai:** sửa `bible/characters.json` hoặc thay `refs/<nhan_vat>/ref.png`, rồi chạy lại. Tool chỉ làm lại phần bị ảnh hưởng.
- **Chi phí chuyển động:** trong `settings.yaml > motion`:
  - `coverage: ratio` + `ratio: 0.3`: chỉ một phần cảnh có chuyển động.
  - `lipsync: false`: tắt nhép miệng.
  - `model: wan22_5b`: dùng model nhẹ.

Chạy test (không cần GPU): `python -m unittest discover -s tests -t .`
