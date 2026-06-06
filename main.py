import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote
from supabase import create_client, Client

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
import httpx
from dotenv import load_dotenv

# .env ファイルの読み込み
load_dotenv(override=True)

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ついっちらんくりんか～ API",
    description="Twitch IDとRiot IDを連携し、ソロランク情報をCSVに保存するバックエンド",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# static フォルダがなければ自動作成してマウント
os.makedirs(os.path.join(os.path.dirname(__file__), "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# セッション管理用ミドルウェアの追加
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    raise RuntimeError("SESSION_SECRET_KEY is not configured in .env file.")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
)

# Jinja2テンプレートエンジンの初期化
templates = Jinja2Templates(directory="templates")

# Supabaseクライアントの初期化
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured in .env file.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


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


# 非同期HTTPクライアントのグローバル定義
http_client = httpx.AsyncClient()


# Global Champion mappings cache
CHAMPION_ID_TO_NAME: Dict[int, str] = {}
DDRAGON_VERSION: str = "14.11.1" # Fallback version


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
                    new_mapping[key] = info.get("id") # 例: "AurelionSol"
                except Exception as ex:
                    logger.error(f"Error parsing champion {champ_name}: {ex}")
            CHAMPION_ID_TO_NAME = new_mapping
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


async def init_static_files():
    """FastAPI起動時にローカルの static/ フォルダを確認し、tmi.min.js を自動でDLしてキャッシュする"""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    tmi_path = os.path.join(static_dir, "tmi.min.js")
    
    # ファイルが存在しても、前回のダウンロード失敗によるゴミ（エラー文字列等）の可能性があれば再DLする
    should_download = True
    if os.path.exists(tmi_path):
        try:
            # 正常なブラウザ向けビルドは約36KBあるため、極端に小さい(1KB未満)場合は無効とみなす
            if os.path.getsize(tmi_path) > 1024:
                should_download = False
            else:
                logger.warning("既存の tmi.min.js が破損している可能性があるため（サイズ1KB未満）、再ダウンロードします。")
        except Exception as e:
            logger.error(f"tmi.min.js のサイズチェック中にエラーが発生しました: {e}")
            
    if should_download:
        logger.info("tmi.min.js を公式リポジトリからダウンロードします...")
        try:
            # tmi.js 1.8.5 相当のブラウザ用ビルド
            url = "https://raw.githubusercontent.com/tmijs/tmi.js/master/dist/tmi.min.js"
            response = await http_client.get(url, timeout=15.0)
            if response.status_code == 200 and len(response.text) > 1024:
                with open(tmi_path, "w", encoding="utf-8") as f:
                    f.write(response.text)
                logger.info("tmi.min.js のダウンロードが完了し、ローカルに保存されました。")
            else:
                status_code = response.status_code
                logger.error(f"tmi.min.js のダウンロードに失敗しました (Status={status_code}, Length={len(response.text) if response else 0})")
        except Exception as e:
            logger.error(f"tmi.min.js のダウンロード中にエラーが発生しました: {e}")


@app.on_event("startup")
async def startup_event():
    try:
        get_api_key()
    except HTTPException:
        logger.warning(
            "RIOT_API_KEY が正しく設定されていません。.env ファイルを確認してください。"
        )
    await init_ddragon_data()
    await init_static_files()


@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()


# Supabase 操作用ヘルパー関数
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


# APIスキーマ
class LinkRequest(BaseModel):
    game_name: str = Field(..., example="下北沢アイバーン倶楽部")
    tag_line: str = Field(..., example="1018")
    platform: str = Field(..., example="jp1")


class PublicLinkResponse(BaseModel):
    twitch_id: str
    tier: Optional[str] = None
    rank: Optional[str] = None
    league_points: Optional[int] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    main_champ: Optional[str] = None


# フロントエンドHTMLの配信（Jinja2テンプレートによるレンダリング）
@app.get("/")
async def get_index(request: Request):
    twitch_id = request.session.get("twitch_id")
    display_name = request.session.get("twitch_display_name")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "twitch_id": twitch_id,
            "display_name": display_name,
        },
    )


# OBS Studio 向け透過チャットオーバーレイの配信
@app.get("/overlay")
async def get_overlay():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "overlay.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="overlay.html not found")
    return FileResponse(html_path)


# Riot API Domain Ownership Verification
@app.get("/riot.txt", response_class=PlainTextResponse)
@app.get("//riot.txt", response_class=PlainTextResponse)
async def get_riot_verification():
    return "9a9de03d-c015-4245-a71e-709dfa446541"


# Twitch OAuth 2.0 ログイン画面へのリダイレクト
@app.get("/auth/twitch/login")
async def twitch_login():
    client_id = os.getenv("TWITCH_CLIENT_ID")
    redirect_uri = os.getenv("TWITCH_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twitch credentials are not configured in .env",
        )

    auth_url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={quote(redirect_uri)}"
        f"&response_type=code"
        f"&scope="
    )
    return RedirectResponse(auth_url)


# Twitch 認可コードの受け取り・トークン交換・ユーザー情報取得
@app.get("/auth/twitch/callback")
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

    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    redirect_uri = os.getenv("TWITCH_REDIRECT_URI")

    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Twitch credentials are not fully configured in .env",
        )

    # 1. 認可コードをアクセストークンと交換
    token_url = "https://id.twitch.tv/oauth2/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
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
        "Client-ID": client_id,
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


# 個別ユーザー連携取得API
@app.get("/api/user/{twitch_id}", response_model=PublicLinkResponse)
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
async def get_riot_account_by_id(game_name: str, tag_line: str, region: str, api_key: str) -> str:
    """① Account-V1 API から puuid を取得する"""
    # 前後の空白を除去し、tag_line の先頭の '#' を削除
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


@app.post("/api/link", response_model=PublicLinkResponse)
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
