import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from downloader import DownloadError, download_media


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
SUPPORTED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "tiktok.com",
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)
SELECTED_URL_KEY = "selected_url"
DOWNLOAD_IN_PROGRESS_KEY = "download_in_progress"


def build_format_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[
        InlineKeyboardButton("MP3 Audio", callback_data="mp3"),
        InlineKeyboardButton("MP4 Video", callback_data="mp4"),
    ]]
    return InlineKeyboardMarkup(keyboard)


async def send_media_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_path: Path,
    format_choice: str,
) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        raise DownloadError("Could not determine the chat for the upload.")

    with file_path.open("rb") as media_file:
        if format_choice == "mp3":
            try:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=media_file,
                    caption="Your audio is ready.",
                )
                return
            except TelegramError as exc:
                LOGGER.warning("send_audio failed, falling back to document: %s", exc)
                media_file.seek(0)
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=media_file,
                    filename=file_path.name,
                    caption="Your audio is ready.",
                )
                return

        try:
            await context.bot.send_video(
                chat_id=chat_id,
                video=media_file,
                caption="Your video is ready.",
                supports_streaming=True,
            )
        except TelegramError as exc:
            LOGGER.warning("send_video failed, falling back to document: %s", exc)
            media_file.seek(0)
            await context.bot.send_document(
                chat_id=chat_id,
                document=media_file,
                filename=file_path.name,
                caption="Your video is ready.",
            )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Hello! I am Viseth \n Video Downloader Bot.\n\n"
        "Supported platforms:\n"
        "- YouTube\n"
        "- Facebook\n"
        "- Instagram\n"
        "- TikTok\n\n"
        "Send me a supported video link, then choose MP3 or MP4.\n",
        # "Large files will be compressed when possible to fit Telegram bot limits.",
    )


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    await update.message.reply_text(
        f"Your Telegram user ID is: {update.effective_user.id}"
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()
    if not any(domain in url for domain in SUPPORTED_DOMAINS):
        await update.message.reply_text(
            "Please send a valid YouTube, Facebook, Instagram, or TikTok link."
        )
        return

    context.user_data[SELECTED_URL_KEY] = url
    await update.message.reply_text(
        "Link received. Choose your download format:",
        reply_markup=build_format_keyboard(),
    )


async def handle_format_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()

    format_choice = query.data or ""
    url = context.user_data.get(SELECTED_URL_KEY)
    if format_choice not in {"mp3", "mp4"}:
        await query.edit_message_text("Unsupported format selection.")
        return

    if not url:
        await query.edit_message_text("Session expired. Please send the link again.")
        return

    if context.user_data.get(DOWNLOAD_IN_PROGRESS_KEY):
        await query.answer(
            "A download is already running for this chat. Please wait for it to finish.",
            show_alert=False,
        )
        return

    context.user_data[DOWNLOAD_IN_PROGRESS_KEY] = True

    await query.edit_message_text(
        f"Downloading {format_choice.upper()} now with the best quality available. "
        "Large files may take longer if compression is needed..."
    )

    file_path: Path | None = None
    try:
        file_path = await asyncio.to_thread(download_media, url, format_choice)
        file_size = file_path.stat().st_size
        if file_size > MAX_UPLOAD_SIZE_BYTES:
            raise DownloadError(
                "The file is still larger than Telegram's current 50 MB bot upload limit."
            )

        await send_media_file(update, context, file_path, format_choice)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="You can use the same link again. Choose another format if you want:",
            reply_markup=build_format_keyboard(),
        )
    except DownloadError as exc:
        LOGGER.warning("Download failed: %s", exc)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Download failed: {exc}",
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="You can still try the same link again with another format:",
            reply_markup=build_format_keyboard(),
        )
    except Exception:  # pragma: no cover - safety net for runtime issues
        LOGGER.exception("Unexpected error while processing download")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Something went wrong while processing that link. The link is still saved, so please try again in a moment.",
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="The link is still saved. You can retry with MP3 or MP4:",
            reply_markup=build_format_keyboard(),
        )
    finally:
        context.user_data.pop(DOWNLOAD_IN_PROGRESS_KEY, None)
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                LOGGER.warning("Could not remove temporary file: %s", file_path)


def validate_environment() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to the .env file before starting.")


def main() -> None:
    validate_environment()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", my_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_format_choice))

    LOGGER.info("Bot is starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
