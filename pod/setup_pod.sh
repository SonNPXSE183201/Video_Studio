#!/usr/bin/env bash
# Cài đặt AI Video Studio trên RunPod.
# Chạy từ bất kỳ thư mục nào:
#   bash /workspace/AI_Video_Studio/pod/setup_pod.sh
#
# Dữ liệu lớn được lưu trong /workspace/ai-video-studio-runtime. Script có thể
# chạy lại nhiều lần; file đã tải đúng kích thước sẽ được giữ nguyên.

set -Eeuo pipefail
IFS=$'\n\t'

trap 'echo "[LỖI] Dừng tại dòng ${LINENO}. Xem log trong ${LOG_DIR:-/workspace}." >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/workspace}"
RUNTIME_DIR="${AI_STUDIO_HOME:-${WORKSPACE_ROOT}/ai-video-studio-runtime}"
LOCAL_RUNTIME_DIR="${AI_STUDIO_LOCAL_HOME:-/opt/ai-video-studio-runtime}"

VENV_ROOT="${LOCAL_RUNTIME_DIR}/venvs"
STUDIO_VENV="${VENV_ROOT}/studio"
COMFY_VENV="${VENV_ROOT}/comfy"
COMFY_DIR="${LOCAL_RUNTIME_DIR}/ComfyUI"
COMFY_MODELS="${RUNTIME_DIR}/models/comfyui"
OLLAMA_HOME="${LOCAL_RUNTIME_DIR}/ollama"
OLLAMA_MODELS="${LOCAL_RUNTIME_DIR}/models/ollama"
OLLAMA_ARCHIVE="${RUNTIME_DIR}/models/ollama-cache.tar"
OLLAMA_ARCHIVE_MARKER="${RUNTIME_DIR}/models/ollama-cache.model"
LEGACY_OLLAMA_MODELS="${RUNTIME_DIR}/models/ollama"
PERSISTENT_CACHE_ROOT="${RUNTIME_DIR}/cache"
CACHE_ROOT="${LOCAL_RUNTIME_DIR}/cache"
HF_ARCHIVE="${PERSISTENT_CACHE_ROOT}/huggingface-cache.tar"
HF_ARCHIVE_MARKER="${PERSISTENT_CACHE_ROOT}/huggingface-cache.model"
LOG_DIR="${RUNTIME_DIR}/logs"
RUN_DIR="${LOCAL_RUNTIME_DIR}/run"
DOWNLOAD_DIR="${RUNTIME_DIR}/downloads"
CONFIG_DIR="${RUNTIME_DIR}/config"

export AI_STUDIO_HOME="${RUNTIME_DIR}"
export HF_HOME="${CACHE_ROOT}/huggingface"
export HUGGINGFACE_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export TORCH_HOME="${CACHE_ROOT}/torch"
# Global Volume không hỗ trợ đầy đủ file attributes nên không dùng làm pip cache.
export PIP_NO_CACHE_DIR=1
export UV_CACHE_DIR="${CACHE_ROOT}/uv"
export OLLAMA_MODELS
export PATH="${OLLAMA_HOME}/bin:${PATH}"
export LD_LIBRARY_PATH="${OLLAMA_HOME}/lib/ollama:${LD_LIBRARY_PATH:-}"

INSTALL_VIDEO_MODELS="${INSTALL_VIDEO_MODELS:-1}"
INSTALL_QWEN_IMAGE="${INSTALL_QWEN_IMAGE:-1}"     # Qwen-Image + Lightning (~30 GB)
INSTALL_QWEN_EDIT="${INSTALL_QWEN_EDIT:-1}"       # Qwen-Image-Edit giữ mặt nhân vật (~20 GB)
INSTALL_SDXL="${INSTALL_SDXL:-1}"                 # SDXL dự phòng (~7 GB)
INSTALL_WAN14B="${INSTALL_WAN14B:-0}"             # Wan 2.2 14B I2V + LightX2V (~32 GB)
PRELOAD_TTS_MODEL="${PRELOAD_TTS_MODEL:-1}"
UPDATE_COMFYUI="${UPDATE_COMFYUI:-0}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu128}"

mkdir -p "${VENV_ROOT}" "${COMFY_MODELS}" "${OLLAMA_MODELS}" "${CACHE_ROOT}" \
  "${PERSISTENT_CACHE_ROOT}" \
  "${LOG_DIR}" "${RUN_DIR}" "${DOWNLOAD_DIR}" "${CONFIG_DIR}"

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

