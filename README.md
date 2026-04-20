# Telegram Video Downloader Bot

This bot accepts supported video links, lets the user choose `MP3` or `MP4`, downloads the media with `yt-dlp`, and uploads the result back to Telegram.

## What was fixed

- Cleaned up broken bot messages and button labels.
- Removed the global per-user URL store and switched to `context.user_data`.
- Added startup validation for a missing `BOT_TOKEN`.
- Moved downloads to a worker thread so the bot stays responsive.
- Added clearer download and upload error handling.
- Added automatic compression for oversized downloads when possible, while still respecting Telegram's current bot upload limit.
- Added video normalization so delivered MP4 files are more compatible with iOS, Android, Windows, macOS, and Linux Telegram clients.
- Added Windows launcher files so the bot can run in the background and auto-start at login.
- Added a simple `run_bot.sh` launcher for macOS and Linux.

## Files for background startup

- `run_bot.ps1`: starts the bot with `py -3` or `python`
- `run_bot.sh`: starts the bot with `python3` or `python` on macOS/Linux
- `start_bot_hidden.vbs`: launches the PowerShell script without a visible console
- `install_autostart.ps1`: creates a Windows Scheduled Task that starts the bot when you log in

## Required setup

1. Install Python 3 if it is not already installed.
2. Install the Python packages:

```powershell
pip install -r requirements.txt
```

3. Install `ffmpeg` and make sure it is on your `PATH`.
   MP3 conversion, video normalization, and large-file compression will not work without it.
4. Put your bot token in `.env` as:

```env
BOT_TOKEN=your_new_bot_token_here
```

## Important security note

The current `.env` file contains a real bot token. You should rotate that token in BotFather now, then update `.env` with the new token.

## Run the bot

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_bot.ps1
```

macOS or Linux:

```sh
sh ./run_bot.sh
```

## Start automatically without opening a terminal on Windows

Run this once in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

After that, Windows will start the bot in the background each time you log in.

## Manual test

Before relying on auto-start, test once with:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_bot.ps1
```

Then open Telegram and send `/start` to your bot.
