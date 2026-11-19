# Hướng dẫn chạy AI Video Studio trên RunPod

> Cập nhật 20/11/2026: chế độ phim (Wan 2.2 14B + nhép miệng S2V), tự chọn model và mức chất lượng theo pod, Google Drive theo ID thư mục, đánh dấu `.done`, volume Global.

## 0. Tóm tắt nhanh

| Việc | Lệnh / thao tác |
|---|---|
| Lần đầu (pod mới) | Mở Jupyter → kéo `rclone.conf` vào `workspace` → Terminal: `curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh \| bash` (40–60 phút) |
| Mỗi lần Start lại pod | Đúng lệnh bootstrap trên (10–20 phút, không tải lại model) |
| Kiểm tra | `cd /root/AI_Video_Studio && bash run.sh check` |
| Tạo dự án | `bash run.sh new "Tên Truyện" --from /workspace/upload` |
| Thử Drive | `bash run.sh drive ten_truyen` |
| Làm video, xong tự tắt pod | `nohup bash run.sh run ten_truyen --stop-pod > /workspace/run.log 2>&1 &` |
| Xem tiến độ | `tail -f /workspace/run.log` hoặc `bash run.sh status ten_truyen` |

## 1. Tài khoản và volume

**Volume Global `ai_video_studio`**, gắn tại `/workspace`, đã tạo sẵn trên tài khoản hiện tại.

| | Global (đang dùng) | Network volume |
|---|---|---|
| Chi phí ~150 GB | 100 GB đầu miễn phí, sau đó $0.09/GB/tháng → **~$4.5/tháng**, cộng phí đọc/ghi | $0.07/GB/tháng, trả theo dung lượng đặt → ~$10.5/tháng |
| Thuê GPU | **ở mọi vùng** | chỉ trong 1 datacenter |
| Tốc độ đọc | ~170 MB/s (đo thực tế) | nhanh hơn, tùy datacenter |

- Tốc độ volume **không ảnh hưởng tốc độ làm video**: setup chép model sang ổ container trước khi chạy. Nó chỉ làm mỗi lần bật pod lâu hơn vài phút.
- Volume Global không cho đổi quyền file (`chmod`). Vì vậy code đặt ở `/root/AI_Video_Studio`; lệnh bootstrap đã tự xử lý.
- Volume tính tiền cả khi pod đang tắt. Video được xóa sau khi lên Drive (`.done`), nên dung lượng chủ yếu là model.

## 2. Chọn GPU

Tool **tự đo VRAM/RAM** rồi chọn model và mức chất lượng (mục 7), nên thuê máy nào cũng chạy được. Khác biệt chỉ là tốc độ và chất lượng.

| Máy (giá trên tài khoản, 20/11/2026) | VRAM / RAM / vCPU | NVENC | Tool tự chọn | Ước tính 1 chương ~11 phút video |
|---|---|---|---|---|
| **A40** ($0.59/h) | 48 / 46–50 / 9 | ✅ | Wan 14B + nhép miệng, mức "thường" | ~3–4 giờ, ~$1.8–2.4 |
| **RTX PRO 4500 SE** ($0.72/h) | 32 / 94 / 16 | ✅ | Wan 14B + nhép miệng, mức "thường" | ~2–2,5 giờ, ~$1.5–1.9 |
| **L40S** ($1.09/h) | 48 / thường ≥ 60 / 16 | ✅ | mức **"cao"**: 720p, LLM 32B | ~2–3 giờ, ~$2.2–3.3 |
| **RTX PRO 6000** ($2.69/h) | 96 / 161 / 16 | ✅ | mức **"tối đa"**: 720p, LLM 72B | ~1–1,5 giờ, ~$2.7–4 |
| RTX 4090 ($0.89/h) | 24 / 31 / 12 | ✅ | Wan 5B, không nhép miệng (RAM < 40 GB) | — |
| B300 MIG 34GB ($0.50/h) | 34 / 71 / 6 | ❌ | Wan 14B + nhép miệng | dựng video bằng CPU, chậm |
| H100 / A100 / B200 | 80+ | ❌ | mức "tối đa" | đắt, dựng video bằng CPU |

