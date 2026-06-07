from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, status
from core.config import get_api_key, logger, PLATFORM_TO_REGION
from core.database import get_link_by_twitch_id, upsert_link
from models.schemas import LinkRequest, PublicLinkResponse
from services.riot import (
    get_league_entries_by_puuid,
    get_top_champion_mastery,
    get_riot_account_by_id,
    CHAMPION_ID_TO_NAME,
)

router = APIRouter()


# 個別ユーザー連携取得API
@router.get("/api/user/{twitch_id}", response_model=PublicLinkResponse)
async def get_user_link(twitch_id: str):
    link = get_link_by_twitch_id(twitch_id)
    if not link:
        raise HTTPException(status_code=404, detail="User link not found")
    
    # データの最終更新日時（timestamp）を確認し、10分（600秒）経過していれば自動更新
    is_stale = False
    db_timestamp_str = link.get("timestamp")
    if not db_timestamp_str:
        is_stale = True
    else:
        try:
            db_time = datetime.strptime(db_timestamp_str, "%Y-%m-%d %H:%M:%S")
            age_seconds = (datetime.now() - db_time).total_seconds()
            if age_seconds > 600:
                is_stale = True
        except Exception as e:
            logger.error(f"Timestamp parse error: {e}")
            is_stale = True

    if is_stale:
        try:
            puuid = link.get("puuid")
            # データベース移行前のレコードで platform が空の場合はデフォルトで "jp1"
            platform = link.get("platform") or "jp1"
            api_key = get_api_key()

            logger.info(f"Dynamically updating rank for Twitch={twitch_id} (PUUID={puuid}, Platform={platform})")
            tier, rank, lp, wins, losses = await get_league_entries_by_puuid(puuid, platform, api_key)
            
            # メインチャンピオンの取得
            main_champ_id = await get_top_champion_mastery(puuid, platform, api_key)
            main_champ = CHAMPION_ID_TO_NAME.get(main_champ_id) if main_champ_id else None

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            updated_data = {
                "twitch_id": link["twitch_id"],
                "game_name": link["game_name"],
                "tag_line": link["tag_line"],
                "puuid": puuid,
                "summoner_id": link.get("summoner_id") or "",
                "platform": platform,
                "tier": tier,
                "rank": rank,
                "league_points": lp,
                "wins": wins,
                "losses": losses,
                "main_champ": main_champ,
                "timestamp": timestamp,
            }
            upsert_link(updated_data)
            link = updated_data
        except Exception as e:
            # 更新失敗時は既存 of キャッシュデータを返し、エラーをログに記録（オーバーレイ表示を落とさないため）
            logger.error(f"Failed to dynamically update rank for {twitch_id}: {e}")

    return {
        "twitch_id": link["twitch_id"],
        "tier": link["tier"],
        "rank": link["rank"],
        "league_points": link.get("league_points"),
        "wins": link.get("wins"),
        "losses": link.get("losses"),
        "main_champ": link.get("main_champ")
    }


# Riot API連携およびCSV保存エンドポイント
@router.post("/api/link", response_model=PublicLinkResponse)
async def link_account(request: Request, payload: LinkRequest):
    twitch_id = request.session.get("twitch_id")
    if not twitch_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Twitch OAuth login is required.",
        )

    logger.info(f"連携要求: Twitch={twitch_id}, Riot={payload.game_name}#{payload.tag_line}")

    api_key = get_api_key()

    # 1. Account-V1 から PUUID 取得 (プラットフォームから対応するリージョンを決定)
    platform = payload.platform.lower()
    region = PLATFORM_TO_REGION.get(platform, "asia")

    puuid = await get_riot_account_by_id(payload.game_name, payload.tag_line, region, api_key)

    # 2. League-V4 (by-puuid) から直接ソロランク情報を取得
    tier, rank, lp, wins, losses = await get_league_entries_by_puuid(puuid, platform, api_key)

    # メインチャンピオンの取得
    main_champ_id = await get_top_champion_mastery(puuid, platform, api_key)
    main_champ = CHAMPION_ID_TO_NAME.get(main_champ_id) if main_champ_id else None

    # 連携データの作成
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    link_data = {
        "twitch_id": twitch_id,
        "game_name": payload.game_name,
        "tag_line": payload.tag_line,
        "puuid": puuid,
        "summoner_id": "",  # puuidによる直接取得になったため空文字列
        "platform": platform,
        "tier": tier,
        "rank": rank,
        "league_points": lp,
        "wins": wins,
        "losses": losses,
        "main_champ": main_champ,
        "timestamp": timestamp,
    }

    # Supabaseへ保存
    upsert_link(link_data)

    return {
        "twitch_id": link_data["twitch_id"],
        "tier": link_data["tier"],
        "rank": link_data["rank"],
        "league_points": link_data["league_points"],
        "wins": link_data["wins"],
        "losses": link_data["losses"],
        "main_champ": link_data["main_champ"]
    }
