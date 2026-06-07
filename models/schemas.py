from typing import Optional
from pydantic import BaseModel, Field


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
