"""ComfyUI client: chạy workflow API (dựng sẵn hoặc template JSON), tải kết quả về.

Template JSON (thư mục workflows/) dùng placeholder dạng "{{positive}}". Node có khóa
"_optional": "<placeholder>" sẽ bị gỡ nếu placeholder rỗng; "_passthrough": "<input>"
cho biết nối thẳng input nào sang node phía sau khi gỡ (ví dụ LoRA -> model).
"""
import copy
import json
import mimetypes
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set

import requests

from core.utils import log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(ROOT, "workflows")


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, host: str = "http://127.0.0.1:8188", timeout: int = 600):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._object_info: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------- service
    def health(self) -> bool:
        try:
            return requests.get(f"{self.host}/system_stats", timeout=5).status_code == 200
        except Exception:
            return False

    def object_info(self, refresh: bool = False) -> Dict[str, Any]:
        if self._object_info is None or refresh:
            res = requests.get(f"{self.host}/object_info", timeout=30)
            res.raise_for_status()
            self._object_info = res.json()
        return self._object_info

    def available_nodes(self) -> Set[str]:
        try:
            return set(self.object_info().keys())
        except Exception:
            return set()

    def model_files(self, node: str, field: str) -> List[str]:
        try:
            spec = self.object_info()[node]["input"]["required"][field]
            return list(spec[0]) if isinstance(spec[0], list) else []
        except Exception:
            return []

    def free_memory(self) -> None:
        try:
            requests.post(f"{self.host}/free", json={"unload_models": True, "free_memory": True}, timeout=60)
        except Exception:
            pass

    def upload_image(self, path: str) -> str:
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as handle:
            res = requests.post(
                f"{self.host}/upload/image",
                files={"image": (os.path.basename(path), handle, mime)},
                data={"overwrite": "true"},
                timeout=120,
            )
        res.raise_for_status()
        data = res.json()
        return f"{data.get('subfolder', '')}/{data.get('name', os.path.basename(path))}".strip("/")

    # ------------------------------------------------------------ template
    @staticmethod
    def load_template(name_or_path: str) -> Dict[str, Any]:
        path = name_or_path
        if not os.path.exists(path):
            path = os.path.join(WORKFLOW_DIR, f"{name_or_path}.json")
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def fill_template(template: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
        graph = copy.deepcopy(template)
        graph.pop("_meta", None)

        # 1) gỡ node tùy chọn khi placeholder rỗng
        removed: Dict[str, Optional[List[Any]]] = {}
        for node_id, node in list(graph.items()):
            key = node.get("_optional") if isinstance(node, dict) else None
            if key and not values.get(key):
                passthrough = node.get("_passthrough")
                removed[node_id] = node["inputs"].get(passthrough) if passthrough else None
                del graph[node_id]

        def resolve_link(link: Any) -> Any:
            seen = 0
            while isinstance(link, list) and len(link) == 2 and str(link[0]) in removed and seen < 10:
                link = removed[str(link[0])]
                seen += 1
            return link

        def substitute(value: Any) -> Any:
            if isinstance(value, str):
                if value.startswith("{{") and value.endswith("}}") and value.count("{{") == 1:
                    return values.get(value[2:-2], value)
                for key, val in values.items():
                    value = value.replace("{{" + key + "}}", str(val))
                return value
            return value

        for node in graph.values():
            node.pop("_optional", None)
            node.pop("_passthrough", None)
            node.pop("_meta", None)
            inputs = node.get("inputs", {})
            for key in list(inputs):
                value = inputs[key]
                if isinstance(value, list) and len(value) == 2 and str(value[0]) in removed:
                    linked = resolve_link(value)
                    if linked is None:
                        del inputs[key]
                    else:
                        inputs[key] = linked
                else:
                    inputs[key] = substitute(value)
        return graph

    def missing_requirements(self, graph: Dict[str, Any]) -> List[str]:
        """Kiểm tra node và file model mà workflow cần đã có trên ComfyUI chưa."""
        info = self.object_info()
        problems = []
        for node in graph.values():
            cls = node.get("class_type")
            if cls not in info:
                problems.append(f"thiếu node {cls}")
                continue
            required = info[cls].get("input", {}).get("required", {})
            for field, value in node.get("inputs", {}).items():
                spec = required.get(field)
                if (
                    isinstance(value, str)
                    and spec
                    and isinstance(spec[0], list)
                    and field.endswith(("_name", "ckpt_name"))
                    and value not in spec[0]
                ):
                    problems.append(f"thiếu file {value} ({cls})")
        return sorted(set(problems))

    # ---------------------------------------------------------------- run
    def run(self, graph: Dict[str, Any], output_path: str, timeout: Optional[int] = None) -> str:
        res = requests.post(f"{self.host}/prompt", json={"prompt": graph}, timeout=60)
        if res.status_code != 200:
            raise ComfyError(f"ComfyUI từ chối workflow: {res.text[:500]}")
        prompt_id = res.json().get("prompt_id")
        started = time.time()
        limit = timeout or self.timeout
        while time.time() - started < limit:
            time.sleep(2)
            try:
                hist = requests.get(f"{self.host}/history/{prompt_id}", timeout=30)
            except requests.RequestException:
                continue
            if hist.status_code != 200:
                continue
            record = hist.json().get(prompt_id)
            if not record:
                continue
            status = record.get("status", {})
            if status.get("status_str") == "error":
                raise ComfyError(f"ComfyUI lỗi node: {str(status.get('messages', []))[:800]}")
            saved = self._find_output(record.get("outputs", {}))
            if saved:
                params = urllib.parse.urlencode(
                    {"filename": saved["filename"], "subfolder": saved.get("subfolder", ""), "type": saved.get("type", "output")}
                )
                data = requests.get(f"{self.host}/view?{params}", timeout=300)
                data.raise_for_status()
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                tmp = f"{output_path}.part"
                with open(tmp, "wb") as handle:
                    handle.write(data.content)
                os.replace(tmp, output_path)
                return output_path
            if status.get("completed"):
                raise ComfyError("Workflow chạy xong nhưng không có file đầu ra.")
        raise ComfyError(f"Quá {limit}s chờ ComfyUI (prompt {prompt_id}).")

    @staticmethod
    def _find_output(outputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        def walk(value: Any) -> Optional[Dict[str, Any]]:
            if isinstance(value, dict):
                if value.get("filename") and value.get("type", "output") == "output":
                    return value
                for nested in value.values():
                    found = walk(nested)
                    if found:
                        return found
            elif isinstance(value, list):
                for nested in value:
                    found = walk(nested)
                    if found:
                        return found
            return None

        return walk(outputs)


class ImageGenerator:
    """Chọn workflow ảnh theo cấu hình, tự rơi về SDXL nếu pod thiếu node/model."""

    def __init__(self, comfy: ComfyClient, cfg: Dict[str, Any], art: Dict[str, Any]):
        self.comfy = comfy
        self.cfg = cfg
        self.art = art
        self.width = int(cfg.get("width", 1664))
        self.height = int(cfg.get("height", 928))
        self._checked: Dict[str, List[str]] = {}
        self.active_workflow: Optional[str] = None
        self.edit_enabled = False

    def settings_fingerprint(self) -> Dict[str, Any]:
        return {"workflow": self.active_workflow, "edit": self.edit_enabled, "cfg": self.cfg, "art": self.art.get("id")}

    # ---------------------------------------------------------- selection
    def _graph(self, name: str, values: Dict[str, Any]) -> Dict[str, Any]:
        if name == "sdxl":
            return self._sdxl_graph(values)
        return self.comfy.fill_template(self.comfy.load_template(name), values)

    def _values(self, name: str, positive: str, negative: str, seed: int, refs: List[str]) -> Dict[str, Any]:
        section = dict(self.cfg.get(name) or {})
        values: Dict[str, Any] = {
            "positive": positive,
            "negative": negative,
            "seed": int(seed),
            "width": int(section.get("width", self.width)),
            "height": int(section.get("height", self.height)),
        }
        for key, value in section.items():
            values.setdefault(key, value)
        for index in range(3):
            values[f"ref_image_{index + 1}"] = refs[index] if index < len(refs) else ""
        return values

    def _drop_missing_lora(self, name: str, problems: List[str]) -> bool:
        """Thiếu file LoRA Lightning: bỏ LoRA, chuyển sang số bước/CFG thường thay vì bỏ cả workflow."""
        section = self.cfg.get(name)
        lora = str((section or {}).get("lora") or "")
        if not lora or not any(lora in p for p in problems):
            return False
        section["lora"] = ""
        section["steps"] = int(section.get("steps_no_lora", 20))
        section["cfg"] = float(section.get("cfg_no_lora", 2.5))
        log(f"Thiếu LoRA {lora}: '{name}' chạy {section['steps']} bước, CFG {section['cfg']} (chậm hơn).", "Ảnh")
        return True

    def _check(self, name: str, refs: List[str]) -> List[str]:
        for _ in range(2):
            try:
                graph = self._graph(name, self._values(name, "t", "t", 1, refs))
                problems = self.comfy.missing_requirements(graph)
            except Exception as exc:
                return [str(exc)]
            # LoadImage báo thiếu ảnh mẫu giả là bình thường.
            problems = [p for p in problems if "LoadImage" not in p]
            if not problems or not self._drop_missing_lora(name, problems):
                return problems
        return problems

    def prepare(self) -> None:
        """Gọi một lần sau khi ComfyUI chạy: chọn workflow khả dụng."""
        primary = str(self.cfg.get("workflow", "qwen_image"))
        for name in (primary, "sdxl"):
            problems = self._check(name, ["x.png"])
            if not problems:
                self.active_workflow = name
                break
            log(f"Workflow ảnh '{name}' chưa dùng được: {'; '.join(problems[:4])}", "Ảnh")
        if not self.active_workflow:
            raise ComfyError("Không có workflow ảnh nào chạy được trên ComfyUI. Chạy lại setup_pod.sh.")
        edit_name = str(self.cfg.get("edit_workflow", "") or "")
        if edit_name and self.cfg.get("use_reference_edit", True):
            problems = self._check(edit_name, ["a.png", "b.png"])
            self.edit_enabled = not problems
            if problems:
                log(f"Workflow giữ mặt '{edit_name}' chưa dùng được: {'; '.join(problems[:4])}", "Ảnh")
        log(
            f"Workflow ảnh: {self.active_workflow}"
            + (f" + giữ mặt bằng {edit_name}" if self.edit_enabled else ""),
            "Ảnh",
        )

    # ------------------------------------------------------------ generate
    def generate(self, positive: str, negative: str, seed: int, output_path: str, refs: Optional[List[str]] = None) -> str:
        if not self.active_workflow:
            self.prepare()
        refs = [r for r in (refs or []) if r and os.path.exists(r)]
        if refs and self.edit_enabled:
            try:
                uploaded = [self.comfy.upload_image(r) for r in refs[:3]]
                name = str(self.cfg.get("edit_workflow"))
                edit_positive = self._edit_prompt(positive, len(uploaded))
                graph = self._graph(name, self._values(name, edit_positive, negative, seed, uploaded))
                return self.comfy.run(graph, output_path)
            except Exception as exc:
                log(f"Giữ mặt bằng ảnh mẫu lỗi ({exc}); vẽ không dùng ảnh mẫu.", "Ảnh")
        elif self.edit_enabled and self.cfg.get("single_model", True):
            # Một model cho mọi cảnh: không phải đổi qua lại hai model 20 GB (mỗi lần đổi phải nạp lại từ ổ).
            name = str(self.cfg.get("edit_workflow"))
            graph = self._graph(name, self._values(name, positive, negative, seed, []))
            return self.comfy.run(graph, output_path)
        name = self.active_workflow
        graph = self._graph(name, self._values(name, positive, negative, seed, []))
        return self.comfy.run(graph, output_path)

    @staticmethod
    def _edit_prompt(positive: str, count: int) -> str:
        if count == 1:
            lead = "Create a new film frame. The person must have exactly the same face, hairstyle and identity as the person in image 1."
        else:
            lead = (
                "Create a new film frame with two people: the person on the left is the person in "
                "image 1 and the person on the right is the person in image 2, keeping their exact faces and identities."
            )
        return f"{lead} Scene: {positive}"

    # ---------------------------------------------------------------- SDXL
    def _sdxl_graph(self, v: Dict[str, Any]) -> Dict[str, Any]:
        sdxl = self.cfg.get("sdxl") or {}
        ckpt = self.art.get("sdxl_checkpoint") or sdxl.get("checkpoint", "sd_xl_base_1.0.safetensors")
        width, height = int(sdxl.get("width", 1344)), int(sdxl.get("height", 768))
        # Nội dung cảnh đưa vào CẢ text_g (OpenCLIP bigG - encoder mạnh) và text_l.
        def encode(text: str) -> Dict[str, Any]:
            return {
                "class_type": "CLIPTextEncodeSDXL",
                "inputs": {
                    "clip": ["10", 1],
                    "width": width * 2,
                    "height": height * 2,
                    "crop_w": 0,
                    "crop_h": 0,
                    "target_width": width,
                    "target_height": height,
                    "text_g": text,
                    "text_l": text,
                },
            }

        lora = self.art.get("sdxl_lora") or ""
        strength = float(self.art.get("sdxl_lora_strength", 0.8)) if lora else 0.0
        graph = {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
            "10": {
                "class_type": "LoraLoader",
                "inputs": {"model": ["4", 0], "clip": ["4", 1], "lora_name": lora, "strength_model": strength, "strength_clip": strength * 0.85},
            },
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "6": encode(v["positive"]),
            "7": encode(v["negative"]),
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["10", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                    "seed": int(v["seed"]),
                    "steps": int(sdxl.get("steps", 30)),
                    "cfg": float(sdxl.get("cfg", 6.0)),
                    "sampler_name": sdxl.get("sampler", "dpmpp_2m"),
                    "scheduler": sdxl.get("scheduler", "karras"),
                    "denoise": 1.0,
                },
            },
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "AIStudio"}},
        }
        if not lora:
            del graph["10"]
            graph["3"]["inputs"]["model"] = ["4", 0]
            graph["6"]["inputs"]["clip"] = ["4", 1]
            graph["7"]["inputs"]["clip"] = ["4", 1]
        return graph
