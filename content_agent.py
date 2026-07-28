"""
PedalHound Content Agent
========================
Generates a new SEO-optimized guitar gear article using the Anthropic API,
saves it as HTML, updates reviews.html and index.html, then commits and
pushes to GitHub so it goes live on Cloudflare Pages.

SETUP
-----
1. Install dependencies:
       pip install anthropic

2. Set your Anthropic API key as an environment variable:
       setx ANTHROPIC_API_KEY "sk-ant-..."
   (restart your terminal after running setx)

3. Run manually:
       python content_agent.py

WINDOWS TASK SCHEDULER - Auto-run weekly
-----------------------------------------
To schedule this script to run every Sunday at 8:00 AM:

1. Open Task Scheduler (search "Task Scheduler" in Start menu)
2. Click "Create Basic Task" in the right panel
3. Name: "PedalHound Content Agent"
4. Trigger: Weekly, Sunday, 8:00 AM
5. Action: Start a program
6. Program/script: C:\\Users\\chris\\AppData\\Local\\Programs\\Python\\Python312\\python.exe
   (adjust path to match your Python installation - run "where python" to find it)
7. Add arguments: content_agent.py
8. Start in: C:\\Users\\chris\\PedalHound
9. Finish and click OK

OR run this one-liner in PowerShell (as Administrator) to create the task automatically:
    $action = New-ScheduledTaskAction -Execute "python" -Argument "content_agent.py" -WorkingDirectory "C:\\Users\\chris\\PedalHound"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 8am
    Register-ScheduledTask -TaskName "PedalHoundContentAgent" -Action $action -Trigger $trigger -RunLevel Highest
"""

import os
import re
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import anthropic

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

SITE_DIR = Path(__file__).parent
ARTICLES_DIR = SITE_DIR / "articles"
AMAZON_TAG = "pedalhound-20"
REVERB_BASE = "https://www.awin1.com/cread.php?awinmid=67144&awinaffid=3000683&ued=https%3A%2F%2Freverb.com%2Fsearch%3Fquery%3D"
CANONICAL_BASE = "https://pedalhound.net/articles/"

# ---------------------------------------------------------------------------
# TOPIC QUEUE
# Topics are removed from this list once used (tracked in used_topics.txt).
# Add new topics here freely - the agent picks the first unused one each run.
# ---------------------------------------------------------------------------

