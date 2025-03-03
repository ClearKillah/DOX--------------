import logging
import json
import os
import sys
import time
import asyncio
import datetime
import random
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv
import telegram

import database as db

# Enable logging with more detailed level
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO,  # Changed to INFO for production
    stream=sys.stdout  # Output to stdout for immediate visibility
)
logger = logging.getLogger(__name__)

# Conversation states
START, CHATTING, PROFILE, EDIT_PROFILE = range(4)

# User data file
USER_DATA_FILE = "user_data.json"

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

# User data structure
user_data = load_user_data()
active_chats = {}  # Store active chat pairs
searching_users = {}  # Store users who are currently searching
chat_stats = {}  # Store chat statistics and message counts

# Constants for achievements
ACHIEVEMENTS = {
    "CHAT_MASTER": {"name": "💬 Мастер общения", "description": "Проведено 50 чатов", "requirement": 50},
    "POPULAR": {"name": "⭐ Популярный собеседник", "description": "Получено 20 оценок 5 звезд", "requirement": 20},
    "ACTIVE": {"name": "🔥 Активный пользователь", "description": "3 дня подряд в чате", "requirement": 3},
}

class ChatStats:
    def __init__(self):
        self.start_time = time.time()
        self.message_count = 0
        self.is_typing = False
        self.last_message_time = time.time()

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Constants for buttons
FIND_PARTNER = "🔍 Найти собеседника"
END_CHAT = "🚫 Завершить чат"
MY_PROFILE = "👤 Мой профиль"
HELP = "❓ Помощь"

# Constants for callback data
CALLBACK_RATE = "rate_"
CALLBACK_GENDER = "gender_"
CALLBACK_AGE = "age_"
CALLBACK_INTEREST = "interest_"

# Interests
INTERESTS = [
    "Музыка", "Кино", "Спорт", "Игры", "Книги", 
    "Путешествия", "Технологии", "Искусство", "Наука", "Кулинария"
]