Các con số thời gian và chi phí là **ước tính**: Wan 14B và S2V chưa đo trên pod thật. Số đo thật của chế độ cũ nằm ở mục 10.

**Lưu ý khi thuê:**
- Xem cột **RAM** ở khung bên phải trang Deploy. RAM quyết định có dùng được Wan 14B hay không (cần ≥ 40 GB). Gắn volume Global có thể làm giảm RAM ở một số máy, ví dụ RTX PRO 4500 thường chỉ còn 30 GB, trong khi bản SE vẫn có 94 GB.
- Nên chọn máy **có NVENC**. Máy không có NVENC phải mã hóa video bằng CPU.
- GPU Blackwell (RTX PRO 4000/4500/6000, 5090, B300) cần template **CUDA 12.8**. Setup tự kiểm tra và tự nâng PyTorch nếu cần.
- Máy hết chỗ: bấm **Deploy when available** để pod tự bật khi có máy. Pod bật là bắt đầu tính tiền.

## 3. Deploy pod

1. **Pods → Deploy.**
2. **Template:** `PyTorch 2.8.0`, phiên bản **CUDA 12.8.1** (`runpod/pytorch:...-cu1281-torch280-ubuntu2404`).
3. **Set overrides:**
   - **Container disk 200 GB**: chỗ chép ~110 GB model cho nhanh.
   - Tích **Start Jupyter notebook** và **SSH terminal access**.
   - Cổng HTTP 8888.
4. **GPU:** theo mục 2. Kiểm tra RAM ở khung bên phải.
5. **Storage → Add volume:** chọn `ai_video_studio` (Global), mount `/workspace`. **Không được bỏ trống mục này.**
6. **Pod name:** ví dụ `video_studio`. **Instance pricing:** On-Demand.
7. Bấm **Deploy Pod**.

## 4. Cài đặt lần đầu

1. **Pods** → bấm tên pod → **Connect** → **Jupyter Lab** (đợi Ready).
2. Kéo thả vào thư mục `workspace` trong Jupyter. Gốc của Jupyter là `/`, nên `workspace` chính là `/workspace`.
   - `rclone.conf`, lấy từ `D:\Dự án truyện\Tool\AI_Video_Studio\rclone.conf`. Remote trong file phải tên `gdrive`.
   - Các file chương `.txt`, đặt trong thư mục `upload` mới tạo.
3. Mở **Terminal** và chạy:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
   cd /root/AI_Video_Studio && bash run.sh check
   ```
   - Lần đầu mất 40–60 phút, chủ yếu để tải ~150 GB model vào volume (~45 MB/s).
   - Muốn đóng trình duyệt mà vẫn cài: `(curl -fsSL .../bootstrap.sh | nohup bash > /workspace/bootstrap.out 2>&1 &)`, rồi theo dõi bằng `tail -f /workspace/setup.log`.
   - Cài xong khi log in dòng `CÀI ĐẶT HOÀN TẤT`.

**Setup tải những gì:** toàn bộ model, kể cả bản dự phòng cho pod yếu. Thuê pod mạnh hơn sau này không phải tải lại; chỉ tải thêm LLM của mức "cao"/"tối đa" một lần.

| Nhóm | Model |
|---|---|
| Vẽ ảnh | Qwen-Image-Edit 2509 + Lightning (chính), Qwen-Image + Lightning, SDXL (dự phòng) |
| Chuyển động | Wan 2.2 14B I2V (2 tầng + LightX2V), Wan 2.2 5B (pod yếu) |
| Nhép miệng | Wan 2.2 S2V 14B + wav2vec2 |
| Đạo diễn / kiểm ảnh | qwen2.5:14b, qwen2.5vl:7b (+ 32b/72b nếu pod đạt mức cao) |
| Giọng đọc | OmniVoice, PhoWhisper-large |

## 5. Google Drive

- Mọi thứ upload vào thư mục có ID `1Y8HB6uJQXZDYvssRodvvNqzCrzMqsgP7` (`settings.yaml > upload.root_folder_id`).
- Tool upload theo **ID thư mục** chứ không theo tên, để tránh lỗi tên tiếng Việt có dấu.
- Mỗi bộ truyện có thư mục con mang tên truyện (lấy từ `series.yaml > title`, đổi được bằng `drive_folder`):

```
<thư mục Drive của bạn>/
└── Nghịch Lưu Quang Âm/
    ├── <du_an>_Tap001_Chuong0001-0010.mp4   video tập (ghép 10 chương)
    ├── chapters/Chuong_0001.mp4              video từng chương (khi bật upload_chapters)
    └── review/                               storyboard, thumbnail, báo cáo lỗi từng chương
