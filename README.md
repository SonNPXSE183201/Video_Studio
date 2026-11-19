# 🎬 AI Video Studio

Biến chương truyện chữ (tiếng Việt) thành video hoàn chỉnh: giọng đọc AI clone, ảnh minh họa đúng nhân vật và bối cảnh, chuyển động, phụ đề, nhạc nền, ghép tập và đẩy lên Google Drive. Chạy hoàn toàn bằng terminal trên RunPod.

**Bạn chỉ cần thả file chương `.txt` vào, tool tự làm phần còn lại.**

## Quy trình tự động

| Bước | Tool làm gì | Tự kiểm tra |
|---|---|---|
| Phân tích bộ truyện | LLM đọc 3 chương đầu → chọn **thể loại + thời đại + phong cách vẽ**, ghi vào `series.yaml` | heuristic từ khóa nếu LLM lỗi |
| Story Bible | Quét **nhân vật** (ngoại hình cố định, trang phục theo chương) và **địa điểm** (mô tả cố định) | gộp bí danh, không ghi đè ngoại hình đã ổn định |
| Đạo diễn | Chia cảnh theo đoạn văn (~15s), LLM chọn nhân vật/hành động/góc máy/bối cảnh, giữ liên tục với cảnh trước | thử lại lô nhỏ hơn, cảnh lỗi được đánh dấu trong báo cáo |
| Giọng đọc | Chuẩn hóa văn bản (số, %, Lv, 【】…), chunk ≤160 ký tự, OmniVoice seed cố định, cắt lặng, nhịp nghỉ theo dấu câu | **PhoWhisper nghe lại**, sai > 15% thì sinh lại (tối đa 3 lần) |
| Casting | Vẽ 3 ảnh chân dung cho nhân vật quan trọng, model thị giác chọn ảnh tốt nhất | — |
| Vẽ ảnh | Qwen-Image (mặc định) + **Qwen-Image-Edit giữ mặt từ ảnh mẫu**; SDXL dự phòng | **VLM kiểm** số người, sai thời đại, dị dạng, chữ → vẽ lại |
| Chuyển động | Wan 2.2 cho ~25% cảnh quan trọng; cảnh khác Ken Burns | clip lỗi → tự về Ken Burns |
| Dựng phim | Crossfade, phụ đề 2 dòng, watermark, nhạc nền tự giảm khi có lời, chuẩn âm lượng −16 LUFS | hình và tiếng dài khớp tuyệt đối theo timeline |
| Đóng gói | Ghép tập (mặc định 10 chương), upload Drive, storyboard + báo cáo để duyệt | — |

Mỗi bước có cache riêng: chạy lại chỉ làm phần thay đổi; pod tắt giữa chừng thì chạy lại sẽ tiếp tục.

## Thể loại có sẵn

```
tien_hiep          Tiên hiệp / tu tiên cổ đại          (mặc định vẽ: hoạt hình 3D)
huyen_huyen        Huyền huyễn / đấu khí               (3D)
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
kinh_doanh    Kinh doanh / trọng sinh làm giàu / thương chiến  (đàm phán, cửa tiệm, nhà xưởng, chứng khoán)
quan_truong   Quan trường / chính trường                       (họp thường vụ, văn phòng, kỷ ủy, tiệc rượu)
dau_tri       Đấu trí / mưu lược / trinh thám                  (ánh mắt tính toán, đối chất, ánh sáng tương phản)
```

Ví dụ truyện trọng sinh làm quan + kinh doanh bắt đầu năm 1984: `genre: do_thi_tq_1980s`, `themes: [quan_truong, kinh_doanh, dau_tri]`.

**Truyện kéo dài nhiều thập kỷ:** tool đếm các năm được nhắc trong từng chương ("năm 2003", "cuối năm 2006"...). Nếu chương đã sang thập kỷ khác, tool tự dùng preset đúng thời đại cho chương đó và ghi vào báo cáo. Muốn cố định thì khai báo:

```yaml
genre_by_chapter:
  "1-150": do_thi_tq_1990s
  "151-400": do_thi_tq_2000s
  "401-": do_thi_tq_2010s
```

Phong cách vẽ: `3d_donghua`, `cinematic_realistic`, `anime_cn`, `ink_painting`. Thêm thể loại mới: chép một file trong `config/styles/`; thêm chủ đề mới: chép một file trong `config/themes/`.

## Sử dụng trên RunPod

> Hướng dẫn chi tiết (chọn GPU, đưa file lên pod, sự cố): **[docs/HUONG_DAN_RUNPOD.md](docs/HUONG_DAN_RUNPOD.md)**

### 1. Tạo Pod
- GPU có NVENC. Khuyến nghị **A40 48 GB**. Máy 24 GB (RTX 4090, 3090, RTX PRO 4000, L4, PRO 6000 MIG 24GB) chạy được với cấu hình mặc định (`qwen2.5:14b`, `wan22_5b`), cần RAM ≥ 48 GB.
- Template RunPod PyTorch (CUDA 12.8 nếu là GPU Blackwell), container disk 60 GB, volume ≥ 150 GB gắn tại `/workspace`.

