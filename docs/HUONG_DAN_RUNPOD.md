# Hướng dẫn chạy trên RunPod

## 1. Chọn GPU

### Bảng hiệu năng các cấu hình đã xem trên RunPod

**Cách đọc bảng**
- **Điểm vẽ ảnh** là mức **ước tính** khi chạy Qwen-Image và Wan 2.2, lấy RTX 4090 = 100. Số càng cao càng nhanh. Đây không phải số đo thật; số thật lấy từ lần chạy thử 1 chương.
- **Dựng video**: máy có NVENC thì mã hóa bằng GPU, rất nhanh. Máy không có NVENC phải dùng CPU, nên tốc độ phụ thuộc số vCPU.
- **Giá** lấy theo trang Deploy lúc ghi lại, và có thể thay đổi.

| Cấu hình pod | VRAM | RAM | vCPU | Kiến trúc | NVENC | Điểm vẽ ảnh (4090=100) | Dựng video | Wan 14B | Đánh giá | Giá |
|---|---|---|---|---|---|---|---|---|---|---|
| **RTX PRO 4500** | 32 GB | 62 GB | 12 | Blackwell | ✅ | ~75–85 | Nhanh (GPU) | Thử được (sát) | ⭐ **Cân bằng nhất**: đủ VRAM, đủ RAM, có NVENC, nhiều CPU | $0.72/h |
| **B300 MIG 34GB** | 34 GB | 71 GB | 6 | Blackwell Ultra (lát MIG) | ❌ | ~80–100 (chưa đo) | Chậm (CPU, 6 vCPU) | Thử được (sát) | Vẽ nhanh, dựng chậm, rủi ro tương thích (mục 1.4) | $0.50/h |
| **RTX PRO 4000** | 24 GB | **31 GB** | 12 | Blackwell | ✅ | ~55–65 | Nhanh (GPU) | ❌ | Chạy được, nhưng **RAM 31 GB thấp** (mục 1.1) | $0.57/h |
| RTX 4090 | 24 GB | thường ≥ 48 GB | — | Ada | ✅ | 100 | Nhanh (GPU) | ❌ | Mốc so sánh | ~$0.35–0.70/h |
| A40 | 48 GB | thường ≥ 48 GB | — | Ampere | ✅ | ~50–60 | Nhanh (GPU) | ✅ | Chậm hơn, nhưng VRAM lớn, chạy mọi model | ~$0.35–0.45/h |
| RTX PRO 6000 MIG 24GB | 24 GB | — | — | Blackwell (lát MIG) | Có thể không | ~45–60 | Tùy | ❌ | Mục 1.2 | — |
| L4 | 24 GB | — | — | Ada | ✅ | ~35–40 | Nhanh (GPU) | ❌ | Chậm (mục 1.3) | ~$0.4/h |

**Xếp hạng theo hiệu năng tổng thể** (cả vẽ ảnh lẫn dựng video, độ ổn định):

**RTX PRO 4500 > RTX 4090 > B300 MIG ≈ RTX PRO 4000 > A40 > PRO 6000 MIG > L4**

**RTX PRO 4500 32 GB**
- Khoảng trống VRAM 32 GB giúp Qwen-Image và Qwen-Image-Edit ít phải đẩy model sang RAM, nên ổn định hơn các máy 24 GB.
- Muốn thử Wan 14B thì cài với `INSTALL_WAN14B=1` và đặt `motion.model: wan22_14b`. Nếu báo hết VRAM thì quay về `wan22_5b`.

**RTX PRO 4000 với 31 GB RAM**
- Thấp hơn mức khuyến nghị 48 GB.
- Chạy thử 1 chương và theo dõi bằng `free -h`. Nếu pod bị kill hoặc ComfyUI tự tắt giữa chừng, nghĩa là thiếu RAM: chuyển sang máy khác.

### Bảng tham khảo chung

Giá dưới đây là mức tham khảo của Community Cloud và thay đổi theo ngày, nên xem lại trên trang Deploy.

