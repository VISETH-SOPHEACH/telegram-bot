import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yt_dlp


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
MIN_MP3_BITRATE_KBPS = 32
DEFAULT_AUDIO_BITRATE_KBPS = 128
FFMPEG_VIDEO_SCALE_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
MIN_MP4_AUDIO_BITRATE_KBPS = 64
MIN_MP4_VIDEO_BITRATE_KBPS = 120
MP4_CONTAINER_OVERHEAD_KBPS = 32
_FFMPEG_PATH: str | None = None


class DownloadError(Exception):
    pass


@dataclass(frozen=True)
class DownloadPlan:
    format_selector: str
    merge_output_format: str | None = None
    preferred_audio_quality_kbps: int | None = None
    expected_size_bytes: int | None = None
    strategy: str = "default"


def _read_upload_limit_bytes() -> int:
    raw_value = os.getenv("TELEGRAM_MAX_UPLOAD_MB", "50").strip()
    try:
        upload_limit_mb = float(raw_value)
    except ValueError:
        upload_limit_mb = 50.0

    if upload_limit_mb <= 0:
        upload_limit_mb = 50.0

    return int(upload_limit_mb * 1024 * 1024)


TELEGRAM_UPLOAD_LIMIT_BYTES = _read_upload_limit_bytes()
TARGET_UPLOAD_BYTES = max(1, TELEGRAM_UPLOAD_LIMIT_BYTES - (2 * 1024 * 1024))


def _get_ffmpeg_path(required: bool = True) -> str | None:
    global _FFMPEG_PATH

    if _FFMPEG_PATH and Path(_FFMPEG_PATH).exists():
        return _FFMPEG_PATH

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        try:
            import imageio_ffmpeg  # type: ignore
        except ImportError:
            ffmpeg_path = None
        else:
            try:
                ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                ffmpeg_path = None

    if not ffmpeg_path and required:
        raise DownloadError(
            "ffmpeg is required for high-quality downloads. Install the dependencies from requirements.txt and try again."
        )

    _FFMPEG_PATH = ffmpeg_path
    return ffmpeg_path


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _replace_file(
    original: Path, replacement: Path, *, keep_original_name: bool = True
) -> Path:
    original.unlink(missing_ok=True)
    if keep_original_name:
        replacement.replace(original)
        return original
    return replacement


def _replace_file_with_new_path(
    original: Path, replacement: Path, destination: Path
) -> Path:
    original.unlink(missing_ok=True)
    replacement.replace(destination)
    return destination


def _run_command(command: list[str], error_message: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return

    details = (result.stderr or result.stdout or "").strip()
    if details:
        raise DownloadError(f"{error_message} ffmpeg said: {details[-400:]}")
    raise DownloadError(error_message)


def _replace_if_better_candidate(
    best_candidate: Path | None, candidate: Path
) -> Path:
    if best_candidate and best_candidate.exists() and best_candidate != candidate:
        best_candidate.unlink(missing_ok=True)
    return candidate


def _probe_media(file_path: Path) -> dict[str, object] | None:
    ffmpeg_path = _get_ffmpeg_path(required=False)
    if not ffmpeg_path:
        return None

    result = subprocess.run(
        [ffmpeg_path, "-hide_banner", "-i", str(file_path)],
        capture_output=True,
        text=True,
    )

    output = "\n".join(part for part in (result.stderr, result.stdout) if part).strip()
    if not output:
        return None

    format_name = ""
    duration_seconds: float | None = None
    video_codec = ""
    pixel_format = ""
    audio_codec = ""

    for line in output.splitlines():
        stripped = line.strip()

        if stripped.startswith("Input #0, "):
            format_name = stripped[len("Input #0, ") :].rsplit(", from", 1)[0].strip()

        if "Duration:" in stripped and duration_seconds is None:
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stripped)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = float(match.group(3))
                duration_seconds = hours * 3600 + minutes * 60 + seconds

        if " Video: " in stripped and not video_codec:
            codec_match = re.search(r"Video:\s*([^\s,(]+)", stripped)
            pixel_match = re.search(
                r"Video:.*?,\s*([a-zA-Z0-9_]+)(?:\(|,|\s)",
                stripped,
            )
            if codec_match:
                video_codec = codec_match.group(1).lower()
            if pixel_match:
                pixel_format = pixel_match.group(1).lower()

        if " Audio: " in stripped and not audio_codec:
            codec_match = re.search(r"Audio:\s*([^\s,(]+)", stripped)
            if codec_match:
                audio_codec = codec_match.group(1).lower()

    return {
        "format_name": format_name.lower(),
        "duration_seconds": duration_seconds,
        "video_codec": video_codec,
        "pixel_format": pixel_format,
        "audio_codec": audio_codec,
    }


