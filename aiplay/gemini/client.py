from google import genai
from aiplay.gemini.key import GEMINI_API_KEY


_client = genai.Client(api_key=GEMINI_API_KEY)


def generate(contents: str) -> str:
    """Generate content using the Gemini API."""
    response = _client.models.generate_content(
        model="gemini-2.0-flash",
        contents=contents,
    )
    text = response.text
    if not text:
        raise ValueError("No text generated")
    return text

