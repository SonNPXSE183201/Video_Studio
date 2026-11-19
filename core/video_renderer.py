"""Dựng video bằng FFmpeg: Ken Burns, clip AI, crossfade, phụ đề, nhạc nền, loudnorm.

Nguyên tắc đồng bộ: cảnh i dài đúng d_i giây theo timeline lời đọc. Mỗi segment được
render dài d_i + T (trừ cảnh cuối) rồi xfade chồng T giây, nên tổng thời lượng hình
bằng đúng tổng thời lượng tiếng.
"""
import os
import random
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from core.utils import find_font, log


class RenderError(RuntimeError):
    pass


def _ff_escape(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


class VideoRenderer:
    KB_MODES = ("in", "out", "pan_left", "pan_right", "up", "down")

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.fps = int(cfg.get("fps", 30))
        self.width, self.height = (int(v) for v in cfg.get("resolution", [1920, 1080]))
        self.base_transition = max(0.0, float(cfg.get("transition_sec", 0.5)))
        self.transition = self.base_transition
        kb = cfg.get("ken_burns", {}) or {}
        self.kb_zoom = float(kb.get("zoom", 1.12))
        self.kb_supersample = max(1, int(kb.get("supersample", 2)))
        self.motion_max_slowdown = float(cfg.get("motion_max_slowdown", 1.4))
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg:
            raise RenderError("Không tìm thấy ffmpeg.")
        self._nvenc: Optional[bool] = None

    # -------------------------------------------------------------- encoder
    def nvenc_available(self) -> bool:
        if self._nvenc is None:
            if str(self.cfg.get("encoder", "auto")) == "libx264":
                self._nvenc = False
            else:
                res = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.5",
                     "-c:v", "h264_nvenc", "-f", "null", "-"],
                    capture_output=True,
                )
                self._nvenc = res.returncode == 0
        return self._nvenc

    def _venc(self, final: bool) -> List[str]:
        gop = ["-g", str(self.fps * 2)]
        if self.nvenc_available():
            cq = int(self.cfg.get("cq", 20)) if final else 16
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                    "-profile:v", "high", "-pix_fmt", "yuv420p"] + gop
        crf = int(self.cfg.get("crf", 20)) if final else 15
        preset = str(self.cfg.get("x264_preset", "medium")) if final else "veryfast"
        return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"] + gop

    def _run(self, cmd: List[str], cwd: Optional[str] = None) -> None:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise RenderError(f"FFmpeg lỗi ({res.returncode}): {res.stderr[-1500:]}")

    def probe_duration(self, path: str) -> float:
        if not self.ffprobe:
            return 0.0
        res = subprocess.run(
            [self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True,
        )
        try:
            return float(res.stdout.strip())
        except ValueError:
            return 0.0

    # ------------------------------------------------------------ segments
    def pick_kb_mode(self, seed: int, shot_type: str = "") -> str:
        rng = random.Random(seed)
        if shot_type in ("close_up", "insert"):
            return rng.choice(("in", "in", "out"))
        if shot_type == "wide_shot":
            return rng.choice(("pan_left", "pan_right", "out", "in"))
        if shot_type == "action_shot":
            return "in"
        return rng.choice(self.KB_MODES)

    def _kb_filter(self, mode: str, frames: int, zoom: Optional[float] = None) -> str:
        W, H, ss = self.width, self.height, self.kb_supersample
        z = zoom or self.kb_zoom
        dz = z - 1.0
        n = max(1, frames - 1)
        center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        exprs = {
            "in": (f"1+{dz:.4f}*on/{n}", center_x, center_y),
            "out": (f"{z:.4f}-{dz:.4f}*on/{n}", center_x, center_y),
            "pan_right": (f"{z:.4f}", f"(iw-iw/zoom)*on/{n}", center_y),
            "pan_left": (f"{z:.4f}", f"(iw-iw/zoom)*(1-on/{n})", center_y),
            "down": (f"{z:.4f}", center_x, f"(ih-ih/zoom)*on/{n}"),
            "up": (f"{z:.4f}", center_x, f"(ih-ih/zoom)*(1-on/{n})"),
        }
        zexpr, x, y = exprs.get(mode, exprs["in"])
        return (
            f"scale={W * ss}:{H * ss}:force_original_aspect_ratio=increase,crop={W * ss}:{H * ss},setsar=1,"
            f"zoompan=z='{zexpr}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={self.fps},format=yuv420p"
        )

    def _cover(self) -> str:
        return (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
            f"crop={self.width}:{self.height},setsar=1"
        )

    def render_image_segment(self, image: str, seconds: float, mode: str, out: str) -> float:
        frames = max(2, int(round(seconds * self.fps)))
        cmd = [self.ffmpeg, "-y", "-i", image, "-vf", self._kb_filter(mode, frames),
               "-frames:v", str(frames), "-an", "-r", str(self.fps)] + self._venc(False) + [out]
        self._run(cmd)
        return frames / float(self.fps)

    def render_clip_segment(self, clip: str, image: str, seconds: float, out: str) -> float:
        frames = max(2, int(round(seconds * self.fps)))
        clip_len = self.probe_duration(clip)
        if clip_len <= 0.2:
            raise RenderError(f"Clip hỏng: {clip}")
        if seconds <= clip_len * self.motion_max_slowdown:
            factor = max(1.0, seconds / clip_len)
            vf = f"{self._cover()},setpts={factor:.5f}*PTS,fps={self.fps},format=yuv420p"
            cmd = [self.ffmpeg, "-y", "-i", clip, "-vf", vf, "-frames:v", str(frames), "-an", "-r", str(self.fps)] + self._venc(False) + [out]
            self._run(cmd)
            return frames / float(self.fps)
        # Cảnh dài hơn clip: chạy clip (chậm tối đa motion_max_slowdown) rồi nối Ken Burns từ frame cuối.
        last_frame = f"{out}.last.jpg"
        self._run([self.ffmpeg, "-y", "-sseof", "-0.25", "-i", clip, "-update", "1", "-frames:v", "1", "-q:v", "2", last_frame])
        part_a = clip_len * self.motion_max_slowdown
        frames_a = max(1, int(round(part_a * self.fps)))
        frames_b = max(2, frames - frames_a)
        graph = (
            f"[0:v]{self._cover()},setpts={self.motion_max_slowdown:.5f}*PTS,fps={self.fps},format=yuv420p,"
            f"trim=end_frame={frames_a},setpts=PTS-STARTPTS[a];"
            f"[1:v]{self._kb_filter('in', frames_b, zoom=1.0 + (self.kb_zoom - 1.0) * 0.6)}[b];"
            f"[a][b]concat=n=2:v=1:a=0[v]"
        )
        cmd = [self.ffmpeg, "-y", "-i", clip, "-i", last_frame, "-filter_complex", graph, "-map", "[v]",
               "-frames:v", str(frames), "-an", "-r", str(self.fps)] + self._venc(False) + [out]
        try:
            self._run(cmd)
        finally:
            if os.path.exists(last_frame):
                os.remove(last_frame)
        return frames / float(self.fps)

    # ------------------------------------------------------------ assembly
    def xfade_chain(self, segments: List[str], durations: List[float], out: str, group: int = 24) -> float:
        """Nối các segment với crossfade T giây. Trả về tổng thời lượng."""
        T = self.transition
        if len(segments) == 1 or T <= 0:
            list_path = f"{out}.txt"
            with open(list_path, "w", encoding="utf-8") as handle:
                for seg in segments:
                    handle.write(f"file '{os.path.abspath(seg).replace(os.sep, '/')}'\n")
            self._run([self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out])
            os.remove(list_path)
            return sum(durations) - (len(durations) - 1) * T
        if len(segments) > group:
            parts, part_durs = [], []
            for start in range(0, len(segments), group):
                sub_out = f"{out}.part{start // group:03d}.mp4"
                part_durs.append(self.xfade_chain(segments[start:start + group], durations[start:start + group], sub_out, group))
                parts.append(sub_out)
            total = self.xfade_chain(parts, part_durs, out, group)
            for path in parts:
                if os.path.exists(path):
                    os.remove(path)
            return total

        cmd = [self.ffmpeg, "-y"]
        for seg in segments:
            cmd += ["-i", seg]
        lines, label, acc = [], "0:v", durations[0]
        for index in range(1, len(segments)):
            offset = acc - T
            new_label = f"x{index}"
            lines.append(f"[{label}][{index}:v]xfade=transition=fade:duration={T:.3f}:offset={offset:.3f}[{new_label}]")
            label = new_label
            acc = acc + durations[index] - T
        # Truyền filter trực tiếp: -filter_complex_script đã bị gỡ ở FFmpeg 7+,
        # còn cú pháp mới "-/filter_complex" không có ở FFmpeg 4-6 của Ubuntu.
        cmd += ["-filter_complex", ";".join(lines), "-map", f"[{label}]", "-an", "-r", str(self.fps)] + self._venc(False) + [out]
        self._run(cmd)
        return acc

    def finalize(
        self,
        video: str,
        audio: str,
        ass_path: Optional[str],
        out: str,
        total_sec: float,
        watermark: str = "",
        bgm: Optional[str] = None,
    ) -> None:
        video, audio = os.path.abspath(video), os.path.abspath(audio)
        bgm = os.path.abspath(bgm) if bgm else None
        work = os.path.dirname(video)
        filters: List[str] = []
        vchain = "[0:v]"
        steps: List[str] = []
        if ass_path and os.path.exists(ass_path):
            local_ass = os.path.join(work, "subs.ass")
            if os.path.abspath(ass_path) != local_ass:
                shutil.copyfile(ass_path, local_ass)
            sub = "subtitles=f=subs.ass"
            fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
            if os.path.isdir(fonts_dir) and os.listdir(fonts_dir):
                sub += f":fontsdir='{_ff_escape(fonts_dir)}'"
            steps.append(sub)
        font = find_font(bold=True)
        if watermark and font:
            with open(os.path.join(work, "watermark.txt"), "w", encoding="utf-8") as handle:
                handle.write(watermark)
            steps.append(
                f"drawtext=textfile=watermark.txt:fontfile='{_ff_escape(font)}':x=w-tw-40:y=36:"
                "fontsize=30:fontcolor=white@0.45:borderw=2:bordercolor=black@0.35"
            )
        filters.append(f"{vchain}{','.join(steps) if steps else 'null'}[v]")
        lufs = float(self.cfg.get("loudness_lufs", -16))
        filters.append(f"[1:a]aresample=48000,loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[voice]")
        cmd = [self.ffmpeg, "-y", "-i", video, "-i", audio]
        if bgm and os.path.exists(bgm):
            bgm_db = float(self.cfg.get("bgm", {}).get("volume_db", -22))
            cmd += ["-stream_loop", "-1", "-i", bgm]
            filters += [
                "[voice]asplit=2[vo][sc]",
                f"[2:a]aresample=48000,volume={bgm_db}dB,afade=t=in:d=2[bg]",
                "[bg][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bgd]",
                "[vo][bgd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]",
            ]
        else:
            filters.append("[voice]anull[a]")
        cmd += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]"] + self._venc(True)
        cmd += ["-c:a", "aac", "-b:a", "192k", "-t", f"{total_sec:.3f}", "-movflags", "+faststart", os.path.abspath(out)]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        tmp_out = os.path.abspath(out) + ".tmp.mp4"
        cmd[-1] = tmp_out
        self._run(cmd, cwd=work)
        os.replace(tmp_out, out)

    def render_chapter(
        self,
        scenes: List[Dict[str, Any]],
        audio_wav: str,
        ass_path: Optional[str],
        out_mp4: str,
        work_dir: str,
        total_sec: float,
        watermark: str = "",
        bgm: Optional[str] = None,
    ) -> None:
        """scenes: [{image, clip|None, duration, kb_mode}] theo thứ tự."""
        os.makedirs(work_dir, exist_ok=True)
        T = self.base_transition
        if scenes:
            T = min(T, min(s["duration"] for s in scenes) / 2.0)
        self.transition = T
        segments, durations = [], []
        for index, scene in enumerate(scenes):
            length = scene["duration"] + (T if index < len(scenes) - 1 else 0.0)
            seg = os.path.join(work_dir, f"seg_{index + 1:04d}.mp4")
            clip = scene.get("clip")
            if clip and os.path.exists(clip):
                try:
                    durations.append(self.render_clip_segment(clip, scene["image"], length, seg))
                    segments.append(seg)
                    continue
                except RenderError as exc:
                    log(f"Cảnh {index + 1}: clip lỗi, dùng Ken Burns ({str(exc)[:120]})", "Render")
            durations.append(self.render_image_segment(scene["image"], length, scene.get("kb_mode", "in"), seg))
            segments.append(seg)
            if (index + 1) % 20 == 0:
                log(f"  segment {index + 1}/{len(scenes)}", "Render")
        silent = os.path.join(work_dir, "video_silent.mp4")
        log("Ghép crossfade...", "Render")
        self.xfade_chain(segments, durations, silent)
        log("Ghép tiếng, phụ đề, nhạc nền...", "Render")
        self.finalize(silent, audio_wav, ass_path, out_mp4, total_sec, watermark, bgm)
        for path in segments + [silent]:
            if os.path.exists(path):
                os.remove(path)

    def concat_videos(self, videos: List[str], out: str) -> None:
        list_path = f"{out}.txt"
        with open(list_path, "w", encoding="utf-8") as handle:
            for video in videos:
                handle.write(f"file '{os.path.abspath(video).replace(os.sep, '/')}'\n")
        tmp = f"{out}.tmp.mp4"
        try:
            self._run([self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", "-movflags", "+faststart", tmp])
            os.replace(tmp, out)
        finally:
            if os.path.exists(list_path):
                os.remove(list_path)