def _is_mp4_container(format_name: str) -> bool:
    if not format_name:
        return False
    return any(part in {"mov", "mp4", "m4a"} for part in format_name.split(","))


def _is_mp4_compatible_video(probe_data: dict[str, object] | None) -> bool:
    if not probe_data:
        return False

    video_codec = str(probe_data.get("video_codec") or "").lower()
    pixel_format = str(probe_data.get("pixel_format") or "").lower()
    audio_codec = str(probe_data.get("audio_codec") or "").lower()

    if video_codec != "h264":
        return False
    if pixel_format not in {"", "yuv420p"}:
        return False
    if audio_codec and audio_codec != "aac":
        return False
    return True


def _get_media_duration_seconds(file_path: Path) -> float | None:
    probe_data = _probe_media(file_path)
    return _safe_float((probe_data or {}).get("duration_seconds"))


def _calculate_mp3_target_bitrate_kbps(duration_seconds: float | None) -> int:
    if not duration_seconds or duration_seconds <= 0:
        return 320

    target_bitrate_kbps = math.floor(
        (TARGET_UPLOAD_BYTES * 8) / duration_seconds / 1000
    )
    return max(
        MIN_MP3_BITRATE_KBPS,
        min(320, target_bitrate_kbps),
    )


def _compress_mp3_to_fit(file_path: Path, duration_seconds: float) -> Path:
    ffmpeg_path = _get_ffmpeg_path()
    if duration_seconds <= 0:
        raise DownloadError("Could not determine audio duration for compression.")

    max_bitrate_kbps = _calculate_mp3_target_bitrate_kbps(duration_seconds)
    if max_bitrate_kbps < MIN_MP3_BITRATE_KBPS:
        raise DownloadError(
            "This audio is too long to fit within Telegram's upload limit."
        )

    best_candidate: Path | None = None
    low = MIN_MP3_BITRATE_KBPS
    high = max_bitrate_kbps

    while low <= high:
        bitrate_kbps = (low + high) // 2
        candidate_path = file_path.with_name(
            f"{file_path.stem}.tg.{bitrate_kbps}k.mp3"
        )
        candidate_path.unlink(missing_ok=True)
        command = [
            ffmpeg_path,
            "-y",
            "-i",
            str(file_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate_kbps}k",
            str(candidate_path),
        ]

        _run_command(command, "ffmpeg could not compress the MP3 for Telegram delivery.")

        if candidate_path.stat().st_size <= TELEGRAM_UPLOAD_LIMIT_BYTES:
            best_candidate = _replace_if_better_candidate(best_candidate, candidate_path)
            low = bitrate_kbps + 1
        else:
            candidate_path.unlink(missing_ok=True)
            high = bitrate_kbps - 1

    if not best_candidate:
        raise DownloadError(
            "The audio is still too large for Telegram after compression."
        )

    return _replace_file(file_path, best_candidate)


