#!/usr/bin/env bash
# Cài/khôi phục runtime trên RunPod, khởi động Ollama + ComfyUI, rồi (tùy chọn)
# tự chạy dự án ở chế độ nền.
#   bash setup.sh                       # cài xong tự chạy nếu chỉ có 1 dự án
#   PROJECT=ten_du_an bash setup.sh     # chỉ định dự án cần chạy
#   AUTO_RUN=0 bash setup.sh            # chỉ cài và bật dịch vụ
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${AI_STUDIO_HOME:-/workspace/ai-video-studio-runtime}"

bash "${PROJECT_DIR}/pod/setup_pod.sh" "$@"

if [[ "${AUTO_RUN:-1}" != "1" ]]; then
  echo "[INFO] AUTO_RUN=0: đã cài xong, chưa chạy dự án."
  exit 0
fi

target="${PROJECT:-}"
if [[ -z "${target}" ]]; then
  mapfile -t candidates < <(
    for dir in "${PROJECT_DIR}"/projects/*/; do
      [[ -d "${dir}chapters" ]] && compgen -G "${dir}chapters/*.txt" >/dev/null && basename "${dir}"
    done
  )
  if (( ${#candidates[@]} == 1 )); then
    target="${candidates[0]}"
  else
    echo "[INFO] Có ${#candidates[@]} dự án có chương: ${candidates[*]:-không có}."
    echo "Chạy một dự án: PROJECT=ten_du_an bash setup.sh  hoặc  bash run.sh run ten_du_an"
    exit 0
  fi
fi

pid_file="${RUNTIME_DIR}/run_${target}.pid"
log_file="${RUNTIME_DIR}/logs/run_${target}.log"
if [[ -s "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
  echo "[OK] Dự án ${target} đang chạy (PID $(cat "${pid_file}")). Log: ${log_file}"
  exit 0
fi
mkdir -p "$(dirname "${log_file}")"
echo "[AUTO] Chạy nền dự án ${target}..."
nohup bash "${PROJECT_DIR}/run.sh" run "${target}" ${RUN_ARGS:-} >"${log_file}" 2>&1 </dev/null &
echo "$!" >"${pid_file}"
sleep 2
if ! kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
  echo "[LỖI] Không khởi động được. Log cuối:" >&2
  tail -n 80 "${log_file}" >&2 || true
  exit 1
fi
echo "[OK] Đang chạy nền (PID $(cat "${pid_file}")). Theo dõi: tail -f ${log_file}"
