import os
import logging
import asyncio
import aiohttp
import requests
from html import escape

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
CHKR_API_URL = "https://api.chkr.cc/"

# ---------------- WEBHOOK SETUP ----------------
def setup_webhook(token: str, webhook_url: str):
    try:
        api_url = f"https://api.telegram.org/bot{token}/setWebhook"
        r = requests.post(
            api_url,
            json={
                "url": webhook_url,
                "allowed_updates": ["message"]
            },
            timeout=20
        )
        result = r.json()
        if result.get("ok"):
            logger.info(f"Webhook set successfully: {webhook_url}")
        else:
            logger.error(f"Webhook setup failed: {result}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")

# ---------------- API CALL ----------------
async def check_card(card_data: str):
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                CHKR_API_URL,
                json={"data": card_data}
            ) as resp:
                return await resp.json()
    except Exception as e:
        logger.error(f"API request error: {e}")
        return None

# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔐 <b>CC Checker Bot</b>\n\n"
        "📌 <b>Usage</b>\n"
        "Send card details in this format:\n"
        "<code>4242424242424242|12|2025|123</code>\n\n"
        "📌 <b>Command</b>\n"
        "<code>/check 4242424242424242|12|2025|123</code>\n\n"
        "⚠️ Only LIVE cards will be shown."
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❗ <b>Usage</b>\n"
            "<code>/check 4242424242424242|12|2025|123</code>",
            parse_mode="HTML"
        )
        return

    card_data = " ".join(context.args)
    await process_card(update, card_data)

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    card_data = update.message.text.strip()
    await process_card(update, card_data)

# ---------------- MAIN LOGIC ----------------
async def process_card(update: Update, card_data: str):
    if "|" not in card_data:
        await update.message.reply_text(
            "❌ <b>Invalid format</b>\n"
            "Use:\n"
            "<code>4242424242424242|12|2025|123</code>",
            parse_mode="HTML"
        )
        return

    processing = await update.message.reply_text("⏳ Checking card...")

    result = await check_card(card_data)

    if not result:
        await processing.edit_text("❌ API Error. Try again later.")
        return

    code = result.get("code")
    status = str(result.get("status", "")).lower()
    message = result.get("message", "No message")
    card = result.get("card", {})

    # ---------------- LIVE CARD ----------------
    if code == 1 and status == "live":
        country = card.get("country", {})

        # HTML escape (VERY IMPORTANT)
        card_num = escape(str(card.get("card", "N/A")))
        bank = escape(str(card.get("bank", "N/A")))
        ctype = escape(str(card.get("type", "N/A")))
        brand = escape(str(card.get("brand", "N/A")))
        cname = escape(str(country.get("name", "N/A")))
        cemoji = escape(str(country.get("emoji", "")))
        ccode = escape(str(country.get("code", "N/A")))
        msg_safe = escape(str(message))

        text = (
            "✅ <b>LIVE CARD</b>\n\n"
            f"💳 Card: <code>{card_num}</code>\n"
            f"🏦 Bank: {bank}\n"
            f"💰 Type: {ctype}\n"
            f"🏷 Brand: {brand}\n"
            f"🌍 Country: {cname} {cemoji} ({ccode})\n\n"
            f"📝 Message: {msg_safe}"
        )

        await processing.edit_text(text, parse_mode="HTML")

    # ---------------- NOT LIVE ----------------
    else:
        await processing.delete()
        msg = await update.message.reply_text("❌ Card is NOT Live")
        await asyncio.sleep(3)
        try:
            await msg.delete()
        except:
            pass

# ---------------- ERROR HANDLER ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update caused error: {context.error}")

# ---------------- MAIN ----------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = int(os.getenv("PORT", 10000))

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    if not render_url:
        raise RuntimeError("RENDER_EXTERNAL_URL not set")

    webhook_url = f"{render_url.rstrip('/')}/{token}"

    setup_webhook(token, webhook_url)

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    main()