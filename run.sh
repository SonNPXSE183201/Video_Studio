#!/usr/bin/env bash
# Chạy studio.py bằng đúng môi trường Python của Pod.
#   bash run.sh run ten_du_an
#   bash run.sh status ten_du_an
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${AI_STUDIO_HOME:-/workspace/ai-video-studio-runtime}"

if [[ ! -f "${RUNTIME_DIR}/env.sh" ]]; then
  echo "Chưa cài runtime. Hãy chạy: bash ${PROJECT_DIR}/setup.sh" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "${RUNTIME_DIR}/env.sh"

case "${1:-}" in
  run|redo|analyze)
    if ! curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || \
       ! curl -fsS --max-time 3 http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
      echo "Ollama/ComfyUI chưa chạy (thường do vừa Stop/Start Pod). Chạy: AUTO_RUN=0 bash setup.sh" >&2
      exit 1
    fi
    ;;
esac

cd "${PROJECT_DIR}"
exec "${AI_STUDIO_PYTHON}" -u studio.py "$@"
