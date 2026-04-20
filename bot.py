import asyncio
import logging
import os
import re
import uuid
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from downloader import (
    DownloadError,
    TELEGRAM_UPLOAD_LIMIT_BYTES,
    cleanup_download_artifacts,
    download_media,
)


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PENDING_REQUESTS_KEY = "pending_requests"
SUPPORTED_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "tiktok.com",
}
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
BOT_API_TIMEOUTS = {
    "read_timeout": 180,
    "write_timeout": 180,
    "connect_timeout": 30,
    "pool_timeout": 30,
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)


def _upload_limit_label() -> str:
    upload_limit_mb = TELEGRAM_UPLOAD_LIMIT_BYTES / (1024 * 1024)
    if upload_limit_mb.is_integer():
        return f"{int(upload_limit_mb)} MB"
    return f"{upload_limit_mb:.1f} MB"


def _build_format_keyboard(request_id: str) -> InlineKeyboardMarkup:
    keyboard = [[
        InlineKeyboardButton("MP3 Audio", callback_data=f"download:{request_id}:mp3"),
        InlineKeyboardButton("MP4 Video", callback_data=f"download:{request_id}:mp4"),
    ]]
    return InlineKeyboardMarkup(keyboard)


def _extract_supported_url(text: str) -> str | None:
    for raw_candidate in URL_PATTERN.findall(text):
        candidate = raw_candidate.strip("()[]{}<>\"'.,")
        if _is_supported_url(candidate):
            return candidate
    return None


def _is_supported_url(url: str) -> bool:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return False

    hostname = parsed_url.netloc.lower().split("@")[-1].split(":")[0]
    if hostname.startswith("www."):
        hostname = hostname[4:]

    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in SUPPORTED_DOMAINS
    )


def _get_pending_requests(
    context: ContextTypes.DEFAULT_TYPE,
) -> dict[str, str]:
    pending_requests = context.user_data.setdefault(PENDING_REQUESTS_KEY, {})
    if isinstance(pending_requests, OrderedDict):
        return pending_requests
    if isinstance(pending_requests, dict):
        pending_requests = OrderedDict(pending_requests.items())
        context.user_data[PENDING_REQUESTS_KEY] = pending_requests
    else:
        pending_requests = OrderedDict()
        context.user_data[PENDING_REQUESTS_KEY] = pending_requests
    return pending_requests


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Hello! I am Viseth Video Downloader Bot.\n\n"
        "Supported platforms:\n"
        "- YouTube\n"
        "- Facebook\n"
        "- Instagram\n"
        "- TikTok\n\n"
        "Send a supported link and choose MP3 or MP4.\n"
        "The bot downloads the highest available quality first, then compresses only if Telegram's upload limit requires it.\n"
        f"Current upload limit: {_upload_limit_label()}.",
        **BOT_API_TIMEOUTS,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Send a YouTube, Facebook, Instagram, or TikTok link.\n"
        "I will ask whether you want MP3 audio or MP4 video, then return the best result that fits Telegram.",
        **BOT_API_TIMEOUTS,
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    url = _extract_supported_url(update.message.text)
    if not url:
        await update.message.reply_text(
            "Please send a valid YouTube, Facebook, Instagram, or TikTok link.",
            **BOT_API_TIMEOUTS,
        )
        return

    request_id = uuid.uuid4().hex[:8]
    pending_requests = _get_pending_requests(context)
    pending_requests[request_id] = url

    while len(pending_requests) > 10:
        pending_requests.popitem(last=False)

    await update.message.reply_text(
        "Link received. Choose your download format:",
        reply_markup=_build_format_keyboard(request_id),
        **BOT_API_TIMEOUTS,
    )


async def handle_format_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.message or not query.data:
        return

    await query.answer()

    try:
        _, request_id, format_choice = query.data.split(":", 2)
    except ValueError:
        await query.edit_message_text("Unsupported format selection.")
        return

    if format_choice not in {"mp3", "mp4"}:
        await query.edit_message_text("Unsupported format selection.")
        return

    pending_requests = _get_pending_requests(context)
    url = pending_requests.pop(request_id, None)
    if not url:
        await query.edit_message_text("This request expired. Please send the link again.")
        return

    await query.edit_message_text(
        f"Downloading {format_choice.upper()} in the highest available quality. Please wait..."
    )

    file_path: Path | None = None
    chat_id = query.message.chat.id
    try:
        file_path = await asyncio.to_thread(download_media, url, format_choice)
        if file_path.stat().st_size > TELEGRAM_UPLOAD_LIMIT_BYTES:
            raise DownloadError(
                "The downloaded file is larger than Telegram's upload limit."
            )

        with file_path.open("rb") as media_file:
            if format_choice == "mp3":
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=media_file,
                    caption="Your audio is ready.",
                    **BOT_API_TIMEOUTS,
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                    caption="Your video is ready.",
                    supports_streaming=True,
                    **BOT_API_TIMEOUTS,
                )
    except DownloadError as exc:
        LOGGER.warning("Download failed: %s", exc)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Download failed: {exc}",
            **BOT_API_TIMEOUTS,
        )
    except Exception:  # pragma: no cover - runtime safety net
        LOGGER.exception("Unexpected error while processing download")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Something went wrong while processing that link. Please try again.",
            **BOT_API_TIMEOUTS,
        )
    finally:
        if file_path:
            cleanup_download_artifacts(file_path)


def validate_environment() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to the .env file before starting.")


def main() -> None:
    validate_environment()

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        CallbackQueryHandler(
            handle_format_choice,
            pattern=r"^download:[0-9a-f]{8}:(mp3|mp4)$",
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    LOGGER.info("Bot is running")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
