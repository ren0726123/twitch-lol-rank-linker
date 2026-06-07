from typing import Optional
from urllib.parse import quote
import httpx
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import RedirectResponse
from core.config import (
    TWITCH_CLIENT_ID,
    TWITCH_CLIENT_SECRET,
    TWITCH_REDIRECT_URI,
    logger,
)
from core.http_client import http_client

router = APIRouter()


@router.get("/auth/twitch/login")
async def twitch_login():
    if not TWITCH_CLIENT_ID or not TWITCH_REDIRECT_URI:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twitch credentials are not configured in .env",
        )

    auth_url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={TWITCH_CLIENT_ID}"
        f"&redirect_uri={quote(TWITCH_REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope="
    )
    return RedirectResponse(auth_url)


@router.get("/auth/twitch/callback")
async def twitch_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Twitch authentication error: {error}",
        )
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code is missing.",
        )

    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET or not TWITCH_REDIRECT_URI:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twitch credentials are not fully configured in .env",
        )

    # 1. 認可コードをアクセストークンと交換
    token_url = "https://id.twitch.tv/oauth2/token"
    data = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": TWITCH_REDIRECT_URI,
    }

    try:
        token_response = await http_client.post(token_url, data=data, timeout=10.0)
    except httpx.RequestError as exc:
        logger.error(f"Failed to connect to Twitch token endpoint: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to contact Twitch Token server.",
        )

    if token_response.status_code != 200:
        logger.error(f"Twitch Token returned error: {token_response.text}")
        raise HTTPException(
            status_code=token_response.status_code,
            detail=f"Twitch Token error: {token_response.json().get('message', 'Unknown error')}",
        )

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Access token not found in Twitch response.",
        )

    # 2. アクセストークンを使ってユーザー情報を取得
    users_url = "https://api.twitch.tv/helix/users"
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {access_token}",
    }

    try:
        users_response = await http_client.get(users_url, headers=headers, timeout=10.0)
    except httpx.RequestError as exc:
        logger.error(f"Failed to connect to Twitch Helix users endpoint: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to contact Twitch Helix users server.",
        )

    if users_response.status_code != 200:
        logger.error(f"Twitch Helix users returned error: {users_response.text}")
        raise HTTPException(
            status_code=users_response.status_code,
            detail=f"Twitch Users API error: {users_response.json().get('message', 'Unknown error')}",
        )

    users_data = users_response.json()
    users_list = users_data.get("data", [])
    if not users_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Twitch user information not found.",
        )

    user_info = users_list[0]
    twitch_login_name = user_info.get("login", "")
    twitch_display_name = user_info.get("display_name", "")

    # セッションに情報を保存
    request.session["twitch_id"] = twitch_login_name
    request.session["twitch_display_name"] = twitch_display_name

    return RedirectResponse("/")
