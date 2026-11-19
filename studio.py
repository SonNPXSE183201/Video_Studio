#!/usr/bin/env python3
"""AI Video Studio - biến chương truyện thành video, chạy hoàn toàn bằng terminal.

  python studio.py new  "Tên bộ truyện" [--from thu_muc_chuong]
  python studio.py run  ten_du_an [--chapters 1-10] [--finish] [--stop-pod]
  python studio.py status ten_du_an
  python studio.py redo ten_du_an --ch 3 [--scene 12] --stage image
  python studio.py check
  python studio.py styles
"""
import argparse
import os
import shutil
import sys
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.pipeline import STAGES, Studio  # noqa: E402
from core.project import Project  # noqa: E402
from core.style import list_art_styles, list_styles, list_themes  # noqa: E402
from core.utils import format_duration, parse_range, read_json, read_yaml  # noqa: E402


def load_config(path: str):
    cfg = read_yaml(path, {})
    if not cfg:
        sys.exit(f"Không đọc được cấu hình {path}")
    return cfg


def projects_dir(cfg) -> str:
    path = cfg.get("paths", {}).get("projects_dir", "projects")
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def open_project(cfg, name: str) -> Project:
    project = Project(projects_dir(cfg), name)
    if not project.exists():
        existing = sorted(os.listdir(projects_dir(cfg))) if os.path.isdir(projects_dir(cfg)) else []
        sys.exit(f"Chưa có dự án '{project.slug}'. Tạo bằng: python studio.py new \"{name}\"\nDự án hiện có: {', '.join(existing) or '(trống)'}")
    return project


# ---------------------------------------------------------------- commands
def set_project_voice(project: Project, wav: str, text: Optional[str] = None) -> None:
    """Chép giọng mẫu (wav + file lời đúng từng chữ) vào dự án và khai báo trong series.yaml."""
    if not os.path.isfile(wav):
        raise SystemExit(f"Không thấy file giọng mẫu: {wav}")
    text = text or os.path.splitext(wav)[0] + ".txt"
    folder = os.path.join(project.root, "voice")
    os.makedirs(folder, exist_ok=True)
    shutil.copyfile(wav, os.path.join(folder, "voice.wav"))
    series = project.load_series()
    series.setdefault("voice", {})["ref_audio"] = "voice/voice.wav"
    if os.path.isfile(text):
        shutil.copyfile(text, os.path.join(folder, "voice.txt"))
        series["voice"]["ref_text"] = "voice/voice.txt"
    else:
        print(f"[Cảnh báo] Không có file lời {text}: OmniVoice sẽ tự nhận dạng lời giọng mẫu (kém ổn định hơn).")
    project.save_series(series)
    print(f"Giọng đọc: {folder}")


def cmd_voice(cfg, args) -> None:
    set_project_voice(open_project(cfg, args.name), args.wav, args.text)


def cmd_new(cfg, args) -> None:
    project = Project(projects_dir(cfg), args.name)
    imported = project.create(args.name, args.import_from)
    print(f"Đã tạo dự án: {project.root}")
    if imported:
        print(f"Đã nhập {len(imported)} chương từ {args.import_from}")
    if args.voice:
        set_project_voice(project, args.voice, args.voice_text)
    print(f"\n1. Chép file chương .txt vào: {project.chapters_dir}")
    print(f"2. (Tùy chọn) sửa {project.series_path} để chọn giọng đọc, thể loại, watermark")
    print(f"3. Chạy: python studio.py run {project.slug}")


def cmd_run(cfg, args) -> None:
    project = open_project(cfg, args.name)
    options = {
        "force": [s.strip() for s in (args.force or "").split(",") if s.strip()],
        "until": args.until,
        "stop_pod": args.stop_pod,
    }
    if args.no_upload:
        cfg.setdefault("upload", {})["enabled"] = False
    ok = Studio(cfg, project, options).run(parse_range(args.chapters), finish=args.finish)
    sys.exit(0 if ok else 1)


def cmd_redo(cfg, args) -> None:
    project = open_project(cfg, args.name)
    stage = {"image": "images", "img": "images"}.get(args.stage, args.stage)
    if stage not in STAGES:
        sys.exit(f"--stage phải là một trong: {', '.join(STAGES)}")
    redo = {}
    force = []
    if args.scene is not None:
        if stage not in ("images", "motion"):
            sys.exit("--scene chỉ dùng với --stage image hoặc motion")
        redo = {args.ch: {args.scene}}
    else:
        force = [stage]
    options = {"force": force + ["render"], "redo_scenes": redo, "stop_pod": False}
    ok = Studio(cfg, project, options).run({args.ch}, finish=False)
    sys.exit(0 if ok else 1)


