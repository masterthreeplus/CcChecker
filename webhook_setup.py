import os
import requests
import sys

def setup_webhook():
    """Setup Telegram webhook"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    render_url = os.getenv('RENDER_EXTERNAL_URL')
    
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not found!")
        sys.exit(1)
    
    if not render_url:
        print("❌ RENDER_EXTERNAL_URL not found!")
        sys.exit(1)
    
    # Remove trailing slash if exists
    render_url = render_url.rstrip('/')
    
    # Set webhook
    webhook_url = f"{render_url}/{token}"
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    
    print(f"Setting webhook to: {webhook_url}")
    
    try:
        response = requests.post(api_url, json={
            "url": webhook_url,
            "allowed_updates": ["message"]
        })
        result = response.json()
        
        if result.get('ok'):
            print("✅ Webhook set successfully!")
            print(f"Description: {result.get('description')}")
        else:
            print(f"❌ Failed to set webhook: {result}")
            
        # Get webhook info
        info_url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        info_response = requests.get(info_url)
        info = info_response.json()
        
        print("
📊 Webhook Info:")
        print(f"URL: {info['result'].get('url')}")
        print(f"Pending updates: {info['result'].get('pending_update_count')}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    setup_webhook()