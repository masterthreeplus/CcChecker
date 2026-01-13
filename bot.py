import os
import json
import logging
import asyncio
import aiohttp
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

CHKR_API_URL = "https://api.chkr.cc/"

def setup_webhook(token, webhook_url):
    try:
        api_url = f"https://api.telegram.org/bot{token}/setWebhook"
        response = requests.post(api_url, json={
            "url": webhook_url,
            "allowed_updates": ["message"]
        })
        result = response.json()
        if result.get('ok'):
            logger.info(f"Webhook set: {webhook_url}")
        else:
            logger.error(f"Webhook setup failed: {result}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")

async def check_card(card_number):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                CHKR_API_URL,
                json={"data": card_number},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                return await response.json()
    except Exception as e:
        logger.error(f"API Error: {e}")
        return None

async def start(update, context):
    welcome_message = """🔐 CC Checker Bot

Usage:
Send card details in format:
`4242424242424242|12|2025|123`

Note: Only Live cards will be displayed.

Send /check command with card details or just send the card number directly."""
    
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def check_command(update, context):
    if not context.args:
        msg = """Please provide card details
Format: `/check 4242424242424242|12|2025|123`"""
        await update.message.reply_text(msg, parse_mode='Markdown')
        return
    
    card_data = ' '.join(context.args)
    await process_card(update, card_data)

async def handle_message(update, context):
    card_data = update.message.text.strip()
    await process_card(update, card_data)

async def process_card(update, card_data):
    if '|' not in card_data:
        await update.message.reply_text(
            "Invalid format. Use: `4242424242424242|12|2025|123`",
            parse_mode='Markdown'
        )
        return
    
    processing_msg = await update.message.reply_text("⏳ Checking card...")
    
    result = await check_card(card_data)
    
    if not result:
        await processing_msg.edit_text("❌ API Error. Please try again.")
        return
    
    code = result.get('code', 2)
    status = result.get('status', 'Unknown')
    message = result.get('message', 'No message')
    card_info = result.get('card', {})
    
    if code == 1 and status.lower() == 'live':
        card_number = card_info.get('card', 'N/A')
        bank_name = card_info.get('bank', 'N/A')
        card_type = card_info.get('type', 'N/A')
        brand = card_info.get('brand', 'N/A')
        country_info = card_info.get('country', {})
        country_name = country_info.get('name', 'N/A')
        country_code = country_info.get('code', 'N/A')
        country_emoji = country_info.get('emoji', '')
        
        response_text = f"""✅ LIVE CARD

💳 Card: `{card_number}`
🏦 Bank: {bank_name}
💰 Type: {card_type}
🏷️ Brand: {brand}
🌍 Country: {country_name} {country_emoji} ({country_code})

📝 Message: {message}"""
        
        await processing_msg.edit_text(response_text, parse_mode='Markdown')
    else:
        await processing_msg.delete()
        notification = await update.message.reply_text("❌ Card is not Live")
        await asyncio.sleep(3)
        await notification.delete()

async def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    render_url = os.getenv('RENDER_EXTERNAL_URL')
    
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    
    if not render_url:
        raise ValueError("RENDER_EXTERNAL_URL environment variable not set")
    
    webhook_url = f"{render_url.rstrip('/')}/{token}"
    setup_webhook(token, webhook_url)
    
    application = Application.builder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    port = int(os.getenv('PORT', 8443))
    logger.info(f"Starting bot on port {port}")
    logger.info(f"Webhook URL: {webhook_url}")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=webhook_url
    )

if __name__ == '__main__':
    main()