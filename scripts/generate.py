#!/usr/bin/env python3
"""
generate.py — daily script + metadata writer. Runs in GitHub Actions.
Calls Claude (Anthropic API) with server-side web search to research today's
today's news for the team configured in channel.json and produce
content/current/script.json + meta.json.

Env: ANTHROPIC_API_KEY  (required)
     MODEL              (default: claude-sonnet-4-5)
     TARGET_MINUTES     (default: 15)
"""
import json, os, re, sys, datetime

try:
    import anthropic
except ImportError:
    sys.exit("pip install anthropic")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(BASE, "content", "current")
LOG = os.path.join(BASE, "content", "topics_log.txt")
MODEL = os.environ.get("MODEL", "claude-sonnet-4-5")
MINUTES = int(os.environ.get("TARGET_MINUTES", "15"))
WORDS = MINUTES * 150  # ~150 wpm narration
PARAS = max(8, round(WORDS / 85))                 # ~85 words per paragraph
SECTIONS = f"{max(4, PARAS // 7)}-{max(5, PARAS // 5)}"

TITLE_GUIDE_TMPL = """
TITLE STYLE (match the channel's proven patterns):
- News-heavy day (trades, signings, rumors) -> hype style: ALL CAPS, exclamation,
  mystery subject. Examples: "MASSIVE TRADE! NOBODY COULD BELIEVE HE'S NOW A KNICK!",
  "{NICK} TARGETING Star Veteran?! TRADE Rumors EXPLAINED! {NICK} News Today"
- Analysis/story day -> documentary style: "The X That Y" / "How ..." with ONE
  power word in CAPS and a concrete number. Examples:
  "The $104M Mistake That Cost Dallas An NBA Title",
  "How One Overlooked Signing REVIVED The {TEAM}",
  "How did the {NICK} Win when they were Outgained by 200 Yards?"
- Always include a number, a name, or a mystery hook. Never bland titles.
"""

SCHEMA_HINT_TMPL = """
Return ONE JSON object inside a ```json fenced block, exactly this shape:
{
 "title": "<=95 char clickable title",
 "thumb_word": "The punch phrase to render ON the thumbnail: 1-4 words, ALL CAPS, usually with '!'. Pull the single most dramatic fact from today's story, e.g. '3 DAYS DEADLINE!' / 'HE'S GONE?!' / '$212M GAMBLE!' / 'BREAKING NEWS!'",
 "thumb_prompt": "One vivid sentence describing the thumbnail SCENE for an image generator: concrete objects and symbols that dramatise today's story (a torn contract on fire, a countdown clock on the jumbotron, an empty locker, a silhouette walking out of the tunnel, a cheque, an X over a player). Arena setting is implied - describe the props, mood and lighting, NOT any real person's face.",
 "thumb_subject": "Short description of the player-like figure to feature, e.g. 'a determined point guard in a blue and orange number two jersey wearing a white headband'. Describe by role and uniform only, never by name.",
 "thumbnail_lines": ["MAX 3 LINES", "SHORT PUNCHY", "ALL CAPS"],
 "sections": [
   {"heading": "SHORT SECTION TITLE",
    "paragraphs": [
      {"text": "60-110 word narration paragraph...",
       "card_title": "<=8 word on-screen title",
       "card_lines": ["2-4 short on-screen bullets", "stats/key facts"]}
    ]}
 ],
 "meta": {
   "description": "2-3 paragraph YouTube description + hashtags ({HASHTAGS}) + line: 'Narration is AI-generated. All commentary and analysis is original.'",
   "tags": ["15-20 seo tags"]
 }
}
"""

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import channel as CH
    EDITORIAL = CH.get("editorial", "news")
    BRAND = CH.get("name", "NY KNICKS DAILY")
    TEAM = CH.get("team", "New York Knicks")
    LEAGUE = CH.get("league", "NBA")
    SPORT = CH.get("sport", "basketball")
    SOURCES = CH.get("sources", "ESPN, SNY, New York Post, HoopsHype, RealGM")
    HASHTAGS = CH.get("hashtags", "#Knicks #NBA #NewYorkKnicks")
    NICK = CH.get("nickname", TEAM.split()[-1])
except Exception:
    EDITORIAL, BRAND = "news", "NY KNICKS DAILY"
    TEAM, LEAGUE, SPORT = "New York Knicks", "NBA", "basketball"
    SOURCES = "ESPN, SNY, New York Post, HoopsHype, RealGM"
    HASHTAGS = "#Knicks #NBA #NewYorkKnicks"
    NICK = "Knicks"

TITLE_GUIDE = TITLE_GUIDE_TMPL.replace("{NICK}", NICK).replace("{TEAM}", TEAM)
SCHEMA_HINT = SCHEMA_HINT_TMPL.replace("{HASHTAGS}", HASHTAGS)

DOC_BRIEF = """You are writing for a """ + TEAM + """ STORYTELLING channel, not a news desk.
Do NOT report today's breaking news — the sister channel covers that. Instead pick
ONE evergreen subject and tell it properly: a legend's career arc, a historic game
or season, a franchise turning point, a tactical breakdown, a statistical deep dive,
a 'what if this trade never happened' scenario, or a season retrospective.
Tone: calm, authoritative, documentary. Build a narrative with a beginning, a
turn and a payoff. Use concrete numbers and dates. No hype, no clickbait shouting.
Titles must be analytical and intriguing, never ALL-CAPS screaming."""

