from google import genai
from google.genai.types import (
    BlobDict,
    ContentDict,
    ContentListUnion,
    ContentListUnionDict,
    CreateCachedContentConfig,
    FileDataDict,
    GenerateContentConfig,
    PartDict,
)
import threading

from aiplay.ai.gemini.key import GEMINI_API_KEY

MODEL_VERSION = "gemini-2.0-flash"

_local = threading.local()


def _get_client() -> genai.Client:
    if not hasattr(_local, "client"):
        setattr(_local, "client", genai.Client(api_key=GEMINI_API_KEY))
    return getattr(_local, "client")


def _generate_content(
    contents: ContentListUnion | ContentListUnionDict, cache_name: str | None
) -> str:
    response = _get_client().models.generate_content(
        model=MODEL_VERSION,
        contents=contents,
        config=GenerateContentConfig(cache_name=cache_name) if cache_name else None,
    )
    text = response.text
    print(
        ">tokens:",
        response.usage_metadata.cached_content_token_count,
        response.usage_metadata.total_token_count,
    )
    if not text:
        raise ValueError("No text generated")
    return text


def _create_cache(
    prompt: str, contents: ContentListUnion | ContentListUnionDict, ttl: int
):
    return _get_client().caches.create(
        model=MODEL_VERSION,
        config=CreateCachedContentConfig(
            system_instruction=prompt,
            contents=contents,
            ttl=f"{ttl}s",
        ),
    )


def cache_inline_file(prompt: str, data: bytes, mime: str, ttl=60) -> str:
    contents: ContentDict = ContentDict(
        parts=[
            PartDict(text=prompt),
            PartDict(inline_data=BlobDict(data=data, mime_type=mime)),
        ],
        role="user",
    )
    cache = _create_cache(prompt, contents, ttl)
    return cache.name


def query(prompt: str, cache_name: str | None = None) -> str:
    contents: ContentDict = ContentDict(
        parts=[
            PartDict(text=prompt),
        ],
        role="user",
    )
    return _generate_content(contents, cache_name)


def query_inline_file(prompt: str, data: bytes, mime: str) -> str:
    contents: ContentDict = ContentDict(
        parts=[
            PartDict(text=prompt),
            PartDict(inline_data=BlobDict(data=data, mime_type=mime)),
        ],
        role="user",
    )
    return _generate_content(contents, None)


def query_url_file(prompt: str, url: str, mime: str) -> str:
    contents: ContentDict = ContentDict(
        parts=[
            PartDict(text=prompt),
            PartDict(file_data=FileDataDict(file_uri=url, mime_type=mime)),
        ],
        role="user",
    )
    return _generate_content(contents, None)