def _split_mp4_bitrates(total_bitrate_kbps: int) -> tuple[int, int]:
    audio_bitrate_kbps = min(
        DEFAULT_AUDIO_BITRATE_KBPS, max(MIN_MP4_AUDIO_BITRATE_KBPS, total_bitrate_kbps // 5)
    )
    video_bitrate_kbps = total_bitrate_kbps - audio_bitrate_kbps - MP4_CONTAINER_OVERHEAD_KBPS
    return video_bitrate_kbps, audio_bitrate_kbps


def _compress_mp4_to_fit(file_path: Path, duration_seconds: float) -> Path:
    ffmpeg_path = _get_ffmpeg_path()
    if duration_seconds <= 0:
        raise DownloadError("Could not determine video duration for compression.")

    max_total_bitrate_kbps = math.floor(
        (TARGET_UPLOAD_BYTES * 8) / duration_seconds / 1000
    )
    min_total_bitrate_kbps = (
        MIN_MP4_VIDEO_BITRATE_KBPS
        + MIN_MP4_AUDIO_BITRATE_KBPS
        + MP4_CONTAINER_OVERHEAD_KBPS
    )
    if max_total_bitrate_kbps < min_total_bitrate_kbps:
        raise DownloadError(
            "This video is too long to fit within Telegram's upload limit."
        )

    best_candidate: Path | None = None
    low = min_total_bitrate_kbps
    high = max_total_bitrate_kbps

    while low <= high:
        total_bitrate_kbps = (low + high) // 2
        video_bitrate_kbps, audio_bitrate_kbps = _split_mp4_bitrates(
            total_bitrate_kbps
        )
        candidate_path = file_path.with_name(
            f"{file_path.stem}.tg.{total_bitrate_kbps}k.mp4"
        )
        candidate_path.unlink(missing_ok=True)
        command = [
            ffmpeg_path,
            "-y",
            "-i",
            str(file_path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-vf",
            FFMPEG_VIDEO_SCALE_FILTER,
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            f"{video_bitrate_kbps}k",
            "-maxrate",
            f"{video_bitrate_kbps}k",
            "-bufsize",
            f"{video_bitrate_kbps * 2}k",
            "-c:a",
            "aac",
            "-b:a",
            f"{audio_bitrate_kbps}k",
            "-movflags",
            "+faststart",
            str(candidate_path),
        ]

        _run_command(command, "ffmpeg could not compress the video for Telegram delivery.")

        if candidate_path.stat().st_size <= TELEGRAM_UPLOAD_LIMIT_BYTES:
            best_candidate = _replace_if_better_candidate(best_candidate, candidate_path)
            low = total_bitrate_kbps + 1
        else:
            candidate_path.unlink(missing_ok=True)
            high = total_bitrate_kbps - 1

    if not best_candidate:
        raise DownloadError(
            "The video is still too large for Telegram after compression."
        )

    return _replace_file(file_path, best_candidate)


def _ensure_upload_size(
    file_path: Path, format_choice: str, duration_seconds: float | None
) -> Path:
    if file_path.stat().st_size <= TELEGRAM_UPLOAD_LIMIT_BYTES:
        return file_path

    duration_seconds = duration_seconds or _get_media_duration_seconds(file_path) or 0
    if format_choice == "mp3":
        return _compress_mp3_to_fit(file_path, duration_seconds)
    if format_choice == "mp4":
        return _compress_mp4_to_fit(file_path, duration_seconds)
    return file_path


def _remux_to_mp4(file_path: Path) -> Path:
    ffmpeg_path = _get_ffmpeg_path()
    remuxed_path = file_path.with_name(f"{file_path.stem}.remux.mp4")
    final_path = file_path.with_suffix(".mp4")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(file_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(remuxed_path),
    ]

    _run_command(command, "ffmpeg could not remux the video to MP4.")
    return _replace_file_with_new_path(file_path, remuxed_path, final_path)


def _transcode_to_mp4(file_path: Path) -> Path:
    ffmpeg_path = _get_ffmpeg_path()
    transcoded_path = file_path.with_name(f"{file_path.stem}.normalized.mp4")
    final_path = file_path.with_suffix(".mp4")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(file_path),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-vf",
        FFMPEG_VIDEO_SCALE_FILTER,
        "-profile:v",
        "high",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(transcoded_path),
    ]

    _run_command(command, "ffmpeg could not normalize the video for delivery.")
    return _replace_file_with_new_path(file_path, transcoded_path, final_path)


def prepare_video_for_delivery(
    file_path: Path, duration_seconds: float | None = None
) -> Path:
    probe_data = _probe_media(file_path)
    normalized_file = file_path

    if _is_mp4_compatible_video(probe_data):
        if file_path.suffix.lower() != ".mp4" or not _is_mp4_container(
            str((probe_data or {}).get("format_name") or "")
        ):
            try:
                normalized_file = _remux_to_mp4(file_path)
            except DownloadError:
                normalized_file = _transcode_to_mp4(file_path)
    elif file_path.suffix.lower() != ".mp4" or probe_data:
        normalized_file = _transcode_to_mp4(file_path)

    return _ensure_upload_size(normalized_file, "mp4", duration_seconds)


def _estimate_format_size_bytes(
    format_info: dict[str, object], duration_seconds: float | None
) -> int | None:
    direct_size = _safe_int(format_info.get("filesize"))
    if direct_size and direct_size > 0:
        return direct_size

    approx_size = _safe_int(format_info.get("filesize_approx"))
    if approx_size and approx_size > 0:
        return approx_size

    total_bitrate_kbps = _safe_float(format_info.get("tbr"))
    if duration_seconds and duration_seconds > 0 and total_bitrate_kbps:
        estimated_bytes = duration_seconds * total_bitrate_kbps * 1000 / 8
        return int(estimated_bytes)

    return None


def _is_mp4_compatible_codec_pair(
    video_codec: str | None,
    audio_codec: str | None,
) -> bool:
    normalized_video = (video_codec or "").lower()
    normalized_audio = (audio_codec or "").lower()
    video_ok = normalized_video in {"avc1", "h264"} or normalized_video.startswith(
        ("avc1", "h264")
    )
    audio_ok = (
        normalized_audio in {"", "aac", "mp4a.40.2"}
        or normalized_audio.startswith("mp4a")
    )
    return video_ok and audio_ok


def _is_mp4_compatible_audio_codec(audio_codec: str | None) -> bool:
    normalized_audio = (audio_codec or "").lower()
    return normalized_audio in {"", "aac", "mp4a.40.2"} or normalized_audio.startswith(
        "mp4a"
    )


def _candidate_quality_score(
    height: int | None,
    fps: float | None,
    total_bitrate_kbps: float | None,
    compatibility_rank: int,
) -> int:
    safe_height = max(0, height or 0)
    safe_fps = max(0, int((fps or 0) * 10))
    safe_tbr = max(0, int(total_bitrate_kbps or 0))
    return (
        safe_height * 1_000_000
        + safe_fps * 10_000
        + safe_tbr * 10
        + compatibility_rank * 500
    )


def _iter_media_formats(info: dict[str, object]) -> list[dict[str, object]]:
    formats = info.get("formats") or []
    if isinstance(formats, list):
        return [item for item in formats if isinstance(item, dict)]
    return []


def _choose_mp3_download_plan(info: dict[str, object]) -> DownloadPlan:
    duration_seconds = _safe_float(info.get("duration"))
    bitrate_kbps = _calculate_mp3_target_bitrate_kbps(duration_seconds)
    return DownloadPlan(
        format_selector="bestaudio/best",
        preferred_audio_quality_kbps=bitrate_kbps,
        strategy="audio_budgeted_extract",
    )


def _choose_mp4_download_plan(info: dict[str, object]) -> DownloadPlan:
    duration_seconds = _safe_float(info.get("duration"))
    formats = _iter_media_formats(info)

    best_plan: DownloadPlan | None = None
    best_score: tuple[int, int, int] | None = None

    progressive_formats: list[dict[str, object]] = []
    video_only_formats: list[dict[str, object]] = []
    audio_only_formats: list[dict[str, object]] = []

    for media_format in formats:
        format_id = str(media_format.get("format_id") or "").strip()
        if not format_id:
            continue

        video_codec = str(media_format.get("vcodec") or "none").lower()
        audio_codec = str(media_format.get("acodec") or "none").lower()

        has_video = video_codec != "none"
        has_audio = audio_codec != "none"

        if has_video and has_audio:
            progressive_formats.append(media_format)
        elif has_video:
            video_only_formats.append(media_format)
        elif has_audio:
            audio_only_formats.append(media_format)

    for media_format in progressive_formats:
        format_id = str(media_format.get("format_id"))
        expected_size_bytes = _estimate_format_size_bytes(media_format, duration_seconds)
        compatibility_rank = 3
        if (
            str(media_format.get("ext") or "").lower() == "mp4"
            and _is_mp4_compatible_codec_pair(
                str(media_format.get("vcodec") or ""),
                str(media_format.get("acodec") or ""),
            )
        ):
            compatibility_rank = 4

        quality_score = _candidate_quality_score(
            _safe_int(media_format.get("height")),
            _safe_float(media_format.get("fps")),
            _safe_float(media_format.get("tbr")),
            compatibility_rank,
        )
        size_rank = (
            2
            if expected_size_bytes is not None and expected_size_bytes <= TARGET_UPLOAD_BYTES
            else 1
            if expected_size_bytes is None
            else 0
        )
        closeness_score = (
            -abs(TARGET_UPLOAD_BYTES - expected_size_bytes)
            if expected_size_bytes is not None
            else -10**18
        )
        plan = DownloadPlan(
            format_selector=format_id,
            expected_size_bytes=expected_size_bytes,
            strategy="progressive_direct",
        )
        score = (size_rank, quality_score, closeness_score)
        if best_score is None or score > best_score:
            best_plan = plan
            best_score = score

    ranked_videos = sorted(
        video_only_formats,
        key=lambda media_format: _candidate_quality_score(
            _safe_int(media_format.get("height")),
            _safe_float(media_format.get("fps")),
            _safe_float(media_format.get("tbr")),
            0,
        ),
        reverse=True,
    )[:12]
    ranked_audios = sorted(
        audio_only_formats,
        key=lambda media_format: (
            _safe_float(media_format.get("abr")) or 0,
            _safe_float(media_format.get("tbr")) or 0,
            1 if str(media_format.get("ext") or "").lower() in {"m4a", "mp4"} else 0,
        ),
        reverse=True,
    )[:8]

    for video_format in ranked_videos:
        video_id = str(video_format.get("format_id") or "").strip()
        video_size = _estimate_format_size_bytes(video_format, duration_seconds)
        if not video_id:
            continue

        for audio_format in ranked_audios:
            audio_id = str(audio_format.get("format_id") or "").strip()
            audio_size = _estimate_format_size_bytes(audio_format, duration_seconds)
            if not audio_id:
                continue

            expected_size_bytes: int | None = None
            if video_size is not None and audio_size is not None:
                expected_size_bytes = video_size + audio_size

            compatibility_rank = 1
            merge_output_format = "mkv"
            if (
                str(video_format.get("ext") or "").lower() == "mp4"
                and str(audio_format.get("ext") or "").lower() in {"m4a", "mp4"}
                and _is_mp4_compatible_codec_pair(
                    str(video_format.get("vcodec") or ""),
                    str(audio_format.get("acodec") or ""),
                )
                and _is_mp4_compatible_audio_codec(str(audio_format.get("acodec") or ""))
            ):
                compatibility_rank = 3
                merge_output_format = "mp4"

            total_bitrate_kbps = (
                (_safe_float(video_format.get("tbr")) or 0)
                + (_safe_float(audio_format.get("tbr")) or 0)
            )
            quality_score = _candidate_quality_score(
                _safe_int(video_format.get("height")),
                _safe_float(video_format.get("fps")),
                total_bitrate_kbps,
                compatibility_rank,
            )
            size_rank = (
                2
                if expected_size_bytes is not None and expected_size_bytes <= TARGET_UPLOAD_BYTES
                else 1
                if expected_size_bytes is None
                else 0
            )
            closeness_score = (
                -abs(TARGET_UPLOAD_BYTES - expected_size_bytes)
                if expected_size_bytes is not None
                else -10**18
            )
            plan = DownloadPlan(
                format_selector=f"{video_id}+{audio_id}",
                merge_output_format=merge_output_format,
                expected_size_bytes=expected_size_bytes,
                strategy="adaptive_merge",
            )
            score = (size_rank, quality_score, closeness_score)
            if best_score is None or score > best_score:
                best_plan = plan
                best_score = score

    if best_plan:
        return best_plan

    return DownloadPlan(
        format_selector="bv*+ba/b",
        merge_output_format="mkv",
        strategy="fallback_best_available",
    )


def _choose_download_plan(info: dict[str, object], format_choice: str) -> DownloadPlan:
    if format_choice == "mp3":
        return _choose_mp3_download_plan(info)
    if format_choice == "mp4":
        return _choose_mp4_download_plan(info)
    raise DownloadError("Only mp3 and mp4 are supported.")


def _build_options(
    format_choice: str,
    download_dir: Path,
    plan: DownloadPlan | None = None,
) -> dict[str, object]:
    output_template = str(download_dir / "%(extractor)s_%(id)s_%(title).80s.%(ext)s")
    ffmpeg_path = _get_ffmpeg_path(required=format_choice in {"mp3", "mp4"})
    plan = plan or DownloadPlan(format_selector="best")
    base_options = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "windowsfilenames": True,
        "restrictfilenames": True,
        "overwrites": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 3,
        "socket_timeout": 30,
        "geo_bypass": True,
        "concurrent_fragment_downloads": 4,
        "ffmpeg_location": ffmpeg_path,
        "format": plan.format_selector,
    }

    if format_choice == "mp3":
        return base_options | {
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": str(plan.preferred_audio_quality_kbps or 320),
                }
            ],
        }

    if format_choice == "mp4":
        video_options: dict[str, object] = {}
        if plan.merge_output_format:
            video_options["merge_output_format"] = plan.merge_output_format
        return base_options | video_options

    raise DownloadError("Only mp3 and mp4 are supported.")