wait_for_url() {
  local url="$1" name="$2" attempts="${3:-90}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "[OK] ${name} đã sẵn sàng."
      return 0
    fi
    sleep 2
  done
  echo "[LỖI] ${name} không sẵn sàng sau $((attempts * 2)) giây." >&2
  return 1
}

download_file() {
  local url="$1" target="$2" min_bytes="$3"
  local current_size=0
  if [[ -f "${target}" ]]; then
    current_size="$(stat -c '%s' "${target}" 2>/dev/null || echo 0)"
  fi
  if (( current_size >= min_bytes )); then
    echo "[BỎ QUA] $(basename "${target}") đã có ($((current_size / 1024 / 1024)) MiB)."
    return 0
  fi

  mkdir -p "$(dirname "${target}")"
  echo "[TẢI] $(basename "${target}")"
  curl -fL --retry 8 --retry-delay 5 --continue-at - \
    --output "${target}.part" "${url}"
  current_size="$(stat -c '%s' "${target}.part" 2>/dev/null || echo 0)"
  if (( current_size < min_bytes )); then
    echo "[LỖI] File tải chưa đủ: ${target}.part (${current_size} byte)." >&2
    return 1
  fi
  mv -f "${target}.part" "${target}"
}

# Model tùy chọn: tải lỗi chỉ cảnh báo, tool sẽ tự dùng phương án dự phòng.
download_optional() {
  if ! download_file "$@"; then
    echo "[CẢNH BÁO] Không tải được $(basename "$2"); tool sẽ dùng workflow dự phòng." >&2
    rm -f "$2.part"
  fi
}

create_venv() {
  local path="$1"
  if [[ ! -x "${path}/bin/python" ]] || \
     ! "${path}/bin/python" -m pip --version >/dev/null 2>&1; then
    # virtualenv tự mang pip seed phù hợp với Python của RunPod template, tránh
    # lệch phiên bản giữa /usr/local Python 3.11 và apt python3-venv 3.10.
    python3 -m virtualenv --system-site-packages --clear "${path}"
  fi
  "${path}/bin/python" -m pip install --upgrade pip setuptools wheel
}

start_detached() {
  local pid_file="$1" log_file="$2"
  shift 2
  setsid "$@" >"${log_file}" 2>&1 < /dev/null &
  echo "$!" >"${pid_file}"
}

directory_has_files() {
  [[ -n "$(find "$1" -mindepth 1 -print -quit 2>/dev/null)" ]]
}

restore_archive() {
  local archive="$1" destination="$2" label="$3"
  if [[ -s "${archive}" ]] && ! directory_has_files "${destination}"; then
    log "Khôi phục ${label} từ persistent storage"
    mkdir -p "${destination}"
    tar -xf "${archive}" -C "${destination}"
  fi
}

save_archive() {
  local source="$1" archive="$2" label="$3"
  log "Lưu ${label} vào persistent storage"
  tar -cf "${archive}.part" -C "${source}" .
  mv -f "${archive}.part" "${archive}"
}

log "1/8 - Cài gói hệ thống"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl ffmpeg git libsndfile1 python3-pip python3-venv \
  rclone unzip wget zstd fontconfig fonts-noto-core fonts-dejavu-core

log "2/8 - Tạo môi trường Python trên container disk"
# Ubuntu 24.04 (PEP 668) chặn pip vào Python hệ thống -> thử lại với --break-system-packages.
python3 -m pip install --upgrade virtualenv || \n  python3 -m pip install --break-system-packages --upgrade virtualenv
create_venv "${STUDIO_VENV}"
create_venv "${COMFY_VENV}"

"${STUDIO_VENV}/bin/python" -m pip install -r "${PROJECT_DIR}/requirements.txt"
"${STUDIO_VENV}/bin/python" -m pip install \
  accelerate huggingface_hub omnivoice sentencepiece soundfile transformers

# Tận dụng PyTorch/CUDA có sẵn trong RunPod PyTorch Template. Nếu template không
# có PyTorch CUDA, chỉ khi đó mới tải wheel CUDA vào hai venv trong /workspace.
if ! python3 -c 'import torch; assert torch.cuda.is_available()' >/dev/null 2>&1; then
  log "Không thấy PyTorch CUDA của template; cài wheel CUDA vào /workspace"
  "${STUDIO_VENV}/bin/python" -m pip install torch torchvision torchaudio --index-url "${TORCH_INDEX_URL}"
  "${COMFY_VENV}/bin/python" -m pip install torch torchvision torchaudio --index-url "${TORCH_INDEX_URL}"
