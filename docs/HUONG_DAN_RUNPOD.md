# Hướng dẫn chạy trên RunPod

## 1. Chọn GPU

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
| A100 / H100 | 40–80 GB | — | ❌ Không nên | Không có NVENC, đắt |

**Mọi GPU 24 GB dùng chung một quy tắc.** Giữ nguyên cấu hình mặc định (`ollama.model: qwen2.5:14b`, `motion.model: wan22_5b`) và **không** đặt `INSTALL_WAN14B=1`. Tool chạy từng bước một và giải phóng VRAM giữa các bước, nên 24 GB là đủ.

**RAM hệ thống ≥ 48 GB.** Với GPU 24 GB, ComfyUI phải đẩy bớt model (text encoder 7B, Qwen-Image) sang RAM. Ở danh sách Deploy, cột RAM nằm cạnh tên GPU. Pod ít RAM dễ bị kill giữa chừng.

### 1.1 RTX PRO 4000 Blackwell 24 GB: dùng được

- Kiến trúc Blackwell: có fp8, có NVENC, tiết kiệm điện. Tốc độ vẽ ảnh nằm khoảng giữa L4 và RTX 4090.
- Cần PyTorch build CUDA 12.8 (kernel `sm_120`). `setup.sh` tự kiểm tra và tự nâng lên PyTorch 2.7.1 cu128 nếu template cũ. Dù vậy, nên chọn template **RunPod PyTorch có CUDA 12.8** cho gọn.
- Nếu log có dòng `no kernel image is available`, chạy lại `AUTO_RUN=0 bash setup.sh`. Lỗi vẫn còn thì gửi log cho người bảo trì.

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

### Cách so sánh thực tế

Chạy thử 1 chương rồi xem thời gian từng bước trong `projects/<du_an>/logs/`:

```
chi phí 1 chương = giá/giờ × (số phút chạy 1 chương / 60)
```

Chọn máy có chi phí một chương thấp nhất, không phải máy có giá theo giờ thấp nhất.

## 2. Tạo pod

- **Template:** RunPod PyTorch 2.x, nên dùng bản CUDA 12.8 (bắt buộc với Blackwell để đỡ phải nâng cấp).
- **Container Disk:** 60 GB. Venv, Ollama và cache giọng nằm ở `/opt` trên ổ này.
- **Volume Disk:** 150 GB, mount tại `/workspace`. Dùng Wan 14B thì để 200 GB.
- Volume của pod gắn với một máy vật lý. Nếu lúc Start lại máy hết GPU, pod sẽ chạy với 0 GPU: chờ máy trống, hoặc dùng Network Volume.

## 3. Cài lần đầu

```bash
cd /workspace
git clone https://github.com/SonNPXSE183201/Video_Studio.git AI_Video_Studio
cd AI_Video_Studio
AUTO_RUN=0 bash setup.sh 2>&1 | tee /workspace/setup.log
bash run.sh check
```

Lần đầu mất khoảng 30–60 phút, chủ yếu để tải khoảng 80 GB model. Sau đó mọi dòng của `check` phải là `[OK]`. Riêng `rclone` được báo `[XX]` nếu không upload Drive.

Tùy chọn đặt trước lệnh `bash setup.sh`:

| Biến | Tác dụng |
|---|---|
| `INSTALL_WAN14B=1` | Chuyển động đẹp hơn, thêm khoảng 32 GB. **Chỉ dùng với GPU 48 GB** |
| `INSTALL_SDXL=0` | Bỏ model dự phòng SDXL, tiết kiệm 7 GB |
| `INSTALL_QWEN_EDIT=0` | Bỏ chức năng giữ mặt nhân vật, tiết kiệm 15 GB (không khuyến nghị) |
| `UPDATE_COMFYUI=1` | Cập nhật ComfyUI khi `check` báo thiếu node |

## 4. Đưa file lên pod

```powershell
# Máy nhà (Windows), dùng runpodctl.exe từ github.com/runpod/runpodctl/releases
runpodctl send rclone.conf
runpodctl send chuong.zip
```
```bash
# Trên pod
cd /workspace/AI_Video_Studio
runpodctl receive <mã>
unzip chuong.zip -d projects/ten_bo_truyen/chapters/
AUTO_RUN=0 bash setup.sh      # cài rclone.conf vào hệ thống (bỏ qua phần đã có)
rclone lsd gdrive:            # kiểm tra kết nối Drive
```

Nếu template có JupyterLab (cổng 8888), bạn cũng có thể kéo thả file qua trình duyệt.

## 5. Tạo dự án và chạy thử

```bash
bash run.sh new "Ten Bo Truyen"
# chép Chuong_0001.txt ... vào projects/ten_bo_truyen/chapters/ (UTF-8)
bash run.sh run ten_bo_truyen --chapters 1 --until images --no-upload   # xem ảnh trước
bash run.sh run ten_bo_truyen --chapters 1 --no-upload                  # làm trọn 1 chương
```

Kiểm tra lại `series.yaml` (thể loại, chủ đề) và `bible/characters.json` (ngoại hình). Sửa nếu sai rồi chạy lại: tool chỉ làm lại phần bị ảnh hưởng.

**Giọng đọc:** chuẩn bị file wav dài 6–10 giây, sạch, không nhạc nền, và file `.txt` ghi đúng từng chữ trong đoạn wav. Khai báo cả hai trong `series.yaml > voice`.

## 6. Chạy cả bộ

```bash
nohup bash run.sh run ten_bo_truyen --stop-pod > /workspace/run.log 2>&1 &
tail -f /workspace/run.log
```

`--stop-pod` tắt pod khi xong. Volume vẫn bị tính phí lưu trữ, khoảng $0.07/GB/tháng.

## 7. Sau mỗi lần Start lại pod

```bash
cd /workspace/AI_Video_Studio
git pull
AUTO_RUN=0 bash setup.sh             # khoảng 10–20 phút, không tải lại model lớn
bash run.sh run ten_bo_truyen        # chạy tiếp từ chỗ dừng
```

Muốn cài xong tự chạy nền luôn thì dùng: `PROJECT=ten_bo_truyen bash setup.sh`.

## 8. Sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| `Ollama/ComfyUI chưa chạy` | `AUTO_RUN=0 bash setup.sh` |
| `CUDA out of memory` | `motion.model: wan22_5b`, hoặc `motion.enabled: false` |
| `no kernel image is available` (Blackwell) | Chạy lại `AUTO_RUN=0 bash setup.sh`; dùng template CUDA 12.8 |
| Pod bị kill, log dừng đột ngột | Thiếu RAM: thuê pod RAM ≥ 48 GB |
| Dựng video rất chậm | Pod không có NVENC (MIG): thuê pod nhiều vCPU hơn, hoặc GPU khác |
| Ảnh một cảnh xấu | `bash run.sh redo <du_an> --ch 3 --scene 12 --stage image` |
| Đọc sai tên riêng | Thêm vào `bible/glossary.json`, rồi `run --force audio` |
| Xem log | `/workspace/run.log`; `/workspace/ai-video-studio-runtime/logs/comfyui.log` và `ollama.log` |
