from pathlib import Path

# This file isn't checked into git with a real key
_key_file = Path(__file__).parent.joinpath("key.txt")

GEMINI_API_KEY = _key_file.read_text().strip()