fi

"${STUDIO_VENV}/bin/python" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("PyTorch không nhận GPU CUDA. Hãy dùng RunPod PyTorch Template phù hợp.")
print(f"[OK] PyTorch {torch.__version__}; GPU: {torch.cuda.get_device_name(0)}")
PY

log "3/8 - Cài Ollama trên container disk, lưu archive model trong /workspace"
if [[ ! -x "${OLLAMA_HOME}/bin/ollama" ]]; then
  case "$(uname -m)" in
    x86_64) ollama_arch="amd64" ;;
    aarch64|arm64) ollama_arch="arm64" ;;
    *) echo "Kiến trúc CPU không hỗ trợ Ollama: $(uname -m)" >&2; exit 1 ;;
  esac
  ollama_archive="${DOWNLOAD_DIR}/ollama-linux-${ollama_arch}.tar.zst"
  download_file \
    "https://ollama.com/download/ollama-linux-${ollama_arch}.tar.zst" \
    "${ollama_archive}" 50000000
  mkdir -p "${OLLAMA_HOME}"
  tar --zstd -xf "${ollama_archive}" -C "${OLLAMA_HOME}"
fi
"${OLLAMA_HOME}/bin/ollama" --version

# Ollama cần chmod/rename kiểu POSIX nên chạy model từ container disk. Bản nén
# một-file trên /workspace dùng để khôi phục nhanh sau Stop/Start Pod.
restore_archive "${OLLAMA_ARCHIVE}" "${OLLAMA_MODELS}" "Ollama model"
if ! directory_has_files "${OLLAMA_MODELS}" && \
   [[ -d "${LEGACY_OLLAMA_MODELS}" ]] && directory_has_files "${LEGACY_OLLAMA_MODELS}"; then
  log "Khôi phục lần tải Ollama dở trước đó từ /workspace"
  cp -r "${LEGACY_OLLAMA_MODELS}/." "${OLLAMA_MODELS}/"
  chmod -R u+rwX "${OLLAMA_MODELS}"
fi

# Luôn khởi động lại tiến trình do setup quản lý để chắc chắn nó dùng model
# local, không dùng đường dẫn Global Volume từ phiên bản setup cũ.
if [[ -s "${RUN_DIR}/ollama.pid" ]]; then
  old_ollama_pid="$(cat "${RUN_DIR}/ollama.pid" 2>/dev/null || true)"
  if [[ "${old_ollama_pid}" =~ ^[0-9]+$ ]] && kill -0 "${old_ollama_pid}" 2>/dev/null; then
    kill "${old_ollama_pid}" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "${old_ollama_pid}" 2>/dev/null || break
      sleep 0.5
    done
  fi
fi
if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "[LỖI] Một Ollama khác vẫn chiếm cổng 11434. Chạy: pkill -x ollama" >&2
  exit 1
fi
start_detached "${RUN_DIR}/ollama.pid" "${LOG_DIR}/ollama.log" \
  env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="${OLLAMA_MODELS}" \
  PATH="${PATH}" LD_LIBRARY_PATH="${LD_LIBRARY_PATH}" \
  "${OLLAMA_HOME}/bin/ollama" serve
wait_for_url http://127.0.0.1:11434/api/tags Ollama 60

mapfile -t OLLAMA_WANTED < <("${STUDIO_VENV}/bin/python" - "${PROJECT_DIR}/config/settings.yaml" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as f:
    cfg = yaml.safe_load(f)["ollama"]
print(cfg["model"])
if cfg.get("vision_model"):
    print(cfg["vision_model"])
PY
)
for model_name in "${OLLAMA_WANTED[@]}"; do
  if ! "${OLLAMA_HOME}/bin/ollama" list | awk 'NR > 1 {print $1}' | grep -Fxq "${model_name}"; then
    log "Tải model Ollama ${model_name}"
    "${OLLAMA_HOME}/bin/ollama" pull "${model_name}" || \
      echo "[CẢNH BÁO] Không tải được ${model_name}." >&2
  else
    echo "[BỎ QUA] Ollama model ${model_name} đã có."
  fi
