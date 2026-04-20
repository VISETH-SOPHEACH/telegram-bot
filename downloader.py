import math
import shutil
import subprocess
from pathlib import Path

import yt_dlp


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
TELEGRAM_UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024
TARGET_UPLOAD_BYTES = 48 * 1024 * 1024
MIN_MP3_BITRATE_KBPS = 32
DEFAULT_AUDIO_BITRATE_KBPS = 96


class DownloadError(Exception):
    pass


def _run_ffmpeg(command: list[str], error_message: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if details:
            raise DownloadError(f"{error_message} ffmpeg said: {details[-300:]}")
        raise DownloadError(error_message)


def _get_ffmpeg_path() -> str:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise DownloadError(
            "ffmpeg is required to process large files. Install ffmpeg and make sure it is on PATH."
        )
    return ffmpeg_path


def _replace_file(original: Path, replacement: Path) -> Path:
    if original.exists():
        original.unlink()
    replacement.replace(original)
    return original


def _compress_mp3_to_fit(file_path: Path, duration_seconds: float) -> Path:
    ffmpeg_path = _get_ffmpeg_path()
    if duration_seconds <= 0:
        raise DownloadError("Could not determine audio duration for compression.")

    target_bitrate_kbps = math.floor(
        (TARGET_UPLOAD_BYTES * 8) / duration_seconds / 1000
    )
    target_bitrate_kbps = min(192, target_bitrate_kbps)
    if target_bitrate_kbps < MIN_MP3_BITRATE_KBPS:
        raise DownloadError(
            "This audio is too long to fit within Telegram's current 50 MB bot upload limit."
        )

    compressed_path = file_path.with_name(f"{file_path.stem}.tg.mp3")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(file_path),
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        f"{target_bitrate_kbps}k",
        str(compressed_path),
    ]

    _run_ffmpeg(command, "ffmpeg could not compress the MP3 for Telegram delivery.")

    if compressed_path.stat().st_size > TELEGRAM_UPLOAD_LIMIT_BYTES:
        compressed_path.unlink(missing_ok=True)
        raise DownloadError(
            "The audio is still too large for Telegram after compression."
        )

    return _replace_file(file_path, compressed_path)


def _compress_mp4_to_fit(file_path: Path, duration_seconds: float) -> Path:
    ffmpeg_path = _get_ffmpeg_path()
    if duration_seconds <= 0:
        raise DownloadError("Could not determine video duration for compression.")

    total_bitrate_kbps = math.floor(
        (TARGET_UPLOAD_BYTES * 8) / duration_seconds / 1000
    )
    audio_bitrate_kbps = min(DEFAULT_AUDIO_BITRATE_KBPS, max(48, total_bitrate_kbps // 5))
    video_bitrate_kbps = total_bitrate_kbps - audio_bitrate_kbps - 32

    if video_bitrate_kbps < 120:
        raise DownloadError(
            "This video is too long to fit within Telegram's current 50 MB bot upload limit."
        )

    compressed_path = file_path.with_name(f"{file_path.stem}.tg.mp4")
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(file_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
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
        str(compressed_path),
    ]

    _run_ffmpeg(command, "ffmpeg could not compress the video for Telegram delivery.")

    if compressed_path.stat().st_size > TELEGRAM_UPLOAD_LIMIT_BYTES:
        compressed_path.unlink(missing_ok=True)
        raise DownloadError(
            "The video is still too large for Telegram after compression."
        )

    return _replace_file(file_path, compressed_path)


def _ensure_upload_size(
    file_path: Path, format_choice: str, duration_seconds: float | None
) -> Path:
    if file_path.stat().st_size <= TELEGRAM_UPLOAD_LIMIT_BYTES:
        return file_path

    duration_seconds = duration_seconds or 0
    if format_choice == "mp3":
        return _compress_mp3_to_fit(file_path, duration_seconds)
    if format_choice == "mp4":
        return _compress_mp4_to_fit(file_path, duration_seconds)

    return file_path


def _build_options(format_choice: str) -> dict:
    output_template = str(DOWNLOAD_DIR / "%(extractor)s_%(id)s_%(title).50s.%(ext)s")
    base_options = {
        "outtmpl": output_template,
        "quiet": True,
        "noplaylist": True,
        "windowsfilenames": True,
        "restrictfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 4,
        "nocheckcertificate": True,
        "geo_bypass": True,
    }

    if format_choice == "mp3":
        ffmpeg_path = _get_ffmpeg_path()

        return base_options | {
            "format": "bestaudio/best",
            "ffmpeg_location": ffmpeg_path,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }

    if format_choice == "mp4":
        return base_options | {
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
            "format_sort": ["hasvid", "res", "fps", "hdr", "vcodec", "acodec"],
        }

    raise DownloadError("Only mp3 and mp4 are supported.")


def _find_downloaded_file(downloaded_file: Path, format_choice: str) -> Path:
    candidates = [downloaded_file]

    if format_choice == "mp3":
        candidates.append(downloaded_file.with_suffix(".mp3"))
    elif format_choice == "mp4":
        candidates.append(downloaded_file.with_suffix(".mp4"))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    pattern = f"{downloaded_file.stem}*"
    matches = sorted(
        (path for path in downloaded_file.parent.glob(pattern) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]

    raise DownloadError("The media was downloaded, but the final file could not be found.")


def download_media(url: str, format_choice: str) -> Path:
    try:
        with yt_dlp.YoutubeDL(_build_options(format_choice)) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)
            duration_seconds = info.get("duration")

            if format_choice == "mp3":
                requested = info.get("requested_downloads") or []
                if requested:
                    filepath = requested[0].get("filepath")
                    if filepath:
                        return _ensure_upload_size(
                            Path(filepath), format_choice, duration_seconds
                        )
                return _ensure_upload_size(
                    _find_downloaded_file(Path(downloaded_file), format_choice),
                    format_choice,
                    duration_seconds,
                )

            if info.get("requested_downloads"):
                filepath = info["requested_downloads"][0].get("filepath")
                if filepath:
                    return _ensure_upload_size(
                        Path(filepath), format_choice, duration_seconds
                    )

            return _ensure_upload_size(
                _find_downloaded_file(Path(downloaded_file), format_choice),
                format_choice,
                duration_seconds,
            )
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc)) from exc
    except DownloadError:
        raise
    except FileNotFoundError as exc:
        raise DownloadError(
            "A required tool was not found while processing this media."
        ) from exc
    except OSError as exc:
        raise DownloadError(f"File processing failed: {exc}") from exc
    except Exception as exc:
        raise DownloadError(f"Unexpected downloader error: {exc}") from exc
