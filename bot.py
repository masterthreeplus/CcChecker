import os
import logging
import asyncio
import aiohttp
import requests
from html import escape
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from motor.motor_asyncio import AsyncIOMotorClient

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
CHKR_API_URL = "https://api.chkr.cc/"
bulk_mode = {}  # Store bulk mode state per user

# MongoDB & Admin Config from environment
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "cc_checker_bot")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(uid.strip()) for uid in ADMIN_IDS_STR.split(",") if uid.strip().isdigit()]

# Global MongoDB variables
mongo_client = None
db = None
users_collection = None

# ---------------- MONGODB INIT ----------------
async def init_mongodb():
    global mongo_client, db, users_collection
    
    if not MONGODB_URI:
        logger.warning("MONGODB_URI not set → MongoDB logging disabled")
        return False
    
    try:
        mongo_client = AsyncIOMotorClient(MONGODB_URI)
        await mongo_client.admin.command('ping')  # test connection
        db = mongo_client[MONGODB_DB_NAME]
        users_collection = db["users"]
        
        # Create indexes
        await users_collection.create_index("user_id", unique=True)
        await users_collection.create_index("username")
        await users_collection.create_index("last_active")
        
        logger.info("MongoDB connected successfully")
        return True
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        return False

# ---------------- SAVE / UPDATE USER ----------------
async def upsert_user(user):
    if not users_collection:
        return
    
    try:
        await users_collection.update_one(
            {"user_id": user.id},
            {
                "$set": {
                    "user_id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "first_name": user.first_name,
                    "last_name": user.last_name or None,
                    "language_code": user.language_code,
                    "is_premium": user.is_premium,
                    "last_active": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "joined_at": datetime.now(timezone.utc),
                    "created_at": datetime.now(timezone.utc),
                    "message_count": 0,
                    "is_blocked": False,
                },
                "$inc": {"message_count": 1}
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to upsert user {user.id}: {e}")

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
    user = update.effective_user
    await upsert_user(user)
    
    text = """🔐 <b>CC Checker Bot</b>

📌 <b>Usage</b>
Send card details in this format:
<code>4242424242424242|12|2025|123</code>

📌 <b>Commands</b>
<code>/check 4242424242424242|12|2025|123</code>
<code>/bulk</code> - Enable bulk checking mode
<code>/users</code> - (Admin only) View user stats

⚠️ Only LIVE cards will be shown."""
    await update.message.reply_text(text, parse_mode="HTML")

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        text = """❗ <b>Usage</b>
<code>/check 4242424242424242|12|2025|123</code>"""
        await update.message.reply_text(text, parse_mode="HTML")
        return

    card_data = " ".join(context.args)
    await process_card(update, card_data)

async def bulk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await upsert_user(user)
    
    user_id = user.id
    bulk_mode[user_id] = []
    
    text = """🔄 <b>Bulk Check Mode Activated</b>

📤 Send multiple card details (one per line)
Example:
<code>4242424242424242|12|2025|123
5555555555554444|01|2026|456
378282246310005|03|2027|789</code>

✅ Bot will check all cards and return only LIVE ones
⏳ Processing time depends on number of cards"""
    await update.message.reply_text(text, parse_mode="HTML")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    
    if not users_collection:
        await update.message.reply_text("⚠️ Database is not connected.")
        return
    
    try:
        total = await users_collection.count_documents({})
        active_7d = await users_collection.count_documents({
            "last_active": {"$gte": datetime.now(timezone.utc) - timedelta(days=7)}
        })
        active_30d = await users_collection.count_documents({
            "last_active": {"$gte": datetime.now(timezone.utc) - timedelta(days=30)}
        })
        
        recent = await users_collection.find().sort("joined_at", -1).limit(10).to_list(10)
        
        text = f"""📊 <b>User Statistics</b>

Total users: <b>{total}</b>
Active (last 7 days): <b>{active_7d}</b>
Active (last 30 days): <b>{active_30d}</b>

<b>Latest 10 joined users:</b>\n"""
        
        for u in recent:
            joined = u.get("joined_at", datetime.now()).strftime("%Y-%m-%d")
            username = f"@{u['username']}" if u.get("username") else "No username"
            premium = "⭐" if u.get("is_premium") else ""
            text += f"• {u.get('full_name','?')} {username} {premium} | ID: <code>{u['user_id']}</code> | {joined}\n"
        
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in /users: {e}")
        await update.message.reply_text("❌ Error fetching user data.")

# ---------------- MESSAGE HANDLER ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await upsert_user(user)
    
    logger.info(f"Received message from {user.id} (@{user.username or 'no username'}): {update.message.text.strip()}")
    
    user_id = user.id
    message_text = update.message.text.strip()
    
    # Check for Bulk Mode
    if user_id in bulk_mode:
        cards = [
            line.strip()
            for line in message_text.splitlines()
            if line.strip() and '|' in line
        ]
        
        if not cards:
            text = """❌ <b>No valid cards found</b>
Make sure each line has format:
<code>4242424242424242|12|2025|123</code>"""
            await update.message.reply_text(text, parse_mode="HTML")
            return
        
        await process_bulk_cards(update, cards, user_id)
    else:
        # Check Single Card
        card_data = message_text
        await process_card(update, card_data)

# ---------------- BULK PROCESSING ----------------
async def process_bulk_cards(update: Update, cards: list, user_id: int):
    total = len(cards)
    processing_msg = await update.message.reply_text(
        f"⏳ <b>Checking {total} cards...</b>\nPlease wait, this may take a moment.",
        parse_mode="HTML"
    )
    
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
    
    try:
        await processing_msg.delete()
    except:
        pass
    
    if live_cards:
        for card in live_cards:
            text = f"""✅ <b>LIVE CARD</b>

💳 Card: <code>{card['card']}</code>
🏦 Bank: {card['bank']}
💰 Type: {card['type']}
🏷 Brand: {card['brand']}
🌍 Country: {card['country']}

📝 Message: {card['message']}"""
            await update.message.reply_text(text, parse_mode="HTML")
            await asyncio.sleep(0.6)  # rate limit safety
    
    summary = f"""✅ <b>Bulk Check Complete</b>

📊 Total Checked: {total}
💚 Live Cards: {len(live_cards)}
❌ Dead Cards: {total - len(live_cards)}"""
    await update.message.reply_text(summary, parse_mode="HTML")
    
    if user_id in bulk_mode:
        del bulk_mode[user_id]

# ---------------- SINGLE CARD PROCESS ----------------
async def process_card(update: Update, card_data: str):
    if "|" not in card_data:
        text = """❌ <b>Invalid format</b>
Use:
<code>4242424242424242|12|2025|123</code>"""
        await update.message.reply_text(text, parse_mode="HTML")
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

    if code == 1 and status == "live":
        country = card.get("country", {})

        card_num = escape(str(card.get("card", "N/A")))
        bank = escape(str(card.get("bank", "N/A")))
        ctype = escape(str(card.get("type", "N/A")))
        brand = escape(str(card.get("brand", "N/A")))
        cname = escape(str(country.get("name", "N/A")))
        cemoji = escape(str(country.get("emoji", "")))
        ccode = escape(str(country.get("code", "N/A")))
        msg_safe = escape(str(message))

        text = f"""✅ <b>LIVE CARD</b>

💳 Card: <code>{card_num}</code>
🏦 Bank: {bank}
💰 Type: {ctype}
🏷 Brand: {brand}
🌍 Country: {cname} {cemoji} ({ccode})

📝 Message: {msg_safe}"""

        await processing.edit_text(text, parse_mode="HTML")
    else:
        try:
            await processing.delete()
        except:
            pass
        msg = await update.message.reply_text("❌ Card is NOT Live")
        await asyncio.sleep(3)
        try:
            await msg.delete()
        except:
            pass

# ---------------- ERROR HANDLER ----------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update caused error: {context.error}")

# ---------------- ASYNC MAIN ----------------
async def main_async():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    port = int(os.getenv("PORT", 10000))

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not render_url:
        raise RuntimeError("RENDER_EXTERNAL_URL not set")

    webhook_url = f"{render_url.rstrip('/')}/{token}"

    logger.info(f"Preparing webhook: {webhook_url}")
    logger.info(f"Listening on port: {port}")

    # Setup webhook
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
            return
    except Exception as e:
        logger.error(f"Webhook setup error: {e}")
        return

    # MongoDB
    await init_mongodb()

    # Build application
    application = Application.builder().token(token).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("bulk", bulk_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    # Start webhook
    await application.initialize()
    await application.start()
    await application.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=webhook_url,
        drop_pending_updates=True,
        allowed_updates=["message"]
    )

    logger.info("Webhook server started successfully. Waiting for updates...")

    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())
