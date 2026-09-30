import os
import logging
import asyncio

from fastapi import FastAPI, Request, HTTPException
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voxly")

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "voxly-secret")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

app = FastAPI()

telegram_app = Application.builder().token(BOT_TOKEN).build()
gemini = genai.Client(api_key=GEMINI_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📝 Transcribe", callback_data="transcribe"),
            InlineKeyboardButton("🧠 Summarize", callback_data="summarize"),
        ],
        [
            InlineKeyboardButton("🌍 Translate", callback_data="translate"),
            InlineKeyboardButton("✍️ Reply", callback_data="reply"),
        ],
    ]

    await update.message.reply_text(
        "🎙️ Voxly AI hazırdır!\n\n"
        "Mənə səsli mesaj göndər. Mən onu yazıya çevirəcəyəm.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    await msg.reply_text("🎧 Səsi qəbul etdim. Bir az gözlə...")

    voice = msg.voice
    tg_file = await context.bot.get_file(voice.file_id)
    data = await tg_file.download_as_bytearray()

    prompt = (
        "Transcribe this Telegram voice message accurately. "
        "Return ONLY the transcript. "
        "Keep the original language and wording as much as possible."
    )

    try:
        response = await asyncio.to_thread(
            gemini.models.generate_content,
            model="gemini-3.8-flash",
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=bytes(data),
                    mime_type="audio/ogg",
                ),
            ],
        )

        transcript = (response.text or "").strip()

        if not transcript:
            raise RuntimeError("Empty transcription")

        await msg.reply_text("📝 " + transcript)

    except Exception:
        logger.exception("Transcription failed")
        await msg.reply_text(
            "❌ Səsi emal edərkən problem oldu. Bir az sonra yenidən yoxla."
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎤 Mənə səsli mesaj göndər. "
        "İlk versiyada səsi yazıya çevirəcəyəm."
    )


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.VOICE, voice_handler))
telegram_app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
)


@app.on_event("startup")
async def startup():
    await telegram_app.initialize()
    await telegram_app.start()

    if not RENDER_EXTERNAL_URL:
        logger.warning("RENDER_EXTERNAL_URL is not set.")
        return

    webhook_url = f"{RENDER_EXTERNAL_URL}/telegram/{WEBHOOK_SECRET}"

    await telegram_app.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )


@app.on_event("shutdown")
async def shutdown():
    try:
        await telegram_app.bot.delete_webhook()
    finally:
        await telegram_app.stop()
        await telegram_app.shutdown()


@app.get("/")
async def health():
    return {"status": "ok", "service": "Voxly AI"}


@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await request.json()
    update = Update.de_json(body, telegram_app.bot)

    await telegram_app.process_update(update)

    return {"ok": True}
