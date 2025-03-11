import os
import json
import logging
from typing import Dict, Any, Optional
import time

logger = logging.getLogger(__name__)

# User data file
USER_DATA_DIR = os.environ.get("DATA_DIR", ".")  # Get data directory from env or use current dir
USER_DATA_FILE = os.path.join(USER_DATA_DIR, "user_data.json")

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
        # Make sure the directory exists
        os.makedirs(os.path.dirname(USER_DATA_FILE), exist_ok=True)
        
        with open(USER_DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        logger.info(f"Saved user data for {len(data)} users")
    except Exception as e:
        logger.error(f"Error saving user data: {e}")
        logger.error(f"Will continue with in-memory data only")

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
    
    if not active_chats_cache:
        try:
            # Try to load from file
            if os.path.exists("active_chats.json"):
                with open("active_chats.json", "r") as f:
                    active_chats_cache = json.load(f)
                    
                # Validate loaded chats
                valid_chats = {}
                for user_id, partner_id in active_chats_cache.items():
                    if partner_id in active_chats_cache and active_chats_cache[partner_id] == user_id:
                        valid_chats[user_id] = partner_id
                active_chats_cache = valid_chats
        except Exception as e:
            logger.error(f"Error loading active chats from file: {e}")
            active_chats_cache = {}
    
    return active_chats_cache

def update_active_chats(active_chats: Dict[str, str]) -> None:
    """Update active chats."""
    global active_chats_cache
    
    # Validate chat pairs
    valid_chats = {}
    for user_id, partner_id in active_chats.items():
        # Check if both users are connected to each other
        if partner_id in active_chats and active_chats[partner_id] == user_id:
            valid_chats[user_id] = partner_id
    
    active_chats_cache = valid_chats
    
    try:
        # Try to save to file for persistence
        with open("active_chats.json", "w") as f:
            json.dump(active_chats_cache, f)
    except Exception as e:
        logger.error(f"Error saving active chats to file: {e}")

def get_searching_users() -> Dict[str, Any]:
    """Get searching users."""
    global searching_users_cache
    
    if not searching_users_cache:
        try:
            # Try to load from file
            if os.path.exists("searching_users.json"):
                with open("searching_users.json", "r") as f:
                    searching_users_cache = json.load(f)
                    
                # Remove any stale searches
                current_time = time.time()
                valid_searches = {
                    user_id: info for user_id, info in searching_users_cache.items()
                    if current_time - info.get("start_time", 0) <= 120
                }
                searching_users_cache = valid_searches
        except Exception as e:
            logger.error(f"Error loading searching users from file: {e}")
            searching_users_cache = {}
    
    return searching_users_cache

def update_searching_users(searching_users: Dict[str, Any]) -> None:
    """Update searching users."""
    global searching_users_cache
    
    # Remove any users that have been searching for too long (over 2 minutes)
    current_time = time.time()
    valid_searches = {
        user_id: info for user_id, info in searching_users.items()
        if current_time - info.get("start_time", 0) <= 120
    }
    
    searching_users_cache = valid_searches
    
    try:
        # Try to save to file for persistence
        with open("searching_users.json", "w") as f:
            json.dump(searching_users_cache, f)
    except Exception as e:
        logger.error(f"Error saving searching users to file: {e}")

def init_db() -> None:
    """Initialize the database by loading user data."""
    load_user_data()
    logger.info("Database initialized successfully") 