import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# User data file
USER_DATA_FILE = "user_data.json"

# In-memory database for Railway (since Railway doesn't provide persistent storage by default)
user_data_cache = {}
active_chats_cache = {}
searching_users_cache = {}

def load_user_data() -> Dict[str, Any]:
    """Load user data from file or initialize empty dict."""
    global user_data_cache
    
    if user_data_cache:
        return user_data_cache
    
    try:
        if os.path.exists(USER_DATA_FILE):
            with open(USER_DATA_FILE, "r", encoding="utf-8") as file:
                user_data_cache = json.load(file)
                logger.info(f"Loaded user data for {len(user_data_cache)} users")
                return user_data_cache
    except Exception as e:
        logger.error(f"Error loading user data: {e}")
    
    user_data_cache = {}
    return user_data_cache

def save_user_data(data: Dict[str, Any]) -> None:
    """Save user data to file."""
    global user_data_cache
    user_data_cache = data
    
    try:
        with open(USER_DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        logger.info(f"Saved user data for {len(data)} users")
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Get user data by user ID."""
    global user_data_cache
    
    if not user_data_cache:
        load_user_data()
    
    if user_id not in user_data_cache:
        user_data_cache[user_id] = {
            "gender": None,
            "age": None,
            "interests": [],
            "chat_count": 0,
            "rating": 0,
            "rating_count": 0
        }
        save_user_data(user_data_cache)
    
    return user_data_cache[user_id]

def update_user_data(user_id: str, data: Dict[str, Any]) -> None:
    """Update user data for a specific user."""
    global user_data_cache
    
    if not user_data_cache:
        load_user_data()
    
    user_data_cache[user_id] = data
    save_user_data(user_data_cache)

def get_active_chats() -> Dict[str, str]:
    """Get active chats."""
    global active_chats_cache
    return active_chats_cache

def update_active_chats(active_chats: Dict[str, str]) -> None:
    """Update active chats."""
    global active_chats_cache
    active_chats_cache = active_chats

def get_searching_users() -> Dict[str, Any]:
    """Get searching users."""
    global searching_users_cache
    return searching_users_cache

def update_searching_users(searching_users: Dict[str, Any]) -> None:
    """Update searching users."""
    global searching_users_cache
    searching_users_cache = searching_users 