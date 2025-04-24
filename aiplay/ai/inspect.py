import json
from pydantic import ValidationError

from aiplay.ai.gemini.base import query as gemini_query
from aiplay.ai.openai.base import openai_query
from aiplay.ai.types import AIModel, LinkKeywords
from aiplay.util.html import ExtractedLink

# While the prompt asks the AI to provide a weighted score for how close a match
# each associated keyword is, there's an additional weighting based on how
# important we deem the keyword to be. (The ones here are somewhat arbitrary, as
# I am not a subject matter expert.)
KEYWORDS = {
    "department": 0.7,
    "contact": 1.0,
    "ACFR": 1.0,
    "budget": 1.0,
    "planning": 1.0,
    "officer": 0.9,
    "director": 0.9,
    "finance": 1.0,
    "elected": 0.7,
    "minutes": 1.0,
    "bid": 0.8,
    "purchasing": 1.0,
    "proposal": 1.0,
    "RFP": 1.0,
    "proposal": 1.0,
    "contract": 1.0,
    "funding": 1.0,
    "report": 0.7,
    "grant": 0.7,
    "improvement": 0.8,
    "project": 0.8,
    "initiative": 0.8,
}


def inspect_links(model: AIModel, links: list[ExtractedLink]) -> list[LinkKeywords]:
    keyword_str = "\n".join([f"- {kw}" for kw in KEYWORDS.keys()])

    prompt = (
        f"""
At the end of this prompt is a JSON list of web links scraped from a single
public sector web page. Each link in the list looks like this:
{{"url": "https://finance.com", "text": "Budget Link"}}

We want to classify links according to keywords that might be present in the
text of the link or in the URL itself. A link might have zero or more
keywords.
Return a JSON list of objects, one for each link that has at least one keyword.
associated with it. Each object should have three keys:
- "url": the URL of the link
- "text": the text of the link
- "keywords": an object with the keywords as keys and their score as values (more on scores later).

Example output follwos. Note how the `url` and `text` are the same as the
example input link - the output will always be 1:1 with some input, but with
the addition of the `keywords` key.

[{{"url": "https://finance.com", "text": "Budget Link", "keywords": {{"finance": 1.0, "budget": 1.0}}}}]

The keywords to look for are below.
{keyword_str}

If a link is determined to be associated with a keyword, that keyword
receives a score. Multiple keyword associations are possible, and the
each keyword gets its own score for that link.

A link associated with an exact keyword (ignoring casing and plurality) gets
a perfect 1.0. A word that is very similar to one of the given keywords can
still count, but will score lower, depending on how similar it is. Synonyms
and related words should be considered, but not too broadly. For example,
"finance" might score 0.8 for being a synonym of "budget", while
"financial" might score 0.7 for being a related word. A word that is
somewhat related to a keyword might score 0.5. A word that is only
tangentially related might score 0.3. A word that is not related at all
should be not cause the keyword to be be associated with the link.

A word that is the adjective form of a noun keyword might
score 0.9. Verb forms are worth less than nouns and adjectives, e.g.
"budgetary" might score 0.9 for being the adjective form of "budget", while
"budgeting" might score only 0.4 for being a verb.

Don't output any code or other text. Just the JSON. If a link has no
keywords, omit it from the ouptput. Do not evaluate against any keywords except
those explicitly listed above. Ignore anything to do with taxes.

If your output would include a keyword other than the ones I've provided,
do not include it. Instead, if it is similar in meaning to one of the requested
keywords, use the requested keyword instead, but adjust its score downward
from 1.0 to reflect how similar or not it is. If the keyword it's similar to is
also present in the output, keep whichever has the higher score and omit the
other. If it's not similar to any requested keyword, omit without replacement.
"""
        + "\n\n"
        + json.dumps(links)
    )

    """
    After the JSON output, you may *suggest* keywords that might be relevant to
    what I'm doing, which is finding links that point to people and departments
    as well as financial and planning documents (particulalry those that might
    indicate future spending).
    """

    if model == AIModel.GEMINI:
        orig_result = gemini_query(prompt)
        prev_id = ""
    elif model == AIModel.OPENAI:
        orig_result, prev_id = openai_query(prompt)
    else:
        raise ValueError(f"Unknown model: {model}")

    def parse_result(result: str) -> list[LinkKeywords]:
        unparsed = json.loads(result)

        if isinstance(unparsed, dict):
            # Sometimes the model returns a single object instead of a list if there
            # was only one relevant link. In that case, wrap it in a list.
            unparsed = [unparsed]

        kw_links: list[LinkKeywords] = []
        for item in unparsed:
            kw_link = LinkKeywords.model_validate(item)
            kw_links.append(kw_link)
        return kw_links

    try:
        kw_links = parse_result(orig_result)
    except json.JSONDecodeError as e:
        if prev_id:
            print(f"Error parsing JSON, poking at the model again: {e}")
            retry_prompt = """
The JSON output from the last prompt was not valid. Try the same response again, but with valid JSON.
"""
            retry_result, prev_id = openai_query(retry_prompt, prev_id)
            try:
                kw_links = parse_result(retry_result)
            except Exception as e:
                print(f"Retry failed: {e}")
                raise
        else:
            raise
    except ValidationError as e:
        if prev_id:
            print(f"Error validating model, poking at the model again: {e}")
            retry_prompt = """
The response did not match the expected format. Try the same response again, but
stick to this format, where the "url" and "keywords" keys are required. The keys
within the "keywords" objects can be anything, but the values should be floating
point numbers. If any output objects don't match this format, omit them.

Example:
[
  {{"url": "https://finance.com", "text": "Budget Link", "keywords": {{"finance": 1.0, "budget": 1.0}}}},
  {{"url": "https://bidding.com", "keywords": {{"bid": 0.9}}}},
]
"""
            retry_result, prev_id = openai_query(retry_prompt, prev_id)
            try:
                kw_links = parse_result(retry_result)
            except Exception as e:
                print(f"Retry failed: {e}")
                raise
        else:
            raise

    def check_invalid(links: list[LinkKeywords]) -> set[str]:
        invalid_keywords: set[str] = set()
        for kw_link in links:
            for kw in kw_link.keywords:
                if kw not in KEYWORDS:
                    invalid_keywords.add(kw)
        return invalid_keywords

    if invalid_keywords := check_invalid(kw_links):
        print(f"Unknown keywords, poking at the model again: {invalid_keywords}")
        retry_prompt = f"""
The JSON output from the last prompt contained keywords that were not in the
list of requested keywords. To remind you, the requested keywords are:
{keyword_str}

The unknown keywords in the output were:
{invalid_keywords}

Try the same response again, but only include the keywords that were in the
original list. If one of the 'unknown' keywords was chosen because it was
similar in meaning to one of the requested keywords, use the requested keyword
instead, but adjust its score downward from 1.0 to reflect how similar or not
it is. If it's not similar to any requested keywords, omit it from the output.
"""
        retry_result, _ = openai_query(retry_prompt, prev_id)
        try:
            kw_links = parse_result(retry_result)
            new_invalid = check_invalid(kw_links)
            if new_invalid:
                print(f"Retry still has unknown keywords: {new_invalid}")
        except Exception as e:
            print(f"Retry failed: {e}")
            raise

    return kw_links