| GPU | VRAM | Giá khoảng | Dùng được? | Ghi chú |
|---|---|---|---|---|
| **A40** | 48 GB | ~$0.35–0.45/h | ✅ Khuyến nghị | Rẻ nhất trong nhóm 48 GB, chạy được cả Wan 14B |
| RTX A6000 | 48 GB | ~$0.35–0.50/h | ✅ | Ngang A40 |
| RTX 4090 | 24 GB | ~$0.35–0.70/h | ✅ | Vẽ ảnh nhanh nhất nhóm 24 GB (hỗ trợ fp8) |
| **RTX PRO 4000 (Blackwell)** | 24 GB | xem giá | ✅ | Xem mục 1.1 |
| **RTX PRO 6000 MIG 24GB** | 24 GB | xem giá | ⚠️ Được, có điều kiện | Xem mục 1.2 |
| **L4** | 24 GB | ~$0.4/h | ✅ nhưng chậm | Xem mục 1.3 |
| RTX 3090 / A5000 | 24 GB | ~$0.2–0.3/h | ✅ | Rẻ, tốc độ khá |
| L40S | 48 GB | ~$0.8–0.9/h | ✅ | Nhanh, sát hoặc vượt ngân sách |
| **B300 MIG 34GB** | 34 GB | ~$0.50/h | ✅ Đáng thử | Xem mục 1.4: không có NVENC, chỉ 6 vCPU |
| A100 / H100 | 40–80 GB | — | ❌ Không nên | Không có NVENC, đắt |

**Mọi GPU 24 GB dùng chung một quy tắc.** Giữ nguyên cấu hình mặc định (`ollama.model: qwen2.5:14b`, `motion.model: wan22_5b`) và **không** đặt `INSTALL_WAN14B=1`. Tool chạy từng bước một và giải phóng VRAM giữa các bước, nên 24 GB là đủ.

**RAM hệ thống ≥ 48 GB.** Với GPU 24 GB, ComfyUI phải đẩy bớt model (text encoder 7B, Qwen-Image) sang RAM. Ở danh sách Deploy, cột RAM nằm cạnh tên GPU. Pod ít RAM dễ bị kill giữa chừng.

### 1.1 RTX PRO 4000 Blackwell 24 GB: dùng được

- Kiến trúc Blackwell: có fp8, có NVENC, tiết kiệm điện. Tốc độ vẽ ảnh nằm khoảng giữa L4 và RTX 4090.
- Cần PyTorch build CUDA 12.8 (kernel `sm_120`). `setup.sh` tự kiểm tra và tự nâng lên PyTorch 2.7.1 cu128 nếu template cũ. Dù vậy, nên chọn template **RunPod PyTorch có CUDA 12.8** cho gọn.
- Nếu log có dòng `no kernel image is available`, chạy lại `AUTO_RUN=0 bash setup.sh`. Lỗi vẫn còn thì gửi log cho người bảo trì.
- Pod RTX PRO 4000 trên RunPod đi kèm **31 GB RAM**, thấp hơn mức khuyến nghị 48 GB. Theo dõi bằng `free -h` khi chạy thử; bị kill giữa chừng thì đổi sang RTX PRO 4500.

### 1.1b RTX PRO 4500 Blackwell 32 GB: lựa chọn ổn định nhất trong các máy đã xem

- Có NVENC, 62 GB RAM và 12 vCPU, nên mọi khâu đều đủ tài nguyên.
- Cùng ghi chú CUDA 12.8 như RTX PRO 4000.
- 32 GB VRAM có thể thử Wan 14B (`INSTALL_WAN14B=1`, `motion.model: wan22_14b`).

### 1.2 RTX PRO 6000 MIG 24 GB: được, nhưng nên ưu tiên lựa chọn khác

MIG là một **lát cắt** của card RTX PRO 6000 96 GB: bạn nhận 24 GB VRAM và khoảng 1/4 số nhân của card.

- **Tốc độ:** chỉ tương đương một card tầm trung, không phải sức mạnh của PRO 6000 đầy đủ.
- **NVENC có thể không có** trong lát MIG. Tool tự thử NVENC rồi mới dùng; nếu không có sẽ chuyển sang libx264 trên CPU. Khi đó bước dựng video chậm hơn, phụ thuộc vào số vCPU của pod.
- Cũng là Blackwell, nên áp dụng ghi chú về CUDA 12.8 ở mục 1.1.
- **Chỉ đáng thuê khi giá rẻ hơn rõ rệt so với 4090 / PRO 4000.**