done
OLLAMA_MARKER_VALUE="$(printf '%s,' "${OLLAMA_WANTED[@]}")"
if [[ ! -s "${OLLAMA_ARCHIVE}" ]] || \
   [[ "$(cat "${OLLAMA_ARCHIVE_MARKER}" 2>/dev/null || true)" != "${OLLAMA_MARKER_VALUE}" ]]; then
  save_archive "${OLLAMA_MODELS}" "${OLLAMA_ARCHIVE}" "Ollama models ${OLLAMA_MARKER_VALUE}"
  printf '%s\n' "${OLLAMA_MARKER_VALUE}" >"${OLLAMA_ARCHIVE_MARKER}"
fi

log "4/8 - Cài ComfyUI trong /workspace"
if [[ ! -d "${COMFY_DIR}/.git" ]]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "${COMFY_DIR}"
elif [[ "${UPDATE_COMFYUI}" == "1" ]]; then
  git -C "${COMFY_DIR}" pull --ff-only
fi
"${COMFY_VENV}/bin/python" -m pip install -r "${COMFY_DIR}/requirements.txt"

# comfy-kitchen mới dùng annotation list[int] trong torch.library.custom_op.
# PyTorch chỉ hỗ trợ kiểu này từ 2.7; template PyTorch 2.4 sẽ làm ComfyUI crash.
# GPU Blackwell (RTX PRO 4000/6000, RTX 50xx: sm_120) cần bản build CUDA 12.8 có
# kernel sm_120; bản cu126 dù >= 2.7 vẫn báo "no kernel image" nên cũng phải nâng.
if ! "${COMFY_VENV}/bin/python" - <<'PY'
import torch
parts = torch.__version__.split("+", 1)[0].split(".")
ok = tuple(map(int, parts[:2])) >= (2, 7)
if ok and torch.cuda.is_available():
    major, minor = torch.cuda.get_device_capability(0)
    arch = f"sm_{major}{minor}"
    # Kernel sm_X.y chạy được trên GPU X.z (z >= y), ví dụ sm_100 chạy trên B300 (sm_103).
    compatible = False
    for a in torch.cuda.get_arch_list():
        digits = "".join(ch for ch in a.split("_", 1)[-1] if ch.isdigit())
        if len(digits) >= 2 and int(digits[:-1]) == major and int(digits[-1]) <= minor:
            compatible = True
    if not compatible:
        print(f"[INFO] PyTorch {torch.__version__} thiếu kernel {arch} cho GPU này")
        ok = False
raise SystemExit(0 if ok else 1)
PY
then
  log "Nâng riêng ComfyUI lên PyTorch 2.7.1 CUDA 12.8"
  "${COMFY_VENV}/bin/python" -m pip install --upgrade \
    torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
    --index-url https://download.pytorch.org/whl/cu128
fi
"${COMFY_VENV}/bin/python" - <<'PY'
import torch, comfy_kitchen
assert torch.cuda.is_available(), "ComfyUI PyTorch không nhận CUDA"
(torch.ones(4, device="cuda") * 2).sum().item()   # bắt lỗi "no kernel image" sớm
free, total = torch.cuda.mem_get_info()
print(f"[OK] ComfyUI PyTorch {torch.__version__}; GPU {torch.cuda.get_device_name(0)} "
      f"{total / 2**30:.0f} GB; comfy-kitchen import thành công")
if total < 30 * 2**30:
    print("[INFO] GPU < 30 GB: giữ ollama.model qwen2.5:14b và motion.model wan22_5b")
PY

# Dùng chung PyTorch CUDA mới của ComfyUI cho pipeline chính để tránh nhân đôi
# nhiều GB wheel CUDA. Các package nghiệp vụ (OmniVoice, transformers, pydub...)
# vẫn nằm trong studio venv và được ghép vào bằng PYTHONPATH.
STUDIO_SITE_PACKAGES="$("${STUDIO_VENV}/bin/python" - <<'PY'
import site
print(site.getsitepackages()[0])
PY
)"
PYTHONPATH="${STUDIO_SITE_PACKAGES}" "${COMFY_VENV}/bin/python" - <<'PY'
import torch, torchaudio, transformers
from omnivoice import OmniVoice
assert torch.cuda.is_available(), "Pipeline chính không nhận CUDA"
print(
    f"[OK] Pipeline PyTorch {torch.__version__}; "
    f"Torchaudio {torchaudio.__version__}; Transformers {transformers.__version__}; "
    "OmniVoice import thành công"
)
PY