def _extract_media_info(url: str) -> dict[str, object]:
    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "geo_bypass": True,
        }
    ) as ydl:
        info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            raise DownloadError("Could not inspect the media before downloading.")
        return info


def _find_downloaded_file(downloaded_file: Path, format_choice: str) -> Path:
    candidates = [downloaded_file]

    if format_choice == "mp3":
        candidates.append(downloaded_file.with_suffix(".mp3"))
    elif format_choice == "mp4":
        candidates.extend(
            [
                downloaded_file.with_suffix(".mkv"),
                downloaded_file.with_suffix(".mp4"),
                downloaded_file.with_suffix(".webm"),
            ]
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    most_recent_match: Path | None = None
    most_recent_mtime = float("-inf")
    for path in downloaded_file.parent.iterdir():
        if not path.is_file() or path.suffix in {".part", ".ytdl"}:
            continue
        mtime = path.stat().st_mtime
        if mtime > most_recent_mtime:
            most_recent_match = path
            most_recent_mtime = mtime
    if most_recent_match:
        return most_recent_match

    raise DownloadError(
        "The media was downloaded, but the final file could not be found."
    )


def _resolve_downloaded_path(
    info: dict[str, object], downloaded_file: Path, format_choice: str
) -> Path:
    requested_downloads = info.get("requested_downloads") or []
    if isinstance(requested_downloads, list):
        for download in requested_downloads:
            if not isinstance(download, dict):
                continue
            filepath = download.get("filepath")
            if filepath and Path(filepath).exists():
                return Path(filepath)

    return _find_downloaded_file(downloaded_file, format_choice)


def cleanup_download_artifacts(file_path: Path) -> None:
    resolved_download_root = DOWNLOAD_DIR.resolve()
    try:
        resolved_file = file_path.resolve()
    except FileNotFoundError:
        resolved_file = file_path

    if resolved_file.exists():
        resolved_file.unlink(missing_ok=True)

    try:
        resolved_parent = resolved_file.parent.resolve()
    except FileNotFoundError:
        resolved_parent = resolved_file.parent

    if (
        resolved_parent.parent == resolved_download_root
        and resolved_parent.name.startswith("job_")
    ):
        shutil.rmtree(resolved_parent, ignore_errors=True)


def download_media(url: str, format_choice: str) -> Path:
    job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=DOWNLOAD_DIR))

    try:
        if format_choice == "mp3":
            plan = DownloadPlan(
                format_selector="bestaudio/best",
                strategy="direct_audio_download",
            )
        else:
            info = _extract_media_info(url)
            plan = _choose_download_plan(info, format_choice)

        with yt_dlp.YoutubeDL(_build_options(format_choice, job_dir, plan)) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = Path(ydl.prepare_filename(info))
            duration_seconds = _safe_float(info.get("duration"))
            media_path = _resolve_downloaded_path(info, downloaded_file, format_choice)

            if format_choice == "mp3":
                return _ensure_upload_size(media_path, format_choice, duration_seconds)

            return prepare_video_for_delivery(media_path, duration_seconds)
    except yt_dlp.utils.DownloadError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloadError(str(exc)) from exc
    except DownloadError:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except FileNotFoundError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloadError(
            "A required tool was not found while processing this media."
        ) from exc
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloadError(f"File processing failed: {exc}") from exc
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise DownloadError(f"Unexpected downloader error: {exc}") from exc