### 1.3 L4 24 GB: dùng được, rẻ điện nhưng chậm

- Kiến trúc Ada: có fp8, có NVENC (xuất video tốt).
- Công suất chỉ 72 W và băng thông bộ nhớ thấp, nên vẽ ảnh và tạo chuyển động **chậm khoảng 2–3 lần so với RTX 4090**.
- Tính theo chi phí mỗi chương thì thường thua 4090 / 3090 ở cùng mức giá. Chỉ chọn khi các máy kia hết chỗ.
- Muốn đỡ chậm, đặt `motion.ratio: 0.15` hoặc `motion.enabled: false` trong `config/settings.yaml`.

### 1.4 B300 MIG 34 GB (~$0.50/h, 71 GB RAM, 6 vCPU): đáng thử

Đây là một lát của card B300, dòng Blackwell Ultra dành cho datacenter.

**Điểm mạnh**
- **34 GB VRAM** thoải mái hơn các máy 24 GB.
- **71 GB RAM** dư dùng.
- Lát MIG có băng thông bộ nhớ cao, nên tốc độ vẽ ảnh dự kiến ngang khoảng RTX 4090. Con số này là ước tính, chưa đo.

**Điểm yếu**
- **GPU datacenter (B200/B300, giống H100) không có NVENC.** Video phải mã hóa bằng CPU (libx264), mà pod này chỉ có **6 vCPU**, nên khâu dựng phim cuối sẽ là bước chậm nhất.
  - Cách giảm: trong `config/settings.yaml`, đặt `video.x264_preset: veryfast` (chất lượng gần như không đổi ở `crf: 20`).
  - Có thể giảm thêm bằng `video.ken_burns.supersample: 1`.
- **Rủi ro tương thích:** B300 là GPU rất mới (kiến trúc sm_103).
  - `setup.sh` có kiểm tra PyTorch và chạy thử một phép tính trên GPU.
  - Nếu báo `no kernel image` hoặc Ollama không nhận GPU (xem `ollama.log`), đổi sang máy khác.
- **Kiểm tra CPU ngay khi vào pod:** chạy `uname -m`. Nếu ra `aarch64`, máy dùng CPU ARM (GB300). Script có hỗ trợ ARM, nhưng một số thư viện Python có thể thiếu bản dựng sẵn; gặp lỗi khi cài thì đổi máy.

**Cấu hình nên dùng**
- Giữ mặc định: `qwen2.5:14b`, `wan22_5b`.
- Có thể thử `INSTALL_WAN14B=1`, nhưng 34 GB khá sát; nếu báo hết VRAM thì quay về `wan22_5b`.

### Cách so sánh thực tế

Chạy thử 1 chương rồi xem thời gian từng bước trong `projects/<du_an>/logs/`:

```
chi phí 1 chương = giá/giờ × (số phút chạy 1 chương / 60)
```

Chọn máy có chi phí một chương thấp nhất, không phải máy có giá theo giờ thấp nhất.

## 2. Host từ đầu (tài khoản mới hoặc lần đầu)

### Bước 1: Chuẩn bị tài khoản RunPod
1. Đăng ký tài khoản ở runpod.io, nạp tiền (Billing). Mỗi giờ chạy khoảng $0.5–0.8.
2. Nên bật MFA (bảo mật hai lớp) cho tài khoản.

### Bước 2: Tạo volume lưu trữ (để không phải tải lại khoảng 90 GB model)

Menu **Storage → Network Volume → New**. Có hai loại:

| Loại | Ưu điểm | Nhược điểm |
|---|---|---|
| **Network volume theo datacenter** | Ổn định, đọc model nhanh | Chỉ thuê được GPU ở đúng datacenter đó |
| **Global** | Gắn được với GPU ở mọi nơi | **Không cho `chmod`** (nên code phải đặt ngoài `/workspace`, script đã tự xử lý). Có thể làm giảm RAM/vCPU của pod. |

Dung lượng: **150 GB** (200 GB nếu dùng Wan 14B). Volume tính phí theo tháng, kể cả khi pod đã tắt.