cat >"${CONFIG_DIR}/extra_model_paths.yaml" <<EOF
ai_video_studio:
  base_path: ${COMFY_MODELS}
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  clip_vision: clip_vision
  loras: loras
EOF

log "5/8 - Tải model tạo ảnh"
HF="https://huggingface.co"
if [[ "${INSTALL_SDXL}" == "1" ]]; then
  download_optional "${HF}/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
    "${COMFY_MODELS}/checkpoints/sd_xl_base_1.0.safetensors" 5000000000
  download_optional "${HF}/goofyai/3d_render_style_xl/resolve/main/3d_render_style_xl.safetensors" \
    "${COMFY_MODELS}/loras/3d_render_style_xl.safetensors" 80000000
fi
if [[ "${INSTALL_QWEN_IMAGE}" == "1" || "${INSTALL_QWEN_EDIT}" == "1" ]]; then
  download_optional "${HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
    "${COMFY_MODELS}/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" 7000000000
  download_optional "${HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" \
    "${COMFY_MODELS}/vae/qwen_image_vae.safetensors" 200000000
fi
if [[ "${INSTALL_QWEN_IMAGE}" == "1" ]]; then
  download_optional "${HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors" \
    "${COMFY_MODELS}/diffusion_models/qwen_image_fp8_e4m3fn.safetensors" 15000000000
  download_optional "${HF}/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-8steps-V1.0.safetensors" \
    "${COMFY_MODELS}/loras/Qwen-Image-Lightning-8steps-V1.0.safetensors" 500000000
fi
if [[ "${INSTALL_QWEN_EDIT}" == "1" ]]; then
  download_optional "${HF}/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" \
    "${COMFY_MODELS}/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors" 15000000000
fi

if [[ "${INSTALL_VIDEO_MODELS}" == "1" ]]; then
  log "6/8 - Tải model Wan 2.2 tạo animation"
  WAN22="${HF}/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files"
  download_optional "${WAN22}/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors" \
    "${COMFY_MODELS}/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors" 8000000000
  download_optional "${HF}/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
    "${COMFY_MODELS}/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" 5000000000
  download_optional "${WAN22}/vae/wan2.2_vae.safetensors" \
    "${COMFY_MODELS}/vae/wan2.2_vae.safetensors" 1000000000
  if [[ "${INSTALL_WAN14B}" == "1" ]]; then
    for f in wan2.2_i2v_high_noise_14B_fp8_scaled wan2.2_i2v_low_noise_14B_fp8_scaled; do
      download_optional "${WAN22}/diffusion_models/${f}.safetensors" \
        "${COMFY_MODELS}/diffusion_models/${f}.safetensors" 10000000000
    done
    for f in wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise; do
      download_optional "${WAN22}/loras/${f}.safetensors" "${COMFY_MODELS}/loras/${f}.safetensors" 100000000
    done
    download_optional "${HF}/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors" \
      "${COMFY_MODELS}/vae/wan_2.1_vae.safetensors" 200000000
  fi
else
  log "6/8 - Bỏ qua model video (INSTALL_VIDEO_MODELS=0)"
fi

log "7/8 - Chuẩn bị cache TTS và rclone"
if [[ "${PRELOAD_TTS_MODEL}" == "1" ]]; then
  TTS_MODEL="$("${STUDIO_VENV}/bin/python" - "${PROJECT_DIR}/config/settings.yaml" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
models = [cfg["tts"]["model_id"]]
if cfg.get("asr", {}).get("enabled", True):
    models.append(cfg["asr"].get("model_id", "vinai/PhoWhisper-large"))
print(",".join(models))
PY
)"
  restore_archive "${HF_ARCHIVE}" "${HF_HOME}" "Hugging Face/TTS cache"
  "${STUDIO_VENV}/bin/python" - "${TTS_MODEL}" <<'PY'
import sys
from huggingface_hub import snapshot_download
for repo in sys.argv[1].split(","):
    print(f"Đang chuẩn bị model {repo}...")
    try:
        snapshot_download(repo_id=repo)
    except Exception as exc:
        print(f"[CẢNH BÁO] Không tải được {repo}: {exc}")
