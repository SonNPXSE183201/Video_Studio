"""Đẩy file lên Google Drive bằng rclone; chỉ xóa bản local khi upload thành công."""
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from core.utils import log


class DriveSync:
    def __init__(self, cfg: Dict[str, Any], log_file: str):
        self.enabled = bool(cfg.get("enabled", True))
        self.remote = str(cfg.get("remote_dest", "gdrive:AI_Video_Studio")).rstrip("/")
        self.config_path = cfg.get("config_path", "rclone.conf")
        self.log_file = log_file

    def _config(self) -> Optional[str]:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for path in (
            self.config_path,
            os.path.join(root, str(self.config_path)),
            "/workspace/rclone.conf",
            os.path.expanduser("~/.config/rclone/rclone.conf"),
        ):
            if path and os.path.exists(path):
                return path
        return None

    def available(self) -> bool:
        return self.enabled and shutil.which("rclone") is not None and self._config() is not None

    def upload(self, local_path: str, subfolder: str = "", delete_after: bool = False) -> bool:
        if not self.enabled or not os.path.exists(local_path):
            return False
        marker = f"{local_path}.uploaded"
        if os.path.exists(marker):
            return True
        if not self.available():
            log("Thiếu rclone hoặc rclone.conf; giữ file trên pod.", "Drive")
            return False
        dest = f"{self.remote}/{subfolder}".rstrip("/") if subfolder else self.remote
        cmd = ["rclone", "copy", local_path, dest, "--config", self._config(), "--retries", "5"]
        log(f"Upload {os.path.basename(local_path)} -> {dest}", "Drive")
        os.makedirs(os.path.dirname(self.log_file) or ".", exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as handle:
            result = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            log(f"Upload thất bại, xem {self.log_file}. File gốc được giữ.", "Drive")
            return False
        open(marker, "a").close()
        if delete_after:
            try:
                os.remove(local_path)
            except OSError:
                pass
        return True