### Bước 3: Deploy pod
Vào **Pods → Deploy**, rồi chọn lần lượt:
1. **Template:** `PyTorch 2.8.0`. Ở ô phiên bản, chọn **CUDA 12.8.1** (image `runpod/pytorch:...-cu1281-torch280-ubuntu2404`).
2. **Set overrides:**
   - Container disk **60 GB**.
   - Tích **Start Jupyter notebook** và **SSH terminal access**.
   - Cổng HTTP `8888`.
3. **GPU:** xem bảng ở mục 1.
   - Sau khi gắn volume, **xem lại cột RAM** ở khung bên phải, vì volume Global có thể làm giảm RAM.
   - Ví dụ thực tế: RTX PRO 4500 bị giảm còn 30 GB RAM, trong khi **RTX PRO 4500 SE** cùng giá vẫn có 94 GB RAM.
4. **Storage → Add volume:** chọn volume ở bước 2, mount `/workspace`.
5. **Instance pricing:** On-Demand.
6. Bấm **Deploy Pod**.

### Bước 4: Mở terminal
Vào **Pods**, bấm tên pod, rồi chọn **Connect**:
- Bấm **Jupyter Lab** (đợi trạng thái Ready).
- Trong Jupyter chọn **Terminal**.

### Bước 5: Cài đặt bằng một lệnh
```bash
curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
```
Lệnh này làm lần lượt:
- Clone code vào `/root/AI_Video_Studio`.
- Cài Python, Ollama, ComfyUI.
- Tải model vào `/workspace/ai-video-studio-runtime`.
- Bật dịch vụ và chạy `check`.

Thời gian:
- **Lần đầu khoảng 30–45 phút**, chủ yếu để tải khoảng 90 GB.
- Muốn chạy nền để đóng được trình duyệt:
  ```bash
  (curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | nohup bash > /workspace/bootstrap.out 2>&1 &)
  tail -f /workspace/setup.log
  ```
- Xong khi log in dòng `CÀI ĐẶT HOÀN TẤT`.

Kiểm tra:
```bash
cd /root/AI_Video_Studio && bash run.sh check
```

### Bước 6: Google Drive (tùy chọn)
1. Tải `rclone.conf` lên **`/workspace/rclone.conf`**: trong Jupyter, kéo thả file vào thư mục gốc.
2. Chạy lại lệnh bootstrap. Setup tự cài file này mỗi lần khởi động.
3. Remote trong file phải tên là `gdrive`.

Trên volume Global sẽ thấy cảnh báo `Failed to set permissions on config file`. Cảnh báo này vô hại.

### Bước 7: Tạo dự án và đưa chương lên
```bash
cd /root/AI_Video_Studio
bash run.sh new "Trong Sinh 2003"          # tạo dự án trong /workspace/video_studio_projects/trong_sinh_2003/
```
Đưa file `Chuong_xxxx.txt` (UTF-8) vào thư mục chương của dự án theo một trong hai cách:
- **Jupyter:** mở thư mục `video_studio_projects/trong_sinh_2003/chapters/` ở cây bên trái, rồi kéo thả file vào.
- **runpodctl:** trên máy nhà chạy `runpodctl send chuong.zip`; trên pod chạy `runpodctl receive <mã>`, rồi `unzip chuong.zip -d /workspace/video_studio_projects/trong_sinh_2003/chapters/`.

`projects/` trong thư mục code là liên kết tới `/workspace/video_studio_projects/`, nên dữ liệu không mất khi tắt pod.

**Giọng đọc riêng:**
1. Chép file `giong.wav` (6–10 giây, sạch) và `giong.txt` (ghi đúng từng chữ trong đoạn wav) vào thư mục dự án.
2. Khai báo trong `series.yaml`:
   ```yaml
   voice:
     ref_audio: giong.wav
     ref_text: giong.txt
   ```

### Bước 8: Chạy thử một chương, rồi chạy cả bộ
```bash
bash run.sh run trong_sinh_2003 --chapters 484 --no-upload      # thử 1 chương
bash run.sh status trong_sinh_2003
nohup bash run.sh run trong_sinh_2003 --stop-pod > /workspace/run.log 2>&1 &   # cả bộ, xong tự tắt pod
tail -f /workspace/run.log
```