def cmd_analyze(cfg, args) -> None:
    project = open_project(cfg, args.name)
    studio = Studio(cfg, project, {"force": ["analyze"]})
    studio.ensure_series()
    print(f"Kết quả đã lưu vào {project.series_path}")


def cmd_status(cfg, args) -> None:
    project = open_project(cfg, args.name)
    series = project.load_series()
    print(f"Dự án   : {project.slug}  ({series.get('title')})")
    print(f"Thể loại: {series.get('genre')} | Chủ đề: {series.get('themes') or '-'} | "
          f"Vẽ: {series.get('art_style')} | {series.get('era_en', '')}")
    if series.get("genre_by_chapter"):
        print(f"Theo chương: {series['genre_by_chapter']}")
    chars = read_json(project.characters_path, {}) or {}
    locs = read_json(project.locations_path, {}) or {}
    refs = sum(1 for c in chars.values() if c.get("anh_tham_chieu"))
    print(f"Bible   : {len(chars)} nhân vật ({refs} có ảnh mẫu), {len(locs)} địa điểm\n")
    print(f"{'Chương':>7} | {'Cảnh':>4} | {'Audio':>8} | {'Ảnh':>7} | {'Motion':>6} | Video")
    for number, _ in project.chapter_files():
        work = os.path.join(project.work_dir, f"ch{number:04d}")
        scenes = (read_json(os.path.join(work, "scenes.json"), {}) or {}).get("scenes", [])
        timeline = read_json(os.path.join(work, "audio", "timeline.json"), {}) or {}
        state = read_json(os.path.join(work, "state.json"), {}) or {}
        images = state.get("images", {})
        qa_fail = sum(1 for r in images.values() if (r.get("qa") or {}).get("ok") is False)
        video = project.chapter_video_path(number)
        audio = format_duration(timeline["total_duration_sec"]) if timeline.get("total_duration_sec") else "-"
        img = f"{len(images)}" + (f"/{qa_fail}!" if qa_fail else "")
        print(f"{number:>7} | {len(scenes) or '-':>4} | {audio:>8} | {img:>7} | {len(state.get('motion', {})):>6} | "
              f"{'XONG (.done, đã lên Drive)' if project.is_done(number) else ('OK' if os.path.exists(video) else '-')}")
    episodes = read_json(project.episodes_state_path, {}) or {}
    if episodes:
        print("\nTập đã ghép:")
        for number, record in sorted(episodes.items(), key=lambda x: int(x[0])):
            print(f"  Tập {number}: {record.get('file')} {'(đã upload)' if record.get('uploaded') else ''}")
    print(f"\nLog: {os.path.join(project.logs_dir, 'studio.log')}")


def cmd_styles(cfg, args) -> None:
    print("THỂ LOẠI (genre trong series.yaml):")
    for style_id, name, desc in list_styles():
        print(f"  {style_id:<20} {name}")
    print("\nCHỦ ĐỀ cộng thêm (themes trong series.yaml, chọn nhiều được):")
    for theme_id, name, desc in list_themes():
        print(f"  {theme_id:<20} {name}")
    print("\nPHONG CÁCH VẼ (art_style trong series.yaml):")
    for style_id, data in list_art_styles().items():
        print(f"  {style_id:<20} {data.get('name', '')}")