### 2. Cài đặt (một lần, chạy lại sau mỗi lần Start pod)
```bash
curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
cd /root/AI_Video_Studio
```
Code nằm ở `/root/AI_Video_Studio`. Dữ liệu (model, dự án) nằm trên volume `/workspace`, còn `rclone.conf` đặt tại `/workspace/rclone.conf`. Sau mỗi lần Start pod, chạy lại đúng lệnh trên.
Tùy chọn khi cài: `INSTALL_WAN14B=1` (chuyển động đẹp hơn, +32 GB), `INSTALL_QWEN_EDIT=0`, `INSTALL_SDXL=0`, `UPDATE_COMFYUI=1`.

Kiểm tra mọi thứ đã sẵn sàng:
```bash
bash run.sh check
```

### 3. Làm phim
```bash
bash run.sh new "Ten Bo Truyen"                    # tạo projects/ten_bo_truyen/
# chép các file chương .txt vào projects/ten_bo_truyen/chapters/
bash run.sh run ten_bo_truyen                       # chạy toàn bộ
```
Chạy nền và tự tắt pod khi xong:
```bash
nohup bash run.sh run ten_bo_truyen --stop-pod > run.log 2>&1 &
tail -f run.log
```

### Lệnh thường dùng
```bash
bash run.sh status ten_bo_truyen                       # tiến độ từng chương
bash run.sh run ten_bo_truyen --chapters 1-3           # chỉ chạy chương 1-3
bash run.sh run ten_bo_truyen --chapters 1 --until images   # xem thử ảnh trước, chưa làm video
bash run.sh run ten_bo_truyen --finish                 # ghép cả tập cuối chưa đủ chương
bash run.sh run ten_bo_truyen --force audio            # đọc lại giọng toàn bộ
bash run.sh redo ten_bo_truyen --ch 3 --scene 12 --stage image   # vẽ lại 1 cảnh
bash run.sh analyze ten_bo_truyen                      # nhận diện lại thể loại
bash run.sh styles                                     # danh sách thể loại/phong cách
```

## Tùy chỉnh không cần UI

Mỗi dự án nằm trong `projects/<ten>/`:

```
chapters/           file chương .txt (tên có số chương, ví dụ Chuong_0001.txt)
series.yaml         thể loại, thời đại, phong cách vẽ, giọng đọc, watermark, số chương/tập
overrides.yaml      sửa tay từng cảnh (nhân vật, bối cảnh, prompt, bật/tắt chuyển động)
bible/characters.json   nhân vật: sửa ngoại hình/trang phục rồi chạy lại → ảnh vẽ theo bản sửa
bible/locations.json    địa điểm
bible/glossary.json     cách đọc riêng cho TTS, ví dụ {"Lv": "cấp", "QQ": "qui qui"}
refs/<nhan_vat>/ref.png ảnh mẫu khuôn mặt (thay bằng ảnh bạn thích được)
output/             chapters/, episodes/, storyboards/, thumbnails/, reports/
```

Sau khi chạy, tool upload `storyboards/Chuong_xxxx.jpg` (bảng ảnh các cảnh) và `reports/Chuong_xxxx.md` (câu đọc lỗi, ảnh không đạt QA) lên Drive để bạn duyệt trên máy nhà.

**Giọng đọc:** đặt file mẫu 6–10 giây (wav) và file `.txt` ghi **chính xác từng chữ** trong mẫu, rồi khai báo trong `series.yaml > voice`. Mẫu sạch, không nhạc nền, đúng tông kể chuyện sẽ cho giọng ổn định nhất.

**Nhạc nền:** chép file mp3 vào `assets/bgm/<mood>/` (mood theo thể loại: `epic_chinese`, `nostalgic`, `modern_drama`, `guzheng_drama`, `dark_tension`, `horror`, `electronic_epic`) hoặc thẳng vào `assets/bgm/`.

## Cấu trúc mã

```
studio.py                 CLI
config/settings.yaml      cấu hình chung (model, TTS, ảnh, motion, video, upload)
config/styles/*.yaml      preset thể loại (kế thừa _base.yaml)
config/art_styles.yaml    phong cách vẽ
workflows/*.json          workflow ComfyUI dạng template (có thể thêm workflow riêng)
core/pipeline.py          điều phối, cache, VRAM
core/scene_director.py    Story Bible, chia cảnh, đạo diễn, ghép prompt
core/vi_normalizer.py     chuẩn hóa tiếng Việt cho TTS
core/text_processor.py    làm sạch, chia chunk, nhịp nghỉ
core/audio_builder.py     sinh giọng + kiểm tra ASR
core/comfy_client.py      ComfyUI + chọn workflow tự động
core/image_qa.py          kiểm tra ảnh bằng model thị giác
core/motion_client.py     Wan 2.2 5B / 14B
core/video_renderer.py    Ken Burns, crossfade, phụ đề, nhạc nền
tests/                    test đơn vị + test end-to-end (model giả lập)
```

Chạy test (không cần GPU): `python -m unittest discover -s tests -t .`
