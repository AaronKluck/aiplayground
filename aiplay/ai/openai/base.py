from openai import OpenAI, RateLimitError
from retry import retry
import threading

from aiplay.ai.openai.key import OPENAI_API_KEY

MODEL_VERSION = "gpt-4.1-nano"
# MODEL_VERSION = "gpt-4o-mini"

_local = threading.local()


def _get_client() -> OpenAI:
    if not hasattr(_local, "client"):
        setattr(_local, "client", OpenAI(api_key=OPENAI_API_KEY))
    return getattr(_local, "client")


@retry(RateLimitError, tries=5, delay=2, backoff=2)
def openai_query(
    prompt: str, previous_response_id: str | None = None
) -> tuple[str, str]:
    try:
        response = _get_client().responses.create(
            model=MODEL_VERSION,
            instructions="You are helping identify content that pertains to businesses that want to win public sector contracts.",
            input=prompt,
            previous_response_id=previous_response_id,
        )
        if response.error:
            raise RuntimeError(
                f"Error: {response.error.message} ({response.error.code})"
            )

        # if response.usage:
        #    print(
        #        ">tokens:",
        #        response.usage.input_tokens,
        #        response.usage.output_tokens,
        #        response.usage.total_tokens,
        #    )
        return response.output_text, response.id
    except RateLimitError as e:
        print(f"Rate limit error: {e}")
        raise
