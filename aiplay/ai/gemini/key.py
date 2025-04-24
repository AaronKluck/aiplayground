from pathlib import Path

# This file isn't checked into git with a real key. Normally, you'd pass in API
# keys with envars or a secrets manager, but I wanted this to be as easy to run
# out of the box as possible, so I'm having it just read from a file.
_key_file = Path(__file__).parent.joinpath("key.txt")

GEMINI_API_KEY = _key_file.read_text().strip()
