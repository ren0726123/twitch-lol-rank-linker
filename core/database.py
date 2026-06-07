from typing import List, Dict, Any, Optional
from fastapi import HTTPException, status
from supabase import create_client, Client
from core.config import SUPABASE_URL, SUPABASE_KEY, logger

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured in .env file.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_all_links() -> List[Dict[str, Any]]:
    """Supabaseからすべての連携データを取得する"""
    try:
        response = supabase.table("links").select("*").execute()
        return response.data
    except Exception as e:
        logger.error(f"Supabase select all error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {str(e)}",
        )


def get_link_by_twitch_id(twitch_id: str) -> Optional[Dict[str, Any]]:
    """Supabaseから特定のTwitch IDの連携データを取得する"""
    try:
        # Twitch IDは小文字で保存および比較されます
        response = supabase.table("links").select("*").eq("twitch_id", twitch_id.lower()).execute()
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"Supabase select user error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {str(e)}",
        )


def upsert_link(data: Dict[str, Any]):
    """データをSupabaseに保存（既存のIDがあれば上書き更新）"""
    try:
        # data 内の twitch_id も小文字にして統一
        data["twitch_id"] = data["twitch_id"].lower()
        supabase.table("links").upsert(data).execute()
        logger.info(f"Supabaseにデータを保存しました: Twitch ID: {data['twitch_id']}")
    except Exception as e:
        logger.error(f"Supabase upsert error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database save failed: {str(e)}",
        )
