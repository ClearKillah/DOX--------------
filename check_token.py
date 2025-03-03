import requests
import sys

def check_token(token):
    """Check if the Telegram bot token is valid."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if data.get("ok"):
            bot_info = data.get("result", {})
            print(f"✅ Токен действителен!")
            print(f"Информация о боте:")
            print(f"ID: {bot_info.get('id')}")
            print(f"Имя: {bot_info.get('first_name')}")
            print(f"Username: @{bot_info.get('username')}")
            return True
        else:
            print(f"❌ Токен недействителен!")
            print(f"Ошибка: {data.get('description', 'Неизвестная ошибка')}")
            return False
    except Exception as e:
        print(f"❌ Ошибка при проверке токена: {str(e)}")
        return False

if __name__ == "__main__":
    token = "8039344227:AAEDCP_902a3r52JIdM9REqUyPx-p2IVtxA"
    print(f"Проверка токена: {token}")
    check_token(token) 