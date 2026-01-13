import os
import json
import logging
import asyncio
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# CHKR.CC API endpoint
CHKR_API_URL = "https://api.chkr.cc/"

async def check_card(card_number: str) -> dict:
    """Check card using CHKR.CC API"""
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message"""
    welcome_message = """
🔐 **CC Checker Bot**

**Usage:**
Send card details in format:
`4242424242424242|12|2025|123`

**Note:** Only **Live** cards will be displayed.

Send /check command with card details or just send the card number directly.
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check command"""
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide card details
"
            "Format: `/check 4242424242424242|12|2025|123`",
            parse_mode='Markdown'
        )
        return
    
    card_data = ' '.join(context.args)
    await process_card(update, card_data)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct card messages"""
    card_data = update.message.text.strip()
    await process_card(update, card_data)

async def process_card(update: Update, card_data: str):
    """Process card check request"""
    # Validate card format (basic validation)
    if '|' not in card_data:
        await update.message.reply_text(
            "❌ Invalid format
"
            "Use: `4242424242424242|12|2025|123`",
            parse_mode='Markdown'
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text("⏳ Checking card...")
    
    # Check card
    result = await check_card(card_data)
    
    if not result:
        await processing_msg.edit_text("❌ API Error. Please try again.")
        return
    
    # Parse response
    code = result.get('code', 2)
    status = result.get('status', 'Unknown')
    message = result.get('message', 'No message')
    card_info = result.get('card', {})
    
    # Only show Live cards (code 1)
    if code == 1 and status.lower() == 'live':
        card_number = card_info.get('card', 'N/A')
        bank_name = card_info.get('bank', 'N/A')
        card_type = card_info.get('type', 'N/A')
        brand = card_info.get('brand', 'N/A')
        country_info = card_info.get('country', {})
        country_name = country_info.get('name', 'N/A')
        country_code = country_info.get('code', 'N/A')
        country_emoji = country_info.get('emoji', '')
        
        response_text = f"""
✅ **LIVE CARD**

💳 **Card:** `{card_number}`
🏦 **Bank:** {bank_name}
💰 **Type:** {card_type}
🏷️ **Brand:** {brand}
🌍 **Country:** {country_name} {country_emoji} ({country_code})

📝 **Message:** {message}
"""
        await processing_msg.edit_text(response_text, parse_mode='Markdown')
    else:
        # Delete processing message for non-live cards
        await processing_msg.delete()
        # Optionally send a brief notification
        notification = await update.message.reply_text("❌ Card is not Live")
        # Auto-delete after 3 seconds
        await asyncio.sleep(3)
        await notification.delete()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Start the bot"""
    # Get token from environment variable
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        handle_message
    ))
    application.add_error_handler(error_handler)
    
    # Start bot
    port = int(os.getenv('PORT', 8443))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=f"{os.getenv('RENDER_EXTERNAL_URL')}/{token}"
    )

if __name__ == '__main__':
    main()
