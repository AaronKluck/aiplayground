from pathlib import Path

# This file isn't checked into git with a real key
KEY_FILE = "key.txt"

GEMINI_API_KEY = Path(__file__).parent.joinpath("key.txt").read_text().strip()
