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

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "cc_checker_bot")
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(uid.strip()) for uid in ADMIN_IDS_STR.split(",") if uid.strip().isdigit()]

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
        await mongo_client.admin.command('ping')
        db = mongo_client[MONGODB_DB_NAME]
        users_collection = db["users"]
        
        await users_collection.create_index("user_id", unique=True)
        await users_collection.create_index("username")
        await users_collection.create_index("last_active")
        
        logger.info("MongoDB connected successfully")
        return True
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        return False

# ---------------- UPSERT USER ----------------
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

# ... (check_command, bulk_command, users_command တွေ အရင်အတိုင်း ဆက်ထားပါ) ...

# ---------------- MESSAGE HANDLER (debug log ထည့်ထားပါတယ်) ----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await upsert_user(user)
    
    logger.info(f"Received message from {user.id} (@{user.username or 'no username'}): {update.message.text.strip()}")
    
    user_id = user.id
    message_text = update.message.text.strip()
    
    if user_id in bulk_mode:
        # ... ကျန်တဲ့ bulk logic အရင်အတိုင်း ...
    else:
        # ... single card logic အရင်အတိုင်း ...

# ... (process_bulk_cards, process_card, error_handler တွေ အရင်အတိုင်း ဆက်ထားပါ) ...

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

    # Setup webhook (sync ဖြစ်နေရင်လည်း အဆင်ပြေတယ်)
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

    # Build app
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
        drop_pending_updates=True,          # အရေးကြီးဆုံး - ကျန်နေတဲ့ updates ရှင်းပါ
        allowed_updates=["message"]
    )

    logger.info("Webhook server started successfully. Waiting for updates...")

    # အဆက်မပြတ် run နေအောင် စောင့်ထားပါ
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main_async())