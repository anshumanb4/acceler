import json
import time
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

PROMPT_TEMPLATE = """Analyze the following web page content and extract all people mentioned. For each person, provide their name, title/role (if mentioned), organization (if mentioned), email address (if found on the page), LinkedIn profile URL (if found on the page), and a personalization-ready context.

The "context" field is the most important part of this extraction — it will be used to write personalized outreach messages to these individuals. Follow these rules for context:

1. BEST: If the person is quoted or paraphrased on the page (something they said, a viewpoint they shared, a topic they presented on), use that. Include the actual quote or a close paraphrase. This is the most valuable context for personalization.
2. FALLBACK: If there is no quote or statement from the person, describe the event or setting where they appear — include the conference/event name, date, location, and their role (e.g. "Speaker at TechCrunch Disrupt 2025, San Francisco, Oct 14-16" or "Panelist on 'AI in Healthcare' at HIMSS 2025, Chicago").
3. Be specific and detailed. Generic context like "mentioned on the page" is useless. Always extract the most concrete, personalizable detail available.

Return ONLY a valid JSON array with no additional text. Each element should have these fields:
- "name": the person's full name
- "title": their title or role (empty string if unknown)
- "organization": their organization (empty string if unknown)
- "email": their email address if explicitly present on the page (empty string if not found)
- "linkedin": their LinkedIn profile URL if explicitly present on the page (empty string if not found)
- "context": the personalization-ready context as described above

Only include email and LinkedIn if they are actually present on the page. Do not guess or fabricate them.

If no people are found, return an empty array [].

Page title: {title}
Page URL: {url}

Page content:
{text}"""


def extract_people(title: str, url: str, text: str) -> list[dict]:
    prompt = PROMPT_TEMPLATE.format(title=title, url=url, text=text)

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
    else:
        raise RuntimeError("Claude API rate limit exceeded after 3 retries")

    content = response.content[0].text
    stop_reason = response.stop_reason

    # Parse JSON — mirrors background.js logic
    json_str = content.strip()

    # Strip code fences
    if json_str.startswith("```"):
        json_str = json_str.split("\n", 1)[-1] if "\n" in json_str else json_str[3:]
    json_str = json_str.rstrip("`").strip()

    # Find the array start
    array_start = json_str.find("[")
    if array_start != -1:
        json_str = json_str[array_start:]

    # Repair truncated JSON
    if stop_reason == "max_tokens" or not json_str.endswith("]"):
        last_complete = json_str.rfind("}")
        if last_complete != -1:
            json_str = json_str[: last_complete + 1] + "]"

    return json.loads(json_str)
