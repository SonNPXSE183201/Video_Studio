"""Đẩy file lên Google Drive bằng rclone; chỉ xóa bản local khi upload thành công.

Nếu khai báo `root_folder_id` (ID trong link drive.google.com/drive/folders/<ID>), mọi file được
đưa vào đúng thư mục đó, mỗi bộ truyện một thư mục con. Dùng ID thay cho đường dẫn chữ để tránh
lỗi tên tiếng Việt có dấu (cùng tên nhưng khác mã Unicode -> rclone tạo thư mục trùng).
"""
import os
import re
import shutil
import subprocess
import unicodedata
from typing import Any, Dict, List, Optional

from core.utils import log


def drive_folder_name(name: str) -> str:
    """Tên thư mục Drive an toàn: NFC, bỏ ký tự rclone/Drive không cho."""
    name = unicodedata.normalize("NFC", str(name or "")).strip()
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", name)
    return re.sub(r"\s+", " ", name).strip(" .") or "Khong_ten"


class DriveSync:
    def __init__(self, cfg: Dict[str, Any], log_file: str):
        self.enabled = bool(cfg.get("enabled", True))
        self.root_folder_id = str(cfg.get("root_folder_id") or "").strip()
        self.remote_name = str(cfg.get("remote", "gdrive")).rstrip(":")
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

    def destination(self, subfolder: str = "") -> List[str]:
        """Đích rclone + cờ cần thêm. subfolder dạng 'Tên truyện/review'."""
        parts = [drive_folder_name(p) for p in str(subfolder or "").split("/") if p.strip()]
        sub = "/".join(parts)
        if self.root_folder_id:
            return [f"{self.remote_name}:{sub}", "--drive-root-folder-id", self.root_folder_id]
        return [f"{self.remote}/{sub}".rstrip("/") if sub else self.remote]

    def upload(self, local_path: str, subfolder: str = "", delete_after: bool = False) -> bool:
        if not self.enabled or not os.path.exists(local_path):
            return False
        marker = f"{local_path}.uploaded"
        if os.path.exists(marker):
            return True
        if not self.available():
            log("Thiếu rclone hoặc rclone.conf; giữ file trên pod.", "Drive")
            return False
        dest = self.destination(subfolder)
        cmd = ["rclone", "copy", local_path, dest[0], *dest[1:], "--config", self._config(), "--retries", "5"]
        log(f"Upload {os.path.basename(local_path)} -> {dest[0]}", "Drive")
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
