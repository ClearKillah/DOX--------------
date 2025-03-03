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
            "• �� Завершить чат - Закончить текущий разговор\n"
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
    
    interests = user_info.get("interests", [])
    interests_text = ""
    if "flirt" in interests:
        interests_text += "• 💘 Флирт\n"
    if "chat" in interests:
        interests_text += "• 💬 Общение\n"
    if not interests_text:
        interests_text = "❓ Не указаны"
    
    chat_count = user_info.get("chat_count", 0)
    
    # Calculate average rating
    rating = user_info.get("rating", 0)
    rating_count = user_info.get("rating_count", 0)
    rating_stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
    if rating:
        rating_text = f"{rating_stars} ({rating:.1f}/5)"
        if rating_count > 0:
            rating_text += f" на основе {rating_count} оценок"
    else:
        rating_text = "❓ Нет оценок"
    
    # Create profile completion percentage
    completed_fields = 0
    total_fields = 3  # gender, age, interests
    
    if user_info.get("gender"):
        completed_fields += 1
    if user_info.get("age"):
        completed_fields += 1
    if interests:
        completed_fields += 1
    
    completion_percentage = int(completed_fields / total_fields * 100)
    completion_bar = "▓" * (completion_percentage // 10) + "░" * (10 - completion_percentage // 10)
    
    profile_text = (
        f"👤 *Ваш профиль:*\n\n"
        f"*Заполнено:* {completion_percentage}% {completion_bar}\n\n"
        f"*Пол:* {gender}\n"
        f"*Возраст:* {age}\n"
        f"*Интересы:*\n{interests_text}\n\n"
        f"*Статистика:*\n"
        f"📊 Количество чатов: {chat_count}\n"
        f"📈 Рейтинг: {rating_text}"
    )
    
    keyboard = [
        [InlineKeyboardButton("✏️ Редактировать профиль", callback_data="edit_profile")],
        [InlineKeyboardButton("🔄 Изменить интересы", callback_data="interest_edit")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
    ]
    
    await query.edit_message_text(
        text=profile_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return PROFILE

async def find_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Find a chat partner."""
    try:
        if update.callback_query:
            query = update.callback_query
            user_id = str(query.from_user.id)
            chat_id = query.message.chat_id
            
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
            search_message = await query.edit_message_text(
                text="🔍 *Поиск собеседника...*\n\n⏱ Время поиска: 00:00",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отменить поиск", callback_data="cancel_search")]
                ])
            )
            
            # Store search start time
            start_time = time.time()
            
            # Simple matching algorithm
            available_users = [uid for uid in user_data.keys() 
                              if uid != user_id 
                              and uid not in active_chats 
                              and uid not in searching_users]
            
            logger.debug(f"Available users for matching: {available_users}")
            
            # Wait a bit to simulate search
            await asyncio.sleep(2)
            
            # Calculate search time
            search_time = time.time() - start_time
            minutes = int(search_time) // 60
            seconds = int(search_time) % 60
            time_text = f"⏱ Время поиска: {minutes:02d}:{seconds:02d}"
            
            if not available_users:
                logger.debug(f"No available users found for {user_id}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"😔 *Не удалось найти собеседника*\n\n{time_text}\n\nПопробуйте позже.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="find_chat")],
                        [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                    ])
                )
                return START
            
            # For demo purposes, just pick the first available user
            partner_id = available_users[0]
            logger.debug(f"Matched user {user_id} with partner {partner_id}")
            
            # Create chat connection
            active_chats[user_id] = partner_id
            active_chats[partner_id] = user_id
            
            # Increment chat count for both users
            user_data[user_id]["chat_count"] = user_data[user_id].get("chat_count", 0) + 1
            user_data[partner_id]["chat_count"] = user_data[partner_id].get("chat_count", 0) + 1
            save_user_data(user_data)
            
            # Store last partner for rating
            context.user_data["last_partner"] = partner_id
            
            # Get partner info
            partner_info = user_data.get(partner_id, {})
            gender = "👨 Мужской" if partner_info.get("gender") == "male" else "👩 Женский" if partner_info.get("gender") == "female" else "Не указан"
            age = partner_info.get("age", "Не указан")
            
            # Prepare partner info message
            if partner_info.get("gender") or partner_info.get("age"):
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
            else:
                partner_text = "*Собеседник полностью анонимен*"
            
            # Notify both users
            keyboard = [
                [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_user")],
                [InlineKeyboardButton("❌ Завершить чат", callback_data="end_chat")]
            ]
            
            # Send message to the user who initiated the search
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ *Собеседник найден!*\n{time_text}\n\n{partner_text}\n\n*Начните общение прямо сейчас!*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Error sending match notification to user: {e}")
                return START
            
            # Prepare info about the user for the partner
            user_info = user_data.get(user_id, {})
            partner_text = f"*Информация о собеседнике:*\n\n"
            
            if user_info.get("gender"):
                gender = "👨 Мужской" if user_info.get("gender") == "male" else "👩 Женский"
                partner_text += f"*Пол:* {gender}\n"
            if user_info.get("age"):
                partner_text += f"*Возраст:* {user_info.get('age')}\n"
            
            interests = user_info.get("interests", [])
            if interests:
                interests_text = ""
                if "flirt" in interests:
                    interests_text += "• 💘 Флирт\n"
                if "chat" in interests:
                    interests_text += "• 💬 Общение\n"
                partner_text += f"*Интересы:*\n{interests_text}"
            
            # Send message to the partner
            try:
                await context.bot.send_message(
                    chat_id=int(partner_id),
                    text=f"✅ *Собеседник найден!*\n\n{partner_text}\n\n*Начните общение прямо сейчас!*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                logger.debug(f"Successfully notified partner {partner_id}")
            except Exception as e:
                logger.error(f"Error notifying partner: {e}")
                # If we can't message the partner, disconnect
                if user_id in active_chats:
                    del active_chats[user_id]
                if partner_id in active_chats:
                    del active_chats[partner_id]
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ *Ошибка соединения с собеседником*\n\nПопробуйте найти другого собеседника.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="find_chat")],
                        [InlineKeyboardButton("👤 Профиль", callback_data="profile")]
                    ])
                )
                return START
            
            return CHATTING
        
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle messages during chat."""
    user_id = str(update.effective_user.id)
    message_text = update.message.text
    
    # Check if editing profile
    if context.user_data.get("edit_field") == "age":
        try:
            age = int(message_text)
            if 13 <= age <= 100:  # Basic age validation
                user_data[user_id]["age"] = age
                save_user_data(user_data)
                
                keyboard = [
                    [InlineKeyboardButton("Флирт", callback_data="interest_flirt")],
                    [InlineKeyboardButton("Общение", callback_data="interest_chat")],
                    [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
                ]
                
                interests = user_data[user_id].get("interests", [])
                interests_text = "✅ Флирт" if "flirt" in interests else "❌ Флирт"
                interests_text += "\n✅ Общение" if "chat" in interests else "\n❌ Общение"
                
                await update.message.reply_text(
                    text=f"*Возраст успешно обновлен!*\n\n*Выберите ваши интересы:*\n\n{interests_text}",
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
    
    # Check if in active chat
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        try:
            # Check if message is a command
            if message_text.startswith('/'):
                if message_text.lower() == '/end':
                    return await end_chat(update, context)
                elif message_text.lower() == '/help':
                    await update.message.reply_text(
                        "*Доступные команды:*\n"
                        "/end - Завершить текущий чат\n"
                        "/help - Показать эту справку",
                        parse_mode="Markdown"
                    )
                    return CHATTING
                else:
                    await update.message.reply_text(
                        "Неизвестная команда. Используйте /help для просмотра доступных команд."
                    )
                    return CHATTING
            
            # Forward message to partner
            await context.bot.send_message(
                chat_id=int(partner_id),
                text=message_text
            )
            
            # Add typing animation for more natural conversation
            try:
                await context.bot.send_chat_action(
                    chat_id=int(partner_id),
                    action="typing"
                )
            except Exception as e:
                logger.error(f"Error sending typing notification: {e}")
            
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
        if message_text.startswith('/'):
            if message_text.lower() == '/start':
                await update.message.reply_text(
                    f"*Добро пожаловать в Dox: Анонимный Чат* 🎭\n\n"
                    f"Здесь вы можете анонимно общаться с другими пользователями.\n\n"
                    f"*Выберите действие:*",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return START
            elif message_text.lower() == '/help':
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
        
        # Store last partner for rating
        context.user_data["last_partner"] = partner_id
        
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
        
        await update.message.reply_text(
            text="*Чат завершен*\n\nОцените вашего собеседника:",
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