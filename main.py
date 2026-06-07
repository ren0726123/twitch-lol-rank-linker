import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from core.config import logger, SESSION_SECRET_KEY, BASE_DIR, get_api_key
from core.http_client import http_client
from services.riot import init_ddragon_data
from services.assets import init_static_files

from routers.pages import router as pages_router
from routers.auth import router as auth_router
from routers.api import router as api_router

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
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# セッション管理用ミドルウェアの追加
if not SESSION_SECRET_KEY:
    raise RuntimeError("SESSION_SECRET_KEY is not configured in .env file.")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
)

# ルーターの登録
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(api_router)


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