SLOT_ANGLES = {
 "early": "Lead with today's hard news and reporting: trades, rumours, injuries, "
          "quotes, game recaps. Newsroom energy.",
 "late":  "This is the SECOND episode of the day, so do NOT repeat the morning's "
          "news beat. Lead with a deeper angle: analysis, a historical story, a "
          "player's journey, tactics, a season projection, or a big-picture debate. "
          "Reference today's news only briefly if it matters.",
}

def build_prompt(today, recent_topics, slot="early"):
    return f"""Today is {today}. You write the daily episode for "{BRAND}",
a faceless YouTube channel about the {TEAM} ({LEAGUE} {SPORT}). Use web search NOW to
research today's {TEAM} news: trades, signings, rumors, injuries, quotes, games (if in
season, the most recent game is the lead story), training camp, roster analysis.
Check multiple sources ({SOURCES}). If news is thin, add one deep-dive topic
(roster analysis, a historical {NICK} story, a player profile, a season projection).
Blend in commentary and opinion, and where natural connect today's stories to
history: past transfers, training camps, game preparations, players' career
arcs and iconic {NICK} moments. Make it feel like an expert host talking.

EPISODE ANGLE: {SLOT_ANGLES[slot]}

AVOID repeating these recent topics:
{recent_topics or "(none)"}

CONTENT MIX: today's news is the spine of the episode, but you are a commentator,
not a news reader — give YOUR analysis and opinions on every story. Weave in
historical context where it fits: past trades and how they aged, training camp
and game-prep storylines, players' career histories and personal journeys,
franchise history parallels. Connect today to the bigger picture.

Then write an energetic, conversational ~{WORDS}-word English narration script
(target {MINUTES} minutes at ~150 wpm). Short sentences. No abbreviations that read
badly aloud (say "points per game", not "PPG"). {SECTIONS} sections, about {PARAS}
paragraphs total, 60-110 words each. EVERY paragraph must have card_title and
card_lines filled.
Total word count across all paragraph texts MUST be between {WORDS-250} and {WORDS+250}.

{TITLE_GUIDE}
{SCHEMA_HINT}
Output ONLY the fenced JSON block, no other prose after your research."""

def extract_json(text):
    m = re.findall(r"```json\s*(.*?)```", text, re.S)
    raw = m[-1] if m else text[text.find("{"):text.rfind("}") + 1]
    return json.loads(raw)

def validate(d):
    words = sum(len(p["text"].split()) for s in d["sections"] for p in s["paragraphs"])
    n_para = sum(len(s["paragraphs"]) for s in d["sections"])
    assert d.get("title") and d.get("sections") and d.get("meta"), "missing keys"
    for s in d["sections"]:
        for p in s["paragraphs"]:
            assert p.get("text") and p.get("card_title") and p.get("card_lines"), \
                "paragraph missing card fields"
    assert words > WORDS * 0.82, f"script too short: {words} words (need {int(WORDS*0.82)})"
    return words, n_para

def main():
    today = datetime.date.today().isoformat()
    recent = ""
    if os.path.exists(LOG):
        recent = "\n".join(open(LOG).read().strip().splitlines()[-14:])

    import datetime as _dt
    slot = os.environ.get("SLOT", "").strip().lower()
    if slot not in ("early", "late"):
        slot = "early" if _dt.datetime.utcnow().hour < 16 else "late"
    print(f"[generate] slot: {slot}")
    client = anthropic.Anthropic()
    prompt = build_prompt(today, recent, slot)
    if EDITORIAL == "documentary":
        prompt = prompt.replace(TITLE_GUIDE, "") + "\n\n" + DOC_BRIEF
    for attempt in range(3):
        with client.messages.stream(
            model=MODEL, max_tokens=32000,
            tools=[{"type": "web_search_20250305", "name": "web_search",
                    "max_uses": 12}],
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            text = "".join(t for t in stream.text_stream)
        try:
            d = extract_json(text)
            words, n_para = validate(d)
            break
        except Exception as e:
            print(f"[generate] attempt {attempt+1} invalid: {e}", flush=True)
            if attempt == 2:
                raise
            prompt = prompt + f"\n\nPrevious attempt failed validation: {e}. Fix it."
    meta = d.pop("meta")
    os.makedirs(CUR, exist_ok=True)
    with open(os.path.join(CUR, "script.json"), "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    meta_out = {"title": d["title"], "description": meta["description"],
                "tags": meta["tags"], "privacy": os.environ.get("PRIVACY", "public")}
    # schedule today's publish time (UTC HH:MM, e.g. 15:00 = 18:00 Istanbul)
    pub_hhmm = os.environ.get("PUBLISH_UTC", "15:00")
    if meta_out["privacy"] == "public" and pub_hhmm:
        h, m = map(int, pub_hhmm.split(":"))
        now = datetime.datetime.utcnow()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now + datetime.timedelta(minutes=15):
            target += datetime.timedelta(days=1)      # missed the slot -> next day
        meta_out["publish_at"] = target.strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(CUR, "meta.json"), "w") as f:
        json.dump(meta_out, f, indent=1, ensure_ascii=False)
    with open(LOG, "a") as f:
        f.write(f"{today} [{slot}]: {d['title']}\n")
    print(f"[generate] OK — {words} words, {n_para} paragraphs: {d['title']}")

if __name__ == "__main__":
    main()
