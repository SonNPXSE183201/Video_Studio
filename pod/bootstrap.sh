#!/usr/bin/env bash
# MỘT LỆNH cho pod mới tạo hoặc pod vừa Start lại:
#
#   curl -fsSL https://raw.githubusercontent.com/SonNPXSE183201/Video_Studio/main/pod/bootstrap.sh | bash
#
# - Code đặt ở /root/AI_Video_Studio (ổ container): volume Global của RunPod không cho
#   chmod nên git clone vào /workspace bị lỗi. Code mất khi Stop pod -> lệnh này tự clone lại.
# - Dữ liệu (model, dự án, rclone.conf) nằm trên volume /workspace nên không mất.
# Biến tùy chọn: AUTO_RUN=1 PROJECT=ten_du_an (cài xong tự chạy), INSTALL_WAN14B=1, ...
set -Eeuo pipefail

REPO="${REPO:-https://github.com/SonNPXSE183201/Video_Studio.git}"
CODE_DIR="${CODE_DIR:-/root/AI_Video_Studio}"
LOG="${SETUP_LOG:-/workspace/setup.log}"

if [[ -d "${CODE_DIR}/.git" ]]; then
  git -C "${CODE_DIR}" pull --ff-only
else
  git clone --depth 1 "${REPO}" "${CODE_DIR}"
fi

cd "${CODE_DIR}"
echo "[INFO] Cài đặt, log đầy đủ: ${LOG}"
AUTO_RUN="${AUTO_RUN:-0}" bash setup.sh 2>&1 | tee "${LOG}"

cat <<EOF

Lệnh tiếp theo:
  cd ${CODE_DIR}
  bash run.sh check
  bash run.sh new "Ten Bo Truyen"     # chương .txt chép vào /workspace/video_studio_projects/<ten>/chapters/
  bash run.sh run ten_bo_truyen
EOF