Kết quả nằm ở `/workspace/video_studio_projects/<du_an>/output/`:
- `chapters/`: video từng chương.
- `episodes/`: video ghép theo tập.
- `storyboards/`: ảnh tổng hợp các cảnh.
- `reports/`: báo cáo lỗi.

Có thể tải về qua Jupyter (chuột phải vào file, chọn Download), hoặc để tool tự upload lên Drive.

## 3. Sau khi Stop pod và Start lại (cùng tài khoản)

Khi pod Stop, ổ container bị xóa: mất code, Python và Ollama. Volume `/workspace` vẫn còn đủ model, dự án và `rclone.conf`.

1. Vào **Pods**, chọn pod, bấm **Start**. Nếu báo hết GPU, Deploy pod mới gắn cùng volume.
2. Mở Jupyter, rồi Terminal.
3. Chạy lại đúng lệnh bootstrap. Lần này **khoảng 5–10 phút** vì không tải lại model:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
   ```
4. Chạy tiếp. Tool tự bỏ qua phần đã làm nhờ cache:
   ```bash
   cd /root/AI_Video_Studio
   nohup bash run.sh run trong_sinh_2003 --stop-pod > /workspace/run.log 2>&1 &
   ```

Muốn cài xong tự chạy luôn thì dùng một lệnh:
```bash
curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | AUTO_RUN=1 PROJECT=trong_sinh_2003 bash
```

## 4. Chuyển sang tài khoản RunPod khác

Volume **không chuyển được giữa tài khoản**. Trên tài khoản mới:
1. Làm lại mục 2 từ đầu, bao gồm tải lại model, khoảng 30–45 phút.
2. Chuyển dữ liệu dự án cũ. Trên pod cũ:
   ```bash
   cd /workspace && tar -czf du_an.tgz video_studio_projects
   ```
   Tải file đó về máy (qua Jupyter, hoặc `runpodctl send du_an.tgz`), rồi đưa lên `/workspace` của pod mới và chạy:
   ```bash
   tar -xzf du_an.tgz -C /workspace
   ```
   Giữ lại dự án cũ giúp tool dùng lại được Story Bible, ảnh mẫu nhân vật và cache, không phải làm lại.
3. Chép `rclone.conf` vào `/workspace/rclone.conf`.

## 5. Tùy chọn khi cài

Đặt biến trước lệnh, ví dụ `... | INSTALL_WAN14B=1 bash`:

| Biến | Tác dụng |
|---|---|
| `INSTALL_WAN14B=1` | Chuyển động đẹp hơn, thêm khoảng 32 GB. Cần GPU ≥ 32 GB, rồi đặt `motion.model: wan22_14b` |
| `INSTALL_SDXL=0` | Bỏ model dự phòng SDXL, tiết kiệm 7 GB |
| `INSTALL_QWEN_EDIT=0` | Bỏ chức năng giữ mặt nhân vật, tiết kiệm 15 GB (không khuyến nghị) |
| `UPDATE_COMFYUI=1` | Cập nhật ComfyUI khi `check` báo thiếu node |
| `AUTO_RUN=1 PROJECT=<du_an>` | Cài xong tự chạy dự án ở chế độ nền |

## 6. Sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| `git clone` báo `chmod ... Operation not permitted` | Volume Global: dùng lệnh bootstrap, vì code đặt ở `/root` |
| `Ollama/ComfyUI chưa chạy` | Chạy lại lệnh bootstrap |
| `CUDA out of memory` | `motion.model: wan22_5b`, hoặc `motion.enabled: false` |
| `no kernel image is available` (Blackwell) | Dùng template CUDA 12.8; chạy lại bootstrap |
| Pod bị kill, log dừng đột ngột | Thiếu RAM: thuê pod RAM ≥ 48 GB |
| Dựng video rất chậm | Pod không có NVENC (MIG/B300): thuê pod nhiều vCPU hơn, hoặc GPU khác |
| Ảnh một cảnh xấu | `bash run.sh redo <du_an> --ch 484 --scene 12 --stage image` |
| Đọc sai tên riêng | Thêm vào `bible/glossary.json`, rồi `run --force audio` |
| Xem log | `/workspace/setup.log`, `/workspace/run.log`, `/workspace/ai-video-studio-runtime/logs/` |
