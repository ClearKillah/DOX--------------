import json
import os
import sys
import time
import asyncio
import datetime
import random
import logging
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv
import telegram

import database as db

# Enable logging with more detailed level
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Conversation states
START, CHATTING, PROFILE, EDIT_PROFILE, GROUP_CHATTING = range(5)

# User data file
USER_DATA_FILE = "user_data.json"

# Global variables
user_data = {}
active_chats = {}
searching_users = {}

# Constants
WELCOME_TEXT = (
    "👋 *Добро пожаловать в анонимный чат!*\n\n"
    "Здесь вы можете общаться с случайными собеседниками анонимно.\n\n"
    "🔍 Нажмите кнопку «Поиск собеседника», чтобы начать чат.\n"
    "👥 Или присоединитесь к групповому чату.\n"
    "👤 В профиле вы можете указать свой пол и интересы."
)

MAIN_KEYBOARD = [
    [InlineKeyboardButton("🔍 Поиск собеседника", callback_data="find_chat")],
    [InlineKeyboardButton("👥 Групповой чат", callback_data="group_chat")],
    [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
    [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
]

# Load user data from file
def load_user_data():
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {}

# Save user data to file
def save_user_data(data):
    with open(USER_DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    await query.answer()
    
    if query.data == "interest_edit":
        keyboard = [
            [InlineKeyboardButton("💘 Флирт", callback_data="interest_flirt")],
            [InlineKeyboardButton("💬 Общение", callback_data="interest_chat")],
            [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
        ]
        
        # Get current interests to show selection state
        if user_id in user_data:
            interests = user_data[user_id].get("interests", [])
            keyboard = [
                [InlineKeyboardButton("💘 Флирт " + ("✅" if "flirt" in interests else ""), callback_data="interest_flirt")],
                [InlineKeyboardButton("💬 Общение " + ("✅" if "chat" in interests else ""), callback_data="interest_chat")],
                [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
            ]
        
        await query.edit_message_text(
            text="*Выберите ваши интересы:*\n\nВыбранные интересы помогают находить собеседников со схожими интересами.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return PROFILE
    
    elif query.data.startswith("interest_"):
        interest = query.data.split("_")[1]
        
        if user_id in user_data:
            interests = user_data[user_id].get("interests", [])
            if interest in interests:
                interests.remove(interest)
            else:
                interests.append(interest)
            user_data[user_id]["interests"] = interests
            save_user_data(user_data)
        
        keyboard = [
            [InlineKeyboardButton("💘 Флирт " + ("✅" if "flirt" in interests else ""), callback_data="interest_flirt")],
            [InlineKeyboardButton("💬 Общение " + ("✅" if "chat" in interests else ""), callback_data="interest_chat")],
            [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
        ]
        
        await query.edit_message_text(
            text="*Выберите ваши интересы:*\n\nВыбранные интересы помогают находить собеседников со схожими интересами.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return PROFILE
    
    elif query.data == "cancel_search":
        # Remove user from searching list
        if user_id in searching_users:
            del searching_users[user_id]
        
        await query.edit_message_text(
            text=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
        )
        return START
        
    elif query.data == "skip_user" or query.data == "end_chat":
        # Skip current chat partner and find a new one
        if user_id in active_chats:
            partner_id = active_chats[user_id]
            
            # Notify partner that chat has ended
            if partner_id in active_chats:
                try:
                    await context.bot.send_message(
                        chat_id=int(partner_id),
                        text=WELCOME_TEXT,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
                    )
                    del active_chats[partner_id]
                except Exception as e:
                    logger.error(f"Error showing welcome message to partner: {e}")
            
            del active_chats[user_id]
        
        if query.data == "skip_user":
            # Start new search
            search_message = await query.edit_message_text(
                text="🔍 *Поиск собеседника...*\n\n⏱ Время поиска: 00:00",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]
                ])
            )
            
            # Add user to searching users
            searching_users[user_id] = {
                "start_time": time.time(),
                "message_id": search_message.message_id,
                "chat_id": query.message.chat_id
            }
            
            # Start continuous search in background
            asyncio.create_task(continuous_search(user_id, context))
            return START
        else:
            # End chat completely
            await query.edit_message_text(
                text=WELCOME_TEXT,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
            )
            return START
    
    return START

def main() -> None:
    """Start the bot."""
    try:
        logger.info("Starting bot...")
        # Create the Application
        token = "8039344227:AAEDCP_902a3r52JIdM9REqUyPx-p2IVtxA"
        logger.info("Using token: %s", token)
        
        # Build application
        application = (
            Application.builder()
            .token(token)
            .build()
        )
        
        # Add conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                START: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.VOICE, handle_message),  # Explicit handler for voice messages
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                CHATTING: [
                    CallbackQueryHandler(button_handler),
                    CommandHandler("end", end_chat),
                    MessageHandler(filters.VOICE, handle_message),  # Explicit handler for voice messages
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                PROFILE: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                EDIT_PROFILE: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                GROUP_CHATTING: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.VOICE, handle_group_message),  # Explicit handler for voice messages
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_group_message)
                ]
            },
            fallbacks=[CommandHandler("start", start)]
        )
        
        application.add_handler(conv_handler)
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Get environment variables for Railway
        PORT = int(os.environ.get('PORT', '8443'))
        RAILWAY_STATIC_URL = os.environ.get('RAILWAY_STATIC_URL', 'dox-production.up.railway.app')
        
        # Start the Bot with webhook if on Railway, otherwise use polling
        if 'RAILWAY_STATIC_URL' in os.environ:
            logger.info(f"Starting webhook on {RAILWAY_STATIC_URL}")
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path=token,
                webhook_url=f"https://{RAILWAY_STATIC_URL}/{token}"
            )
        else:
            logger.info("Starting polling...")
            application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
        logger.info("Bot stopped")
    except Exception as e:
        logger.critical("Fatal error starting bot: %s", str(e), exc_info=True)
        sys.exit(1)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the dispatcher."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Send message to the user
    if update and isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз."
        )

if __name__ == "__main__":
    main() 