def cmd_drive(cfg, args) -> None:
    import tempfile
    import time

    from core.drive_sync import DriveSync

    project = open_project(cfg, args.name)
    series = project.load_series()
    folder = str(series.get("drive_folder") or series.get("title") or project.slug)
    drive = DriveSync(cfg.get("upload", {}), os.path.join(project.logs_dir, "upload.log"))
    print(f"Đích: {' '.join(drive.destination(folder + '/review'))}")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "_kiem_tra_ket_noi.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"AI Video Studio - kiểm tra upload {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        ok = drive.upload(path, f"{folder}/review")
    print("[OK] Upload được, xem thư mục trên Drive." if ok else f"[XX] Upload lỗi, xem {drive.log_file}")


def cmd_check(cfg, args) -> None:
    from core.comfy_client import ComfyClient, ImageGenerator
    from core.motion_client import MotionGenerator
    from core.ollama_client import OllamaClient
    from core.style import load_art_style

    ok = True

    def report(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"[{'OK' if good else 'XX'}] {label}{(' - ' + detail) if detail else ''}")

    report("ffmpeg", bool(shutil.which("ffmpeg")))
    report("ffprobe", bool(shutil.which("ffprobe")))
    report("rclone", bool(shutil.which("rclone")), "chỉ cần khi upload Drive")
    ollama = OllamaClient(cfg.get("ollama", {}))
    if ollama.health():
        report("Ollama", True, ollama.host)
        report(f"LLM {ollama.model}", ollama.has_model(ollama.model))
        report(f"VLM {ollama.vision_model}", ollama.has_model(ollama.vision_model), "thiếu thì bỏ qua QA ảnh")
    else:
        report("Ollama", False, f"không chạy ở {ollama.host}")
    comfy = ComfyClient(cfg.get("comfyui", {}).get("host", "http://127.0.0.1:8188"))
    if comfy.health():
        report("ComfyUI", True, comfy.host)
        try:
            gen = ImageGenerator(comfy, cfg.get("image", {}), load_art_style("3d_donghua"))
            gen.prepare()
            report("Workflow ảnh", True, f"{gen.active_workflow}{' + giữ mặt' if gen.edit_enabled else ''}")
        except Exception as exc:
            report("Workflow ảnh", False, str(exc))
        motion = MotionGenerator(comfy, cfg.get("motion", {}))
        report(f"Motion {motion.model}", motion.prepare(), "; ".join(motion.problems[:3]))
    else:
        report("ComfyUI", False, f"không chạy ở {comfy.host}")
    try:
        import torch

        report("CUDA", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    except ImportError:
        report("PyTorch", False, "chưa cài")
    for module, label in (("omnivoice", "OmniVoice"), ("transformers", "Transformers (ASR)"), ("soundfile", "soundfile")):
        try:
            __import__(module)
            report(label, True)
        except ImportError:
            report(label, False)
    sys.exit(0 if ok else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Video Studio - chương truyện thành video tự động")
    parser.add_argument("--config", default=os.path.join(ROOT, "config", "settings.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="Tạo dự án (bộ truyện) mới")
    p.add_argument("name")
    p.add_argument("--from", dest="import_from", help="Thư mục chứa các file chương .txt để nhập")
    p.add_argument("--voice", help="File giọng mẫu .wav (6-10 giây) để clone")
    p.add_argument("--voice-text", help="File lời của giọng mẫu (mặc định: cùng tên .txt)")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("voice", help="Đổi giọng clone của dự án")
    p.add_argument("name")
    p.add_argument("wav")
    p.add_argument("--text", help="File lời của giọng mẫu (mặc định: cùng tên .txt)")
    p.set_defaults(func=cmd_voice)

    p = sub.add_parser("run", help="Chạy toàn bộ quy trình")
    p.add_argument("name")
    p.add_argument("--chapters", help="Ví dụ: 1-10 hoặc 3,5,8 (mặc định: tất cả)")
    p.add_argument("--until", choices=STAGES, help="Dừng sau bước này (xem thử nhanh)")
    p.add_argument("--force", help=f"Làm lại các bước: {','.join(STAGES)},analyze,done (chạy lại cả chương đã .done)")
    p.add_argument("--finish", action="store_true", help="Ghép cả tập cuối dù chưa đủ số chương")
    p.add_argument("--no-upload", action="store_true", help="Không upload Google Drive")
    p.add_argument("--stop-pod", action="store_true", help="Tự tắt RunPod khi xong")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("redo", help="Làm lại một bước / một cảnh của một chương")
    p.add_argument("name")
    p.add_argument("--ch", type=int, required=True)
    p.add_argument("--scene", type=int)
    p.add_argument("--stage", required=True, help="direct | audio | image | motion | render")
    p.set_defaults(func=cmd_redo)

    p = sub.add_parser("analyze", help="Phân tích lại thể loại/thời đại bộ truyện")
    p.add_argument("name")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("status", help="Xem tiến độ dự án")
    p.add_argument("name")
    p.set_defaults(func=cmd_status)

    sub.add_parser("styles", help="Liệt kê thể loại và phong cách vẽ").set_defaults(func=cmd_styles)
    sub.add_parser("check", help="Kiểm tra dịch vụ, model, GPU").set_defaults(func=cmd_check)

    p = sub.add_parser("drive", help="Thử upload một file nhỏ lên thư mục Drive của bộ truyện")
    p.add_argument("name")
    p.set_defaults(func=cmd_drive)

    args = parser.parse_args()
    args.func(load_config(args.config), args)


if __name__ == "__main__":
    main()
