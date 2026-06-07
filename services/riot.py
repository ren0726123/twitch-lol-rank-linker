from typing import Optional, Dict, Any
from urllib.parse import quote
import httpx
from fastapi import HTTPException, status
from core.config import logger
from core.http_client import http_client

# Global Champion mappings cache
CHAMPION_ID_TO_NAME: Dict[int, str] = {}
DDRAGON_VERSION: str = "14.11.1"  # Fallback version


async def init_ddragon_data():
    global CHAMPION_ID_TO_NAME, DDRAGON_VERSION
    try:
        # 1. 最新の Data Dragon バージョンを取得
        versions_url = "https://ddragon.leagueoflegends.com/api/versions.json"
        response = await http_client.get(versions_url, timeout=10.0)
        if response.status_code == 200:
            versions = response.json()
            if versions:
                DDRAGON_VERSION = versions[0]
                logger.info(f"Latest Data Dragon version: {DDRAGON_VERSION}")
        
        # 2. チャンピオンIDから英語名（Data Dragonキー）へのマッピングを作成
        champ_url = f"https://ddragon.leagueoflegends.com/cdn/{DDRAGON_VERSION}/data/en_US/champion.json"
        champ_response = await http_client.get(champ_url, timeout=10.0)
        if champ_response.status_code == 200:
            champ_data = champ_response.json().get("data", {})
            new_mapping = {}
            for champ_name, info in champ_data.items():
                try:
                    key = int(info.get("key"))
                    new_mapping[key] = info.get("id")  # 例: "AurelionSol"
                except Exception as ex:
                    logger.error(f"Error parsing champion {champ_name}: {ex}")
            CHAMPION_ID_TO_NAME.clear()
            CHAMPION_ID_TO_NAME.update(new_mapping)
            logger.info(f"Loaded {len(CHAMPION_ID_TO_NAME)} champions mapping from Data Dragon.")
    except Exception as e:
        logger.error(f"Failed to initialize Data Dragon data: {e}")


async def get_top_champion_mastery(puuid: str, platform: str, api_key: str) -> Optional[int]:
    """CHAMPION-MASTERY-V4 API から最もマスタリーポイントが高いチャンピオンID（数値）を取得する"""
    url = f"https://{platform.lower()}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count=1"
    headers = {"X-Riot-Token": api_key}
    
    try:
        response = await http_client.get(url, headers=headers, timeout=10.0)
        if response.status_code == 200:
            masteries = response.json()
            if masteries and len(masteries) > 0:
                return masteries[0].get("championId")
            logger.info(f"No champion mastery found for puuid={puuid}")
        else:
            logger.error(f"Champion mastery API returned {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Failed to fetch champion mastery: {e}")
    return None


async def get_riot_account_by_id(game_name: str, tag_line: str, region: str, api_key: str) -> str:
    """① Account-V1 API から puuid を取得する"""
    # 前後の空白を除去し、tag_line の先頭 of '#' を削除
    game_name = game_name.strip()
    tag_line = tag_line.strip().lstrip('#')

    encoded_game_name = quote(game_name)
    encoded_tag_line = quote(tag_line)

    url = f"https://{region.lower()}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_game_name}/{encoded_tag_line}"
    headers = {"X-Riot-Token": api_key}

    try:
        response = await http_client.get(url, headers=headers, timeout=10.0)
    except httpx.RequestError as exc:
        logger.error(f"Account-V1 API connection error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Riot Account API connection failed.",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Riot ID '{game_name}#{tag_line}' was not found.",
        )
    elif response.status_code == 403:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Riot API Key is invalid or expired.",
        )
    elif response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
        )
    elif response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Riot API (Account-V1) returned {response.status_code}: {response.text}",
        )

    data = response.json()
    puuid = data.get("puuid")
    if not puuid:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PUUID not found in Riot Account response.",
        )
    return puuid


async def get_league_entries_by_puuid(puuid: str, platform: str, api_key: str) -> tuple[Optional[str], Optional[str], Optional[int], Optional[int], Optional[int]]:
    """② League-V4 API から PUUID を使用して直接ソロランク情報を取得する"""
    url = f"https://{platform.lower()}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    headers = {"X-Riot-Token": api_key}

    try:
        response = await http_client.get(url, headers=headers, timeout=10.0)
    except httpx.RequestError as exc:
        logger.error(f"League-V4 API connection error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Riot League API connection failed.",
        )

    if response.status_code == 404:
        # 新しいアカウントでまだ一度もランクをプレイしていない場合、404になることがあります
        return None, None, None, None, None
    elif response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "unknown")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
        )
    elif response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Riot API (League-V4 by PUUID) returned {response.status_code}: {response.text}",
        )

    entries = response.json()
    logger.info(f"League-V4 (by-puuid) Response JSON: {entries}")
    for entry in entries:
        if entry.get("queueType") == "RANKED_SOLO_5x5":
            return (
                entry.get("tier"),
                entry.get("rank"),
                entry.get("leaguePoints"),
                entry.get("wins"),
                entry.get("losses"),
            )

    return None, None, None, None, None
