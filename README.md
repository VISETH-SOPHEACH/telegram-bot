# Telegram Video Downloader Bot

This bot accepts supported video links, lets the user choose `MP3` or `MP4`, downloads the media with `yt-dlp`, and uploads the result back to Telegram.

## What is fixed

- Rebuilt the broken `bot.py` runtime flow and Telegram handlers.
- Added safer per-request state so multiple links from the same user do not overwrite each other.
- Moved each download into its own temporary job folder to avoid collisions between concurrent downloads.
- Upgraded the video pipeline to download the highest available quality first, then remux or transcode only when needed for Telegram-friendly MP4 delivery.
- Added metadata-aware download planning so the bot estimates format sizes before downloading and prefers the best candidate that is most likely to fit Telegram cleanly.
- Added cross-platform `ffmpeg` fallback through `imageio-ffmpeg`, so high-quality merging and conversion work on Windows, macOS, and Linux without relying only on a system `ffmpeg`.
- Kept automatic compression for files that exceed Telegram's upload limit.
- Updated launcher and setup scripts to prefer a local `.venv` on every OS.

## Supported sites

- YouTube
- Facebook
- Instagram
- TikTok

## Requirements

- Python 3.10 or newer is recommended.
- A Telegram bot token in `.env`:

```env
BOT_TOKEN=your_bot_token_here
```

Optional:

```env
TELEGRAM_MAX_UPLOAD_MB=50
```

Change `TELEGRAM_MAX_UPLOAD_MB` only if your Telegram bot setup supports a different upload limit.

## Setup

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_bot.ps1
```

macOS or Linux:

```sh
sh ./setup_bot.sh
```

## Run the bot

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_bot.ps1
```

macOS or Linux:

```sh
sh ./run_bot.sh
```

## Docker

Build and run with Docker Compose:

```sh
docker compose up -d --build
```

Stop it:

```sh
docker compose down
```

Notes:

- `docker-compose.yml` reads `BOT_TOKEN` and optional `TELEGRAM_MAX_UPLOAD_MB` from `.env`.
- The container installs system `ffmpeg`, so media processing works without extra setup.
- `./downloads` is mounted into the container so temporary media files stay in the project folder.
- This bot uses polling, so no port mapping is needed.
- The image only copies `bot.py`, `downloader.py`, and `requirements.txt` to keep the build smaller.

## Windows background startup

Install the login-time auto-start task:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

Restart the background bot:

```powershell
powershell -ExecutionPolicy Bypass -File .\restart_bot.ps1
```

## Download behavior

- `MP3`: downloads the best available audio, then converts it to MP3.
- `MP3`: now targets a bitrate based on the media duration and Telegram budget before post-download compression is needed.
- `MP4`: now inspects available formats first, prefers high-quality options that are likely to fit, and falls back to remux/transcode only when required for Telegram-friendly delivery.
- If the finished file is too large, the bot compresses it just enough to fit the configured Telegram upload limit.

## Notes

- The `downloads/` folder is used for temporary work files and should not be committed.
- If `.env` contains a real production token, rotate it in BotFather if that token was ever shared.