```

- **Thử kết nối:** `bash run.sh drive <du_an>` ghi file `_kiem_tra_ket_noi.txt` vào `review/`. Lần đầu chậm 20–30 giây vì rclone làm mới đăng nhập.
- **`.done`:** tập đã lên Drive thì các chương của tập được đánh dấu `.done`, xóa ảnh/clip/audio/video trung gian (~1 GB/chương), và lần chạy sau tự bỏ qua. Muốn làm lại: `--force done`.
- **Upload lỗi:** file vẫn được giữ trên pod, lần chạy sau thử lại.

## 6. Làm video

```bash
cd /root/AI_Video_Studio
bash run.sh new "Nghịch Lưu Quang Âm" --from /workspace/upload   # nhập chương; giọng mặc định = clone_voice_clean
bash run.sh run nghich_luu_quang_am --chapters 1 --until images    # xem thử ảnh trước (~30-40 phút)
nohup bash run.sh run nghich_luu_quang_am --stop-pod > /workspace/run.log 2>&1 &   # chạy hết, xong tự tắt pod
```

- **Giọng riêng cho một bộ truyện:** `bash run.sh new "Tên" --voice giong.wav` (kèm `giong.txt` ghi đúng từng chữ), hoặc `bash run.sh voice <du_an> giong.wav`.
- **`--stop-pod`:** tắt pod qua RunPod API, dự phòng bằng `runpodctl`. Pod vẫn tắt kể cả khi không còn chương nào cần làm. Dữ liệu trên volume giữ nguyên.
- **Kết quả trên pod:** `/workspace/video_studio_projects/<du_an>/output/`.
  - `chapters/`: video từng chương.
  - `episodes/`: video tập.
  - `storyboards/`: bảng ảnh các cảnh.
  - `reports/`: báo cáo lỗi.

**Chế độ phim làm gì:**
- **Mọi cảnh đều chuyển động.** Cảnh ~10 giây được phủ bằng 2–3 clip Wan nối tiếp (clip sau bắt đầu từ khung cuối của clip trước). Mỗi clip diễn một **nhịp hành động** do đạo diễn viết.
- **Nhép miệng:** cảnh nhân vật nói thoại khi đang một mình trong khung hình dùng Wan 2.2 S2V. Audio đưa vào chỉ giữ phần thoại, phần dẫn truyện bị tắt tiếng.
- **Ảnh mô tả đúng sự kiện:** đồ vật trong chương, tương tác giữa nhân vật, góc máy đa dạng.
- **Giới hạn:** bộ mã hóa âm thanh của S2V được huấn luyện bằng tiếng Anh, nên khẩu hình với tiếng Việt khớp nhịp nhưng không khớp chính xác từng âm.

## 7. Tự chọn model và nâng chất lượng theo pod

| Mức | Điều kiện | Thay đổi |
|---|---|---|
| thường | mọi pod | Video 832×480 phóng lên 1080p, LLM đạo diễn 14B |
| cao | VRAM ≥ 44 GB và RAM ≥ 60 GB | Video **1280×720**, nhép miệng 1024×576, **LLM 32B** |
| tối đa | VRAM ≥ 80 GB và RAM ≥ 120 GB | Video 720p, nhép miệng 720p, **LLM 72B + VLM 32B**, QA chặt hơn |

**Model chuyển động** (`motion.model: auto`):
- VRAM ≥ 24 GB và RAM ≥ 40 GB: Wan 14B + nhép miệng.
- VRAM ≥ 20 GB và RAM ≥ 40 GB: Wan 14B, không nhép miệng.
- Yếu hơn: Wan 5B.
- Thiếu file model nào thì tự lùi sang model còn lại, cuối cùng là Ken Burns.

**Cấu hình thêm:**
- Log ghi rõ lựa chọn, ví dụ: `Pod: NVIDIA A40 45 GB VRAM, RAM 46 GB -> mức chất lượng 'thường'`.
- Ngưỡng và giá trị sửa trong `settings.yaml > quality` và `motion.auto`.
- Muốn cố định: `quality.auto: false`, `motion.model: wan22_14b`.

## 8. Tắt pod rồi bật lại

1. **Pods** → chọn pod → **Start**. Nếu hết máy: Deploy pod mới, gắn **cùng volume `ai_video_studio`** (volume Global dùng được ở mọi vùng).
2. Jupyter → Terminal:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
   cd /root/AI_Video_Studio && nohup bash run.sh run <du_an> --stop-pod > /workspace/run.log 2>&1 &
   ```
   - Lệnh đầu mất 10–20 phút: cài lại Python/ComfyUI rồi chép model từ volume sang ổ nhanh.
   - Lệnh sau tự làm tiếp từ chỗ dừng và bỏ qua chương đã `.done`.
   - Gộp thành một lệnh: `curl ... | AUTO_RUN=1 PROJECT=<du_an> bash`.

