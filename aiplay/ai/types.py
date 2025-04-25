from pydantic import BaseModel


class LinkKeywords(BaseModel):
    """
    Includes both the input url and text that's given to the AI, as well as the
    keywords that the AI has identified in the text and URL.
    It's slightly redundant to include the text, but one could feasibly have
    multiple links with the same URL, plus is prevents me from having to do
    a bunch of mapping AI responses back to the input.
    """

    url: str
    text: str
    keywords: dict[str, float]