PY
  if [[ ! -s "${HF_ARCHIVE}" ]] || \
     [[ "$(cat "${HF_ARCHIVE_MARKER}" 2>/dev/null || true)" != "${TTS_MODEL}" ]]; then
    save_archive "${HF_HOME}" "${HF_ARCHIVE}" "TTS model ${TTS_MODEL}"
    printf '%s\n' "${TTS_MODEL}" >"${HF_ARCHIVE_MARKER}"
  fi
fi

# rclone.conf: ưu tiên thư mục tool, sau đó /workspace/rclone.conf (giữ qua các lần Stop).
for rclone_src in "${PROJECT_DIR}/rclone.conf" "${WORKSPACE_ROOT}/rclone.conf"; do
  if [[ -f "${rclone_src}" ]]; then
    mkdir -p /root/.config/rclone
    install -m 600 "${rclone_src}" /root/.config/rclone/rclone.conf
    [[ -f "${PROJECT_DIR}/rclone.conf" ]] || cp "${rclone_src}" "${PROJECT_DIR}/rclone.conf" 2>/dev/null || true
    echo "[OK] Dùng rclone.conf từ ${rclone_src}"
    break
  fi
done

# Code đặt ngoài /workspace (volume Global không cho chmod nên git clone vào đó lỗi):
# dữ liệu dự án vẫn phải nằm trên volume để không mất khi Stop pod.
if [[ "${PROJECT_DIR}" != "${WORKSPACE_ROOT}"/* ]]; then
  DATA_PROJECTS="${WORKSPACE_ROOT}/video_studio_projects"
  mkdir -p "${DATA_PROJECTS}"
  if [[ ! -L "${PROJECT_DIR}/projects" ]]; then
    if [[ -d "${PROJECT_DIR}/projects" ]]; then
      cp -r "${PROJECT_DIR}/projects/." "${DATA_PROJECTS}/"
      rm -rf "${PROJECT_DIR}/projects"
    fi
    ln -s "${DATA_PROJECTS}" "${PROJECT_DIR}/projects"
  fi
  echo "[OK] Dự án lưu trên volume: ${DATA_PROJECTS} (liên kết tại ${PROJECT_DIR}/projects)"
fi

cat >"${RUNTIME_DIR}/env.sh" <<EOF
export AI_STUDIO_HOME="${RUNTIME_DIR}"
export AI_STUDIO_LOCAL_HOME="${LOCAL_RUNTIME_DIR}"
export HF_HOME="${HF_HOME}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE}"
export TORCH_HOME="${TORCH_HOME}"
export PIP_NO_CACHE_DIR=1
export UV_CACHE_DIR="${UV_CACHE_DIR}"
export OLLAMA_MODELS="${OLLAMA_MODELS}"
export PATH="${OLLAMA_HOME}/bin:\${PATH}"
export LD_LIBRARY_PATH="${OLLAMA_HOME}/lib/ollama:\${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${STUDIO_SITE_PACKAGES}:\${PYTHONPATH:-}"
export AI_STUDIO_PYTHON="${COMFY_VENV}/bin/python"
export COMFYUI_DIR="${COMFY_DIR}"
EOF

# Ổ container đọc nhanh hơn volume rất nhiều (đo trên volume Global: ~170 MB/s so với ~5 GB/s).
# Model nạp lại nhiều lần mỗi chương (Qwen-Image <-> Qwen-Image-Edit <-> Wan), nên chép các model
# hay dùng sang ổ container nếu đủ chỗ; phần còn lại dùng symlink tới volume.
# Tắt: LOCAL_MODEL_CACHE=0. Container disk khuyến nghị 150 GB để chép được toàn bộ.
MODEL_BASE="${COMFY_MODELS}"
LOCAL_COMFY_MODELS="${LOCAL_RUNTIME_DIR}/models/comfyui"
if [[ "${LOCAL_MODEL_CACHE:-1}" != "0" ]]; then
  log "Chép model hay dùng sang ổ container (đọc nhanh hơn volume)"
  mkdir -p "${LOCAL_COMFY_MODELS}"
  reserve=$((15 * 1024 * 1024 * 1024))
  mapfile -t model_files < <(
    cd "${COMFY_MODELS}" && {
      ls -1 text_encoders/qwen_2.5_vl* diffusion_models/qwen_image_fp8* vae/qwen_image* loras/Qwen-Image* \
        diffusion_models/qwen_image_edit* diffusion_models/wan2.2_ti2v* text_encoders/umt5* vae/wan2.2* \
        diffusion_models/wan2.2_i2v* loras/wan2.2* vae/wan_2.1* 2>/dev/null || true
      find . -type f -name '*.safetensors' | sed 's|^\./||'
    }
  )
  declare -A seen_model=()
  copied=0
  for rel in "${model_files[@]}"; do
    [[ -n "${rel}" && -z "${seen_model[$rel]:-}" ]] || continue
    seen_model[$rel]=1
    src="${COMFY_MODELS}/${rel}"
    dst="${LOCAL_COMFY_MODELS}/${rel}"
    [[ -f "${src}" ]] || continue
    mkdir -p "$(dirname "${dst}")"
    size="$(stat -c %s "${src}")"
    if [[ -f "${dst}" && ! -L "${dst}" ]] && [[ "$(stat -c %s "${dst}")" == "${size}" ]]; then
      continue
    fi
    avail="$(df --output=avail -B1 "${LOCAL_COMFY_MODELS}" | tail -1 | tr -d ' ')"
    if (( avail - size > reserve )); then
      rm -f "${dst}" "${dst}.part"
      if cp "${src}" "${dst}.part" && mv -f "${dst}.part" "${dst}"; then
        echo "[CHÉP] ${rel} ($((size / 1024 / 1024)) MiB)"
        copied=$((copied + 1))
        continue
      fi
      rm -f "${dst}.part"
    fi
    [[ -L "${dst}" ]] || { rm -f "${dst}"; ln -s "${src}" "${dst}"; echo "[LIÊN KẾT] ${rel} (ổ container không đủ chỗ, đọc từ volume)"; }
  done
  MODEL_BASE="${LOCAL_COMFY_MODELS}"
fi
cat >"${CONFIG_DIR}/extra_model_paths.yaml" <<YAML
ai_video_studio:
  base_path: ${MODEL_BASE}
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  clip_vision: clip_vision
  loras: loras
YAML

log "8/8 - Khởi động ComfyUI"
if ! curl -fsS --max-time 3 http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
  start_detached "${RUN_DIR}/comfyui.pid" "${LOG_DIR}/comfyui.log" \
    env HF_HOME="${HF_HOME}" TORCH_HOME="${TORCH_HOME}" \
    "${COMFY_VENV}/bin/python" "${COMFY_DIR}/main.py" \
    --listen 0.0.0.0 --port 8188 \
    --extra-model-paths-config "${CONFIG_DIR}/extra_model_paths.yaml"
fi
if ! wait_for_url http://127.0.0.1:8188/system_stats ComfyUI 120; then
  tail -n 100 "${LOG_DIR}/comfyui.log" || true
  exit 1
fi

curl -fsS http://127.0.0.1:8188/object_info >"${RUN_DIR}/comfyui_object_info.json"
for node in Wan22ImageToVideoLatent TextEncodeQwenImageEditPlus ModelSamplingAuraFlow; do
  if ! grep -q "\"${node}\"" "${RUN_DIR}/comfyui_object_info.json"; then
    echo "[CẢNH BÁO] ComfyUI thiếu node ${node}. Cập nhật: UPDATE_COMFYUI=1 bash setup.sh" >&2
  fi
done

log "Kiểm tra tổng thể"
(cd "${PROJECT_DIR}" && source "${RUNTIME_DIR}/env.sh" && "${COMFY_VENV}/bin/python" studio.py check) || \
  echo "[CẢNH BÁO] Một số thành phần chưa sẵn sàng (xem danh sách trên); tool sẽ dùng phương án dự phòng."

echo
echo "============================================================"
echo "CÀI ĐẶT HOÀN TẤT"
echo "Project : ${PROJECT_DIR}"
echo "Persistent runtime : ${RUNTIME_DIR}"
echo "Local runtime      : ${LOCAL_RUNTIME_DIR}"
echo "Log     : ${LOG_DIR}"
echo "Dung lượng runtime: $(du -sh "${RUNTIME_DIR}" | cut -f1)"
echo
echo "Sử dụng:"
echo "  cd \"${PROJECT_DIR}\""
echo "  bash run.sh new \"Ten bo truyen\"        # tạo dự án, chép chương vào projects/<ten>/chapters/"
echo "  bash run.sh run ten_bo_truyen           # chạy toàn bộ"
echo "  bash run.sh status ten_bo_truyen        # xem tiến độ"
echo "============================================================"
