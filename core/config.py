import os
import logging
from dotenv import load_dotenv
from fastapi import HTTPException, status

# .env ファイルの読み込み
load_dotenv(override=True)

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("twitch_app")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_REDIRECT_URI = os.getenv("TWITCH_REDIRECT_URI")

PLATFORM_TO_REGION = {
    "jp1": "asia",
    "kr": "asia",
    "na1": "americas",
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    "euw1": "europe",
    "eun1": "europe",
    "tr1": "europe",
    "ru": "europe",
    "oc1": "sea",
}

def get_api_key() -> str:
    """.envからAPIキーを動的に取得する（開発時のキー変更を即座に反映するため）"""
    load_dotenv(override=True)
    key = os.getenv("RIOT_API_KEY")
    if not key or key == "RGAPI-your-actual-api-key-here":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RIOT_API_KEY is not configured.",
        )
    return key
