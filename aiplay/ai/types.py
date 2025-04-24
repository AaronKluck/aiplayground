from enum import StrEnum
from pydantic import BaseModel


class AIModel(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"


class LinkKeywords(BaseModel):
    url: str
    text: str
    keywords: dict[str, float]
