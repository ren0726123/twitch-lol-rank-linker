import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from core.config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@router.get("/")
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


@router.get("/terms")
async def get_terms(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="terms.html",
        context={"request": request},
    )



@router.get("/overlay")
async def get_overlay():
    html_path = os.path.join(BASE_DIR, "templates", "overlay.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="overlay.html not found")
    return FileResponse(html_path)


@router.get("/riot.txt", response_class=PlainTextResponse)
@router.get("//riot.txt", response_class=PlainTextResponse)
async def get_riot_verification():
    return "9a9de03d-c015-4245-a71e-709dfa446541"