| Còn (volume `/workspace`) | Mất khi Stop (bootstrap tạo lại) |
|---|---|
| Model AI, `rclone.conf`, dự án (chương, bible, ảnh mẫu, cache, `.done`) | Code `/root/AI_Video_Studio`, Python, ComfyUI, Ollama, bản chép model trên ổ nhanh |

## 9. Chuyển sang tài khoản RunPod khác

Volume **không chuyển được giữa các tài khoản**.
1. Trên tài khoản mới, làm lại mục 3–4 (tải lại model, 40–60 phút).
2. Mang dự án cũ sang:
   - Trên pod cũ: `cd /workspace && tar -czf du_an.tgz video_studio_projects`.
   - Tải file về máy (chuột phải → Download trong Jupyter), rồi kéo vào `/workspace` của pod mới.
   - Trên pod mới: `tar -xzf du_an.tgz -C /workspace`.

   Giữ dự án cũ để dùng lại Story Bible, ảnh mẫu nhân vật và cache.
3. Kéo `rclone.conf` vào `/workspace`.

## 10. Chi phí và số đo thực tế

**Volume:** ~$4.5/tháng (Global, ~150 GB), cộng phí đọc/ghi.

**Pod:** giá GPU + ổ container 200 GB (~$0.028/giờ). Chỉ tính tiền khi pod chạy; mỗi lần bật mất thêm 10–20 phút cài.

**Số đo thật (chế độ cũ, 19/11/2026, RTX PRO 4500, chương 7,5 phút video):**