ALL_TOPICS = [
    # Mainstream roundups
    "Best Phaser Pedals 2026",
    "Best Tremolo Pedals 2026",
    "Best Octave Pedals 2026",
    "Best Ring Modulator Pedals",
    "Best Envelope Filter Pedals",
    "Best Pitch Shifter Pedals",
    "Best Harmonizer Pedals",
    "Best Synth Pedals for Guitar",
    "Best Volume Pedals",
    "Best Preamp Pedals",
    "Best Amp Attenuators",
    "Best Spring Reverb Pedals",
    "Best Shimmer Reverb Pedals",
    "Best Bitcrusher and Glitch Pedals for Guitar",
    "Best Tape Echo Emulator Pedals",
    "Best Tube Screamer Clones Ranked",
    "Best RAT Clones and Variants Ranked",
    "Best Big Muff Variants Ranked",

    # Boutique builders
    "Best EarthQuaker Devices Pedals",
    "Best Chase Bliss Audio Pedals",
    "Best Death By Audio Pedals",
    "Best Strymon Pedals Ranked",
    "Best Walrus Audio Pedals",
    "Best JHS Pedals",
    "Best Mythos Pedals",
    "Best Origin Effects Pedals",
    "Best Fairfield Circuitry Pedals",
    "Best Caroline Guitar Company Pedals",
    "Best Zvex Pedals",
    "Best Fredric Effects Pedals",
    "Best Meris Pedals",
    "Best Old Blood Noise Endeavors Pedals",
    "Best Iron Ether Pedals",
    "Best Alexander Pedals",
    "Best Wampler Pedals Ranked",
    "Best Keeley Electronics Pedals Ranked",

    # Brand roundups
    "Best Electro-Harmonix Pedals Ranked",
    "Best Boss Compact Pedals Ranked",
    "Best MXR Pedals Ranked",

    # Niche and vintage
    "Best Japanese Boutique Pedals: Shin's Music, Maxon, Providence",
    "Best Vintage Fuzz: Tonebender, Fuzz Face, Ram's Head Compared",
    "Germanium vs Silicon Fuzz: What Actually Sounds Different",
    "Best Germanium Overdrive Pedals",

    # Pickups and hardware
    "Best Fender Telecaster Pickup Sets",
    "Best Humbucker Pickup Sets for Les Paul",
    "Best P-90 Pickup Sets",
    "Best Single Coil Sized Humbuckers",

    # Accessories
    "Best Guitar Capos",
    "Best Guitar Slides",
    "Best Expression Pedals",
    "Best DI Boxes for Guitar",
    "Best Guitar Reamping Boxes",
    "Best Guitar Maintenance Kits",

    # Guides
    "How to Build Your First Pedalboard: Complete Setup Guide",
    "True Bypass vs Buffered Bypass: Which Do You Actually Need",
    "How to Power Your Pedalboard: Complete Guide",
    "Best Soldering Irons for DIY Pedal Building",
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def slugify(title: str) -> str:
    """Convert article title to a URL-safe filename slug."""
    slug = title.lower()
    slug = re.sub(r"[''']", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug


def amazon_url(product_name: str) -> str:
    query = product_name.replace(" ", "+")
    return f"https://www.amazon.com/s?k={query}&tag={AMAZON_TAG}"


def reverb_url(product_name: str) -> str:
    query = product_name.replace(" ", "%2B")
    return f"{REVERB_BASE}{query}"


def youtube_url(product_name: str) -> str:
    query = (product_name + " demo review").replace(" ", "+")
    return f"https://www.youtube.com/results?search_query={query}"


def get_used_topics() -> set:
    used_file = SITE_DIR / "used_topics.txt"
    if used_file.exists():
        return set(line.strip() for line in used_file.read_text(encoding="utf-8").splitlines() if line.strip())
    return set()


def mark_topic_used(topic: str):
    used_file = SITE_DIR / "used_topics.txt"
    with open(used_file, "a", encoding="utf-8") as f:
        f.write(topic + "\n")


def pick_next_topic() -> str:
    used = get_used_topics()
    for topic in ALL_TOPICS:
        if topic not in used:
            return topic
    raise RuntimeError("All topics have been used. Add more topics to ALL_TOPICS in content_agent.py.")


def get_badge_and_category(title: str) -> tuple[str, str, str]:
    """Return (badge_text, badge_css_class, data_category) based on article title."""
    title_lower = title.lower()
    if any(w in title_lower for w in ["fuzz", "overdrive", "distortion", "boost", "klon", "tube screamer", "rat clone", "big muff", "preamp"]):
        return "Overdrive", "badge-pedal", "overdrive"
    if any(w in title_lower for w in ["delay", "echo", "tape echo"]):
        return "Delay", "badge-fx", "delay"
    if any(w in title_lower for w in ["reverb", "shimmer", "spring reverb"]):
        return "Reverb", "badge-fx", "reverb"
    if any(w in title_lower for w in ["chorus", "modulation", "phaser", "tremolo", "vibrato", "flanger", "octave", "pitch", "harmonizer", "ring"]):
        return "Modulation", "badge-fx", "modulation"
    if any(w in title_lower for w in ["looper", "loop"]):
        return "Looper", "badge-fx", "looper"
    if any(w in title_lower for w in ["wah", "filter", "envelope"]):
        return "Wah", "badge-fx", "wah"
    if any(w in title_lower for w in ["tuner"]):
        return "Tuner", "badge-fx", "tuner"
    if any(w in title_lower for w in ["noise gate", "noise suppressor", "compressor"]):
        return "Dynamics", "badge-fx", "dynamics"
    if any(w in title_lower for w in ["amp", "amplifier", "attenuator"]):
        return "Amp", "badge-amp", "amp"
    if any(w in title_lower for w in ["pickup", "humbucker", "p-90", "telecaster pickup", "single coil"]):
        return "Pickups", "badge-pedal", "pickups"
    if any(w in title_lower for w in ["string", "cable", "pedalboard", "power supply", "capo", "slide", "case", "di box", "reamping", "maintenance", "solder", "expression", "volume pedal"]):
        return "Accessories", "badge-fx", "accessories"
    if any(w in title_lower for w in ["synth", "bitcrusher", "glitch"]):
        return "Synth/FX", "badge-fx", "synth"
    if any(w in title_lower for w in ["earthqu", "chase bliss", "death by audio", "strymon", "walrus", "jhs", "mythos", "origin effects", "fairfield", "caroline", "zvex", "fredric", "meris", "old blood", "iron ether", "alexander", "wampler", "keeley", "electro-harmonix", "boss", "mxr"]):
        return "Multi", "badge-fx", "boutique"
    if any(w in title_lower for w in ["guide", "how to", "bypass", "true bypass", "buffered"]):
        return "Guide", "badge-fx", "guide"
    return "Gear", "badge-fx", "gear"


# ---------------------------------------------------------------------------
# ARTICLE GENERATION
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior editor at PedalHound, a guitar gear review site with a loyal audience of working musicians. Your writing is direct, opinionated, and practical. You write like a guitarist who has actually gigged with all of this gear, not a spec-sheet summarizer.

STRICT STYLE RULES:
- Never use em dashes (--  or —). Use commas, periods, or colons instead.
- Never use these phrases: "dive into", "delve into", "it's worth noting", "in conclusion", "game changer", "game-changing", "world-class", "cutting edge", "in the realm of", "when it comes to", "at the end of the day", "needle the", "tapestry", "leverage", "elevate your", "take your playing to the next level", "without further ado"
- Write in second person ("you") where it helps, but don't overdo it.
- Keep sentences short and punchy. Vary sentence length.
- Opinions are fine. Be direct. If something has a flaw, say so.
- No filler paragraphs. Every sentence earns its place.
- Scores should be real (not every product is a 9.5).

OUTPUT FORMAT:
Return a JSON object with exactly this structure:

{
  "title": "Best X Pedals 2026: Ranked for Every Budget",
  "meta_description": "One sentence, under 155 chars, include year and main keywords",
  "meta_keywords": "comma separated keywords, 5-8 total",
  "hero_badges": ["Category", "Buying Guide"],
  "hero_title": "Best X Pedals 2026: Ranked for Every Budget",
  "hero_date": "July 28, 2026",
  "hero_read_time": "12 min read",
  "hero_tagline": "Five X pedals tested side by side",
  "intro_section_title": "What Makes a Great X Pedal",
  "intro_section_id": "intro",
  "intro_html": "<p>Opening paragraph...</p><p>Second paragraph with internal link if relevant...</p>",
  "section2_title": "What to Look for",
  "section2_id": "what-to-look-for",
  "section2_html": "<ul><li><strong>Key feature:</strong> explanation</li>...</ul>",
  "toc": [
    {"id": "intro", "label": "What Makes a Great X Pedal"},
    {"id": "what-to-look-for", "label": "What to Look for"},
    {"id": "rankings", "label": "The Rankings"},
    {"id": "buying-guide", "label": "Buying Guide"},
    {"id": "verdict", "label": "Final Verdict"}
  ],
  "products": [
    {
      "rank": 1,
      "name": "Full Product Name",
      "subtitle": "Best overall, one sentence reason",
      "score": "9.2",
      "brand": "Brand Name",
      "description_html": "<p>First paragraph about the product. Real details, no fluff.</p><p>Second paragraph covering practical use, price context, who it's for.</p>",
      "pros": ["Pro 1", "Pro 2", "Pro 3", "Pro 4"],
      "cons": ["Con 1", "Con 2"]
    }
  ],
  "buying_guide_html": "<ul><li><strong>Use case 1:</strong> explanation</li>...</ul>",
  "verdict_html": "<p>Direct recommendation paragraph naming specific products for specific needs.</p>",
  "prev_article": {"title": "Best Delay Pedals", "slug": "best-delay-pedals"},
  "next_article": {"title": "Best Reverb Pedals", "slug": "best-reverb-pedals"}
}

PRODUCT COUNT: Include exactly 5 products unless the topic is a brand roundup, in which case include 6-7.
SCORES: Vary them. Range from about 8.4 to 9.6. The #1 pick should score highest.
DESCRIPTION LENGTH: Each product description should be 2 paragraphs, 80-150 words total.
PROS: 3-5 bullet points each.
CONS: 2-3 bullet points each. Be honest.
BUYING GUIDE: 4-6 bullet points, practical purchase decision advice.
VERDICT: 2-3 sentences, direct product recommendations for different buyer types.
WORD COUNT: The combined text (intro + section2 + all product descriptions + buying guide + verdict) should be 1000+ words.
"""

USER_PROMPT_TEMPLATE = """Write a PedalHound article for this topic: {topic}

Today's date: {date}

Pick real, well-known products for the category. For boutique/niche topics, use the actual pedals those builders are known for. Include budget options where relevant. Make the intro section substantive (2-4 paragraphs covering the category properly). The "what to look for" section should have 5-7 bullet points with real technical/practical detail.

Return ONLY the JSON object, no markdown fences, no preamble."""


def generate_article(topic: str) -> dict:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    today = datetime.now().strftime("%B %d, %Y")

    print(f"  Calling Anthropic API for: {topic}")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT_TEMPLATE.format(topic=topic, date=today)
            }
        ],
        system=SYSTEM_PROMPT,
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if model added them despite instructions
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    return json.loads(raw)


# ---------------------------------------------------------------------------
# HTML BUILDER
# ---------------------------------------------------------------------------

NAV_SVG = '<svg class="nav-logo-icon" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><ellipse cx="10" cy="7" rx="3" ry="4" fill="#e8a020"/><ellipse cx="22" cy="7" rx="3" ry="4" fill="#e8a020"/><ellipse cx="5" cy="15" rx="2.5" ry="3.5" fill="#e8a020"/><ellipse cx="27" cy="15" rx="2.5" ry="3.5" fill="#e8a020"/><path d="M16 13c-5 0-9 3.5-9 8 0 3.5 2.5 5 5 4.5 1.5-.3 2.5-1 4-1s2.5.7 4 1c2.5.5 5-1 5-4.5 0-4.5-4-8-9-8z" fill="#e8a020"/></svg>'
READ_MORE_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>'


def build_json_ld(data: dict, slug: str) -> str:
    items = []
    for p in data["products"]:
        items.append({
            "@type": "ListItem",
            "position": p["rank"],
            "item": {
                "@type": "Product",
                "name": p["name"],
                "brand": {"@type": "Brand", "name": p["brand"]},
                "review": {
                    "@type": "Review",
                    "reviewRating": {
                        "@type": "Rating",
                        "ratingValue": p["score"],
                        "bestRating": "10"
                    },
                    "author": {"@type": "Organization", "name": "PedalHound"},
                    "datePublished": datetime.now().strftime("%Y-%m-%d")
                }
            }
        })

    schema = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": data["title"],
        "description": data["meta_description"],
        "url": f"{CANONICAL_BASE}{slug}.html",
        "numberOfItems": len(data["products"]),
        "itemListElement": items
    }
    return json.dumps(schema, separators=(",", ":"))


def build_product_card(p: dict) -> str:
    pros_li = "\n".join(f"<li>{pr}</li>" for pr in p["pros"])
    cons_li = "\n".join(f"<li>{c}</li>" for c in p["cons"])
    amazon = amazon_url(p["name"])
    reverb = reverb_url(p["name"])
    youtube = youtube_url(p["name"])
    score_display = f"{p['score']} / 10"

    return f"""
      <div class="product-card">
        <div class="product-card-header">
          <div>
            <div class="product-card-title">{p["rank"]}. {p["name"]}</div>
            <div class="product-card-sub">{p["subtitle"]}</div>
          </div>
          <span class="product-score">{score_display}</span>
        </div>
        {p["description_html"]}
        <div class="pros-cons">
          <div class="pros"><h4>Pros</h4><ul>{pros_li}</ul></div>
          <div class="cons"><h4>Cons</h4><ul>{cons_li}</ul></div>
        </div>
        <div class="affiliate-buttons">
          <a href="{amazon}" class="btn-affiliate">Check Price on Amazon</a>
          <a href="{reverb}" class="btn-reverb">Check on Reverb</a>
          <a href="{youtube}" class="btn-youtube" target="_blank" rel="noopener noreferrer">Watch Demo</a>
        </div>
      </div>"""


def build_toc(toc_items: list) -> str:
    items = "\n".join(f'          <li><a href="#{item["id"]}">{item["label"]}</a></li>' for item in toc_items)
    return f"""      <div class="toc">
        <div class="toc-title">In This Article</div>
        <ol>
{items}
        </ol>
      </div>"""


def build_article_html(data: dict, slug: str) -> str:
    json_ld = build_json_ld(data, slug)
    toc_html = build_toc(data["toc"])
    product_cards = "\n".join(build_product_card(p) for p in data["products"])

    badges_html = "".join(
        f'<span class="badge badge-fx">{b}</span>' if i == 0
        else f'<span class="badge" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);">{b}</span>'
        for i, b in enumerate(data.get("hero_badges", ["Gear", "Buying Guide"]))
    )

    prev = data.get("prev_article", {})
    next_ = data.get("next_article", {})
    prev_link = f'<a href="{prev["slug"]}.html" class="art-nav-link"><div class="art-nav-dir">&#8592; Previous</div><div class="art-nav-title">{prev["title"]}</div></a>' if prev else '<span></span>'
    next_link = f'<a href="{next_["slug"]}.html" class="art-nav-link next"><div class="art-nav-dir">Next Review &#8594;</div><div class="art-nav-title">{next_["title"]}</div></a>' if next_ else '<span></span>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{data["title"]} | PedalHound</title>
  <meta name="description" content="{data["meta_description"]}">
  <meta name="keywords" content="{data["meta_keywords"]}">
  <link rel="canonical" href="{CANONICAL_BASE}{slug}.html">
  <meta property="og:title" content="{data["hero_title"]}">
  <meta property="og:description" content="{data["meta_description"]}">
  <meta property="og:type" content="article">
  <script type="application/ld+json">{json_ld}</script>
  <link rel="stylesheet" href="../css/style.css">
  <link rel="stylesheet" href="../css/article.css">
  <style>
    .btn-youtube {{
      display: inline-flex;
      align-items: center;
      gap: .5rem;
      background: #ff0000;
      border: 1px solid #ff0000;
      color: #fff;
      font-size: .82rem;
      font-weight: 600;
      padding: .45rem 1rem;
      border-radius: var(--radius);
      text-decoration: none;
      transition: all var(--transition);
      cursor: pointer;
      font-family: var(--font);
    }}
    .btn-youtube:hover {{ background: #cc0000; border-color: #cc0000; color: #fff; }}
    .btn-youtube::before {{ content: '▶'; font-size: .75rem; }}
  </style>
</head>
<body>
<header class="site-header">
  <div class="container">
    <nav class="nav" aria-label="Main navigation">
      <a href="../index.html" class="nav-logo">
        {NAV_SVG}
        PedalHound
      </a>
      <ul class="nav-links" role="list">
        <li><a href="../index.html">Home</a></li>
        <li><a href="../reviews.html">Reviews</a></li>
      </ul>
      <a href="../reviews.html" class="btn btn-primary nav-cta">Browse Reviews</a>
      <button class="hamburger" aria-label="Toggle navigation"><span></span><span></span><span></span></button>
    </nav>
  </div>
</header>
<div class="mobile-nav" role="dialog" aria-modal="true" aria-label="Mobile navigation">
  <div class="mobile-nav-panel">
    <a href="../index.html">Home</a>
    <a href="../reviews.html">Reviews</a>
  </div>
</div>

<main>
  <div class="art-wrap">
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="../index.html">Home</a><span class="breadcrumb-sep">&#x203A;</span>
      <a href="../reviews.html">Reviews</a><span class="breadcrumb-sep">&#x203A;</span>
      <span>{data["hero_title"]}</span>
    </nav>

    <div class="art-hero">
      <div class="art-hero-badges">
        {badges_html}
      </div>
      <h1>{data["hero_title"]}</h1>
      <div class="art-hero-meta">
        <span>&#128197; {data["hero_date"]}</span>
        <span>&#9203; {data["hero_read_time"]}</span>
        <span>&#127928; {data["hero_tagline"]}</span>
      </div>
    </div>

    <div class="art-body">
{toc_html}

      <h2 id="{data["intro_section_id"]}">{data["intro_section_title"]}</h2>
      {data["intro_html"]}

      <h2 id="{data["section2_id"]}">{data["section2_title"]}</h2>
      {data["section2_html"]}

      <h2 id="rankings">The Rankings</h2>
{product_cards}

      <div class="buying-guide" id="buying-guide">
        <div class="buying-guide-label">Buying Guide</div>
        <h3>How to Choose</h3>
        {data["buying_guide_html"]}
      </div>

      <div class="verdict" id="verdict">
        <div class="verdict-label">Final Verdict</div>
        <h3>Which Should You Buy?</h3>
        {data["verdict_html"]}
      </div>

      <div class="art-nav">
        {prev_link}
        {next_link}
      </div>
    </div>
  </div>
</main>

<footer class="site-footer">
  <div class="container">
    <div class="footer-grid">
      <div class="footer-brand">
        <a href="../index.html" class="nav-logo">
          {NAV_SVG}
          PedalHound
        </a>
        <p>Honest gear reviews for serious players.</p>
      </div>
      <div class="footer-col"><h4>Reviews</h4><ul><li><a href="../reviews.html">All Reviews</a></li><li><a href="best-delay-pedals.html">Delay Pedals</a></li><li><a href="best-reverb-pedals.html">Reverb Pedals</a></li></ul></div>
      <div class="footer-col"><h4>Site</h4><ul><li><a href="../index.html">Home</a></li></ul></div>
      <div class="footer-col"><h4>Legal</h4><ul><li><a href="#">Disclosure</a></li><li><a href="#">Privacy Policy</a></li></ul></div>
    </div>
    <div class="footer-bottom"><p>&#169; 2026 PedalHound. All rights reserved. As an Amazon Associate we earn from qualifying purchases.</p></div>
  </div>
</footer>
<script>
  const ham = document.querySelector('.hamburger');
  const nav = document.querySelector('.mobile-nav');
  if (ham && nav) {{ ham.addEventListener('click', () => {{ nav.classList.toggle('open'); ham.classList.toggle('open'); }}); }}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# SITEMAP UPDATE
# ---------------------------------------------------------------------------

def update_sitemap(slug: str):
    sitemap_path = SITE_DIR / "sitemap.xml"
    if not sitemap_path.exists():
        return

    today = datetime.now().strftime("%Y-%m-%d")
    new_url = f"""  <url>
    <loc>https://pedalhound.net/articles/{slug}.html</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>"""

    content = sitemap_path.read_text(encoding="utf-8")
    if f"{slug}.html" in content:
        print(f"  Sitemap already has {slug}.html, skipping.")
        return

    content = content.replace("</urlset>", f"{new_url}\n</urlset>")
    sitemap_path.write_text(content, encoding="utf-8")
    print(f"  Added {slug}.html to sitemap.xml")


# ---------------------------------------------------------------------------
# REVIEWS.HTML INJECTION
# ---------------------------------------------------------------------------

REVIEWS_CARD_TEMPLATE = """
        <!-- AUTO-GENERATED -->
        <article class="review-card" data-category="{category}">
          <div class="review-card-img">
            <span class="badge {badge_class}">{badge_text}</span>
            <img src="https://placehold.co/400x300/2a2a2a/e8a020?text={placeholder_text}" alt="{title}" loading="lazy">
          </div>
          <div class="review-card-body">
            <div class="review-card-meta"><span>{date_short}</span><span class="star-rating">&#9733;&#9733;&#9733;&#9733;&#9733;</span></div>
            <h2 class="review-card-title"><a href="articles/{slug}.html">{title}</a></h2>
            <p class="review-card-excerpt">{excerpt}</p>
            <div class="review-card-footer"><span class="score-pill">{top_score}</span><a href="articles/{slug}.html" class="read-more">Read More {arrow}</a></div>
          </div>
        </article>"""


def update_reviews_html(data: dict, slug: str, badge_text: str, badge_class: str, category: str):
    reviews_path = SITE_DIR / "reviews.html"
    content = reviews_path.read_text(encoding="utf-8")

    if f"{slug}.html" in content:
        print("  reviews.html already has this article, skipping.")
        return

    top_score = data["products"][0]["score"]
    title = data["title"]
    date_short = datetime.now().strftime("%b %d, %Y")
    excerpt = data["meta_description"][:140]
    placeholder_text = title.split(":")[0].replace(" ", "+")

    card = REVIEWS_CARD_TEMPLATE.format(
        category=category,
        badge_class=badge_class,
        badge_text=badge_text,
        placeholder_text=placeholder_text,
        title=title,
        date_short=date_short,
        slug=slug,
        excerpt=excerpt,
        top_score=top_score,
        arrow=READ_MORE_SVG,
    )

    # Inject before the closing of the reviews grid
    injection_marker = '</div>\n\n      </div>'
    if injection_marker not in content:
        # Fallback: try to find the reviews-list-grid close
        content = content.replace('      </div>\n\n    </div>\n  </div>\n</section>', card + '\n\n      </div>\n\n    </div>\n  </div>\n</section>', 1)
    else:
        content = content.replace(injection_marker, card + '\n' + injection_marker, 1)

    reviews_path.write_text(content, encoding="utf-8")
    print("  Updated reviews.html")


# ---------------------------------------------------------------------------
# INDEX.HTML INJECTION
# ---------------------------------------------------------------------------

INDEX_CARD_TEMPLATE = """
        <!-- AUTO-GENERATED -->
        <article class="review-card">
          <div class="review-card-img">
            <span class="badge {badge_class}">{badge_text}</span>
            <img src="https://placehold.co/400x300/2a2a2a/e8a020?text={placeholder_text}" alt="{title}" loading="lazy">
          </div>
          <div class="review-card-body">
            <div class="review-card-meta">
              <span>{date_long}</span>
              <span class="star-rating">&#9733;&#9733;&#9733;&#9733;&#9733;</span>
            </div>
            <h3 class="review-card-title">
              <a href="articles/{slug}.html">{title}</a>
            </h3>
            <p class="review-card-excerpt">{excerpt}</p>
            <div class="review-card-footer">
              <span class="score-pill">{top_score} / 10</span>
              <a href="articles/{slug}.html" class="read-more">
                Full Review {arrow}
              </a>
            </div>
          </div>
        </article>"""


def update_index_html(data: dict, slug: str, badge_text: str, badge_class: str):
    index_path = SITE_DIR / "index.html"
    content = index_path.read_text(encoding="utf-8")

    if f"{slug}.html" in content:
        print("  index.html already has this article, skipping.")
        return

    top_score = data["products"][0]["score"]
    title = data["title"]
    date_long = datetime.now().strftime("%B %d, %Y")
    excerpt = data["meta_description"][:130]
    placeholder_text = title.split(":")[0].replace(" ", "+")

    card = INDEX_CARD_TEMPLATE.format(
        badge_class=badge_class,
        badge_text=badge_text,
        placeholder_text=placeholder_text,
        title=title,
        date_long=date_long,
        slug=slug,
        excerpt=excerpt,
        top_score=top_score,
        arrow=READ_MORE_SVG,
    )

    # Find the reviews-grid section and inject after the first card
    marker = '      <div class="reviews-grid">'
    if marker in content:
        content = content.replace(marker, marker + card, 1)
    else:
        print("  WARNING: Could not find reviews-grid in index.html. Card not added.")
        return

    index_path.write_text(content, encoding="utf-8")
    print("  Updated index.html")


# ---------------------------------------------------------------------------
# GIT PUSH
# ---------------------------------------------------------------------------

def git_push(topic: str, slug: str):
    today = datetime.now().strftime("%Y-%m-%d")
    commit_msg = f"Add article: {topic} ({today})"

    cmds = [
        ["git", "add", f"articles/{slug}.html", "reviews.html", "index.html", "sitemap.xml", "used_topics.txt"],
        ["git", "commit", "-m", commit_msg],
        ["git", "push", "origin", "master"],
    ]

    for cmd in cmds:
        print(f"  $ {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(SITE_DIR), capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr}")
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
        if result.stdout.strip():
            print(f"  {result.stdout.strip()}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PedalHound Content Agent")
    print("=" * 60)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nERROR: ANTHROPIC_API_KEY environment variable not set.")
        print('Set it with: setx ANTHROPIC_API_KEY "sk-ant-..."')
        print("Then restart your terminal and try again.")
        sys.exit(1)

    # 1. Pick next topic
    topic = pick_next_topic()
    slug = slugify(topic)
    print(f"\nTopic: {topic}")
    print(f"Slug:  {slug}")

    # 2. Generate article via API
    print("\n[1/5] Generating article...")
    data = generate_article(topic)
    print(f"  Title: {data['title']}")
    print(f"  Products: {', '.join(p['name'] for p in data['products'])}")

    # 3. Save HTML file
    print("\n[2/5] Saving article HTML...")
    html = build_article_html(data, slug)
    article_path = ARTICLES_DIR / f"{slug}.html"
    article_path.write_text(html, encoding="utf-8")
    print(f"  Saved: articles/{slug}.html")

    # 4. Update site files
    badge_text, badge_class, category = get_badge_and_category(topic)
    print("\n[3/5] Updating site files...")
    update_sitemap(slug)
    update_reviews_html(data, slug, badge_text, badge_class, category)
    update_index_html(data, slug, badge_text, badge_class)

    # 5. Mark topic used
    mark_topic_used(topic)
    print(f"  Marked topic as used: {topic}")

    # 6. Git push
    print("\n[4/5] Committing and pushing to GitHub...")
    git_push(topic, slug)

    print("\n[5/5] Done!")
    print(f"\nArticle live at: https://pedalhound.net/articles/{slug}.html")
    print("Cloudflare Pages will deploy in ~1 minute.")


if __name__ == "__main__":
    main()
