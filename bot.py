import os
import logging
import asyncio
from datetime import datetime

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    JobQueue,
)

# --- Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# CoinGecko API Endpoint
COINGECKO_API = "https://api.coingecko.com/api/v3"

# --- Helper Functions ---
async def fetch_crypto_price(coin_id: str, currency: str = "usd"):
    """Fetch the current price for a coin from CoinGecko."""
    try:
        url = f"{COINGECKO_API}/simple/price?ids={coin_id}&vs_currencies={currency}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if coin_id in data:
            return data[coin_id][currency]
        return None
    except Exception as e:
        logger.error(f"Error fetching price for {coin_id}: {e}")
        return None

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message."""
    user = update.effective_user
    await update.message.reply_text(
        f"🚀 Welcome to CoinPulse989Bot, {user.first_name}!\n\n"
        "I'm your trusted crypto assistant for live market tracking and alerts.\n"
        "Use /help to see all available commands.",
        parse_mode="Markdown",
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all available commands."""
    text = (
        "*CoinPulse989Bot Commands*\n\n"
        "📈 /price `<coin>` - Get the current price (e.g., `/price bitcoin`)\n"
        "🔔 /alert `<coin> <target_price>` - Set a price alert\n"
        "📋 /alerts - View your active alerts\n"
        "❌ /remove `<alert_id>` - Remove an alert\n"
        "💡 /trending - See trending coins on CoinGecko\n"
        "ℹ️ /about - About this bot\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and display the price of a specified coin."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a coin ID. Example: `/price bitcoin`",
            parse_mode="Markdown"
        )
        return

    coin_id = context.args[0].lower()
    await update.message.reply_text(f"🔍 Fetching price for *{coin_id}*...", parse_mode="Markdown")

    price = await fetch_crypto_price(coin_id)
    if price is not None:
        await update.message.reply_text(
            f"💰 *{coin_id.capitalize()}*: `${price:,}` USD",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Could not find data for `{coin_id}`. Please check the coin ID and try again.\n"
            "Use `/trending` to see popular coins.",
            parse_mode="Markdown"
        )

async def trending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show trending coins from CoinGecko."""
    try:
        url = f"{COINGECKO_API}/search/trending"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "coins" in data and data["coins"]:
            trending_list = []
            for i, coin in enumerate(data["coins"][:5], 1):
                item = coin["item"]
                trending_list.append(f"{i}. {item['name']} ({item['symbol']})")
            
            message = "🔥 *Trending Coins*\n\n" + "\n".join(trending_list)
            message += "\n\nUse `/price <coin_id>` to check their price."
            await update.message.reply_text(message, parse_mode="Markdown")
        else:
            await update.message.reply_text("No trending data available right now.")
    except Exception as e:
        logger.error(f"Error fetching trending coins: {e}")
        await update.message.reply_text("❌ Failed to fetch trending coins. Please try again later.")

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display information about the bot."""
    text = (
        "ℹ️ *About CoinPulse989Bot*\n\n"
        "Your trusted crypto assistant for live blockchain tracking, "
        "intelligent automation, and up-to-the-minute market updates.\n\n"
        "Powered by CoinGecko data."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# --- Price Alert System ---
async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set a price alert for a specific coin."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/alert <coin_id> <target_price>`\n"
            "Example: `/alert bitcoin 100000`",
            parse_mode="Markdown"
        )
        return

    coin_id = context.args[0].lower()
    try:
        target_price = float(context.args[1])
        if target_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid positive number for the target price.")
        return

    chat_id = update.effective_chat.id
    alert_id = f"{coin_id}_{int(target_price)}"

    # Store alert in bot_data for simplicity (resets on redeploy)
    if 'alerts' not in context.bot_data:
        context.bot_data['alerts'] = {}
    
    context.bot_data['alerts'][alert_id] = {
        'chat_id': chat_id,
        'coin_id': coin_id,
        'target_price': target_price,
        'created_at': datetime.now().isoformat()
    }

    # Schedule the job to check the price
    context.job_queue.run_repeating(
        check_alert,
        interval=60,  # Check every 60 seconds
        first=10,     # First check after 10 seconds
        data={'alert_id': alert_id},
        name=f"alert_{alert_id}"
    )

    await update.message.reply_text(
        f"✅ Alert set for *{coin_id.capitalize()}* at `${target_price:,}`\n"
        f"Alert ID: `{alert_id}`\n\n"
        "I'll notify you when the price hits this target.",
        parse_mode="Markdown"
    )

async def check_alert(context: ContextTypes.DEFAULT_TYPE):
    """Check if the price alert condition is met."""
    job = context.job
    alert_id = job.data['alert_id']
    alerts = context.bot_data.get('alerts', {})
    
    if alert_id not in alerts:
        job.schedule_removal()
        return

    alert = alerts[alert_id]
    current_price = await fetch_crypto_price(alert['coin_id'])

    if current_price is None:
        logger.warning(f"Could not fetch price for {alert['coin_id']}")
        return

    if current_price >= alert['target_price']:
        await context.bot.send_message(
            chat_id=alert['chat_id'],
            text=f"🔔 *Price Alert Triggered!*\n\n"
                 f"*{alert['coin_id'].capitalize()}* has reached `${current_price:,}`\n"
                 f"Your target was: `${alert['target_price']:,}`",
            parse_mode="Markdown"
        )
        # Remove the alert after it triggers
        del alerts[alert_id]
        job.schedule_removal()

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all active alerts for the user."""
    user_chat_id = update.effective_chat.id
    alerts = context.bot_data.get('alerts', {})
    
    user_alerts = {k: v for k, v in alerts.items() if v['chat_id'] == user_chat_id}
    
    if not user_alerts:
        await update.message.reply_text("📭 You have no active price alerts.")
        return

    message = "📋 *Your Active Alerts*\n\n"
    for alert_id, alert in user_alerts.items():
        message += f"• ID: `{alert_id}`\n"
        message += f"  Coin: {alert['coin_id'].capitalize()}\n"
        message += f"  Target: `${alert['target_price']:,}`\n\n"
    
    message += "Use `/remove <alert_id>` to delete an alert."
    await update.message.reply_text(message, parse_mode="Markdown")

async def remove_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a price alert by ID."""
    if not context.args:
        await update.message.reply_text("Usage: `/remove <alert_id>`", parse_mode="Markdown")
        return

    alert_id = context.args[0]
    alerts = context.bot_data.get('alerts', {})
    user_chat_id = update.effective_chat.id

    if alert_id in alerts and alerts[alert_id]['chat_id'] == user_chat_id:
        # Remove any scheduled jobs for this alert
        for job in context.job_queue.get_jobs_by_name(f"alert_{alert_id}"):
            job.schedule_removal()
        
        del alerts[alert_id]
        await update.message.reply_text(f"✅ Alert `{alert_id}` removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Alert not found or you don't have permission to remove it.")

# --- Main Application ---
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    application = Application.builder().token(token).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("alert", alert_command))
    application.add_handler(CommandHandler("alerts", list_alerts))
    application.add_handler(CommandHandler("remove", remove_alert))
    application.add_handler(CommandHandler("trending", trending_command))
    application.add_handler(CommandHandler("about", about_command))

    logger.info("Starting CoinPulse989Bot with long polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
