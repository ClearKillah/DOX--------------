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
    
    elif query.data == "search_no_filters":
        logger.debug(f"User {user_id} is looking for a chat partner without filters")
        
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
    
    elif query.data == "cancel_search":
        # Remove user from searching list
        if user_id in searching_users:
            del searching_users[user_id]
        
        # Return to main menu
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="*Поиск отменен* ❌\n\n*Выберите действие:*",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return START
    
    elif query.data == "back_to_start":
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="*Dox: Анонимный Чат* 🎭\n\n*Выберите действие:*",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return START
    
    elif query.data == "help":
        help_text = (
            "🤖 *Dox: Анонимный Чат* - Помощь\n\n"
            "*Основные команды:*\n"
            "• /start - Запустить бота\n"
            "• /help - Показать это сообщение\n\n"
            "*Кнопки:*\n"
            "• 🔍 Найти собеседника - Начать поиск партнера для чата\n"
            "• 🚫 Завершить чат - Закончить текущий разговор\n"
            "• 👤 Мой профиль - Просмотр и редактирование профиля\n"
            "• ❓ Помощь - Показать это сообщение\n\n"
            "*Как это работает:*\n"
            "1. Заполните свой профиль (пол, возраст, интересы)\n"
            "2. Нажмите 'Найти собеседника'\n"
            "3. Бот подберет вам партнера для анонимного общения\n"
            "4. После завершения чата вы можете оценить собеседника\n\n"
            "*Правила:*\n"
            "• Будьте вежливы и уважительны\n"
            "• Не отправляйте спам или оскорбительный контент\n"
            "• Не делитесь личной информацией\n\n"
            "Приятного общения! 😊"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]]
        
        await query.edit_message_text(
            text=help_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
    elif query.data == "skip_user":
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
        
        # Find new chat
        return await find_chat(update, context)
    
    elif query.data == "end_chat":
        # End current chat
        if user_id in active_chats:
            partner_id = active_chats[user_id]
            
            # Store last partner for rating
            context.user_data["last_partner"] = partner_id
            
            # Notify partner that chat has ended
            if partner_id in active_chats:
                try:
                    await context.bot.send_message(
                        chat_id=int(partner_id),
                        text="❌ *Собеседник завершил чат*\n\nВыберите действие:",
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
            
            # Ask to rate the partner
            keyboard = [
                [
                    InlineKeyboardButton("1⭐", callback_data="rate_1"),
                    InlineKeyboardButton("2⭐", callback_data="rate_2"),
                    InlineKeyboardButton("3⭐", callback_data="rate_3"),
                    InlineKeyboardButton("4⭐", callback_data="rate_4"),
                    InlineKeyboardButton("5⭐", callback_data="rate_5")
                ]
            ]
            
            await query.edit_message_text(
                text="*Чат завершен*\n\nОцените вашего собеседника:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return START
        
        # If not in chat, return to main menu
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ]
        ]
        
        await query.edit_message_text(
            text="У вас нет активного чата.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return START
    
    elif query.data == "edit_profile":
        keyboard = [
            [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
            [InlineKeyboardButton("👩 Женский", callback_data="gender_female")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile")]
        ]
        await query.edit_message_text(
            text="*Выберите ваш пол:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data == "interest_edit":
        interests = user_data[user_id].get("interests", [])
        interests_text = "✅ Флирт" if "flirt" in interests else "❌ Флирт"
        interests_text += "\n✅ Общение" if "chat" in interests else "\n❌ Общение"
        
        keyboard = [
            [InlineKeyboardButton("💘 Флирт " + ("✅" if "flirt" in interests else "❌"), callback_data="interest_flirt")],
            [InlineKeyboardButton("💬 Общение " + ("✅" if "chat" in interests else "❌"), callback_data="interest_chat")],
            [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
        ]
        
        await query.edit_message_text(
            text=f"*Ваши интересы:*\n\nВыберите интересы, которые хотите добавить или удалить:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data.startswith("gender_"):
        gender = query.data.split("_")[1]
        user_data[user_id]["gender"] = gender
        save_user_data(user_data)
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="profile")]
        ]
        await query.edit_message_text(
            text=f"*Укажите ваш возраст:*\n\nОтправьте сообщение с вашим возрастом.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        context.user_data["edit_field"] = "age"
        return EDIT_PROFILE
    
    elif query.data.startswith("interest_"):
        interest = query.data.split("_")[1]
        interests = user_data[user_id].get("interests", [])
        
        if interest in interests:
            interests.remove(interest)
        else:
            interests.append(interest)
        
        user_data[user_id]["interests"] = interests
        save_user_data(user_data)
        
        # Show updated interests
        keyboard = [
            [InlineKeyboardButton("💘 Флирт " + ("✅" if "flirt" in interests else "❌"), callback_data="interest_flirt")],
            [InlineKeyboardButton("💬 Общение " + ("✅" if "chat" in interests else "❌"), callback_data="interest_chat")],
            [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
        ]
        
        # Calculate profile completion
        completed_fields = 0
        total_fields = 3  # gender, age, interests
        
        if user_data[user_id].get("gender"):
            completed_fields += 1
        if user_data[user_id].get("age"):
            completed_fields += 1
        if interests:
            completed_fields += 1
        
        completion_percentage = int(completed_fields / total_fields * 100)
        completion_bar = "▓" * (completion_percentage // 10) + "░" * (10 - completion_percentage // 10)
        
        await query.edit_message_text(
            text=f"*Ваши интересы обновлены!*\n\n"
                 f"Текущие интересы:\n"
                 f"• 💘 Флирт: {('✅' if 'flirt' in interests else '❌')}\n"
                 f"• 💬 Общение: {('✅' if 'chat' in interests else '❌')}\n\n"
                 f"Заполнено {completion_percentage}% профиля.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return EDIT_PROFILE
    
    elif query.data == "rate_1" or query.data == "rate_2" or query.data == "rate_3" or query.data == "rate_4" or query.data == "rate_5":
        rating = int(query.data.split("_")[1])
        partner_id = context.user_data.get("last_partner")
        
        if partner_id:
            # Update partner's rating
            if partner_id in user_data:
                current_rating = user_data[partner_id].get("rating", 0)
                rating_count = user_data[partner_id].get("rating_count", 0)
                
                # Calculate new average rating
                new_rating = (current_rating * rating_count + rating) / (rating_count + 1)
                user_data[partner_id]["rating"] = new_rating
                user_data[partner_id]["rating_count"] = rating_count + 1
                save_user_data(user_data)
        
        # Show rating stars
        rating_stars = "⭐" * rating + "☆" * (5 - rating)
        
        keyboard = [
            [
                InlineKeyboardButton("🔍 Найти нового собеседника", callback_data="find_chat")
            ],
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_start")
            ]
        ]
        
        await query.edit_message_text(
            text=f"*Спасибо за оценку!* {rating_stars}\n\n"
                 f"Вы поставили оценку {rating}/5\n\n"
                 f"Что хотите сделать дальше?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
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
    """Find a chat partner."""
    try:
        if update.callback_query:
            query = update.callback_query
            user_id = str(query.from_user.id)
            
            # If this is initial search request, show filter options
            if query.data == "find_chat":
                keyboard = [
                    [InlineKeyboardButton("🔍 Поиск без фильтров", callback_data="search_no_filters")],
                    [InlineKeyboardButton("⚙️ Настроить фильтры", callback_data="setup_filters")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
                ]
                
                await query.edit_message_text(
                    text="*Поиск собеседника*\n\n"
                         "Выберите вариант поиска:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return START
            
            # Handle filter setup
            elif query.data == "setup_filters":
                keyboard = [
                    [InlineKeyboardButton("👨 Мужской", callback_data="filter_gender_male"),
                     InlineKeyboardButton("👩 Женский", callback_data="filter_gender_female")],
                    [InlineKeyboardButton("🎯 Возраст", callback_data="filter_age")],
                    [InlineKeyboardButton("💭 Интересы", callback_data="filter_interests")],
                    [InlineKeyboardButton("✅ Начать поиск", callback_data="search_with_filters")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="find_chat")]
                ]
                
                await query.edit_message_text(
                    text="*Настройка фильтров поиска*\n\n"
                         "Выберите параметры для поиска:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return START
        
        return START
    except Exception as e:
        logger.error(f"Error in find_chat: {e}", exc_info=True)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text="❌ *Произошла ошибка при поиске собеседника*\n\nПожалуйста, попробуйте еще раз.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="find_chat")],
                        [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                    ])
                )
            except Exception:
                pass
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
            
            # Find available users
            available_users = []
            for uid in user_data.keys():
                if (uid != user_id and 
                    uid not in active_chats and 
                    uid not in searching_users):
                    available_users.append(uid)
            
            if available_users:
                # Found a partner!
                partner_id = random.choice(available_users)
                logger.debug(f"Matched user {user_id} with partner {partner_id}")
                
                # Remove user from searching
                if user_id in searching_users:
                    del searching_users[user_id]
                
                # Create chat connection
                active_chats[user_id] = partner_id
                active_chats[partner_id] = user_id
                
                # Initialize chat stats
                chat_stats[user_id] = ChatStats()
                chat_stats[partner_id] = ChatStats()
                
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
                    pinned_message = await context.bot.pin_chat_message(
                        chat_id=chat_id,
                        message_id=message_id,
                        disable_notification=True
                    )
                    context.user_data["pinned_message_id"] = message_id
                    
                    # Send message to partner
                    user_info = user_data.get(user_id, {})
                    user_text = f"*Информация о собеседнике:*\n\n"
                    if user_info.get("gender"):
                        gender = "👨 Мужской" if user_info.get("gender") == "male" else "👩 Женский"
                        user_text += f"*Пол:* {gender}\n"
                    if user_info.get("age"):
                        user_text += f"*Возраст:* {user_info.get('age')}\n"
                    
                    interests = user_info.get("interests", [])
                    if interests:
                        interests_text = ""
                        if "flirt" in interests:
                            interests_text += "• 💘 Флирт\n"
                        if "chat" in interests:
                            interests_text += "• 💬 Общение\n"
                        user_text += f"*Интересы:*\n{interests_text}"
                    
                    partner_message = await context.bot.send_message(
                        chat_id=int(partner_id),
                        text=f"✅ *Собеседник найден!*\n\n{user_text}\n\n*Начните общение прямо сейчас!*",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    # Pin message for partner
                    await context.bot.pin_chat_message(
                        chat_id=int(partner_id),
                        message_id=partner_message.message_id,
                        disable_notification=True
                    )
                    context.user_data[f"partner_{partner_id}_pinned_message"] = partner_message.message_id
                    
                except Exception as e:
                    logger.error(f"Error notifying users about match: {e}")
                    # Clean up if notification fails
                    if user_id in active_chats:
                        del active_chats[user_id]
                    if partner_id in active_chats:
                        del active_chats[partner_id]
                    if user_id in searching_users:
                        del searching_users[user_id]
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
                await context.bot.send_message(
                    chat_id=int(partner_id),
                    text=update.message.text
                )
            elif update.message.voice:
                voice = await update.message.voice.get_file()
                await context.bot.send_voice(
                    chat_id=int(partner_id),
                    voice=voice.file_id
                )
            elif update.message.video_note:
                video_note = await update.message.video_note.get_file()
                await context.bot.send_video_note(
                    chat_id=int(partner_id),
                    video_note=video_note.file_id
                )
            
            # Update typing status
            chat_stats[user_id].is_typing = False
            chat_stats[user_id].last_message_time = time.time()
            
            return CHATTING
            
        except Exception as e:
            logger.error(f"Error forwarding message: {e}")
            
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
    user_id = str(update.effective_user.id)
    
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # Update chat statistics
        if user_id in chat_stats:
            stats = chat_stats[user_id]
            chat_duration = time.time() - stats.start_time
            
            # Update average chat duration
            user_data[user_id]["total_chat_duration"] = user_data[user_id].get("total_chat_duration", 0) + chat_duration
            user_data[user_id]["chat_count"] = user_data[user_id].get("chat_count", 0) + 1
            user_data[user_id]["avg_chat_duration"] = (
                user_data[user_id]["total_chat_duration"] / user_data[user_id]["chat_count"]
            )
            
            # Update active days
            today = datetime.date.today().isoformat()
            active_days = user_data[user_id].get("active_days_dates", [])
            if today not in active_days:
                active_days.append(today)
                user_data[user_id]["active_days_dates"] = active_days[-30:]  # Keep last 30 days
                user_data[user_id]["active_days"] = len(active_days)
            
            # Clean up chat stats
            del chat_stats[user_id]
        
        # Store last partner for rating
        context.user_data["last_partner"] = partner_id
        
        # Unpin messages for both users
        try:
            # Unpin message for current user
            pinned_message_id = context.user_data.get("pinned_message_id")
            if pinned_message_id:
                await context.bot.unpin_chat_message(
                    chat_id=update.effective_chat.id,
                    message_id=pinned_message_id
                )
                del context.user_data["pinned_message_id"]
        except Exception as e:
            logger.error(f"Error unpinning message for user: {e}")
        
        # Notify partner and update their stats
        if partner_id in active_chats:
            try:
                # Update partner's statistics
                if partner_id in chat_stats:
                    partner_stats = chat_stats[partner_id]
                    partner_duration = time.time() - partner_stats.start_time
                    
                    user_data[partner_id]["total_chat_duration"] = user_data[partner_id].get("total_chat_duration", 0) + partner_duration
                    user_data[partner_id]["chat_count"] = user_data[partner_id].get("chat_count", 0) + 1
                    user_data[partner_id]["avg_chat_duration"] = (
                        user_data[partner_id]["total_chat_duration"] / user_data[partner_id]["chat_count"]
                    )
                    
                    # Update partner's active days
                    partner_active_days = user_data[partner_id].get("active_days_dates", [])
                    if today not in partner_active_days:
                        partner_active_days.append(today)
                        user_data[partner_id]["active_days_dates"] = partner_active_days[-30:]
                        user_data[partner_id]["active_days"] = len(partner_active_days)
                    
                    del chat_stats[partner_id]
                
                # Unpin message for partner
                partner_pinned_message = context.user_data.get(f"partner_{partner_id}_pinned_message")
                if partner_pinned_message:
                    await context.bot.unpin_chat_message(
                        chat_id=int(partner_id),
                        message_id=partner_pinned_message
                    )
                    del context.user_data[f"partner_{partner_id}_pinned_message"]
                
                # Send end chat notification
                await context.bot.send_message(
                    chat_id=int(partner_id),
                    text="❌ *Собеседник завершил чат*\n\nВыберите действие:",
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
        save_user_data(user_data)
        
        # Check and update achievements
        await update_achievements(user_id, context)
        await update_achievements(partner_id, context)
        
        # Ask to rate the partner
        keyboard = [
            [
                InlineKeyboardButton("1⭐", callback_data="rate_1"),
                InlineKeyboardButton("2⭐", callback_data="rate_2"),
                InlineKeyboardButton("3⭐", callback_data="rate_3"),
                InlineKeyboardButton("4⭐", callback_data="rate_4"),
                InlineKeyboardButton("5⭐", callback_data="rate_5")
            ]
        ]
        
        # Show chat statistics in rating request
        if user_id in chat_stats:
            stats = chat_stats[user_id]
            duration = int((time.time() - stats.start_time) / 60)
            stats_text = (
                f"📊 *Статистика чата:*\n"
                f"⏱ Длительность: {duration} мин.\n"
                f"💬 Сообщений отправлено: {stats.message_count}\n\n"
            )
        else:
            stats_text = ""
        
        await update.message.reply_text(
            text=f"*Чат завершен*\n\n{stats_text}Оцените вашего собеседника:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
    keyboard = [
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
        ]
    ]
    
    await update.message.reply_text(
        text="У вас нет активного чата.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
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
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
                ],
                CHATTING: [
                    CallbackQueryHandler(button_handler),
                    CommandHandler("end", end_chat),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
                ],
                PROFILE: [
                    CallbackQueryHandler(button_handler)
                ],
                EDIT_PROFILE: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
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