import json
import os
import sys
import time
import asyncio
import datetime
import random
import logging
import string
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
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
group_chats = {}
GROUP_MAX_MEMBERS = 10

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
        try:
            with open(USER_DATA_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except Exception as e:
            logger.error(f"Error loading user data: {e}")
            return {}
    return {}

# Save user data to file
def save_user_data(data):
    try:
        with open(USER_DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

# Load data on startup
user_data = load_user_data()

# Create avatar directory if it doesn't exist
if not os.path.exists("avatars"):
    os.makedirs("avatars")

# Chat statistics class
class ChatStats:
    def __init__(self):
        self.total_chats = 0
        self.active_chats = 0
        self.total_messages = 0
        self.users_online = 0
        self.last_update = datetime.datetime.now()

# Initialize chat stats
chat_stats = ChatStats()

async def update_search_timer(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update search timer for all searching users."""
    try:
        for user_id, search_info in list(searching_users.items()):
            start_time = search_info.get("start_time", time.time())
            chat_id = search_info.get("chat_id")
            message_id = search_info.get("message_id")
            
            elapsed_time = int(time.time() - start_time)
            minutes = elapsed_time // 60
            seconds = elapsed_time % 60
            time_str = f"{minutes:02d}:{seconds:02d}"
            
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"🔍 *Поиск собеседника...*\n\n⏱ Время поиска: {time_str}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]
                    ])
                )
            except Exception as e:
                if "Message is not modified" in str(e):
                    # Ignore this error, it's normal when the timer hasn't changed
                    pass
                else:
                    logger.error(f"Error updating search time: {e}")
                    # If we can't update the message, remove user from searching
                    if user_id in searching_users:
                        del searching_users[user_id]
                    break
            
            # Wait before checking again
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error in update_search_timer: {e}")

async def send_typing_notification(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send typing notification to chat partners."""
    try:
        for user_id, partner_id in list(active_chats.items()):
            try:
                await context.bot.send_chat_action(
                    chat_id=int(partner_id),
                    action=telegram.constants.ChatAction.TYPING
                )
            except Exception as e:
                logger.error(f"Error sending typing notification to user {partner_id}: {e}")
    except Exception as e:
        logger.error(f"Error in send_typing_notification: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send welcome message when the command /start is issued."""
    user_id = str(update.effective_user.id)
    
    # Initialize user data if not exists
    if user_id not in user_data:
        user_data[user_id] = {
            "join_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "chat_count": 0,
            "rating": 0,
            "rating_count": 0
        }
        save_user_data(user_data)
    
    # Send welcome message with main menu
    try:
        await update.message.reply_text(
            text=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
        )
        logger.info(f"Welcome message sent to user {user_id}")
    except Exception as e:
        logger.error(f"Error sending welcome message to user {user_id}: {e}")
    
    return START

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    await query.answer()
    
    if query.data == "find_chat":
        return await find_chat(update, context)
    
    elif query.data == "group_chat":
        keyboard = [
            [InlineKeyboardButton("🆕 Создать группу", callback_data="create_group")],
            [InlineKeyboardButton("🔍 Найти группу", callback_data="find_group")],
            [InlineKeyboardButton("🔑 Ввести код приглашения", callback_data="group_enter_code")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        
        await query.edit_message_text(
            text="*Групповой чат*\n\n"
                 "Вы можете создать свою группу или присоединиться к существующей.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return START
    
    elif query.data == "profile":
        return await show_profile(update, context)
    
    elif query.data == "help":
        help_text = (
            "*ℹ️ Помощь*\n\n"
            "*Как пользоваться ботом:*\n"
            "1. Нажмите кнопку «Поиск собеседника», чтобы найти случайного собеседника\n"
            "2. Общайтесь анонимно\n"
            "3. Если собеседник вам не подходит, нажмите «Пропустить»\n"
            "4. Чтобы завершить чат, нажмите «Завершить чат»\n\n"
            "*Групповой чат:*\n"
            "1. Создайте группу или присоединитесь к существующей\n"
            "2. Общайтесь с несколькими людьми одновременно\n\n"
            "*Профиль:*\n"
            "Укажите свой пол, возраст и интересы, чтобы находить подходящих собеседников"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
        ]
        
        await query.edit_message_text(
            text=help_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return START
    
    elif query.data == "back_to_menu":
        await query.edit_message_text(
            text=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
        )
        return START
    
    elif query.data == "interest_edit":
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
        else:
            # End chat completely
            await query.edit_message_text(
                text=WELCOME_TEXT,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
            )
            return START
    
    elif query.data == "edit_profile":
        keyboard = [
            [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
            [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
            [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile")]
        ]
        
        await query.edit_message_text(
            text="*Редактирование профиля*\n\nВыберите, что хотите изменить:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data == "edit_gender":
        keyboard = [
            [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
            [InlineKeyboardButton("👩 Женский", callback_data="gender_female")]
        ]
        
        await query.edit_message_text(
            text="*Выберите ваш пол:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data.startswith("gender_"):
        gender = query.data.split("_")[1]
        if user_id in user_data:
            user_data[user_id]["gender"] = gender
            save_user_data(user_data)
        
        # Сразу возвращаемся к редактированию профиля без промежуточного сообщения
        keyboard = [
            [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
            [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
            [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile")]
        ]
        
        await query.edit_message_text(
            text=f"*Редактирование профиля*\n\n"
                 f"✅ Пол успешно изменен на: {'👨 Мужской' if gender == 'male' else '👩 Женский'}\n\n"
                 f"Выберите, что хотите изменить:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data == "edit_age":
        # Сохраняем ID сообщения для последующего редактирования
        context.user_data["profile_message_id"] = query.message.message_id
        context.user_data["profile_chat_id"] = query.message.chat_id
        
        await query.edit_message_text(
            text="*Введите ваш возраст:*\n\n"
                 "Отправьте число от 13 до 100.",
            parse_mode="Markdown"
        )
        context.user_data["edit_field"] = "age"
        return EDIT_PROFILE
    
    elif query.data == "upload_avatar":
        # Сохраняем ID сообщения для последующего редактирования
        context.user_data["profile_message_id"] = query.message.message_id
        context.user_data["profile_chat_id"] = query.message.chat_id
        
        await query.edit_message_text(
            text="*Загрузка аватара*\n\n"
                 "Отправьте фотографию, которую хотите использовать как аватар.\n\n"
                 "Аватар будет виден только вам и не будет показываться собеседникам.",
            parse_mode="Markdown"
        )
        context.user_data["edit_field"] = "avatar"
        return EDIT_PROFILE
    
    elif query.data == "create_group":
        # Create a new group chat
        return await create_group_chat(update, context)
    
    elif query.data == "find_group":
        # Find available group chats
        return await find_group_chat(update, context)
    
    elif query.data.startswith("join_group_"):
        # Join a specific group
        group_id = query.data.split("_")[2]
        return await handle_group_join(update, context, group_id)
    
    elif query.data.startswith("leave_group_"):
        # Leave a specific group
        group_id = query.data.split("_")[2]
        return await leave_group_chat(update, context, group_id)
    
    return START

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user messages."""
    user_id = str(update.effective_user.id)
    
    # Check if user is in active chat
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # Forward message to partner
        try:
            # Handle different message types
            if update.message.text:
                await context.bot.send_message(
                    chat_id=int(partner_id),
                    text=update.message.text
                )
            elif update.message.photo:
                photo = update.message.photo[-1]
                await context.bot.send_photo(
                    chat_id=int(partner_id),
                    photo=photo.file_id,
                    caption=update.message.caption
                )
            elif update.message.voice:
                await context.bot.send_voice(
                    chat_id=int(partner_id),
                    voice=update.message.voice.file_id
                )
            elif update.message.video:
                await context.bot.send_video(
                    chat_id=int(partner_id),
                    video=update.message.video.file_id,
                    caption=update.message.caption
                )
            elif update.message.sticker:
                await context.bot.send_sticker(
                    chat_id=int(partner_id),
                    sticker=update.message.sticker.file_id
                )
            else:
                await context.bot.send_message(
                    chat_id=int(partner_id),
                    text="[Сообщение не поддерживается]"
                )
                
            return CHATTING
        except Exception as e:
            logger.error(f"Error forwarding message: {e}")
            # If partner is unavailable, end chat
            await end_chat(update, context)
            return START
    
    # Check if user is in a group chat
    for group_id, group_info in group_chats.items():
        if user_id in group_info.get("members", []):
            return await handle_group_message(update, context)
    
    # If user is editing profile - AGE
    if context.user_data.get("edit_field") == "age":
        # Try to delete the user's message
        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Error deleting age message: {e}")
        
        # Process age input
        if update.message.text and update.message.text.isdigit():
            try:
                age = int(update.message.text)
                if 13 <= age <= 100:
                    # Update user data
                    if user_id in user_data:
                        user_data[user_id]["age"] = age
                        save_user_data(user_data)
                    
                    # Get profile message details
                    profile_message_id = context.user_data.get("profile_message_id")
                    profile_chat_id = context.user_data.get("profile_chat_id")
                    
                    # Create keyboard
                    keyboard = [
                        [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
                        [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
                        [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
                        [InlineKeyboardButton("🔙 Назад", callback_data="profile")]
                    ]
                    
                    # Edit original message or send new one
                    if profile_message_id and profile_chat_id:
                        try:
                            await context.bot.edit_message_text(
                                chat_id=profile_chat_id,
                                message_id=profile_message_id,
                                text=f"*Редактирование профиля*\n\n"
                                     f"✅ Возраст успешно изменен на: {age}\n\n"
                                     f"Выберите, что хотите изменить:",
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.error(f"Error editing profile message: {e}")
                            await update.message.reply_text(
                                text=f"*Редактирование профиля*\n\n"
                                     f"✅ Возраст успешно изменен на: {age}\n\n"
                                     f"Выберите, что хотите изменить:",
                                reply_markup=InlineKeyboardMarkup(keyboard),
                                parse_mode="Markdown"
                            )
                    else:
                        await update.message.reply_text(
                            text=f"*Редактирование профиля*\n\n"
                                 f"✅ Возраст успешно изменен на: {age}\n\n"
                                 f"Выберите, что хотите изменить:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode="Markdown"
                        )
                    
                    # Clear edit field
                    context.user_data.pop("edit_field", None)
                    context.user_data.pop("profile_message_id", None)
                    context.user_data.pop("profile_chat_id", None)
                    
                    return EDIT_PROFILE
                else:
                    # Age is out of range
                    profile_message_id = context.user_data.get("profile_message_id")
                    profile_chat_id = context.user_data.get("profile_chat_id")
                    
                    if profile_message_id and profile_chat_id:
                        try:
                            await context.bot.edit_message_text(
                                chat_id=profile_chat_id,
                                message_id=profile_message_id,
                                text="*Введите ваш возраст:*\n\n"
                                     "⚠️ Пожалуйста, введите корректный возраст (от 13 до 100 лет).",
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.error(f"Error editing age message: {e}")
                            await update.message.reply_text(
                                "⚠️ Пожалуйста, введите корректный возраст (от 13 до 100 лет)."
                            )
                    else:
                        await update.message.reply_text(
                            "⚠️ Пожалуйста, введите корректный возраст (от 13 до 100 лет)."
                        )
                    
                    return EDIT_PROFILE
            except ValueError:
                # Not a valid number
                profile_message_id = context.user_data.get("profile_message_id")
                profile_chat_id = context.user_data.get("profile_chat_id")
                
                if profile_message_id and profile_chat_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=profile_chat_id,
                            message_id=profile_message_id,
                            text="*Введите ваш возраст:*\n\n"
                                 "⚠️ Пожалуйста, введите корректный возраст (число от 13 до 100).",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Error editing age message: {e}")
                        await update.message.reply_text(
                            "⚠️ Пожалуйста, введите корректный возраст (число от 13 до 100)."
                        )
                else:
                    await update.message.reply_text(
                        "⚠️ Пожалуйста, введите корректный возраст (число от 13 до 100)."
                    )
                
                return EDIT_PROFILE
    
    # If user is editing profile - AVATAR
    elif context.user_data.get("edit_field") == "avatar":
        if update.message.photo:
            # Try to delete the user's message
            try:
                await update.message.delete()
            except Exception as e:
                logger.error(f"Error deleting avatar message: {e}")
            
            # Save avatar
            photo_file = await update.message.photo[-1].get_file()
            avatar_path = await save_avatar(user_id, photo_file)
            
            if user_id in user_data:
                user_data[user_id]["avatar"] = avatar_path
                save_user_data(user_data)
            
            # Get profile message details
            profile_message_id = context.user_data.get("profile_message_id")
            profile_chat_id = context.user_data.get("profile_chat_id")
            
            # Create keyboard
            keyboard = [
                [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
                [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
                [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
                [InlineKeyboardButton("🔙 Назад", callback_data="profile")]
            ]
            
            # Edit original message or send new one
            if profile_message_id and profile_chat_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=profile_chat_id,
                        message_id=profile_message_id,
                        text=f"*Редактирование профиля*\n\n"
                             f"✅ Аватар успешно загружен!\n\n"
                             f"Выберите, что хотите изменить:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error editing profile message: {e}")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"*Редактирование профиля*\n\n"
                             f"✅ Аватар успешно загружен!\n\n"
                             f"Выберите, что хотите изменить:",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"*Редактирование профиля*\n\n"
                         f"✅ Аватар успешно загружен!\n\n"
                         f"Выберите, что хотите изменить:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            
            # Clear edit field
            context.user_data.pop("edit_field", None)
            context.user_data.pop("profile_message_id", None)
            context.user_data.pop("profile_chat_id", None)
            
            return EDIT_PROFILE
        else:
            # Not a photo
            profile_message_id = context.user_data.get("profile_message_id")
            profile_chat_id = context.user_data.get("profile_chat_id")
            
            if profile_message_id and profile_chat_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=profile_chat_id,
                        message_id=profile_message_id,
                        text="*Загрузка аватара*\n\n"
                             "⚠️ Пожалуйста, отправьте фотографию.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error editing avatar message: {e}")
                    await update.message.reply_text(
                        "⚠️ Пожалуйста, отправьте фотографию."
                    )
            else:
                await update.message.reply_text(
                    "⚠️ Пожалуйста, отправьте фотографию."
                )
            
            return EDIT_PROFILE
    
    # If user is joining a group by code
    if context.user_data.get("joining_group"):
        invite_code = update.message.text.strip()
        
        # Find group by invite code
        found_group = None
        for group_id, group_info in group_chats.items():
            if group_info.get("invite_code") == invite_code:
                found_group = group_id
                break
        
        if found_group:
            context.user_data.pop("joining_group", None)
            return await handle_group_join(update, context, found_group)
        else:
            await update.message.reply_text(
                "❌ *Группа не найдена*\n\n"
                "Проверьте код приглашения и попробуйте снова.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
            context.user_data.pop("joining_group", None)
            return START
    
    # Default response if not in chat or editing profile
    await update.message.reply_text(
        text=WELCOME_TEXT,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
    )
    return START

async def find_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start looking for a chat partner."""
    user_id = str(update.effective_user.id)
    logger.debug(f"User {user_id} is looking for a chat partner")
    
    # End current chat if any
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
    
    # Send initial search message
    if update.callback_query:
        search_message = await update.callback_query.edit_message_text(
            text="🔍 *Поиск собеседника...*\n\n⏱ Время поиска: 00:00",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]
            ])
        )
    else:
        search_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
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
        "chat_id": update.effective_chat.id
    }
    
    # Start continuous search in background
    asyncio.create_task(continuous_search(user_id, context))
    
    return START

async def continuous_search(user_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Continuously search for a chat partner."""
    try:
        # Get search info
        search_info = searching_users.get(user_id)
        if not search_info:
            return
        
        chat_id = search_info.get("chat_id")
        message_id = search_info.get("message_id")
        start_time = search_info.get("start_time", time.time())
        
        # Search for a partner
        while user_id in searching_users:
            # Find potential partners
            potential_partners = []
            for partner_id, partner_info in searching_users.items():
                if partner_id != user_id:
                    potential_partners.append(partner_id)
            
            # If found a partner
            if potential_partners:
                # Choose a random partner
                partner_id = random.choice(potential_partners)
                partner_info = searching_users[partner_id]
                
                # Remove both users from searching
                partner_chat_id = partner_info.get("chat_id")
                partner_message_id = partner_info.get("message_id")
                
                if user_id in searching_users:
                    del searching_users[user_id]
                if partner_id in searching_users:
                    del searching_users[partner_id]
                
                # Add to active chats
                active_chats[user_id] = partner_id
                active_chats[partner_id] = user_id
                
                # Increment chat count for both users
                if user_id in user_data:
                    user_data[user_id]["chat_count"] = user_data[user_id].get("chat_count", 0) + 1
                if partner_id in user_data:
                    user_data[partner_id]["chat_count"] = user_data[partner_id].get("chat_count", 0) + 1
                save_user_data(user_data)
                
                # Get partner info
                partner_info = user_data.get(partner_id, {})
                gender = "👨 Мужской" if partner_info.get("gender") == "male" else "👩 Женский" if partner_info.get("gender") == "female" else "Не указан"
                age = partner_info.get("age", "Не указан")
                
                # Prepare partner info message
                partner_text = f"*Информация о собеседнике:*\n\n"
                if partner_info.get("gender"):
                    partner_text += f"*Пол:* {gender}\n"
                if partner_info.get("age"):
                    partner_text += f"*Возраст:* {age}\n"
                
                interests = partner_info.get("interests", [])
                if interests:
                    interests_text = ""
                    if "flirt" in interests:
                        interests_text += "• 💘 Флирт\n"
                    if "chat" in interests:
                        interests_text += "• 💬 Общение\n"
                    partner_text += f"*Интересы:*\n{interests_text}"
                
                # Notify both users
                keyboard = [
                    [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_user")],
                    [InlineKeyboardButton("❌ Завершить чат", callback_data="end_chat")]
                ]
                
                try:
                    # Send message to the user who initiated the search
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"✅ *Собеседник найден!*\n\n{partner_text}\n\n*Начните общение прямо сейчас!*",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    # Pin the message
                    try:
                        await context.bot.pin_chat_message(
                            chat_id=chat_id,
                            message_id=message_id,
                            disable_notification=True
                        )
                    except Exception as e:
                        logger.error(f"Error pinning message for user {user_id}: {e}")
                except Exception as e:
                    logger.error(f"Error editing message for user {user_id}: {e}")
                    # Attempt to send a new message instead of editing
                    try:
                        sent_message = await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"✅ *Собеседник найден!*\n\n{partner_text}\n\n*Начните общение прямо сейчас!*",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        message_id = sent_message.message_id
                        
                        # Try to pin the new message
                        try:
                            await context.bot.pin_chat_message(
                                chat_id=chat_id,
                                message_id=message_id,
                                disable_notification=True
                            )
                        except Exception as e:
                            logger.error(f"Error pinning new message for user {user_id}: {e}")
                    except Exception as e:
                        logger.error(f"Failed to send fallback message to user {user_id}: {e}")
                
                # Get user info for partner
                user_info = user_data.get(user_id, {})
                user_text = f"*Информация о собеседнике:*\n\n"
                if user_info.get("gender"):
                    user_gender = "👨 Мужской" if user_info.get("gender") == "male" else "👩 Женский"
                    user_text += f"*Пол:* {user_gender}\n"
                if user_info.get("age"):
                    user_text += f"*Возраст:* {user_info.get('age')}\n"
                
                user_interests = user_info.get("interests", [])
                if user_interests:
                    interests_text = ""
                    if "flirt" in user_interests:
                        interests_text += "• 💘 Флирт\n"
                    if "chat" in user_interests:
                        interests_text += "• 💬 Общение\n"
                    user_text += f"*Интересы:*\n{interests_text}"
                
                # If partner was also searching, edit their search message
                if partner_chat_id and partner_message_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=partner_chat_id,
                            message_id=partner_message_id,
                            text=f"✅ *Собеседник найден!*\n\n{user_text}\n\n*Начните общение прямо сейчас!*",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        
                        # Pin message for partner
                        try:
                            await context.bot.pin_chat_message(
                                chat_id=partner_chat_id,
                                message_id=partner_message_id,
                                disable_notification=True
                            )
                        except Exception as e:
                            logger.error(f"Error pinning message for partner {partner_id}: {e}")
                            
                    except Exception as e:
                        logger.error(f"Error updating partner's search message: {e}")
                else:
                    # Partner wasn't searching, send a new message
                    try:
                        partner_message = await context.bot.send_message(
                            chat_id=int(partner_id),
                            text=f"✅ *Собеседник найден!*\n\n{user_text}\n\n*Начните общение прямо сейчас!*",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        
                        # Pin message for partner
                        try:
                            await context.bot.pin_chat_message(
                                chat_id=int(partner_id),
                                message_id=partner_message.message_id,
                                disable_notification=True
                            )
                        except Exception as e:
                            logger.error(f"Error pinning message for partner {partner_id}: {e}")
                            
                    except Exception as e:
                        logger.error(f"Error sending message to partner {partner_id}: {e}")
                        # If we can't send a message to the partner, clean up the chat
                        if user_id in active_chats:
                            del active_chats[user_id]
                        if partner_id in active_chats:
                            del active_chats[partner_id]
                        
                        # Notify the user that the partner is unavailable
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=message_id,
                                text="❌ *Не удалось связаться с собеседником*\n\nПожалуйста, попробуйте найти другого собеседника.",
                                parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                                    [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                                ])
                            )
                        except Exception as e:
                            logger.error(f"Error notifying user about partner unavailability: {e}")
                        
                        # Continue searching
                        continue
                
                # Update chat stats
                chat_stats.total_chats += 1
                chat_stats.active_chats += 1
                
                break
            
            # Wait before checking again
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error in continuous_search: {e}", exc_info=True)
        # Clean up if there was an error
        if user_id in searching_users:
            del searching_users[user_id]

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show user profile."""
    user_id = str(update.effective_user.id)
    
    # Get user data
    user_info = user_data.get(user_id, {})
    
    # Build profile text
    profile_text = "*👤 Ваш профиль:*\n\n"
    
    if user_info.get("gender"):
        gender = "👨 Мужской" if user_info.get("gender") == "male" else "👩 Женский"
        profile_text += f"*Пол:* {gender}\n"
    else:
        profile_text += "*Пол:* Не указан\n"
    
    if user_info.get("age"):
        profile_text += f"*Возраст:* {user_info.get('age')}\n"
    else:
        profile_text += "*Возраст:* Не указан\n"
    
    # Add interests
    interests = user_info.get("interests", [])
    if interests:
        profile_text += "\n*Интересы:*\n"
        if "flirt" in interests:
            profile_text += "• 💘 Флирт\n"
        if "chat" in interests:
            profile_text += "• 💬 Общение\n"
    else:
        profile_text += "\n*Интересы:* Не указаны\n"
    
    # Add stats
    profile_text += f"\n*Статистика:*\n"
    profile_text += f"• 💬 Всего чатов: {user_info.get('chat_count', 0)}\n"
    
    # Create keyboard
    keyboard = [
        [InlineKeyboardButton("✏️ Редактировать профиль", callback_data="edit_profile")],
        [InlineKeyboardButton("💬 Интересы", callback_data="interest_edit")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ]
    
    # Send or edit message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=profile_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text=profile_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return PROFILE

async def handle_avatar_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle avatar upload."""
    user_id = str(update.effective_user.id)
    
    if update.message.photo:
        # Save avatar
        photo_file = await update.message.photo[-1].get_file()
        avatar_path = await save_avatar(user_id, photo_file)
        
        if user_id in user_data:
            user_data[user_id]["avatar"] = avatar_path
            save_user_data(user_data)
        
        # Show profile
        await update.message.reply_text(
            "✅ *Аватар успешно загружен!*",
            parse_mode="Markdown"
        )
        return await show_profile(update, context)
    else:
        await update.message.reply_text(
            "⚠️ Пожалуйста, отправьте фотографию."
        )
        return EDIT_PROFILE

async def find_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Find available group chats."""
    user_id = str(update.effective_user.id)
    
    # Get available groups
    available_groups = []
    for group_id, group_info in group_chats.items():
        if len(group_info.get("members", [])) < GROUP_MAX_MEMBERS and not group_info.get("private", False):
            available_groups.append((group_id, group_info))
    
    if available_groups:
        # Sort groups by number of members (descending)
        available_groups.sort(key=lambda x: len(x[1].get("members", [])), reverse=True)
        
        # Create keyboard with groups
        keyboard = []
        for group_id, group_info in available_groups[:5]:  # Show top 5 groups
            members_count = len(group_info.get("members", []))
            keyboard.append([
                InlineKeyboardButton(
                    f"{group_info.get('name')} ({members_count}/{GROUP_MAX_MEMBERS})",
                    callback_data=f"join_group_{group_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="group_chat")])
        
        # Show available groups
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="*Доступные группы:*\n\n"
                     "Выберите группу, к которой хотите присоединиться:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                text="*Доступные группы:*\n\n"
                     "Выберите группу, к которой хотите присоединиться:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        # No available groups
        keyboard = [
            [InlineKeyboardButton("🆕 Создать группу", callback_data="create_group")],
            [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="*Нет доступных групп*\n\n"
                     "В данный момент нет доступных групп. Вы можете создать свою группу.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                text="*Нет доступных групп*\n\n"
                     "В данный момент нет доступных групп. Вы можете создать свою группу.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    return START

async def create_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create a new group chat."""
    user_id = str(update.effective_user.id)
    
    # Generate unique group ID
    group_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    # Generate invite code
    invite_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    # Create group
    group_chats[group_id] = {
        "name": f"Группа {group_id[:4]}",
        "creator": user_id,
        "members": [user_id],
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "invite_code": invite_code,
        "private": False
    }
    
    # Show group info
    keyboard = [
        [InlineKeyboardButton("❌ Покинуть группу", callback_data=f"leave_group_{group_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=f"✅ *Группа создана!*\n\n"
                 f"Название: {group_chats[group_id]['name']}\n"
                 f"Код приглашения: `{invite_code}`\n"
                 f"Участники: 1/{GROUP_MAX_MEMBERS}\n\n"
                 f"Поделитесь кодом приглашения с друзьями, чтобы они могли присоединиться к вашей группе.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text=f"✅ *Группа создана!*\n\n"
                 f"Название: {group_chats[group_id]['name']}\n"
                 f"Код приглашения: `{invite_code}`\n"
                 f"Участники: 1/{GROUP_MAX_MEMBERS}\n\n"
                 f"Поделитесь кодом приглашения с друзьями, чтобы они могли присоединиться к вашей группе.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return GROUP_CHATTING

async def join_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Join a group chat by invite code."""
    user_id = str(update.effective_user.id)
    
    # Ask for invite code
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text="🔑 *Введите код приглашения*\n\n"
                 "Отправьте код приглашения, который вам дал создатель группы.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text="🔑 *Введите код приглашения*\n\n"
                 "Отправьте код приглашения, который вам дал создатель группы.",
            parse_mode="Markdown"
        )
    
    # Set flag so handle_message will process the invite code
    context.user_data["joining_group"] = True
    
    return GROUP_CHATTING

async def handle_group_join(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str) -> int:
    """Handle joining a group chat."""
    user_id = str(update.effective_user.id)
    
    # Check if group exists
    if group_id not in group_chats:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="❌ *Группа не найдена*\n\n"
                     "Группа, к которой вы пытаетесь присоединиться, не существует.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        else:
            await update.message.reply_text(
                text="❌ *Группа не найдена*\n\n"
                     "Группа, к которой вы пытаетесь присоединиться, не существует.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        return START
    
    # Check if group is full
    group_info = group_chats[group_id]
    if len(group_info.get("members", [])) >= GROUP_MAX_MEMBERS:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="❌ *Группа заполнена*\n\n"
                     "В этой группе уже максимальное количество участников.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        else:
            await update.message.reply_text(
                text="❌ *Группа заполнена*\n\n"
                     "В этой группе уже максимальное количество участников.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        return START
    
    # Check if user is already in the group
    if user_id in group_info.get("members", []):
        # User is already in the group, show group info
        member_list = ""
        for i, member_id in enumerate(group_info.get("members", []), 1):
            member_info = user_data.get(member_id, {})
            gender = "👨" if member_info.get("gender") == "male" else "👩" if member_info.get("gender") == "female" else "👤"
            member_list += f"{i}. {gender} Участник {i}\n"
        
        keyboard = [
            [InlineKeyboardButton("❌ Покинуть группу", callback_data=f"leave_group_{group_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=f"✅ *Вы уже в группе!*\n\n"
                     f"Название: {group_info['name']}\n"
                     f"Участники: {len(group_info['members'])}/{GROUP_MAX_MEMBERS}\n\n"
                     f"Текущие участники:\n{member_list}\n"
                     f"Все сообщения в этом чате анонимны.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                text=f"✅ *Вы уже в группе!*\n\n"
                     f"Название: {group_info['name']}\n"
                     f"Участники: {len(group_info['members'])}/{GROUP_MAX_MEMBERS}\n\n"
                     f"Текущие участники:\n{member_list}\n"
                     f"Все сообщения в этом чате анонимны.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        return GROUP_CHATTING
    
    # Add user to group
    group_info["members"].append(user_id)
    
    # Create member list
    member_list = ""
    for i, member_id in enumerate(group_info.get("members", []), 1):
        member_info = user_data.get(member_id, {})
        gender = "👨" if member_info.get("gender") == "male" else "👩" if member_info.get("gender") == "female" else "👤"
        member_list += f"{i}. {gender} Участник {i}\n"
    
    # Show group info
    keyboard = [
        [InlineKeyboardButton("❌ Покинуть группу", callback_data=f"leave_group_{group_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=f"✅ *Вы присоединились к группе!*\n\n"
                 f"Название: {group_info['name']}\n"
                 f"Участники: {len(group_info['members'])}/{GROUP_MAX_MEMBERS}\n\n"
                 f"Текущие участники:\n{member_list}\n"
                 f"Все сообщения в этом чате анонимны.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=f"✅ *Вы присоединились к группе!*\n\n"
                 f"Название: {group_info['name']}\n"
                 f"Участники: {len(group_info['members'])}/{GROUP_MAX_MEMBERS}\n\n"
                 f"Текущие участники:\n{member_list}\n"
                 f"Все сообщения в этом чате анонимны.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    # Notify other members that someone joined
    for member_id in group_info["members"]:
        if member_id != user_id:  # Don't notify the user who just joined
            try:
                await context.bot.send_message(
                    chat_id=int(member_id),
                    text=f"👋 *Новый участник присоединился к группе!*\n\n"
                         f"В группе теперь {len(group_info['members'])} участников.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error notifying group member {member_id}: {e}")
    
    return GROUP_CHATTING

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle messages in group chats."""
    user_id = str(update.effective_user.id)
    
    # Find which group the user is in
    user_group = None
    for group_id, group_info in group_chats.items():
        if user_id in group_info.get("members", []):
            user_group = group_id
            break
    
    if not user_group:
        # User is not in any group
        await update.message.reply_text(
            text="❌ *Вы не состоите в группе*\n\n"
                 "Присоединитесь к группе или создайте свою.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Групповой чат", callback_data="group_chat")]
            ])
        )
        return START
    
    # Get group info
    group_info = group_chats[user_group]
    
    # Get user info
    user_info = user_data.get(user_id, {})
    gender = "👨" if user_info.get("gender") == "male" else "👩" if user_info.get("gender") == "female" else "👤"
    
    # Get user index in group
    user_index = group_info["members"].index(user_id) + 1
    
    # Forward message to all group members
    for member_id in group_info["members"]:
        if member_id != user_id:  # Don't send message back to sender
            try:
                # Handle different message types
                if update.message.text:
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"{gender} *Участник {user_index}:*\n{update.message.text}",
                        parse_mode="Markdown"
                    )
                elif update.message.photo:
                    photo = update.message.photo[-1]
                    caption = f"{gender} *Участник {user_index}:*\n{update.message.caption or ''}"
                    await context.bot.send_photo(
                        chat_id=int(member_id),
                        photo=photo.file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                elif update.message.voice:
                    await context.bot.send_voice(
                        chat_id=int(member_id),
                        voice=update.message.voice.file_id,
                        caption=f"{gender} *Участник {user_index}*",
                        parse_mode="Markdown"
                    )
                elif update.message.video:
                    caption = f"{gender} *Участник {user_index}:*\n{update.message.caption or ''}"
                    await context.bot.send_video(
                        chat_id=int(member_id),
                        video=update.message.video.file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                elif update.message.sticker:
                    # Send sticker
                    await context.bot.send_sticker(
                        chat_id=int(member_id),
                        sticker=update.message.sticker.file_id
                    )
                    # Send info about who sent it
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"{gender} *Участник {user_index}* отправил стикер",
                        parse_mode="Markdown"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"{gender} *Участник {user_index}:*\n[Сообщение не поддерживается]",
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Error forwarding group message to {member_id}: {e}")
    
    return GROUP_CHATTING

async def leave_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str) -> int:
    """Leave a group chat."""
    user_id = str(update.effective_user.id)
    
    # Check if group exists
    if group_id not in group_chats:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="❌ *Группа не найдена*\n\n"
                     "Группа, из которой вы пытаетесь выйти, не существует.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        else:
            await update.message.reply_text(
                text="❌ *Группа не найдена*\n\n"
                     "Группа, из которой вы пытаетесь выйти, не существует.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        return START
    
    # Get group info
    group_info = group_chats[group_id]
    
    # Check if user is in the group
    if user_id not in group_info.get("members", []):
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="❌ *Вы не состоите в этой группе*\n\n"
                     "Вы не можете покинуть группу, в которой не состоите.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        else:
            await update.message.reply_text(
                text="❌ *Вы не состоите в этой группе*\n\n"
                     "Вы не можете покинуть группу, в которой не состоите.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        return START
    
    # Remove user from group
    group_info["members"].remove(user_id)
    
    # If group is empty, delete it
    if not group_info["members"]:
        del group_chats[group_id]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text="✅ *Вы покинули группу*\n\n"
                     "Так как вы были последним участником, группа была удалена.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
        else:
            await update.message.reply_text(
                text="✅ *Вы покинули группу*\n\n"
                     "Так как вы были последним участником, группа была удалена.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="group_chat")]
                ])
            )
    
    return START

async def end_chat_session(user_id: str, partner_id: str, context: ContextTypes.DEFAULT_TYPE, reason: str = "user_choice") -> None:
    """End a chat session between two users."""
    # Remove from active chats
    if user_id in active_chats:
        del active_chats[user_id]
    if partner_id in active_chats:
        del active_chats[partner_id]
    
    # Delete chat messages for both users
    try:
        # Get the last 100 messages for both users
        user_messages = await context.bot.get_chat_history(chat_id=int(user_id), limit=100)
        partner_messages = await context.bot.get_chat_history(chat_id=int(partner_id), limit=100)
        
        # Delete messages for the user
        for message in user_messages:
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"Error deleting message for user {user_id}: {e}")
        
        # Delete messages for the partner
        for message in partner_messages:
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"Error deleting message for partner {partner_id}: {e}")
    except Exception as e:
        logger.error(f"Error deleting chat messages: {e}")
    
    # Notify partner
    try:
        await context.bot.send_message(
            chat_id=int(partner_id),
            text=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
        )
    except Exception as e:
        logger.error(f"Error notifying partner {partner_id} about chat end: {e}")

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """End the current chat."""
    user_id = str(update.effective_user.id)
    
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # End chat session
        await end_chat_session(user_id, partner_id, context)
    
    # Show main menu
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
        )
    else:
        await update.message.reply_text(
            text=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(MAIN_KEYBOARD)
        )
    
    return START

async def save_avatar(user_id: str, photo_file) -> str:
    """Save avatar to disk and return path."""
    # Create avatars directory if it doesn't exist
    if not os.path.exists("avatars"):
        os.makedirs("avatars")
    
    # Save avatar
    avatar_path = f"avatars/{user_id}.jpg"
    await photo_file.download_to_drive(avatar_path)
    
    return avatar_path

async def main() -> None:
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
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("end", end_chat))
        
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
            # Set webhook
            await application.bot.set_webhook(
                url=f"https://{RAILWAY_STATIC_URL}/webhook",
                allowed_updates=Update.ALL_TYPES
            )
            # Start webhook server
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="webhook"
            )
        else:
            logger.info("Starting polling...")
            await application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
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
    asyncio.run(main()) 