| Bước | Thời gian |
|---|---|
| Phân tích + đạo diễn 27 cảnh | ~3 phút |
| Giọng đọc 90 đoạn | 3,8 phút |
| Vẽ 27 ảnh + QA + vẽ lại | 14 phút (~10 s/ảnh không có ảnh mẫu, ~20 s/ảnh có ảnh mẫu) |
| Chuyển động 7 clip Wan 5B | 19 phút (~2 phút/clip) |
| Dựng video (NVENC) | 4 phút |
| **Tổng** | **~45 phút, ~$0.55** |

Các điểm nghẽn đo được đã sửa trong code:
- Chép model sang ổ container: volume Global đọc chỉ ~170 MB/s.
- Dùng LoRA Lightning cho Qwen-Edit: từ 130 s/ảnh xuống ~20 s/ảnh.
- Dùng một model vẽ cho mọi cảnh: đổi model mất ~6 phút mỗi lần.

**Chế độ phim** tạo chuyển động cho mọi cảnh (~120 clip mỗi chương), nên ước tính đắt hơn khoảng 3–4 lần: **~$1.5–2.5/chương**. Muốn giảm:
- `motion.coverage: ratio` + `motion.ratio: 0.3`: chỉ 30% số cảnh có chuyển động.
- `motion.lipsync: false`: tắt nhép miệng.

## 11. Tùy chọn khi cài

Đặt biến trước `bash`, ví dụ `curl ... | INSTALL_SDXL=0 bash`:

| Biến | Mặc định | Tác dụng |
|---|---|---|
| `INSTALL_WAN14B` | 1 | Wan 2.2 14B I2V (~30 GB) |
| `INSTALL_S2V` | 1 | Wan 2.2 S2V nhép miệng (~17 GB) |
| `INSTALL_WAN5B` | 1 | Wan 2.2 5B cho pod yếu (~10 GB) |
| `INSTALL_QWEN_EDIT` | 1 | Qwen-Image-Edit, model vẽ chính (~21 GB) |
| `INSTALL_QWEN_IMAGE` | 1 | Qwen-Image dự phòng (~21 GB) |
| `INSTALL_SDXL` | 1 | SDXL dự phòng cuối (~7 GB) |
| `UPDATE_COMFYUI` | 0 | `1` = cập nhật ComfyUI khi `check` báo thiếu node |
| `LOCAL_MODEL_CACHE` | 1 | `0` = không chép model sang ổ container (khi container disk nhỏ) |
| `LOCAL_MODEL_CACHE_RESERVE_GB` | 8 | Dung lượng chừa lại trên ổ container |
| `AUTO_RUN=1 PROJECT=<du_an>` | — | Cài xong tự chạy dự án ở chế độ nền |

## 12. Sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| `git clone` báo `chmod ... Operation not permitted` | Volume Global: dùng lệnh bootstrap (code đặt ở `/root`) |
| `Ollama/ComfyUI chưa chạy` | Chạy lại lệnh bootstrap |
| `CUDA out of memory` | Đặt `motion.model: wan22_5b`, hoặc `quality.auto: false` |
| `no kernel image is available` | GPU Blackwell: dùng template CUDA 12.8, chạy lại bootstrap |
| Pod bị kill, log dừng đột ngột | Thiếu RAM: thuê máy RAM cao hơn (xem cột RAM khi Deploy) |
| Dựng video rất chậm | Máy không có NVENC: chọn máy khác |
| Upload Drive lỗi `invalid_grant` | Token hết hạn: trên máy nhà chạy `rclone config reconnect gdrive:`, rồi kéo `rclone.conf` mới vào `/workspace` |
| Ảnh một cảnh xấu | `bash run.sh redo <du_an> --ch 1 --scene 12 --stage image` |
| Đọc sai tên riêng / từ mượn | Thêm vào `bible/glossary.json`, rồi chạy `run --force audio` |
| Terminal Jupyter không hiện chữ | Gõ `echo .` rồi Enter để làm mới màn hình |
| Log | `/workspace/setup.log`, `/workspace/run.log`, `/workspace/ai-video-studio-runtime/logs/`, `<du_an>/logs/` |
