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
bulk_mode = {}  # Store bulk mode state per user

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
        "🔐 <b>CC Checker Bot</b>

"
        "📌 <b>Usage</b>
"
        "Send card details in this format:
"
        "<code>4242424242424242|12|2025|123</code>

"
        "📌 <b>Commands</b>
"
        "<code>/check 4242424242424242|12|2025|123</code>
"
        "<code>/bulk</code> - Enable bulk checking mode

"
        "⚠️ Only LIVE cards will be shown."
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❗ <b>Usage</b>
"
            "<code>/check 4242424242424242|12|2025|123</code>",
            parse_mode="HTML"
        )
        return

    card_data = " ".join(context.args)
    await process_card(update, card_data)

async def bulk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bulk_mode[user_id] = []
    
    await update.message.reply_text(
        "🔄 <b>Bulk Check Mode Activated</b>

"
        "📤 Send multiple card details (one per line)
"
        "Example:
"
        "<code>4242424242424242|12|2025|123
"
        "5555555555554444|01|2026|456
"
        "378282246310005|03|2027|789</code>

"
        "✅ Bot will check all cards and return only LIVE ones
"
        "⏳ Processing time depends on number of cards",
        parse_mode="HTML"
    )

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Check if user is in bulk mode
    if user_id in bulk_mode:
        cards = [line.strip() for line in message_text.split('
') if line.strip() and '|' in line]
        
        if not cards:
            await update.message.reply_text(
                "❌ <b>No valid cards found</b>
"
                "Make sure each line has format:
"
                "<code>4242424242424242|12|2025|123</code>",
                parse_mode="HTML"
            )
            return
        
        await process_bulk_cards(update, cards, user_id)
    else:
        # Single card check
        card_data = message_text
        await process_card(update, card_data)

# ---------------- BULK PROCESSING ----------------
async def process_bulk_cards(update: Update, cards: list, user_id: int):
    total = len(cards)
    processing_msg = await update.message.reply_text(
        f"⏳ <b>Checking {total} cards...</b>
"
        f"Please wait, this may take a moment.",
        parse_mode="HTML"
    )
    
    # Process all cards concurrently
    tasks = [check_card(card) for card in cards]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    live_cards = []
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error checking card {i+1}: {result}")
            continue
        
        if not result:
            continue
        
        code = result.get("code")
        status = str(result.get("status", "")).lower()
        
        if code == 1 and status == "live":
            card_info = result.get("card", {})
            message = result.get("message", "No message")
            country = card_info.get("country", {})
            
            # HTML escape
            card_num = escape(str(card_info.get("card", cards[i])))
            bank = escape(str(card_info.get("bank", "N/A")))
            ctype = escape(str(card_info.get("type", "N/A")))
            brand = escape(str(card_info.get("brand", "N/A")))
            cname = escape(str(country.get("name", "N/A")))
            cemoji = escape(str(country.get("emoji", "")))
            ccode = escape(str(country.get("code", "N/A")))
            msg_safe = escape(str(message))
            
            live_cards.append({
                "card": card_num,
                "bank": bank,
                "type": ctype,
                "brand": brand,
                "country": f"{cname} {cemoji} ({ccode})",
                "message": msg_safe
            })
    
    # Delete processing message
    await processing_msg.delete()
    
    # Send results
    if live_cards:
        for card in live_cards:
            text = (
                "✅ <b>LIVE CARD</b>

"
                f"💳 Card: <code>{card['card']}</code>
"
                f"🏦 Bank: {card['bank']}
"
                f"💰 Type: {card['type']}
"
                f"🏷 Brand: {card['brand']}
"
                f"🌍 Country: {card['country']}

"
                f"📝 Message: {card['message']}"
            )
            await update.message.reply_text(text, parse_mode="HTML")
            await asyncio.sleep(0.5)  # Prevent rate limit
    
    # Send completion message
    summary = (
        f"✅ <b>Bulk Check Complete</b>

"
        f"📊 Total Checked: {total}
"
        f"💚 Live Cards: {len(live_cards)}
"
        f"❌ Dead Cards: {total - len(live_cards)}"
    )
    await update.message.reply_text(summary, parse_mode="HTML")
    
    # Exit bulk mode
    del bulk_mode[user_id]

# ---------------- MAIN LOGIC ----------------
async def process_card(update: Update, card_data: str):
    if "|" not in card_data:
        await update.message.reply_text(
            "❌ <b>Invalid format</b>
"
            "Use:
"
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
            "✅ <b>LIVE CARD</b>

"
            f"💳 Card: <code>{card_num}</code>
"
            f"🏦 Bank: {bank}
"
            f"💰 Type: {ctype}
"
            f"🏷 Brand: {brand}
"
            f"🌍 Country: {cname} {cemoji} ({ccode})

"
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
    app.add_handler(CommandHandler("bulk", bulk_command))
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