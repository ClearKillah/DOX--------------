import logging
import json
import os
import sys
import time
import asyncio
import datetime
import random
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, InputFile
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
START, CHATTING, PROFILE, EDIT_PROFILE, GROUP_CHATTING = range(5)

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

# Group chat related variables
group_chats = {}  # Store active group chats: {group_id: {members: [user_ids], name: "name", creator: "user_id"}}
group_searching_users = {}  # Store users looking for group chat: {user_id: {timestamp, message_id, max_members: int}}
GROUP_MAX_MEMBERS = 10  # Maximum number of members in a group

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
FIND_GROUP = "👥 Найти групповой чат"
END_CHAT = "🚫 Завершить чат"
MY_PROFILE = "👤 Мой профиль"
HELP = "❓ Помощь"

# Constants for callback data
CALLBACK_RATE = "rate_"
CALLBACK_GENDER = "gender_"
CALLBACK_AGE = "age_"
CALLBACK_INTEREST = "interest_"
CALLBACK_GROUP = "group_"

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
    """Send welcome message when the command /start is issued, with a subscription check."""
    try:
        logger.debug("Start command received from user %s", update.effective_user.id)
        user_id = str(update.effective_user.id)
        
        # Check if user is subscribed to the channel
        channel_name = "твое чудо"  # Display name for the channel
        channel_url = "https://t.me/+DZnkhC9iv69jYjAy"  # Join link
        channel_token = "+DZnkhC9iv69jYjAy"  # Token part of the link for verification
        subscription_required = True  # Set this to False to disable subscription requirement
        
        # Set to True to perform actual subscription check
        perform_actual_check = True
        
        # Check if user already verified subscription previously
        if user_id in user_data and user_data[user_id].get("subscription_verified", False):
            logger.info(f"User {user_id} already verified subscription, skipping check")
            # User already verified - skip subscription check
            pass
        elif subscription_required:
            if perform_actual_check:
                try:
                    # Use the channel ID for verification
                    channel_id = "-1001945632215"  # This is only used if the bot is an admin
                    
                    # Check membership
                    member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                    
                    if member.status not in ['member', 'administrator', 'creator']:
                        # User is not subscribed
                        await update.message.reply_text(
                            f"❌ *Вы не подписаны на канал {channel_name}*\n"
                            "Пожалуйста, подпишитесь на канал, чтобы получить полный доступ к боту.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("Подписаться на канал", url=channel_url)],
                                [InlineKeyboardButton("Я подписался ✅", callback_data="check_subscription")]
                            ]),
                            parse_mode="Markdown"
                        )
                        # Store in context that this user needs subscription verification
                        context.user_data["needs_subscription"] = True
                        return START
                    else:
                        # User is already subscribed - mark as verified
                        if user_id in user_data:
                            user_data[user_id]["subscription_verified"] = True
                            save_user_data(user_data)
                except Exception as e:
                    logger.error(f"Error checking subscription: {e}")
                    # Always show subscription requirement even if check fails
                    await update.message.reply_text(
                        f"❌ *Для использования бота требуется подписка на канал {channel_name}*\n"
                        "Пожалуйста, подпишитесь на канал по ссылке ниже:",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Подписаться на канал", url=channel_url)],
                            [InlineKeyboardButton("Я подписался ✅", callback_data="check_subscription")]
                        ]),
                        parse_mode="Markdown"
                    )
                    # Store in context that this user needs subscription verification
                    context.user_data["needs_subscription"] = True
                    return START
            else:
                # Always show subscription requirement (no actual check)
                await update.message.reply_text(
                    f"❌ *Для использования бота требуется подписка на канал {channel_name}*\n"
                    "Пожалуйста, подпишитесь на канал по ссылке ниже:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Подписаться на канал", url=channel_url)],
                        [InlineKeyboardButton("Я подписался ✅", callback_data="check_subscription")]
                    ]),
                    parse_mode="Markdown"
                )
                # Store in context that this user needs subscription verification
                context.user_data["needs_subscription"] = True
                return START
        
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
        
        # Create a more visually appealing welcome message
        welcome_text = (
            f"*Добро пожаловать в DOX Анонимный Чат!* 🎭\n\n"
            f"👋 Привет, {update.effective_user.first_name}!\n\n"
            f"🔒 *Анонимность гарантирована*\n"
            f"💬 *Мгновенный поиск собеседников*\n"
            f"🌐 *Общение без границ*\n\n"
        )
        
        # Add user stats if they have any chats
        if chat_count > 0:
            welcome_text += (
                f"📊 *Ваша статистика:*\n"
                f"• Количество чатов: {chat_count}\n"
            )
            if rating > 0:
                welcome_text += f"• Рейтинг: {rating_stars} ({rating:.1f}/5)\n"
            welcome_text += "\n"
        
        welcome_text += "👇 *Выберите действие:* 👇"
        
        # Create a better organized menu with clear categories
        keyboard = [
            [
                InlineKeyboardButton("👤 Мой профиль", callback_data="profile")
            ],
            [
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat"),
                InlineKeyboardButton("👥 Групповой чат", callback_data="group_find")
            ],
            [
                InlineKeyboardButton("ℹ️ Помощь", callback_data="help"),
                InlineKeyboardButton("🌟 О боте", callback_data="about")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.debug("Sending welcome message with logo to user %s", user_id)
        
        # Check if logo file exists
        logo_path = "images/logo.png"
        if os.path.exists(logo_path):
            # Send logo with caption
            try:
                with open(logo_path, "rb") as photo:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=photo,
                        caption=welcome_text,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Error sending photo: {e}", exc_info=True)
                # Fallback to text-only message if photo fails
                await update.message.reply_text(
                    welcome_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        else:
            # No logo file, send text-only message
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
    
    # Handle subscription check
    if query.data == "check_subscription":
        # User clicked "I subscribed" button
        channel_name = "твое чудо"
        channel_url = "https://t.me/+DZnkhC9iv69jYjAy"
        channel_id = "-1001945632215"  # Use your actual channel ID
        
        # Try to verify subscription
        try:
            # Check membership
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            
            if member.status in ['member', 'administrator', 'creator']:
                # User is subscribed - show welcome message
                # Remove the "needs_subscription" flag
                if "needs_subscription" in context.user_data:
                    del context.user_data["needs_subscription"]
                
                # Mark as verified in user_data
                if user_id in user_data:
                    user_data[user_id]["subscription_verified"] = True
                    save_user_data(user_data)
                
                # Create a detailed welcome message
                chat_count = user_data.get(user_id, {}).get("chat_count", 0)
                rating = user_data.get(user_id, {}).get("rating", 0)
                rating_stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
                
                welcome_text = (
                    f"✅ *Подписка подтверждена!*\n\n"
                    f"*Добро пожаловать в DOX Анонимный Чат!* 🎭\n\n"
                    f"👋 Привет, {query.from_user.first_name}!\n\n"
                    f"🔒 *Анонимность гарантирована*\n"
                    f"💬 *Мгновенный поиск собеседников*\n"
                    f"🌐 *Общение без границ*\n\n"
                )
                
                # Add user stats if they have any chats
                if chat_count > 0:
                    welcome_text += (
                        f"📊 *Ваша статистика:*\n"
                        f"• Количество чатов: {chat_count}\n"
                    )
                    if rating > 0:
                        welcome_text += f"• Рейтинг: {rating_stars} ({rating:.1f}/5)\n"
                    welcome_text += "\n"
                
                welcome_text += "👇 *Выберите действие:* 👇"
                
                # Send success message and show main menu
                await query.edit_message_text(
                    welcome_text,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("👤 Мой профиль", callback_data="profile")
                        ],
                        [
                            InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat"),
                            InlineKeyboardButton("👥 Групповой чат", callback_data="group_find")
                        ],
                        [
                            InlineKeyboardButton("ℹ️ Помощь", callback_data="help"),
                            InlineKeyboardButton("🌟 О боте", callback_data="about")
                        ]
                    ]),
                    parse_mode="Markdown"
                )
                return START
            else:
                # User is still not subscribed
                await query.edit_message_text(
                    f"❌ *Вы все еще не подписаны на канал {channel_name}*\n"
                    "Пожалуйста, подпишитесь на канал для доступа к боту.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Подписаться на канал", url=channel_url)],
                        [InlineKeyboardButton("Проверить снова ♻️", callback_data="check_subscription")]
                    ]),
                    parse_mode="Markdown"
                )
                return START
        except Exception as e:
            logger.error(f"Error verifying subscription: {e}")
            # Mark as verified even if verification fails (fallback)
            if "needs_subscription" in context.user_data:
                del context.user_data["needs_subscription"]
            
            # Mark as verified in user_data
            if user_id in user_data:
                user_data[user_id]["subscription_verified"] = True
                save_user_data(user_data)
            
            # Create a full welcome message
            chat_count = user_data.get(user_id, {}).get("chat_count", 0)
            rating = user_data.get(user_id, {}).get("rating", 0)
            rating_stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
            
            welcome_text = (
                f"✅ *Доступ предоставлен!*\n\n"
                f"*Добро пожаловать в DOX Анонимный Чат!* 🎭\n\n"
                f"👋 Привет, {query.from_user.first_name}!\n\n"
                f"🔒 *Анонимность гарантирована*\n"
                f"💬 *Мгновенный поиск собеседников*\n"
                f"🌐 *Общение без границ*\n\n"
            )
            
            # Add user stats if they have any chats
            if chat_count > 0:
                welcome_text += (
                    f"📊 *Ваша статистика:*\n"
                    f"• Количество чатов: {chat_count}\n"
                )
                if rating > 0:
                    welcome_text += f"• Рейтинг: {rating_stars} ({rating:.1f}/5)\n"
                welcome_text += "\n"
            
            welcome_text += "🔽 *Выберите действие:* 🔽"
            
            await query.edit_message_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                        InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
                    ],
                    [InlineKeyboardButton("👥 Групповой чат", callback_data="group_find")],
                    [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
                ]),
                parse_mode="Markdown"
            )
            return START
    
    elif query.data == "profile":
        return await show_profile(update, context)
    
    elif query.data == "find_chat":
        return await find_chat(update, context)
    
    elif query.data == "help":
        # Show help information
        help_text = (
            "📌 *Руководство по использованию бота*\n\n"
            "🔍 *Как начать общение:*\n"
            "• Нажмите кнопку \"Найти собеседника\"\n"
            "• Дождитесь подключения партнера\n"
            "• Начните диалог\n\n"
            
            "👥 *Групповой чат:*\n"
            "• Создайте свою группу или присоединитесь к существующей\n"
            "• Общайтесь одновременно с несколькими людьми\n"
            "• Получите код для приглашения друзей\n\n"
            
            "✏️ *Полезные команды:*\n"
            "• /start - перезапустить бота\n"
            "• /end - завершить текущий чат\n"
            "• /profile - показать свой профиль\n"
            "• /report - пожаловаться на собеседника\n\n"
            
            "👤 *Профиль:*\n"
            "• Заполните информацию о себе\n"
            "• Загрузите аватар (виден только вам)\n"
            "• Укажите интересы для лучшего поиска\n\n"
            
            "🏆 *Достижения:*\n"
            "• Зарабатывайте достижения за активность\n"
            "• Улучшайте свой рейтинг для большей популярности\n\n"
            
            "Если у вас остались вопросы, свяжитесь с нашей поддержкой: @YourSupportUsername"
        )
        
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_to_menu")]
            ]),
            parse_mode="Markdown"
        )
        return START
    
    elif query.data == "back_to_menu" or query.data == "back_to_start":
        # Go back to main menu
        keyboard = [
            [
                InlineKeyboardButton("👤 Профиль", callback_data="profile"),
                InlineKeyboardButton("🔍 Найти собеседника", callback_data="find_chat")
            ],
            [InlineKeyboardButton("👥 Групповой чат", callback_data="group_find")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "*Добро пожаловать в DOX Анонимный Чат!* 🎭\n\n"
            "Выберите действие:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return START
    
    elif query.data == "group_find":
        return await find_group_chat(update, context)
    
    elif query.data == "group_create":
        # Create a new group
        return await create_group_chat(update, context)
    
    elif query.data == "group_join":
        # Join an existing group
        return await join_group_chat(update, context)
    
    elif query.data.startswith("group_leave_"):
        # Handle group leave request
        group_id = query.data.split("group_leave_")[1]
        return await leave_group_chat(update, context, group_id)
    
    elif query.data.startswith("group_invite_"):
        # Show invite code for a group
        group_id = query.data.split("group_invite_")[1]
        
        if group_id not in group_chats:
            await query.edit_message_text(
                text="❌ *Группа не найдена*",
                parse_mode="Markdown"
            )
            return START
        
        invite_code = group_chats[group_id].get("invite_code")
        
        keyboard = [
            [InlineKeyboardButton("🚪 Покинуть группу", callback_data=f"group_leave_{group_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
        ]
        
        await query.edit_message_text(
            text=f"👥 *Код приглашения в группу*\n\n"
                 f"Поделитесь этим кодом с друзьями:\n"
                 f"`{invite_code}`\n\n"
                 f"Участники: {len(group_chats[group_id]['members'])}/{GROUP_MAX_MEMBERS}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return GROUP_CHATTING
    
    elif query.data.startswith("group_join_"):
        # Handle direct group join by ID
        group_id = query.data.split("group_join_")[1]
        
        user_id = str(query.from_user.id)
        
        if group_id not in group_chats:
            await query.edit_message_text(
                text="❌ *Группа не найдена*\n\n"
                     "Возможно, эта группа больше не существует.",
                parse_mode="Markdown"
            )
            return START
        
        # Check if group is full
        if len(group_chats[group_id]["members"]) >= GROUP_MAX_MEMBERS:
            keyboard = [
                [InlineKeyboardButton("🔍 Присоединиться к другой группе", callback_data="group_join")],
                [InlineKeyboardButton("🆕 Создать новую группу", callback_data="group_create")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
            ]
            
            await query.edit_message_text(
                text="⚠️ *Группа заполнена*\n\n"
                     "В этой группе уже максимальное количество участников.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return GROUP_CHATTING
        
        # Check if user is already in this group
        if user_id in group_chats[group_id]["members"]:
            keyboard = [
                [InlineKeyboardButton("🚪 Покинуть группу", callback_data=f"group_leave_{group_id}")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
            ]
            
            await query.edit_message_text(
                text="⚠️ *Вы уже состоите в этой группе*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return GROUP_CHATTING
        
        # Add user to group
        group_chats[group_id]["members"].append(user_id)
        
        # Fetch member names
        group_info = group_chats[group_id]
        member_list = ""
        for member_id in group_info["members"]:
            try:
                member_info = await context.bot.get_chat(int(member_id))
                member_list += f"• {member_info.first_name}\n"
            except Exception as e:
                logger.error(f"Error fetching member info: {e}")
                member_list += f"• Пользователь {member_id}\n"
        
        # Notify user
        keyboard = [
            [InlineKeyboardButton("🚪 Покинуть группу", callback_data=f"group_leave_{group_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
        ]
        
        await query.edit_message_text(
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
    
    elif query.data == "group_enter_code":
        # Allow user to enter an invite code manually
        await query.edit_message_text(
            text="🔑 *Введите код приглашения*\n\n"
                 "Отправьте код приглашения, который вам дал создатель группы.",
            parse_mode="Markdown"
        )
        
        # Set flag so handle_group_message will process the invite code
        context.user_data["joining_group"] = True
        return GROUP_CHATTING
    
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
            ],
            [InlineKeyboardButton("👥 Групповой чат", callback_data="group_find")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
        ]
        
        # Get user stats
        user_id = str(query.from_user.id)
        chat_count = user_data[user_id].get("chat_count", 0)
        rating = user_data[user_id].get("rating", 0)
        rating_stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
        
        # Create a more visually appealing welcome message
        welcome_text = (
            f"*Добро пожаловать в DOX Анонимный Чат!* 🎭\n\n"
            f"👋 Привет, {query.from_user.first_name}!\n\n"
            f"🔒 *Анонимность гарантирована*\n"
            f"💬 *Мгновенный поиск собеседников*\n"
            f"🌐 *Общение без границ*\n\n"
        )
        
        # Add user stats if they have any chats
        if chat_count > 0:
            welcome_text += (
                f"📊 *Ваша статистика:*\n"
                f"• Количество чатов: {chat_count}\n"
            )
            if rating > 0:
                welcome_text += f"• Рейтинг: {rating_stars} ({rating:.1f}/5)\n"
            welcome_text += "\n"
        
        welcome_text += "👇 *Выберите действие:* 👇"
        
        await query.edit_message_text(
            text=welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
    # Handle interest edit button
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
        
        # Show updated interests selection menu
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
    
    # Handle edit profile
    elif query.data == "edit_profile":
        keyboard = [
            [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
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
        
    elif query.data == "edit_gender":
        keyboard = [
            [InlineKeyboardButton("👨 Мужской", callback_data="gender_male")],
            [InlineKeyboardButton("👩 Женский", callback_data="gender_female")],
            [InlineKeyboardButton("🔙 Назад", callback_data="edit_profile")]
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
            
        keyboard = [
            [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
            [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
            [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
            [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
        ]
        
        await query.edit_message_text(
            text=f"✅ *Пол успешно обновлен!*\n\n"
                 f"Ваш текущий пол: {'👨 Мужской' if gender == 'male' else '👩 Женский'}\n\n"
                 f"*Редактирование профиля*\n\n"
                 f"Выберите, что хотите изменить:",
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
    
    elif query.data == "about":
        # Show information about the bot
        about_text = (
            "*DOX Анонимный Чат* 🎭\n\n"
            "Бот для анонимного общения с незнакомцами.\n\n"
            "✨ *Особенности:*\n"
            "• Полная анонимность собеседников\n"
            "• Поиск по интересам\n"
            "• Групповые чаты до 10 человек\n"
            "• Персональные профили\n"
            "• Рейтинговая система\n"
            "• Система достижений\n\n"
            "📱 *Версия:* 1.0\n"
            "👨‍💻 *Разработчик:* @YourUsername\n\n"
            "Спасибо, что пользуетесь нашим ботом! 🙏"
        )
        
        await query.edit_message_text(
            about_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")]
            ]),
            parse_mode="Markdown"
        )
        return START
        
    elif query.data == "show_stats":
        # Show detailed statistics
        user_info = user_data.get(user_id, {})
        chat_count = user_info.get("chat_count", 0)
        total_messages = user_info.get("messages_sent", 0)
        chat_time = user_info.get("chat_time", 0)
        rating = user_info.get("rating", 0)
        rating_count = user_info.get("rating_count", 0)
        
        # Calculate additional stats
        avg_messages = round(total_messages / max(chat_count, 1), 1)
        total_hours = round(chat_time / 3600, 1)
        first_chat_date = user_info.get("first_chat_date", "Нет данных")
        
        stats_text = (
            "📊 *Подробная статистика*\n\n"
            f"👥 *Чаты:*\n"
            f"• Всего чатов: {chat_count}\n"
            f"• Первый чат: {first_chat_date}\n"
            f"• Средняя длительность: {round(chat_time / max(chat_count * 60, 1), 1)} мин.\n\n"
            f"💬 *Сообщения:*\n"
            f"• Всего отправлено: {total_messages}\n"
            f"• Среднее в чате: {avg_messages}\n\n"
            f"⏱ *Время:*\n"
            f"• Общее время в чатах: {total_hours} ч.\n\n"
            f"⭐ *Рейтинг:*\n"
            f"• Средний рейтинг: {rating:.1f}/5\n"
            f"• Количество оценок: {rating_count}\n"
        )
        
        await query.edit_message_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад к профилю", callback_data="profile")]
            ]),
            parse_mode="Markdown"
        )
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
        f"👤 *Ваш профиль*\n\n"
        f"*Заполнено:* {completion_percentage}% {completion_bar}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Основная информация:*\n"
        f"• Пол: {gender}\n"
        f"• Возраст: {age}\n\n"
        f"🔖 *Интересы:*\n{interests_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Ваша статистика:*\n"
        f"• Всего чатов: {chat_count}\n"
        f"• Сообщений: {total_messages}\n"
        f"• Средняя длительность: {avg_duration_min} мин.\n"
        f"• Рейтинг: {rating_stars} {rating_trend} ({rating:.1f}/5)\n"
        f"  На основе {rating_count} оценок\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *Достижения:*\n{achievements_text}"
    )
    
    # Create keyboard with better organization
    keyboard = [
        [
            InlineKeyboardButton("✏️ Изменить профиль", callback_data="edit_profile"),
            InlineKeyboardButton("📸 Аватар", callback_data="upload_avatar")
        ],
        [
            InlineKeyboardButton("🔄 Интересы", callback_data="interest_edit"),
            InlineKeyboardButton("📈 Статистика", callback_data="show_stats")
        ],
        [InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_to_start")]
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
        try:
            # Get the largest photo (best quality)
            photo = update.message.photo[-1]
            photo_file = await photo.get_file()
            
            # Create avatars directory if it doesn't exist
            os.makedirs("avatars", exist_ok=True)
            
            # Save avatar
            avatar_path = await save_avatar(user_id, photo_file)
            
            if avatar_path:
                # Show success message and return to profile
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ Изменить профиль", callback_data="edit_profile"),
                        InlineKeyboardButton("📸 Аватар", callback_data="upload_avatar")
                    ],
                    [
                        InlineKeyboardButton("🔄 Интересы", callback_data="interest_edit"),
                        InlineKeyboardButton("📈 Статистика", callback_data="show_stats")
                    ],
                    [InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_to_start")]
                ]
                
                await update.message.reply_text(
                    text="✅ *Аватар успешно обновлен!*",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return PROFILE
            else:
                await update.message.reply_text(
                    text="❌ *Ошибка при сохранении аватара*\n\nПожалуйста, попробуйте еще раз.",
                    parse_mode="Markdown"
                )
                return PROFILE
                
        except Exception as e:
            logger.error(f"Error handling avatar upload: {e}", exc_info=True)
            await update.message.reply_text(
                text="❌ *Произошла ошибка при загрузке аватара*\n\nПожалуйста, попробуйте еще раз.",
                parse_mode="Markdown"
            )
            return PROFILE
    else:
        await update.message.reply_text(
            text="📸 *Отправьте фотографию, которую хотите использовать как аватар.*\n\n"
                 "Или нажмите /cancel для отмены.",
            parse_mode="Markdown"
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
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id]["age"] = age
                save_user_data(user_data)
                
                # Send response back to edit profile menu
                keyboard = [
                    [InlineKeyboardButton("👨👩 Изменить пол", callback_data="edit_gender")],
                    [InlineKeyboardButton("✏️ Изменить возраст", callback_data="edit_age")],
                    [InlineKeyboardButton("🖼 Загрузить аватар", callback_data="upload_avatar")],
                    [InlineKeyboardButton("🔙 Назад к профилю", callback_data="profile")]
                ]
                
                await update.message.reply_text(
                    text=f"✅ *Возраст успешно обновлен на {age}!*\n\n*Редактирование профиля*\n\nВыберите, что хотите изменить:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                del context.user_data["edit_field"]
                return EDIT_PROFILE
            else:
                await update.message.reply_text(
                    "⚠️ Пожалуйста, введите корректный возраст (от 13 до 100).\n\n"
                    "Попробуйте еще раз или нажмите /cancel для отмены.",
                    parse_mode="Markdown"
                )
                return EDIT_PROFILE
        except ValueError:
            await update.message.reply_text(
                "⚠️ Пожалуйста, введите корректный возраст в виде числа.\n\n"
                "Попробуйте еще раз или нажмите /cancel для отмены.",
                parse_mode="Markdown"
            )
            return EDIT_PROFILE
        except Exception as e:
            logger.error(f"Error handling age input: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке вашего запроса.\n"
                "Пожалуйста, попробуйте еще раз или нажмите /cancel для отмены.",
                parse_mode="Markdown"
            )
            return EDIT_PROFILE
    
    # Check if uploading avatar
    if context.user_data.get("uploading_avatar"):
        if update.message.photo:
            return await handle_avatar_upload(update, context)
        elif update.message.text and update.message.text.startswith("/cancel"):
            del context.user_data["uploading_avatar"]
            
            keyboard = [
                [
                    InlineKeyboardButton("✏️ Изменить профиль", callback_data="edit_profile"),
                    InlineKeyboardButton("📸 Аватар", callback_data="upload_avatar")
                ],
                [
                    InlineKeyboardButton("🔄 Интересы", callback_data="interest_edit"),
                    InlineKeyboardButton("📈 Статистика", callback_data="show_stats")
                ],
                [InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_to_start")]
            ]
            
            await update.message.reply_text(
                "❌ *Загрузка аватара отменена.*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return PROFILE
        else:
            await update.message.reply_text(
                "📸 *Пожалуйста, отправьте фотографию или нажмите /cancel для отмены.*",
                parse_mode="Markdown"
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
                # For voice messages, use a completely different approach to guarantee anonymity
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
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filenames
                    timestamp = int(time.time())
                    temp_file_path = f"temp/voice_{user_id}_{timestamp}.ogg"
                    
                    # Get the voice file
                    voice_file = await context.bot.get_file(voice_file_id)
                    
                    # Download to temporary file
                    await voice_file.download_to_drive(temp_file_path)
                    logger.info(f"Downloaded voice message to {temp_file_path}")
                    
                    # Send as a new voice message using file path
                    with open(temp_file_path, "rb") as voice_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(voice_file)
                        
                        # Send the voice message
                        sent = await context.bot.send_voice(
                            chat_id=int(partner_id),
                            voice=input_file,  # Using InputFile to ensure a fresh upload
                            duration=voice_duration,
                            caption=update.message.caption if update.message.caption else None
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent voice message from {user_id} to {partner_id}")
                        return CHATTING
                    
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
                # For video notes, use InputFile to guarantee anonymity
                try:
                    # First, notify the partner that video note is being processed
                    await context.bot.send_chat_action(
                        chat_id=int(partner_id),
                        action="record_video_note"
                    )
                    
                    # Get the video note file details
                    video_note_file_id = update.message.video_note.file_id
                    video_note_length = update.message.video_note.length
                    video_note_duration = update.message.video_note.duration
                    
                    logger.info(f"Processing video note from {user_id} to {partner_id}: file_id={video_note_file_id}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename
                    timestamp = int(time.time())
                    temp_file_path = f"temp/videonote_{user_id}_{timestamp}.mp4"
                    
                    # Get the file
                    video_note_file = await context.bot.get_file(video_note_file_id)
                    
                    # Download to temporary file
                    await video_note_file.download_to_drive(temp_file_path)
                    
                    # Send as a new video note
                    with open(temp_file_path, "rb") as video_note_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(video_note_file)
                        
                        sent = await context.bot.send_video_note(
                            chat_id=int(partner_id),
                            video_note=input_file,  # Using InputFile to ensure a fresh upload
                            length=video_note_length,
                            duration=video_note_duration
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent video note from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending video note: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить видео-кружок. Попробуйте еще раз."
                    )
                    
            elif update.message.photo:
                # For photos, use InputFile to guarantee anonymity
                try:
                    # Get the largest photo (best quality)
                    photo = update.message.photo[-1]
                    photo_file_id = photo.file_id
                    caption = update.message.caption
                    
                    logger.info(f"Processing photo from {user_id} to {partner_id}: file_id={photo_file_id}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename
                    timestamp = int(time.time())
                    temp_file_path = f"temp/photo_{user_id}_{timestamp}.jpg"
                    
                    # Get the file
                    photo_file = await context.bot.get_file(photo_file_id)
                    
                    # Download to temporary file
                    await photo_file.download_to_drive(temp_file_path)
                    
                    # Send as a new photo
                    with open(temp_file_path, "rb") as photo_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(photo_file)
                        
                        sent = await context.bot.send_photo(
                            chat_id=int(partner_id),
                            photo=input_file,  # Using InputFile to ensure a fresh upload
                            caption=caption
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent photo from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending photo: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить фото. Попробуйте еще раз."
                    )
                    
            elif update.message.video:
                # For videos, use InputFile to guarantee anonymity
                try:
                    # Get video details
                    video_file_id = update.message.video.file_id
                    video_duration = update.message.video.duration
                    video_width = update.message.video.width
                    video_height = update.message.video.height
                    caption = update.message.caption
                    
                    logger.info(f"Processing video from {user_id} to {partner_id}: file_id={video_file_id}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename
                    timestamp = int(time.time())
                    temp_file_path = f"temp/video_{user_id}_{timestamp}.mp4"
                    
                    # Get the file
                    video_file = await context.bot.get_file(video_file_id)
                    
                    # Download to temporary file
                    await video_file.download_to_drive(temp_file_path)
                    
                    # Send as a new video
                    with open(temp_file_path, "rb") as video_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(video_file)
                        
                        sent = await context.bot.send_video(
                            chat_id=int(partner_id),
                            video=input_file,  # Using InputFile to ensure a fresh upload
                            duration=video_duration,
                            width=video_width,
                            height=video_height,
                            caption=caption
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent video from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending video: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить видео. Попробуйте еще раз."
                    )
                    
            elif update.message.sticker:
                # For stickers, use InputFile to guarantee anonymity
                try:
                    # Get sticker details
                    sticker_file_id = update.message.sticker.file_id
                    
                    logger.info(f"Processing sticker from {user_id} to {partner_id}: file_id={sticker_file_id}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename
                    timestamp = int(time.time())
                    temp_file_path = f"temp/sticker_{user_id}_{timestamp}.webp"
                    
                    # Get the file
                    sticker_file = await context.bot.get_file(sticker_file_id)
                    
                    # Download to temporary file
                    await sticker_file.download_to_drive(temp_file_path)
                    
                    # Send as a new sticker
                    with open(temp_file_path, "rb") as sticker_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(sticker_file)
                        
                        sent = await context.bot.send_sticker(
                            chat_id=int(partner_id),
                            sticker=input_file  # Using InputFile to ensure a fresh upload
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent sticker from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending sticker: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить стикер. Попробуйте еще раз."
                    )
                    
            elif update.message.document:
                # For documents, use InputFile to guarantee anonymity
                try:
                    # Get document details
                    document_file_id = update.message.document.file_id
                    document_filename = update.message.document.file_name
                    caption = update.message.caption
                    
                    logger.info(f"Processing document from {user_id} to {partner_id}: file_id={document_file_id}, filename={document_filename}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename but preserve extension
                    timestamp = int(time.time())
                    file_ext = os.path.splitext(document_filename)[1] if document_filename else ""
                    temp_file_path = f"temp/document_{user_id}_{timestamp}{file_ext}"
                    
                    # Get the file
                    document_file = await context.bot.get_file(document_file_id)
                    
                    # Download to temporary file
                    await document_file.download_to_drive(temp_file_path)
                    
                    # Send as a new document
                    with open(temp_file_path, "rb") as document_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(document_file, filename=document_filename)
                        
                        sent = await context.bot.send_document(
                            chat_id=int(partner_id),
                            document=input_file,  # Using InputFile to ensure a fresh upload
                            caption=caption
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent document from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending document: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить файл. Попробуйте еще раз."
                    )
            elif update.message.animation:
                # For animations (GIFs), use InputFile to guarantee anonymity
                try:
                    # Get animation details
                    animation_file_id = update.message.animation.file_id
                    animation_duration = update.message.animation.duration
                    animation_width = update.message.animation.width
                    animation_height = update.message.animation.height
                    caption = update.message.caption
                    
                    logger.info(f"Processing animation from {user_id} to {partner_id}: file_id={animation_file_id}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename
                    timestamp = int(time.time())
                    temp_file_path = f"temp/animation_{user_id}_{timestamp}.mp4"
                    
                    # Get the file
                    animation_file = await context.bot.get_file(animation_file_id)
                    
                    # Download to temporary file
                    await animation_file.download_to_drive(temp_file_path)
                    
                    # Send as a new animation
                    with open(temp_file_path, "rb") as animation_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(animation_file)
                        
                        sent = await context.bot.send_animation(
                            chat_id=int(partner_id),
                            animation=input_file,  # Using InputFile to ensure a fresh upload
                            duration=animation_duration,
                            width=animation_width,
                            height=animation_height,
                            caption=caption
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent animation from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending animation: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить GIF. Попробуйте еще раз."
                    )
                    
            elif update.message.audio:
                # For audio files, use InputFile to guarantee anonymity
                try:
                    # Get audio details
                    audio_file_id = update.message.audio.file_id
                    audio_duration = update.message.audio.duration
                    audio_performer = update.message.audio.performer
                    audio_title = update.message.audio.title
                    caption = update.message.caption
                    
                    logger.info(f"Processing audio from {user_id} to {partner_id}: file_id={audio_file_id}")
                    
                    # Create temporary directory if it doesn't exist
                    os.makedirs("temp", exist_ok=True)
                    
                    # Generate unique filename
                    timestamp = int(time.time())
                    temp_file_path = f"temp/audio_{user_id}_{timestamp}.mp3"
                    
                    # Get the file
                    audio_file = await context.bot.get_file(audio_file_id)
                    
                    # Download to temporary file
                    await audio_file.download_to_drive(temp_file_path)
                    
                    # Send as a new audio file
                    with open(temp_file_path, "rb") as audio_file:
                        # Create an InputFile object which creates a fresh upload
                        input_file = InputFile(audio_file)
                        
                        sent = await context.bot.send_audio(
                            chat_id=int(partner_id),
                            audio=input_file,  # Using InputFile to ensure a fresh upload
                            duration=audio_duration,
                            performer=audio_performer,
                            title=audio_title,
                            caption=caption
                        )
                    
                    # Clean up temporary file
                    try:
                        os.remove(temp_file_path)
                        logger.info(f"Removed temporary file {temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {temp_file_path}: {e}")
                    
                    if sent:
                        logger.info(f"Successfully sent audio from {user_id} to {partner_id}")
                        return CHATTING
                    
                except Exception as e:
                    logger.error(f"Error sending audio: {e}", exc_info=True)
                    await update.message.reply_text(
                        "⚠️ Не удалось отправить аудио. Попробуйте еще раз."
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

async def find_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start looking for a group chat or create a new one."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    # Check if user is already in a chat
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        # End the current chat first
        await end_chat_session(user_id, partner_id, context, reason="user_choice")
        
        # Notify the user
        await query.edit_message_text(
            text="✅ *Ваш текущий чат завершен*",
            parse_mode="Markdown"
        )
    
    # Check if user is already in a group chat
    user_in_group = False
    group_id_for_user = None
    
    for group_id, group_info in group_chats.items():
        if user_id in group_info["members"]:
            user_in_group = True
            group_id_for_user = group_id
            break
    
    if user_in_group:
        keyboard = [
            [InlineKeyboardButton("🚪 Покинуть группу", callback_data=f"group_leave_{group_id_for_user}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
        ]
        
        await query.edit_message_text(
            text="⚠️ *Вы уже находитесь в групповом чате*\n\n"
                 "Вы можете продолжить общение или покинуть группу.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return GROUP_CHATTING
    
    # Options for group chat
    keyboard = [
        [InlineKeyboardButton("🆕 Создать новую группу", callback_data="group_create")],
        [InlineKeyboardButton("🔍 Присоединиться к группе", callback_data="group_join")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
    ]
    
    await query.edit_message_text(
        text="👥 *Групповой чат*\n\n"
             "Выберите, что вы хотите сделать:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return START


async def create_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create a new group chat."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    # Create a new group ID
    group_id = f"group_{int(time.time())}_{user_id}"
    
    # Initialize the group with the creator as the first member
    group_chats[group_id] = {
        "members": [user_id],
        "name": f"Группа #{len(group_chats) + 1}",
        "creator": user_id,
        "created_at": time.time()
    }
    
    # Generate invite code
    invite_code = f"{random.randint(1000, 9999)}"
    group_chats[group_id]["invite_code"] = invite_code
    
    keyboard = [
        [InlineKeyboardButton("🚪 Покинуть группу", callback_data=f"group_leave_{group_id}")],
        [InlineKeyboardButton("👥 Пригласить в группу", callback_data=f"group_invite_{group_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
    ]
    
    await query.edit_message_text(
        text=f"✅ *Групповой чат создан!*\n\n"
             f"Название: {group_chats[group_id]['name']}\n"
             f"Код приглашения: `{invite_code}`\n\n"
             f"Участники (1/{GROUP_MAX_MEMBERS}):\n"
             f"• {query.from_user.first_name}\n\n"
             f"Отправьте код другим пользователям, чтобы они могли присоединиться.\n"
             f"Все сообщения в этом чате анонимны.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return GROUP_CHATTING


async def join_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle request to join a group chat."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    # Count active groups and members
    active_groups = len(group_chats)
    total_members = sum(len(info["members"]) for info in group_chats.values())
    
    # Prepare the list of active groups
    group_list_text = ""
    keyboard = []
    for group_id, group_info in group_chats.items():
        member_count = len(group_info["members"])
        group_list_text += f"• {group_info['name']} ({member_count}/{GROUP_MAX_MEMBERS})\n"
        keyboard.append([InlineKeyboardButton(f"Вступить в {group_info['name']}", callback_data=f"group_join_{group_id}")])
    
    if not group_list_text:
        group_list_text = "Нет активных групповых чатов. Создайте новый!"
    
    # Add option to enter invite code manually
    keyboard.append([InlineKeyboardButton("✉️ Ввести код приглашения", callback_data="group_enter_code")])
    
    # Add a back button
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")])
    
    await query.edit_message_text(
        text=f"👥 *Присоединение к группе*\n\n"
             f"Активных групп: {active_groups}\n"
             f"Всего участников: {total_members}\n\n"
             f"{group_list_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    
    return GROUP_CHATTING


async def handle_group_join(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str) -> int:
    """Handle joining a specific group chat by ID."""
    user_id = str(update.effective_user.id)
    
    if group_id not in group_chats:
        await update.message.reply_text(
            text="❌ *Группа не найдена*",
            parse_mode="Markdown"
        )
        return GROUP_CHATTING
    
    # Check if group is full
    if len(group_chats[group_id]["members"]) >= GROUP_MAX_MEMBERS:
        await update.message.reply_text(
            text="⚠️ *Группа заполнена*\n\n"
                 "В этой группе уже максимальное количество участников.",
            parse_mode="Markdown"
        )
        return GROUP_CHATTING
    
    # Add user to group
    group_chats[group_id]["members"].append(user_id)
    
    # Notify user
    group_info = group_chats[group_id]
    member_names = [context.bot.get_chat(int(member_id)).first_name for member_id in group_info["members"]]
    member_list = "\n".join(f"• {name}" for name in member_names)
    
    await update.message.reply_text(
        text=f"✅ *Вы присоединились к группе!*\n\n"
             f"Название: {group_info['name']}\n"
             f"Участники: {len(group_info['members'])}/{GROUP_MAX_MEMBERS}\n\n"
             f"Текущие участники:\n{member_list}",
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
    
    # Find which group this user is in
    user_group = None
    for group_id, group_info in group_chats.items():
        if user_id in group_info["members"]:
            user_group = group_id
            break
    
    if not user_group:
        # User is not in a group but tried to send a message
        keyboard = [
            [InlineKeyboardButton("👥 Групповой чат", callback_data="group_find")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_start")]
        ]
        
        await update.message.reply_text(
            text="⚠️ *Вы не состоите в групповом чате*\n\n"
                 "Чтобы отправить сообщение, сначала присоединитесь к группе.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return START
    
    # Check if user is trying to join a group using invite code
    if context.user_data.get("joining_group") and update.message.text:
        # User is entering an invite code
        invite_code = update.message.text.strip()
        
        # Find the group with this invite code
        target_group = None
        for group_id, group_info in group_chats.items():
            if group_info.get("invite_code") == invite_code:
                target_group = group_id
                break
        
        if not target_group:
            await update.message.reply_text(
                text="❌ *Неверный код приглашения*\n\n"
                     "Проверьте код и попробуйте снова, или создайте свою группу.",
                parse_mode="Markdown"
            )
            return GROUP_CHATTING
        
        # Check if group is full
        if len(group_chats[target_group]["members"]) >= GROUP_MAX_MEMBERS:
            await update.message.reply_text(
                text="⚠️ *Группа заполнена*\n\n"
                     "В этой группе уже максимальное количество участников.",
                parse_mode="Markdown"
            )
            return GROUP_CHATTING
        
        # Add user to group
        group_chats[target_group]["members"].append(user_id)
        
        # Remove the joining_group flag
        del context.user_data["joining_group"]
        
        # Notify user
        keyboard = [
            [InlineKeyboardButton("🚪 Покинуть группу", callback_data=f"group_leave_{target_group}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
        ]
        
        await update.message.reply_text(
            text=f"✅ *Вы присоединились к группе!*\n\n"
                 f"Название: {group_chats[target_group]['name']}\n"
                 f"Участники: {len(group_chats[target_group]['members'])}/{GROUP_MAX_MEMBERS}\n\n"
                 f"Все сообщения в этом чате анонимны.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
        # Notify other members that someone joined
        group_members = group_chats[target_group]["members"]
        for member_id in group_members:
            if member_id != user_id:  # Don't notify the user who just joined
                try:
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"👋 *Новый участник присоединился к группе!*\n\n"
                             f"В группе теперь {len(group_members)} участников.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error notifying group member {member_id}: {e}")
        
        return GROUP_CHATTING
    
    # Handle regular group message
    group_members = group_chats[user_group]["members"]
    
    # Construct anonymous name (same for each user in the group)
    anonymous_name = f"Аноним {group_members.index(user_id) + 1}"
    
    # Forward the message to all other group members
    for member_id in group_members:
        if member_id != user_id:  # Don't send back to the sender
            try:
                # Forward different types of messages
                if update.message.text:
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"{anonymous_name}: {update.message.text}"
                    )
                # Handle various media types similar to handle_message function
                elif update.message.voice:
                    voice = update.message.voice
                    timestamp = int(time.time())
                    
                    try:
                        voice_file = await context.bot.get_file(voice.file_id)
                        temp_file_path = f"temp/voice_{user_id}_{timestamp}.ogg"
                        
                        # Download the voice message
                        await voice_file.download_to_drive(temp_file_path)
                        
                        # Send as a new voice message
                        with open(temp_file_path, "rb") as audio:
                            await context.bot.send_voice(
                                chat_id=int(member_id),
                                voice=InputFile(audio),
                                caption=f"{anonymous_name}",
                                duration=voice.duration
                            )
                        
                        # Clean up the temporary file
                        if os.path.exists(temp_file_path):
                            os.remove(temp_file_path)
                            
                    except Exception as e:
                        logger.error(f"Error handling voice message in group: {e}")
                        continue
                elif update.message.photo:
                    photo = update.message.photo[-1]  # Get the largest photo
                    caption = update.message.caption or ""
                    timestamp = int(time.time())
                    
                    try:
                        photo_file = await context.bot.get_file(photo.file_id)
                        temp_file_path = f"temp/photo_{user_id}_{timestamp}.jpg"
                        
                        # Download the photo
                        await photo_file.download_to_drive(temp_file_path)
                        
                        # Send as a new photo
                        with open(temp_file_path, "rb") as img:
                            await context.bot.send_photo(
                                chat_id=int(member_id),
                                photo=InputFile(img),
                                caption=f"{anonymous_name}: {caption}" if caption else anonymous_name
                            )
                        
                        # Clean up the temporary file
                        if os.path.exists(temp_file_path):
                            os.remove(temp_file_path)
                            
                    except Exception as e:
                        logger.error(f"Error handling photo in group: {e}")
                        continue
                # Can add handlers for other media types as well
                
            except Exception as e:
                logger.error(f"Error sending message to group member {member_id}: {e}")
    
    # Update message count for statistics
    if user_id in user_data:
        user_data[user_id]["total_messages"] = user_data[user_id].get("total_messages", 0) + 1
        save_user_data(user_data)
    
    return GROUP_CHATTING


async def leave_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str) -> int:
    """Handle a user leaving a group chat."""
    query = update.callback_query
    user_id = str(query.from_user.id)
    
    if group_id not in group_chats:
        await query.edit_message_text(
            text="❌ *Группа не найдена*\n\n"
                 "Эта группа больше не существует.",
            parse_mode="Markdown"
        )
        return START
    
    # Check if user is in this group
    if user_id not in group_chats[group_id]["members"]:
        await query.edit_message_text(
            text="❌ *Вы не состоите в этой группе*",
            parse_mode="Markdown"
        )
        return START
    
    # Remove user from group
    group_chats[group_id]["members"].remove(user_id)
    
    # Notify the user
    await query.edit_message_text(
        text="✅ *Вы вышли из группового чата*",
        parse_mode="Markdown"
    )
    
    # If group is empty, delete it
    if not group_chats[group_id]["members"]:
        del group_chats[group_id]
        return START
    
    # If the creator left, assign a new creator
    if user_id == group_chats[group_id]["creator"]:
        group_chats[group_id]["creator"] = group_chats[group_id]["members"][0]
    
    # Notify other members that someone left
    group_members = group_chats[group_id]["members"]
    for member_id in group_members:
        try:
            await context.bot.send_message(
                chat_id=int(member_id),
                text=f"👋 *Участник покинул группу*\n\n"
                     f"В группе осталось {len(group_members)} участников.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error notifying group member {member_id} about user leaving: {e}")
    
    return START


async def end_chat_session(user_id: str, partner_id: str, context: ContextTypes.DEFAULT_TYPE, reason: str = "user_choice") -> None:
    """End an active chat session between two users."""
    # Remove users from active chats
    if user_id in active_chats:
        del active_chats[user_id]
    if partner_id in active_chats:
        del active_chats[partner_id]
    
    # Code for rating and closing the chat continues...

def main() -> None:
    """Start the bot."""
    try:
        logger.info("Starting bot...")
        # Create the Application
        token = os.getenv("TELEGRAM_TOKEN")
        if not token:
            logger.error("TELEGRAM_TOKEN environment variable not set. Please set it and try again.")
            sys.exit(1)
        logger.info("Using token from environment variable.")
        
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