async def update_search_timer(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update the search timer message."""
    job = context.job
    user_id, message_id, start_time = job.data
    
    # Calculate elapsed time
    elapsed_seconds = int(time.time() - start_time)
    minutes = elapsed_seconds // 60
    seconds = elapsed_seconds % 60
    
    # Update message with new timer
    try:
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=f"🔍 *Поиск собеседника...*\n\n⏱ Время поиска: {minutes:02d}:{seconds:02d}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]
            ])
        )
    except Exception as e:
        logger.error(f"Error updating search timer: {e}")
        context.job_queue.remove_job(job.name)

async def send_typing_notification(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send typing notification to simulate real conversation."""
    job = context.job
    chat_id = job.data
    
    try:
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action="typing"
        )
    except Exception as e:
        logger.error(f"Error sending typing notification: {e}")
        context.job_queue.remove_job(job.name)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send welcome message when the command /start is issued."""
    try:
        logger.debug("Start command received from user %s", update.effective_user.id)
        user_id = str(update.effective_user.id)
        
        # Initialize user if not exists
        if user_id not in user_data:
            user_data[user_id] = {
                "gender": None,
                "age": None,
                "interests": [],
                "chat_count": 0,
                "rating": 0,
                "rating_count": 0
            }
            save_user_data(user_data)
            logger.debug("New user initialized: %s", user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Get user stats
        chat_count = user_data[user_id].get("chat_count", 0)
        rating = user_data[user_id].get("rating", 0)
        rating_stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
        
        # Create welcome message
        welcome_text = (
            f"👋 Привет, {update.effective_user.first_name}!\n\n"
            f"Добро пожаловать в Dox: Анонимный Чат!\n\n"
            f"Здесь ты можешь анонимно общаться с другими пользователями. "
            f"Используй кнопки ниже для навигации."
        )
        
        # Add user stats if they have any chats
        if chat_count > 0:
            welcome_text += (
                f"📊 Количество чатов: {chat_count}\n"
            )
            if rating > 0:
                welcome_text += f"📈 Рейтинг: {rating_stars} ({rating:.1f}/5)\n"
            welcome_text += "\n"
        
        welcome_text += "*Выберите действие:*"
        
        logger.debug("Sending welcome message to user %s", user_id)
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        logger.debug("Welcome message sent successfully")
        
        return START
    except Exception as e:
        logger.error("Error in start command: %s", str(e), exc_info=True)
        # Try to send a simple message without formatting or buttons if there was an error
        try:
            await update.message.reply_text(
                "Произошла ошибка при запуске бота. Пожалуйста, попробуйте еще раз или свяжитесь с администратором."
            )
        except Exception:
            logger.error("Failed to send error message", exc_info=True)
        return START

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses."""
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    
    if query.data == "profile":
        return await show_profile(update, context)
    
    elif query.data == "find_chat":
        return await find_chat(update, context)
    
    elif query.data == "cancel_search":
        # Remove user from searching list
        if user_id in searching_users:
            del searching_users[user_id]
        
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ]
        ]
        
        await query.edit_message_text(
            text="❌ *Поиск отменен*\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
    elif query.data == "skip_user":
        # Skip current chat partner and find a new one
        if user_id in active_chats:
            partner_id = active_chats[user_id]
            
            # Notify partner that chat has ended
            if partner_id in active_chats:
                try:
                    await context.bot.send_message(
                        chat_id=int(partner_id),
                        text="❌ *Собеседник покинул чат*\n\nВыберите действие:",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                            [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                        ])
                    )
                    del active_chats[partner_id]
                except Exception as e:
                    logger.error(f"Error notifying partner: {e}")
            
            del active_chats[user_id]
        
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
    
    elif query.data == "end_chat":
        return await end_chat(update, context)
    
    elif query.data.startswith("rate_"):
        # Handle rating
        parts = query.data.split("_")
        if len(parts) == 3:
            partner_id = parts[1]
            rating = int(parts[2])
            
            # Save rating
            if partner_id in user_data:
                ratings = user_data[partner_id].get("ratings", [])
                ratings.append(rating)
                user_data[partner_id]["ratings"] = ratings
                user_data[partner_id]["avg_rating"] = sum(ratings) / len(ratings)
                save_user_data(user_data)
            
            await query.edit_message_text(
                text=f"✅ *Спасибо за оценку!*\n\nВы поставили {rating} {'⭐' * rating}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                    [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                ])
            )
        else:
            await query.edit_message_text(
                text="❌ *Ошибка при оценке собеседника*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                    [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                ])
            )
        return START
    
    elif query.data == "skip_rating":
        await query.edit_message_text(
            text="✅ *Оценка пропущена*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
            ])
        )
        return START
    
    elif query.data == "back_to_start":
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ]
        ]
        
        await query.edit_message_text(
            text="*Добро пожаловать в Dox: Анонимный Чат* 🎭\n\n"
                 "Здесь вы можете анонимно общаться с другими пользователями.\n\n"
                 "*Выберите действие:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
    # Handle interest selection
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
        
        # Show updated profile
        return await show_profile(update, context)
    
    # Handle edit profile
    elif query.data == "edit_profile":
        keyboard = [
            [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
            [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
            [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
        ]
        
        await query.edit_message_text(
            text="*Редактирование профиля*\n\nВыберите, что хотите изменить:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data == "edit_age":
        await query.edit_message_text(
            text="*Введите ваш возраст:*\n\n"
                 "Отправьте число от 13 до 100.",
            parse_mode="Markdown"
        )
        context.user_data["edit_field"] = "age"
        return EDIT_PROFILE
    
    elif query.data == "upload_avatar":
        await query.edit_message_text(
            text="*Загрузка аватара*\n\n"
                 "Отправьте фотографию, которую хотите использовать как аватар.\n\n"
                 "Для отмены нажмите /cancel",
            parse_mode="Markdown"
        )
        context.user_data["uploading_avatar"] = True
        return PROFILE
    
    return START

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show user profile."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    user_info = user_data.get(user_id, {})
    gender = "👨 Мужской" if user_info.get("gender") == "male" else "👩 Женский" if user_info.get("gender") == "female" else "❓ Не указан"
    age = user_info.get("age", "❓ Не указан")
    
    # Get chat statistics
    chat_count = user_info.get("chat_count", 0)
    total_messages = user_info.get("total_messages", 0)
    avg_chat_duration = user_info.get("avg_chat_duration", 0)
    achievements = user_info.get("achievements", [])
    
    # Calculate average chat duration in minutes
    avg_duration_min = int(avg_chat_duration / 60) if avg_chat_duration else 0
    
    # Format interests
    interests = user_info.get("interests", [])
    interests_text = ""
    if "flirt" in interests:
        interests_text += "• 💘 Флирт\n"
    if "chat" in interests:
        interests_text += "• 💬 Общение\n"
    if not interests_text:
        interests_text = "❓ Не указаны"
    
    # Calculate rating and trend
    rating = user_info.get("rating", 0)
    rating_count = user_info.get("rating_count", 0)
    prev_rating = user_info.get("prev_rating", 0)
    rating_trend = "📈" if rating > prev_rating else "📉" if rating < prev_rating else "➡️"
    rating_stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
    
    # Format achievements
    achievements_text = ""
    if achievements:
        for achievement_id in achievements:
            achievement = ACHIEVEMENTS.get(achievement_id)
            if achievement:
                achievements_text += f"• {achievement['name']}\n"
    else:
        achievements_text = "Пока нет достижений"
    
    # Create profile completion percentage
    completed_fields = 0
    total_fields = 3
    if user_info.get("gender"): completed_fields += 1
    if user_info.get("age"): completed_fields += 1
    if interests: completed_fields += 1
    completion_percentage = int(completed_fields / total_fields * 100)
    completion_bar = "▓" * (completion_percentage // 10) + "░" * (10 - completion_percentage // 10)
    
    # Build profile text
    profile_text = (
        f"👤 *Ваш профиль:*\n\n"
        f"*Заполнено:* {completion_percentage}% {completion_bar}\n\n"
        f"*Основная информация:*\n"
        f"• Пол: {gender}\n"
        f"• Возраст: {age}\n"
        f"*Интересы:*\n{interests_text}\n\n"
        f"*📊 Статистика:*\n"
        f"• Всего чатов: {chat_count}\n"
        f"• Сообщений отправлено: {total_messages}\n"
        f"• Средняя длительность чата: {avg_duration_min} мин.\n"
        f"• Рейтинг: {rating_stars} {rating_trend} ({rating:.1f}/5)\n"
        f"  На основе {rating_count} оценок\n\n"
        f"*🏆 Достижения:*\n{achievements_text}"
    )
    
    # Create keyboard
    keyboard = [
        [InlineKeyboardButton("📸 Загрузить аватар", callback_data="upload_avatar")],
        [InlineKeyboardButton("✏️ Редактировать профиль", callback_data="edit_profile")],
        [InlineKeyboardButton("🔄 Изменить интересы", callback_data="interest_edit")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
    ]
    
    # Send avatar if exists
    avatar_path = f"avatars/{user_id}.jpg"
    if os.path.exists(avatar_path):
        try:
            with open(avatar_path, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo,
                    caption=profile_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            return PROFILE
        except Exception as e:
            logger.error(f"Error sending avatar: {e}")
    
    # Send profile without avatar
    await query.edit_message_text(
        text=profile_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return PROFILE

async def handle_avatar_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle avatar photo upload."""
    user_id = str(update.effective_user.id)
    
    if update.message and update.message.photo:
        photo_file = await update.message.photo[-1].get_file()
        avatar_path = await save_avatar(user_id, photo_file)
        
        if avatar_path:
            await update.message.reply_text(
                "✅ Аватар успешно обновлен!\n\nВозвращаемся к профилю...",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👤 Показать профиль", callback_data="profile")
                ]])
            )
        else:
            await update.message.reply_text(
                "❌ Произошла ошибка при сохранении аватара. Попробуйте позже."
            )
    else:
        await update.message.reply_text(
            "📸 Отправьте фотографию, которую хотите использовать как аватар.\n"
            "Или нажмите /cancel для отмены."
        )
    
    return PROFILE

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
                    text="❌ *Собеседник покинул чат*\n\nВыберите действие:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                        [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                    ])
                )
                del active_chats[partner_id]
            except Exception as e:
                logger.error(f"Error notifying partner: {e}")
        
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
    """Continuously search for a chat partner in the background."""
    try:
        if user_id not in searching_users:
            return
        
        search_info = searching_users[user_id]
        start_time = search_info["start_time"]
        chat_id = search_info["chat_id"]
        message_id = search_info["message_id"]
        
        # Keep searching until a partner is found or search is cancelled
        while user_id in searching_users:
            # Update search time
            current_time = time.time()
            search_time = current_time - start_time
            minutes = int(search_time) // 60
            seconds = int(search_time) % 60
            time_text = f"⏱ Время поиска: {minutes:02d}:{seconds:02d}"
            
            # Update search message every 5 seconds
            if seconds % 5 == 0:
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"🔍 *Поиск собеседника...*\n\n{time_text}",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"Error updating search message: {e}")
            
            # Find available users - ONLY those who are also searching
            available_users = []
            for uid, search_data in searching_users.items():
                # Skip the current user and users already in chat
                if uid != user_id and uid not in active_chats:
                    available_users.append(uid)
            
            if available_users:
                # Found a partner!
                partner_id = random.choice(available_users)
                logger.debug(f"Matched user {user_id} with partner {partner_id}")
                
                # Get partner's search info before removing from searching
                partner_search_info = searching_users.get(partner_id, {})
                partner_chat_id = partner_search_info.get("chat_id")
                partner_message_id = partner_search_info.get("message_id")
                
                # Remove both users from searching
                if user_id in searching_users:
                    del searching_users[user_id]
                if partner_id in searching_users:
                    del searching_users[partner_id]
                
                # Create chat connection
                active_chats[user_id] = partner_id
                active_chats[partner_id] = user_id
                
                # Initialize chat stats
                chat_stats[user_id] = ChatStats()
                chat_stats[partner_id] = ChatStats()
                
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
                        pinned_message = await context.bot.pin_chat_message(
                            chat_id=chat_id,
                            message_id=message_id,
                            disable_notification=True
                        )
                    except Exception as e:
                        logger.error(f"Error pinning message for user {user_id}: {e}")
                    
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
                    
                except Exception as e:
                    logger.error(f"Error notifying users about match: {e}")
                    # Clean up if notification fails
                    if user_id in active_chats:
                        del active_chats[user_id]
                    if partner_id in active_chats:
                        del active_chats[partner_id]
                    continue
                
                break
            
            # Wait before checking again
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Error in continuous_search: {e}", exc_info=True)
        # Clean up if there was an error
        if user_id in searching_users:
            del searching_users[user_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle messages during chat."""
    user_id = str(update.effective_user.id)
    
    # Check if editing profile
    if context.user_data.get("edit_field") == "age":
        try:
            age = int(update.message.text)
            if 13 <= age <= 100:  # Basic age validation
                user_data[user_id]["age"] = age
                save_user_data(user_data)
                
                keyboard = [
                    [InlineKeyboardButton("Флирт", callback_data="interest_flirt")],
                    [InlineKeyboardButton("Общение", callback_data="interest_chat")],
                    [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
                ]
                
                await update.message.reply_text(
                    text="✅ *Возраст успешно обновлен!*\n\n*Выберите ваши интересы:*",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                del context.user_data["edit_field"]
                return EDIT_PROFILE
            else:
                await update.message.reply_text(
                    "⚠️ Пожалуйста, введите корректный возраст (от 13 до 100)."
                )
                return EDIT_PROFILE
        except ValueError:
            await update.message.reply_text(
                "⚠️ Пожалуйста, введите корректный возраст в виде числа."
            )
            return EDIT_PROFILE
    
    # Check if uploading avatar
    if context.user_data.get("uploading_avatar"):
        if update.message.photo:
            return await handle_avatar_upload(update, context)
        elif update.message.text == "/cancel":
            del context.user_data["uploading_avatar"]
            await update.message.reply_text(
                "❌ Загрузка аватара отменена.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👤 Вернуться к профилю", callback_data="profile")
                ]])
            )
            return PROFILE
        else:
            await update.message.reply_text(
                "📸 Пожалуйста, отправьте фотографию или нажмите /cancel для отмены."
            )
            return PROFILE
    
    # Check if in active chat
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        try:
            # Initialize chat stats if not exists
            if user_id not in chat_stats:
                chat_stats[user_id] = ChatStats()
            
            # Update message count
            chat_stats[user_id].message_count += 1
            user_data[user_id]["total_messages"] = user_data[user_id].get("total_messages", 0) + 1
            
            # Check if message is a command
            if update.message.text and update.message.text.startswith('/'):
                if update.message.text.lower() == '/end':
                    return await end_chat(update, context)
                elif update.message.text.lower() == '/help':
                    await update.message.reply_text(
                        "*Доступные команды:*\n"
                        "/end - Завершить текущий чат\n"
                        "/help - Показать эту справку\n"
                        "/stats - Показать статистику чата",
                        parse_mode="Markdown"
                    )
                    return CHATTING
                elif update.message.text.lower() == '/stats':
                    stats = chat_stats.get(user_id)
                    if stats:
                        duration = int((time.time() - stats.start_time) / 60)
                        await update.message.reply_text(
                            f"📊 *Статистика текущего чата:*\n\n"
                            f"⏱ Длительность: {duration} мин.\n"
                            f"💬 Сообщений отправлено: {stats.message_count}",
                            parse_mode="Markdown"
                        )
                    return CHATTING
                else:
                    await update.message.reply_text(
                        "❓ Неизвестная команда. Используйте /help для просмотра доступных команд."
                    )
                    return CHATTING
            
            # Send typing notification
            chat_stats[user_id].is_typing = True
            await context.bot.send_chat_action(
                chat_id=int(partner_id),
                action="typing"
            )
            
            # Handle different types of messages
            if update.message.text:
                # For text messages, use regular send_message
                await context.bot.send_message(
                    chat_id=int(partner_id),
                    text=update.message.text
                )
            elif update.message.voice:
                # For voice messages, download and send directly
                try:
                    # First, notify the partner that voice is being processed
                    await context.bot.send_chat_action(
                        chat_id=int(partner_id),
                        action="record_voice"
                    )
                    
                    # Log voice message details for debugging
                    voice_file_id = update.message.voice.file_id
                    voice_duration = update.message.voice.duration
                    logger.info(f"Processing voice message from {user_id} to {partner_id}: file_id={voice_file_id}, duration={voice_duration}s")
                    
                    # Get the voice file
                    voice_file = await context.bot.get_file(voice_file_id)
                    
                    # Download the voice file
                    voice_bytes = await voice_file.download_as_bytearray()
                    
                    # Send as a new voice message
                    sent = await context.bot.send_voice(
                        chat_id=int(partner_id),
                        voice=voice_bytes,
                        duration=voice_duration,
                        caption=update.message.caption if update.message.caption else None
                    )
                    
                    if sent:
                        logger.info(f"Successfully sent voice message from {user_id} to {partner_id}")
                    else:
                        logger.warning(f"Voice message send returned None, but no exception was raised")
                        
                except telegram.error.BadRequest as e:
                    logger.error(f"BadRequest error sending voice message: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить голосовое сообщение из-за ошибки Telegram. Попробуйте еще раз."
                    )
                except telegram.error.Unauthorized as e:
                    logger.error(f"Unauthorized error sending voice message: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить голосовое сообщение. Возможно, собеседник заблокировал бота."
                    )
                    # End the chat since the partner is unavailable
                    return await end_chat(update, context)
                except Exception as e:
                    logger.error(f"Error sending voice message: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить голосовое сообщение. Попробуйте еще раз или используйте текстовые сообщения."
                    )
            elif update.message.video_note:
                # For video notes (circles), download and send directly
                try:
                    # First, notify the partner that video note is being processed
                    await context.bot.send_chat_action(
                        chat_id=int(partner_id),
                        action="record_video_note"
                    )
                    
                    # Get the video note file
                    video_note_file_id = update.message.video_note.file_id
                    video_note_length = update.message.video_note.length
                    video_note_duration = update.message.video_note.duration
                    
                    logger.info(f"Processing video note from {user_id} to {partner_id}: file_id={video_note_file_id}")
                    
                    # Get the file
                    video_note_file = await context.bot.get_file(video_note_file_id)
                    
                    # Download the file
                    video_note_bytes = await video_note_file.download_as_bytearray()
                    
                    # Send as a new video note
                    sent = await context.bot.send_video_note(
                        chat_id=int(partner_id),
                        video_note=video_note_bytes,
                        length=video_note_length,
                        duration=video_note_duration
                    )
                    
                    if sent:
                        logger.info(f"Successfully sent video note from {user_id} to {partner_id}")
                    
                except Exception as e:
                    logger.error(f"Error sending video note: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить видео-кружок. Попробуйте еще раз."
                    )
            elif update.message.video:
                # For videos, download and send directly
                try:
                    # Get video details
                    video_file_id = update.message.video.file_id
                    video_duration = update.message.video.duration
                    video_width = update.message.video.width
                    video_height = update.message.video.height
                    caption = update.message.caption
                    
                    logger.info(f"Processing video from {user_id} to {partner_id}: file_id={video_file_id}")
                    
                    # Get the file
                    video_file = await context.bot.get_file(video_file_id)
                    
                    # Download the file
                    video_bytes = await video_file.download_as_bytearray()
                    
                    # Send as a new video
                    sent = await context.bot.send_video(
                        chat_id=int(partner_id),
                        video=video_bytes,
                        duration=video_duration,
                        width=video_width,
                        height=video_height,
                        caption=caption
                    )
                    
                    if sent:
                        logger.info(f"Successfully sent video from {user_id} to {partner_id}")
                    
                except Exception as e:
                    logger.error(f"Error sending video: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить видео. Попробуйте еще раз."
                    )
            elif update.message.photo:
                # For photos, download and send directly
                try:
                    # Get the largest photo (best quality)
                    photo = update.message.photo[-1]
                    photo_file_id = photo.file_id
                    caption = update.message.caption
                    
                    logger.info(f"Processing photo from {user_id} to {partner_id}: file_id={photo_file_id}")
                    
                    # Get the file
                    photo_file = await context.bot.get_file(photo_file_id)
                    
                    # Download the file
                    photo_bytes = await photo_file.download_as_bytearray()
                    
                    # Send as a new photo
                    sent = await context.bot.send_photo(
                        chat_id=int(partner_id),
                        photo=photo_bytes,
                        caption=caption
                    )
                    
                    if sent:
                        logger.info(f"Successfully sent photo from {user_id} to {partner_id}")
                    
                except Exception as e:
                    logger.error(f"Error sending photo: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить фото. Попробуйте еще раз."
                    )
            elif update.message.video:
                # For videos, use copy_message
                try:
                    await context.bot.copy_message(
                        chat_id=int(partner_id),
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    logger.debug(f"Copied video from {user_id} to {partner_id}")
                except Exception as e:
                    logger.error(f"Error copying video: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить видео. Попробуйте еще раз."
                    )
            elif update.message.sticker or update.message.animation or update.message.document or update.message.audio:
                # For other media types, use copy_message
                try:
                    await context.bot.copy_message(
                        chat_id=int(partner_id),
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    logger.debug(f"Copied media from {user_id} to {partner_id}")
                except Exception as e:
                    logger.error(f"Error copying media: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить медиа-файл. Попробуйте еще раз."
                    )
            else:
                # Unsupported message type
                await update.message.reply_text(
                    "⚠️ Этот тип сообщения не поддерживается."
                )
            
            # Update typing status
            chat_stats[user_id].is_typing = False
            chat_stats[user_id].last_message_time = time.time()
            
            return CHATTING
            
        except Exception as e:
            logger.error(f"Error forwarding message: {e}", exc_info=True)
            
            # If we can't message the partner, end the chat
            if user_id in active_chats:
                del active_chats[user_id]
            if partner_id in active_chats:
                del active_chats[partner_id]
            
            keyboard = [
                [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
                [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
            ]
            
            await update.message.reply_text(
                text="❌ *Ошибка соединения с собеседником*\n\nЧат завершен.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return START
    else:
        # Not in chat, show main menu
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ]
        ]
        
        # Check if message is a command
        if update.message.text and update.message.text.startswith('/'):
            if update.message.text.lower() == '/start':
                await update.message.reply_text(
                    f"*Добро пожаловать в Dox: Анонимный Чат* 🎭\n\n"
                    f"Здесь вы можете анонимно общаться с другими пользователями.\n\n"
                    f"*Выберите действие:*",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return START
            elif update.message.text.lower() == '/help':
                await update.message.reply_text(
                    "*Доступные команды:*\n"
                    "/start - Начать использование бота\n"
                    "/help - Показать эту справку",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return START
        
        await update.message.reply_text(
            text="Выберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return START

async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """End the current chat."""
    try:
        user_id = str(update.effective_user.id)
        
        # Check if user is in active chat
        if user_id not in active_chats:
            keyboard = [
                [InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")],
                [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
            ]
            
            await update.effective_message.reply_text(
                text="❌ *У вас нет активного чата*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return START
        
        partner_id = active_chats[user_id]
        
        # Update chat statistics
        if user_id in chat_stats:
            stats = chat_stats[user_id]
            chat_duration = time.time() - stats.start_time
            
            # Update user data with chat statistics
            if user_id in user_data:
                user_data[user_id]["chat_count"] = user_data[user_id].get("chat_count", 0) + 1
                user_data[user_id]["total_chat_duration"] = user_data[user_id].get("total_chat_duration", 0) + chat_duration
                
                # Calculate average chat duration
                chat_count = user_data[user_id]["chat_count"]
                total_duration = user_data[user_id]["total_chat_duration"]
                user_data[user_id]["avg_chat_duration"] = total_duration / chat_count
                
                # Update active days
                today = datetime.now().strftime("%Y-%m-%d")
                active_days = user_data[user_id].get("active_days", [])
                if today not in active_days:
                    active_days.append(today)
                    # Keep only last 30 days
                    if len(active_days) > 30:
                        active_days = active_days[-30:]
                user_data[user_id]["active_days"] = active_days
                
                save_user_data(user_data)
            
            # Delete chat stats
            del chat_stats[user_id]
        
        # Unpin messages
        try:
            if "pinned_message_id" in context.user_data:
                await context.bot.unpin_chat_message(
                    chat_id=update.effective_chat.id,
                    message_id=context.user_data["pinned_message_id"]
                )
                del context.user_data["pinned_message_id"]
        except Exception as e:
            logger.error(f"Error unpinning message: {e}")
        
        # Clean up chat connection
        del active_chats[user_id]
        
        # Delete all messages in the chat (for the current user)
        try:
            # Send a message that will be used to clear the chat
            clear_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🧹 *Очистка чата...*",
                parse_mode="Markdown"
            )
            
            # Delete all messages up to this one
            for i in range(clear_message.message_id - 1, 0, -1):
                try:
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=i
                    )
                except Exception:
                    # Ignore errors for messages that can't be deleted
                    pass
            
            # Delete the clear message itself
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=clear_message.message_id
            )
        except Exception as e:
            logger.error(f"Error clearing chat messages: {e}")
        
        # Notify the user that chat has ended
        keyboard = [
            [InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")],
            [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
        ]
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ *Чат завершен*\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        # Notify partner that chat has ended and update their stats
        if partner_id in active_chats:
            # Update partner's chat statistics
            if partner_id in chat_stats:
                partner_stats = chat_stats[partner_id]
                partner_chat_duration = time.time() - partner_stats.start_time
                
                # Update partner data with chat statistics
                if partner_id in user_data:
                    user_data[partner_id]["chat_count"] = user_data[partner_id].get("chat_count", 0) + 1
                    user_data[partner_id]["total_chat_duration"] = user_data[partner_id].get("total_chat_duration", 0) + partner_chat_duration
                    
                    # Calculate average chat duration
                    partner_chat_count = user_data[partner_id]["chat_count"]
                    partner_total_duration = user_data[partner_id]["total_chat_duration"]
                    user_data[partner_id]["avg_chat_duration"] = partner_total_duration / partner_chat_count
                    
                    # Update active days
                    today = datetime.now().strftime("%Y-%m-%d")
                    partner_active_days = user_data[partner_id].get("active_days", [])
                    if today not in partner_active_days:
                        partner_active_days.append(today)
                        # Keep only last 30 days
                        if len(partner_active_days) > 30:
                            partner_active_days = partner_active_days[-30:]
                    user_data[partner_id]["active_days"] = partner_active_days
                    
                    save_user_data(user_data)
                
                # Delete partner's chat stats
                del chat_stats[partner_id]
            
            # Unpin messages for partner
            try:
                if f"partner_{partner_id}_pinned_message" in context.user_data:
                    await context.bot.unpin_chat_message(
                        chat_id=int(partner_id),
                        message_id=context.user_data[f"partner_{partner_id}_pinned_message"]
                    )
                    del context.user_data[f"partner_{partner_id}_pinned_message"]
            except Exception as e:
                logger.error(f"Error unpinning partner's message: {e}")
            
            # Delete all messages in the chat (for the partner)
            try:
                # Send a message that will be used to clear the chat
                partner_clear_message = await context.bot.send_message(
                    chat_id=int(partner_id),
                    text="🧹 *Очистка чата...*",
                    parse_mode="Markdown"
                )
                
                # Delete all messages up to this one
                for i in range(partner_clear_message.message_id - 1, 0, -1):
                    try:
                        await context.bot.delete_message(
                            chat_id=int(partner_id),
                            message_id=i
                        )
                    except Exception:
                        # Ignore errors for messages that can't be deleted
                        pass
                
                # Delete the clear message itself
                await context.bot.delete_message(
                    chat_id=int(partner_id),
                    message_id=partner_clear_message.message_id
                )
            except Exception as e:
                logger.error(f"Error clearing partner's chat messages: {e}")
            
            # Notify partner that chat has ended
            await context.bot.send_message(
                chat_id=int(partner_id),
                text="❌ *Собеседник завершил чат*\n\nВыберите действие:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            
            # Clean up partner's chat connection
            del active_chats[partner_id]
        
        # Check for achievements
        await update_achievements(user_id, context)
        if partner_id in user_data:
            await update_achievements(partner_id, context)
        
        # Ask user to rate the partner
        rating_keyboard = []
        for i in range(1, 6):
            stars = "⭐" * i
            rating_keyboard.append([InlineKeyboardButton(stars, callback_data=f"rate_{partner_id}_{i}")])
        
        rating_keyboard.append([InlineKeyboardButton("Пропустить", callback_data="skip_rating")])
        
        # Include chat statistics in rating request
        chat_duration_minutes = int(chat_duration / 60)
        message_count = user_data[user_id].get("total_messages", 0) - user_data[user_id].get("prev_total_messages", 0)
        user_data[user_id]["prev_total_messages"] = user_data[user_id].get("total_messages", 0)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"📊 *Статистика чата:*\n"
                 f"⏱ Длительность: {chat_duration_minutes} мин.\n"
                 f"💬 Сообщений: {message_count}\n\n"
                 f"Оцените вашего собеседника:",
            reply_markup=InlineKeyboardMarkup(rating_keyboard),
            parse_mode="Markdown"
        )
        
        return START
        
    except Exception as e:
        logger.error(f"Error in end_chat: {e}", exc_info=True)
        return START

async def save_avatar(user_id: str, photo_file) -> str:
    """Save user's avatar photo."""
    try:
        os.makedirs("avatars", exist_ok=True)
        file_path = f"avatars/{user_id}.jpg"
        await photo_file.download_to_drive(file_path)
        return file_path
    except Exception as e:
        logger.error(f"Error saving avatar: {e}")
        return None

async def update_achievements(user_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Update user achievements based on their stats."""
    user = user_data.get(user_id, {})
    achievements = user.get("achievements", [])
    chat_count = user.get("chat_count", 0)
    rating_5_count = user.get("rating_5_count", 0)
    active_days = user.get("active_days", 0)
    
    new_achievements = []
    
    if chat_count >= ACHIEVEMENTS["CHAT_MASTER"]["requirement"] and "CHAT_MASTER" not in achievements:
        new_achievements.append(ACHIEVEMENTS["CHAT_MASTER"])
        achievements.append("CHAT_MASTER")
    
    if rating_5_count >= ACHIEVEMENTS["POPULAR"]["requirement"] and "POPULAR" not in achievements:
        new_achievements.append(ACHIEVEMENTS["POPULAR"])
        achievements.append("POPULAR")
    
    if active_days >= ACHIEVEMENTS["ACTIVE"]["requirement"] and "ACTIVE" not in achievements:
        new_achievements.append(ACHIEVEMENTS["ACTIVE"])
        achievements.append("ACTIVE")
    
    if new_achievements:
        user_data[user_id]["achievements"] = achievements
        save_user_data(user_data)
        
        # Notify user about new achievements
        achievement_text = "*🏆 Новые достижения!*\n\n"
        for achievement in new_achievements:
            achievement_text += f"{achievement['name']} - {achievement['description']}\n"
        
        try:
            await context.bot.send_message(
                chat_id=int(user_id),
                text=achievement_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error sending achievement notification: {e}")

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
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                CHATTING: [
                    CallbackQueryHandler(button_handler),
                    CommandHandler("end", end_chat),
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                PROFILE: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
                ],
                EDIT_PROFILE: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
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