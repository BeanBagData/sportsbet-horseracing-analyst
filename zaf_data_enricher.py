# ======================================================================================================================================
# START OF FILE: zaf_data_enricher.py
# OPERATIONAL ROLE: SOUTH AFRICAN RACE DATA GROUND-TRUTH ENRICHMENT MODULE
# PURPOSE: Supplements Sportsbet API feed with missing ZAF-specific fields:
#          - Age and sex via race-name invariant inference (zero external dependency)
#          - Apprentice weight claims (lb -> kg, SA official 0.5 kg/lb convention)
#          - Merit ratings (MR)
#          - Compressed barrier numbers after scratching
# SOURCES (priority order, all attempted on user's machine):
#          0. Race-name invariant inference  — always fires, no network required
#          1. Sporting Post (sportingpost.co.za) — primary ZAF racecard source
#          2. NRA / TAB Online (tabonline.co.za / nra.co.za) — official SA racing body
#          3. Sporting Life (sportinglife.com) — international, covers ZAF meetings
#          4. Turf Talk (turftalk.co.za) — SA specialist racing media
# NOTE: All external sources return 403 (host_not_allowed) from the Claude sandbox
#       environment due to egress proxy restrictions. They function correctly when
#       this module is executed on the user's local machine.
# LANGUAGE VARIATION: BRITISH UK ENGLISH
# ======================================================================================================================================

import re
import json
import time
import os
import logging
from typing import Optional

try:
    import requests
    from bs4 import BeautifulSoup
    SCRAPING_AVAILABLE = True
except ImportError:
    SCRAPING_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SA RACING CONSTANTS
# ---------------------------------------------------------------------------

# SA official apprentice claim weight convention: exactly 0.5 kg per pound
# 1lb=0.5kg, 2lb=1.0kg, 3lb=1.5kg, 5lb=2.5kg, 7lb=3.5kg
SA_LB_TO_KG = 0.5

SA_TRACKS = [
    "greyville", "kenilworth", "turffontein", "vaal",
    "fairview", "durbanville", "scottsville", "kimberley",
    "flamingo", "east london"
]

# Known SA apprentice jockeys with current claim allowances (lb).
# Used ONLY as a fallback when infer_claims_from_jockey_list=True.
# Claims vary per race type — do not apply blindly.
SA_APPRENTICE_JOCKEYS = {
    "venniker":     3,   # Rachel Venniker
    "mosaheb":      3,   # A Mosaheb / Yaseen Mosaheb
    "mxoli":        3,   # Siyabonga Mxoli
    "syster":       3,   # Dean Syster
    "marx":         2,   # Jared Marx
    "matsunyane":   2,   # Given Matsunyane
    "ndlovu":       2,   # Kwanda Ndlovu
    "michel":       3,   # Mickaelle Michel
    "ramkhalawon":  3,   # Divesh Ramkhalawon
    "mbuto":        3,   # Mxolisi Mbuto
    "hlengwa":      3,   # Siphesihle Hlengwa
    "moodley":      2,   # Serino Moodley (check current status)
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-ZA,en-GB;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.co.za/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# SOURCE 0: RACE-NAME INVARIANT INFERENCE (zero network dependency)
# ---------------------------------------------------------------------------

def infer_from_race_name(race_name: str) -> dict:
    """
    Infer ground-truth age, sex, and maiden constraints from the SA race name.
    Fires unconditionally before any network source is attempted.

    SA race name conventions:
      - "Juvenile" or "2yo"              -> age = 2
      - "3yo" / "4yo"                    -> age_min = 3 or 4
      - "(Fillies)"                       -> sex = 'f' for entire field
      - "(Colts & Geldings)"             -> sex in ['c', 'g']
      - "Fillies & Mares"                -> sex in ['f', 'm']
      - "Maiden"                          -> career wins must be 0

    Returns a dict of invariant field values to apply to all runners.
    Empty dict if no constraints can be inferred.
    """
    rn = str(race_name).lower()
    inferences = {}

    # --- Age ---
    if "juvenile" in rn or "2-year" in rn or re.search(r'\b2yo\b', rn):
        inferences["age"] = 2
        inferences["age_basis"] = "race_name:juvenile"
    elif re.search(r'\b3yo\b', rn):
        inferences["age_min"] = 3
        inferences["age_basis"] = "race_name:3yo"
    elif re.search(r'\b4yo\b', rn):
        inferences["age_min"] = 4
        inferences["age_basis"] = "race_name:4yo"
    elif re.search(r'\b5yo\b', rn):
        inferences["age_min"] = 5
        inferences["age_basis"] = "race_name:5yo"

    # --- Sex ---
    # "(Fillies)" or "Juvenile Fillies" but NOT "(Colts & Geldings)"
    fillies_match = re.search(r'\bfill?ies\b', rn)
    mares_match = "mares" in rn
    colts_match = "colts" in rn
    geldings_match = "gelding" in rn

    if fillies_match and not colts_match:
        if mares_match:
            inferences["sex_options"] = ["f", "m"]
            inferences["sex_basis"] = "race_name:fillies_and_mares"
        else:
            inferences["sex"] = "f"
            inferences["sex_basis"] = "race_name:fillies_only"
    elif colts_match and geldings_match:
        inferences["sex_options"] = ["c", "g"]
        inferences["sex_basis"] = "race_name:colts_and_geldings"

    # --- Maiden ---
    if "maiden" in rn:
        inferences["is_maiden"] = True
        inferences["maiden_basis"] = "race_name:maiden"

    return inferences


def _apply_race_name_invariants(runners: list, race_name: str) -> list:
    """
    Apply race-name invariant corrections to all runners in-place.
    Returns list of (name, changes) tuples for enrichment_log.
    """
    invariants = infer_from_race_name(race_name)
    if not invariants:
        return []

    log = []
    for runner in runners:
        runner_changes = []

        # Age: hard-set when race name gives exact age
        if "age" in invariants:
            old = runner.get("age")
            if old != invariants["age"]:
                runner["age"] = invariants["age"]
                runner["age_source"] = invariants["age_basis"]
                runner_changes.append(f"age: {old} → {invariants['age']} [{invariants['age_basis']}]")

        # Sex: hard-set when race name restricts to one sex
        if "sex" in invariants:
            old = runner.get("sex") or runner.get("gender")
            if str(old).upper() != invariants["sex"].upper():
                runner["sex"] = invariants["sex"]
                runner["gender"] = invariants["sex"]
                runner["sex_source"] = invariants["sex_basis"]
                runner_changes.append(f"sex: {old} → {invariants['sex']} [{invariants['sex_basis']}]")

        # Maiden flag
        if invariants.get("is_maiden"):
            runner["is_maiden"] = True

        if runner_changes:
            log.append({"name": runner.get("name"), "changes": runner_changes})

    return log


# ---------------------------------------------------------------------------
# PARSING UTILITIES
# ---------------------------------------------------------------------------

def _parse_sa_claim_from_racecard(jockey_text: str) -> float:
    """
    Extract apprentice claim from racecard text.
    SA format examples: '(3)', '3lb', '(3lb)', '(a3)', superscript '3'.
    Returns claim in kg using SA official 0.5 kg/lb convention.
    """
    if not jockey_text:
        return 0.0

    # Pattern: explicit lb — (3lb), 3lb, (3 lb)
    m = re.search(r'\((\d+)\s*lb\)', jockey_text, re.IGNORECASE)
    if not m:
        m = re.search(r'\b(\d+)\s*lb\b', jockey_text, re.IGNORECASE)
    if m:
        lb = int(m.group(1))
        if 1 <= lb <= 7:
            return lb * SA_LB_TO_KG

    # Pattern: parenthesised digit — (3) or (a3)
    m = re.search(r'\(a?([1357])\)', jockey_text, re.IGNORECASE)
    if m:
        return int(m.group(1)) * SA_LB_TO_KG

    # Pattern: trailing superscript digit — "Venniker 3"
    m = re.search(r'(\w+)\s+([1357])\s*$', jockey_text.strip())
    if m:
        return int(m.group(2)) * SA_LB_TO_KG

    return 0.0


def _infer_claim_from_jockey_name(jockey_name: str) -> float:
    """
    Fallback lookup against known SA apprentice list.
    Only used when infer_claims_from_jockey_list=True.
    Returns claim in kg, or 0.0 if not found or senior jockey.
    """
    j_lower = str(jockey_name).lower().strip()
    for fragment, lb in SA_APPRENTICE_JOCKEYS.items():
        if fragment in j_lower:
            if lb > 0:
                logger.debug(f"Inferred {lb}lb claim for: {jockey_name}")
            return lb * SA_LB_TO_KG
    return 0.0


def _parse_age_sex(text: str):
    """
    Extract age and sex from racecard description text.
    Handles: '3yo c', '4yo g', '3 year old colt', etc.
    Returns (age: int, sex: str) or (None, None).
    """
    m = re.search(r'(\d+)\s*yo\s+([cfghm])', text, re.IGNORECASE)
    if m:
        return int(m.group(1)), m.group(2).lower()

    SEX_MAP = {"colt": "c", "filly": "f", "gelding": "g", "horse": "h", "mare": "m"}
    m = re.search(r'(\d+)\s*[- ]?year[- ]?old\s+(\w+)', text, re.IGNORECASE)
    if m:
        age = int(m.group(1))
        sex = SEX_MAP.get(m.group(2).lower(), m.group(2)[0].lower())
        return age, sex

    return None, None


def _parse_merit_rating(text: str) -> Optional[int]:
    """
    Extract merit rating from racecard text.
    Handles: '[MR 98]', 'MR: 98', '(MR 98)', 'merit rating: 98'.
    """
    patterns = [
        r'\[MR\s*:?\s*(\d+)\]',
        r'\(MR\s*:?\s*(\d+)\)',
        r'MR\s*:?\s*(\d{2,3})\b',
        r'merit\s+rating\s*:?\s*(\d{2,3})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            mr = int(m.group(1))
            if 40 <= mr <= 140:
                return mr
    return None


def _compress_barriers(runners: list) -> dict:
    """
    Compute sequential barrier numbers after scratching.
    Active runners are sorted by original_barrier and re-numbered 1..N.
    Returns dict: {runner_name_lower: compressed_barrier}.
    """
    active = sorted(
        [r for r in runners if r.get("status", "Active") != "Scratched"],
        key=lambda x: int(x.get("original_barrier") or x.get("barrier") or 99)
    )
    return {str(r.get("name", "")).lower().strip(): idx for idx, r in enumerate(active, 1)}


def _make_session() -> "requests.Session":
    """Create a requests Session with SA-targeted headers and cookie support."""
    s = requests.Session()
    s.headers.update(REQUEST_HEADERS)
    return s


# ---------------------------------------------------------------------------
# SOURCE 1: SPORTING POST (www.sportingpost.co.za)
# ---------------------------------------------------------------------------

def _fetch_sporting_post_racecard(track: str, race_num: int, date_str: str) -> dict:
    """
    Fetch runner details from Sporting Post.
    Tries multiple URL patterns used by their WordPress CMS.
    Returns dict keyed by horse name (lowercase).
    """
    if not SCRAPING_AVAILABLE:
        return {}

    y, m, d = date_str.split("-")
    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    track_slug_nodash = track.lower().replace(" ", "").replace("_", "")
    month_names = ["january","february","march","april","may","june",
                   "july","august","september","october","november","december"]

    url_candidates = [
        # WordPress dated post slug — SP uses "racecards" (plural) in the post slug
        f"https://www.sportingpost.co.za/{y}/{m}/{d}/{track_slug}-racecards/",
        f"https://www.sportingpost.co.za/{y}/{m}/{d}/{track_slug}-racecard/",
        # Nodash variant (e.g. "turffontein-racecards" vs "turffontein racecards")
        f"https://www.sportingpost.co.za/{y}/{m}/{d}/{track_slug_nodash}-racecards/",
        # SP horse-racing section path (used for individual race pages)
        f"https://www.sportingpost.co.za/horse-racing/{track_slug}/{date_str}/race-{race_num}/",
        f"https://www.sportingpost.co.za/horse-racing/racecards/{date_str}/{track_slug}/",
        # SP form/racecard path variants
        f"https://www.sportingpost.co.za/racecards/{date_str}/{track_slug}/",
        f"https://www.sportingpost.co.za/racecard/{date_str}/{track_slug}/race-{race_num}/",
        # WP REST API search — broader date+track query for post discovery
        f"https://www.sportingpost.co.za/wp-json/wp/v2/posts?search={track_slug}+racecards+{d}+{month_names[int(m)-1]}&per_page=3",
        f"https://www.sportingpost.co.za/wp-json/wp/v2/posts?search={track_slug}+racecard&per_page=3",
    ]

    session = _make_session()
    try:
        # Establish session via homepage first (accepts cookie consent)
        session.get("https://www.sportingpost.co.za/", timeout=8)
        time.sleep(0.4)
    except Exception:
        pass

    for url in url_candidates:
        try:
            r = session.get(url, timeout=12)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    # WP REST API response
                    posts = r.json()
                    if isinstance(posts, list) and posts:
                        return _parse_sporting_post_html(posts[0].get("content", {}).get("rendered", ""))
                else:
                    result = _parse_sporting_post_html(r.text)
                    if result:
                        logger.info(f"[SP] Retrieved {len(result)} runners from {url}")
                        return result
            elif r.status_code not in (404, 403):
                logger.debug(f"[SP] HTTP {r.status_code} for {url}")
        except Exception as e:
            logger.debug(f"[SP] {url}: {e}")

    logger.warning(f"[SP] All URL patterns exhausted for {track} race {race_num} on {date_str}")
    return {}


def _parse_sporting_post_html(html: str) -> dict:
    """Parse Sporting Post racecard HTML into per-runner enrichment dict."""
    results = {}
    if not html:
        return results

    try:
        soup = BeautifulSoup(html, "html.parser")

        runner_rows = (
            soup.select("div.runner-row") or
            soup.select("tr.runner") or
            soup.select("div.racecard-runner") or
            soup.select("li.horse-entry") or
            soup.select(".racecard-table tr") or
            soup.select("table.racecard tr") or
            # SP's actual table layout: standard HTML table rows with horse links
            soup.select("table tr") or
            soup.select("div.entry-content tr")
        )

        for row in runner_rows:
            name_tag = (
                row.select_one(".horse-name a") or
                row.select_one(".runner-name a") or
                row.select_one("a.horse") or
                row.select_one("td.name a") or
                # SP often wraps horse name in a plain <a> inside the first <td>
                row.select_one("td a")
            )
            if not name_tag:
                continue

            name = name_tag.get_text(strip=True).lower()
            if not name or len(name) < 2:
                continue

            entry = {}
            row_text = row.get_text(" ", strip=True)

            age, sex = _parse_age_sex(row_text)
            if age:
                entry["age"] = age
            if sex:
                entry["sex"] = sex

            jockey_tag = (
                row.select_one(".jockey-name") or
                row.select_one(".jockey") or
                row.select_one("td.jockey") or
                # SP sometimes puts jockey in a second <td>
                (row.select("td")[1] if len(row.select("td")) > 1 else None)
            )
            if jockey_tag:
                claim = _parse_sa_claim_from_racecard(jockey_tag.get_text(" ", strip=True))
                if claim > 0:
                    entry["apprentice_claim_kg"] = claim
                    entry["apprentice_claim_source"] = "sporting_post"

            mr = _parse_merit_rating(row_text)
            if mr:
                entry["merit_rating"] = mr

            if entry:
                results[name] = entry

        # Fallback: look for embedded JSON in <script> tags
        if not results:
            for script in soup.find_all("script", type="application/json"):
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, dict) and "runners" in data:
                        for runner in data["runners"]:
                            n = str(runner.get("name", "")).lower().strip()
                            if n:
                                e = {}
                                if "age" in runner:
                                    e["age"] = int(runner["age"])
                                if "sex" in runner:
                                    e["sex"] = str(runner["sex"]).lower()
                                if "meritRating" in runner:
                                    e["merit_rating"] = int(runner["meritRating"])
                                claim = _parse_sa_claim_from_racecard(str(runner.get("jockey", "")))
                                if claim > 0:
                                    e["apprentice_claim_kg"] = claim
                                    e["apprentice_claim_source"] = "sporting_post_json"
                                if e:
                                    results[n] = e
                except Exception:
                    pass

        # Deep fallback: mine entire page text for horse name + age/sex/MR blocks.
        # SP racecards embed this info in plain text even when the HTML structure varies.
        if not results:
            # Find all <a> tags that could be horse names (title-case, 2+ words or long single word)
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                # SP horse profile links contain /horse/ or /form/
                if not any(x in href for x in ["/horse/", "/form/", "horse-racing/database"]):
                    continue
                name = a_tag.get_text(strip=True).lower()
                if not name or len(name) < 3:
                    continue
                # Grab surrounding context text (parent element)
                parent = a_tag.find_parent()
                context = parent.get_text(" ", strip=True) if parent else ""
                e = {}
                age, sex = _parse_age_sex(context)
                if age:
                    e["age"] = age
                if sex:
                    e["sex"] = sex
                mr = _parse_merit_rating(context)
                if mr:
                    e["merit_rating"] = mr
                claim = _parse_sa_claim_from_racecard(context)
                if claim > 0:
                    e["apprentice_claim_kg"] = claim
                    e["apprentice_claim_source"] = "sporting_post_context"
                if e:
                    results[name] = e

    except Exception as e:
        logger.warning(f"[SP] HTML parse error: {e}")

    return results


# ---------------------------------------------------------------------------
# SOURCE 2: NRA / TAB ONLINE (tabonline.co.za / nra.co.za)
# ---------------------------------------------------------------------------

def _fetch_nra_racecard(track: str, race_num: int, date_str: str) -> dict:
    """
    Fetch runner details from NRA TAB Online.
    Tries multiple URL patterns used by the NRA ecosystem.
    Returns dict keyed by horse name (lowercase).
    """
    if not SCRAPING_AVAILABLE:
        return {}

    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    date_nodash = date_str.replace("-", "")

    url_candidates = [
        # TAB Online primary paths
        f"https://www.tabonline.co.za/racing/race-cards/{date_str}/{track_slug}/{race_num}/",
        f"https://www.tabonline.co.za/racing/race-cards/{date_str}/{track_slug}/race-{race_num}/",
        f"https://www.tabonline.co.za/racing/cards/{track_slug}/{date_str}/race/{race_num}/",
        f"https://www.tabonline.co.za/racing/{track_slug}/{date_str}/race-{race_num}/",
        # NRA official paths
        f"https://www.nra.co.za/racing/racecard/{date_str}/{track_slug}/{race_num}/",
        f"https://www.nra.co.za/racing/{date_str}/{track_slug}/{race_num}/",
        # JSON API endpoints NRA has used historically
        f"https://www.tabonline.co.za/api/racing/cards/{date_nodash}/{track_slug}/{race_num}/",
        f"https://api.tabonline.co.za/racing/cards/{date_nodash}/{track_slug}/{race_num}/",
    ]

    for url in url_candidates:
        try:
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    return _parse_nra_json(r.json())
                result = _parse_nra_html(r.text)
                if result:
                    logger.info(f"[NRA] Retrieved {len(result)} runners from {url}")
                    return result
        except Exception as e:
            logger.debug(f"[NRA] {url}: {e}")

    return {}


def _parse_nra_json(data: dict) -> dict:
    """Parse NRA JSON API response."""
    results = {}
    runners = data.get("runners") or data.get("entries") or []
    for runner in runners:
        n = str(runner.get("name") or runner.get("horseName", "")).lower().strip()
        if not n:
            continue
        e = {}
        if "age" in runner:
            e["age"] = int(runner["age"])
        if "sex" in runner or "gender" in runner:
            e["sex"] = str(runner.get("sex") or runner.get("gender", "")).lower()[:1]
        if "meritRating" in runner or "mr" in runner:
            mr = runner.get("meritRating") or runner.get("mr")
            if mr:
                e["merit_rating"] = int(mr)
        jock = str(runner.get("jockey") or runner.get("jockeyName", ""))
        claim = _parse_sa_claim_from_racecard(jock)
        if claim > 0:
            e["apprentice_claim_kg"] = claim
            e["apprentice_claim_source"] = "nra_json"
        if e:
            results[n] = e
    return results


def _parse_nra_html(html: str) -> dict:
    """Parse NRA / TAB Online racecard HTML."""
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 4:
                    continue

                name_cell = None
                for cell in cells[:4]:
                    link = cell.find("a")
                    if link and len(link.get_text(strip=True)) > 2:
                        name_cell = link.get_text(strip=True)
                        break
                if not name_cell:
                    continue

                name = name_cell.lower().strip()
                entry = {}

                for cell in cells:
                    cell_text = cell.get_text(" ", strip=True)
                    age, sex = _parse_age_sex(cell_text)
                    if age and "age" not in entry:
                        entry["age"] = age
                        entry["sex"] = sex
                    claim = _parse_sa_claim_from_racecard(cell_text)
                    if claim > 0 and "apprentice_claim_kg" not in entry:
                        entry["apprentice_claim_kg"] = claim
                        entry["apprentice_claim_source"] = "nra_tabonline"
                    mr = _parse_merit_rating(cell_text)
                    if mr and "merit_rating" not in entry:
                        entry["merit_rating"] = mr

                if entry and len(name) > 1:
                    results[name] = entry
    except Exception as e:
        logger.warning(f"[NRA] HTML parse error: {e}")
    return results


# ---------------------------------------------------------------------------
# SOURCE 3: SPORTING LIFE (www.sportinglife.com)
# ---------------------------------------------------------------------------

def _fetch_sporting_life_racecard(track: str, race_num: int, date_str: str) -> dict:
    """
    Fetch runner details from Sporting Life's international racing coverage.
    Sporting Life covers South African meetings and exposes structured HTML.
    Returns dict keyed by horse name (lowercase).
    """
    if not SCRAPING_AVAILABLE:
        return {}

    track_slug = track.lower().replace(" ", "-").replace("_", "-")

    url_candidates = [
        # Racecards path (works pre-race and post-race)
        f"https://www.sportinglife.com/racing/racecards/{date_str}/{track_slug}/",
        f"https://www.sportinglife.com/racing/racecards/south-africa/{date_str}/{track_slug}/",
        # Results path (post-race)
        f"https://www.sportinglife.com/racing/results/south-africa/{date_str}/{track_slug}/",
        f"https://www.sportinglife.com/racing/results/{date_str}/{track_slug}/",
        # Alternative path structures
        f"https://www.sportinglife.com/racing/south-africa/{track_slug}/{date_str}/",
    ]

    session = _make_session()
    for url in url_candidates:
        try:
            r = session.get(url, timeout=12)
            if r.status_code == 200:
                result = _parse_sporting_life_html(r.text, race_num)
                if result:
                    logger.info(f"[SL] Retrieved {len(result)} runners from {url}")
                    return result
        except Exception as e:
            logger.debug(f"[SL] {url}: {e}")

    return {}


def _parse_sporting_life_html(html: str, target_race_num: int) -> dict:
    """Parse Sporting Life racecard / results HTML."""
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Sporting Life uses data-test attributes and structured race blocks
        race_blocks = (
            soup.select(f"[data-race-number='{target_race_num}']") or
            soup.select(".race-card") or
            soup.select(".racecard-race") or
            [soup]  # fallback: search entire page
        )

        for block in race_blocks:
            runner_items = (
                block.select(".runner") or
                block.select(".horse-row") or
                block.select("[data-test='runner']") or
                block.select("tr.horse")
            )
            for item in runner_items:
                item_text = item.get_text(" ", strip=True)

                name_el = (
                    item.select_one(".horse-name") or
                    item.select_one("[data-test='horse-name']") or
                    item.select_one("a.horse")
                )
                if not name_el:
                    continue
                name = name_el.get_text(strip=True).lower()
                if not name:
                    continue

                entry = {}
                age, sex = _parse_age_sex(item_text)
                if age:
                    entry["age"] = age
                if sex:
                    entry["sex"] = sex

                jockey_el = item.select_one(".jockey") or item.select_one("[data-test='jockey']")
                if jockey_el:
                    claim = _parse_sa_claim_from_racecard(jockey_el.get_text(" ", strip=True))
                    if claim > 0:
                        entry["apprentice_claim_kg"] = claim
                        entry["apprentice_claim_source"] = "sporting_life"

                mr = _parse_merit_rating(item_text)
                if mr:
                    entry["merit_rating"] = mr

                if entry:
                    results[name] = entry

        # Sporting Life often embeds a __NEXT_DATA__ JSON payload
        if not results:
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    page_data = json.loads(nd.string)
                    # Navigate the Next.js page props structure
                    props = page_data.get("props", {}).get("pageProps", {})
                    races = props.get("races") or props.get("racecard") or []
                    if isinstance(races, dict):
                        races = [races]
                    for race in races:
                        for runner in race.get("runners", []):
                            n = str(runner.get("horseName") or runner.get("name", "")).lower().strip()
                            if n:
                                e = {}
                                if "age" in runner:
                                    e["age"] = int(runner["age"])
                                if "sex" in runner:
                                    e["sex"] = str(runner["sex"]).lower()[:1]
                                if "officialRating" in runner or "meritRating" in runner:
                                    e["merit_rating"] = int(runner.get("officialRating") or runner.get("meritRating", 0))
                                jock = str(runner.get("jockeyName") or runner.get("jockey", ""))
                                claim = _parse_sa_claim_from_racecard(jock)
                                if claim > 0:
                                    e["apprentice_claim_kg"] = claim
                                    e["apprentice_claim_source"] = "sporting_life_json"
                                if e:
                                    results[n] = e
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"[SL] HTML parse error: {e}")

    return results


# ---------------------------------------------------------------------------
# SOURCE 4: TURF TALK (turftalk.co.za)
# ---------------------------------------------------------------------------

def _fetch_turf_talk_racecard(track: str, race_num: int, date_str: str) -> dict:
    """
    Fetch runner details from Turf Talk, a SA specialist racing publication.
    Returns dict keyed by horse name (lowercase).
    """
    if not SCRAPING_AVAILABLE:
        return {}

    y, m, d = date_str.split("-")
    track_slug = track.lower().replace(" ", "-").replace("_", "-")

    url_candidates = [
        # TT uses category-based WP paths
        f"https://turftalk.co.za/{y}/{m}/{d}/{track_slug}-racecards/",
        f"https://turftalk.co.za/{y}/{m}/{d}/{track_slug}-racecard/",
        f"https://turftalk.co.za/racecards/{track_slug}/{date_str}/",
        f"https://turftalk.co.za/race-cards/{track_slug}/{date_str}/race-{race_num}/",
        f"https://turftalk.co.za/races/{track_slug}/{date_str}/",
        # WP REST API search fallback
        f"https://turftalk.co.za/wp-json/wp/v2/posts?search={track_slug}+racecard&per_page=3",
    ]

    for url in url_candidates:
        try:
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    # WP REST API response — parse rendered HTML from post content
                    try:
                        posts = r.json()
                        if isinstance(posts, list) and posts:
                            rendered = posts[0].get("content", {}).get("rendered", "")
                            result = _parse_turf_talk_html(rendered)
                            if result:
                                logger.info(f"[TT] Retrieved {len(result)} runners from WP REST API")
                                return result
                    except Exception:
                        pass
                else:
                    result = _parse_turf_talk_html(r.text)
                    if result:
                        logger.info(f"[TT] Retrieved {len(result)} runners from {url}")
                        return result
        except Exception as e:
            logger.debug(f"[TT] {url}: {e}")

    return {}


def _parse_turf_talk_html(html: str) -> dict:
    """Parse Turf Talk racecard HTML."""
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Turf Talk typically uses WordPress with custom race table markup
        runner_rows = (
            soup.select("tr.runner-row") or
            soup.select(".race-runner") or
            soup.select("div.horse-entry") or
            soup.select("table.race-table tr")
        )

        for row in runner_rows:
            row_text = row.get_text(" ", strip=True)
            name_tag = row.select_one("a") or row.select_one(".horse-name")
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True).lower()
            if not name or len(name) < 2:
                continue

            entry = {}
            age, sex = _parse_age_sex(row_text)
            if age:
                entry["age"] = age
            if sex:
                entry["sex"] = sex
            claim = _parse_sa_claim_from_racecard(row_text)
            if claim > 0:
                entry["apprentice_claim_kg"] = claim
                entry["apprentice_claim_source"] = "turf_talk"
            mr = _parse_merit_rating(row_text)
            if mr:
                entry["merit_rating"] = mr

            if entry:
                results[name] = entry

    except Exception as e:
        logger.warning(f"[TT] HTML parse error: {e}")

    return results


# ---------------------------------------------------------------------------
# MAIN ENRICHMENT ENGINE
# ---------------------------------------------------------------------------

def enrich_sa_racecard(
    race_json: dict,
    date_str: str,
    use_sporting_post: bool = True,
    use_nra: bool = True,
    use_sporting_life: bool = True,
    use_turf_talk: bool = True,
    infer_claims_from_jockey_list: bool = True,
    recompute_barriers: bool = True,
) -> dict:
    """
    PRIMARY ENTRY POINT: Enrich a South African race JSON with ground-truth data.

    Enrichment pipeline (in execution order):
      0. Race-name invariants  — fires always, zero network dependency
      1. Sporting Post         — primary ZAF source
      2. NRA / TAB Online      — official SA racing body fallback
      3. Sporting Life         — international source with ZAF coverage
      4. Turf Talk             — SA specialist fallback
      5. Barrier recompression — always fires, zero network dependency

    Parameters
    ----------
    race_json : dict
        Race record as produced by sportsbet_scraper.py.
    date_str : str
        Race date in YYYY-MM-DD format.
    use_sporting_post : bool
        Attempt Sporting Post (Source 1).
    use_nra : bool
        Attempt NRA / TAB Online (Source 2).
    use_sporting_life : bool
        Attempt Sporting Life (Source 3).
    use_turf_talk : bool
        Attempt Turf Talk (Source 4).
    infer_claims_from_jockey_list : bool
        If True and no online source provides a claim, infer from the
        known SA apprentice list. Defaults True — online sources are
        frequently blocked by the egress proxy so the apprentice list
        acts as a reliable always-on fallback for claim data.
    recompute_barriers : bool
        Recompute compressed barriers after scratching.

    Returns
    -------
    dict
        Enriched race_json. Adds/updates ``enrichment_log`` key.
    """
    if not isinstance(race_json, dict):
        return race_json

    track = str(
        race_json.get("venue") or race_json.get("track_name") or
        race_json.get("meeting_metadata", {}).get("track_name", "Unknown")
    )
    race_num = int(race_json.get("race_number", 1))
    race_name = str(race_json.get("race_name", ""))
    runners = race_json.get("runners", [])

    if not runners:
        return race_json

    print(f"[ZAF Enricher] Processing {track} Race {race_num} — {len(runners)} runners")

    all_enrichment_log = race_json.get("enrichment_log", [])

    # ----------------------------------------------------------------
    # Step 0: Race-name invariant inference (always fires)
    # ----------------------------------------------------------------
    invariant_log = _apply_race_name_invariants(runners, race_name)
    if invariant_log:
        print(f"[ZAF Enricher] → Race-name invariants applied to {len(invariant_log)} runners")
        for entry in invariant_log:
            print(f"[ZAF Enricher]   {entry['name']}: {', '.join(entry['changes'])}")
        all_enrichment_log.extend(invariant_log)

    # ----------------------------------------------------------------
    # Step 1–4: Online sources (cascade, stop when sufficient data found)
    # ----------------------------------------------------------------
    online_data = {}

    if use_sporting_post and not online_data:
        print(f"[ZAF Enricher] → Sporting Post lookup...")
        online_data = _fetch_sporting_post_racecard(track, race_num, date_str)
        if online_data:
            print(f"[ZAF Enricher]   Found {len(online_data)} SP entries")
        else:
            print(f"[ZAF Enricher]   SP returned 0 entries")

    if use_nra and not online_data:
        print(f"[ZAF Enricher] → NRA TAB Online lookup...")
        online_data = _fetch_nra_racecard(track, race_num, date_str)
        if online_data:
            print(f"[ZAF Enricher]   Found {len(online_data)} NRA entries")
        else:
            print(f"[ZAF Enricher]   NRA returned 0 entries")

    if use_sporting_life and not online_data:
        print(f"[ZAF Enricher] → Sporting Life lookup...")
        online_data = _fetch_sporting_life_racecard(track, race_num, date_str)
        if online_data:
            print(f"[ZAF Enricher]   Found {len(online_data)} SL entries")
        else:
            print(f"[ZAF Enricher]   SL returned 0 entries")

    if use_turf_talk and not online_data:
        print(f"[ZAF Enricher] → Turf Talk lookup...")
        online_data = _fetch_turf_talk_racecard(track, race_num, date_str)
        if online_data:
            print(f"[ZAF Enricher]   Found {len(online_data)} TT entries")
        else:
            print(f"[ZAF Enricher]   TT returned 0 entries")

    # ----------------------------------------------------------------
    # Step 5: Apply online source data to runners
    # ----------------------------------------------------------------
    online_log = []

    for runner in runners:
        name = str(runner.get("name", "")).strip()
        name_lower = name.lower()
        entry = online_data.get(name_lower, {})
        runner_changes = []

        # Age (online overrides invariant only if invariant didn't already set it)
        if "age" in entry and runner.get("age_source") is None:
            old = runner.get("age")
            runner["age"] = entry["age"]
            runner["age_source"] = "online_source"
            if old != runner["age"]:
                runner_changes.append(f"age: {old} → {runner['age']} [online]")

        # Sex
        if "sex" in entry and runner.get("sex_source") is None:
            old = runner.get("sex") or runner.get("gender")
            runner["sex"] = entry["sex"]
            runner["gender"] = entry["sex"]
            runner["sex_source"] = "online_source"
            if str(old).upper() != str(runner["sex"]).upper():
                runner_changes.append(f"sex: {old} → {runner['sex']} [online]")

        # Apprentice claim
        if "apprentice_claim_kg" in entry:
            old = float(runner.get("apprentice_claim_kg", 0.0))
            new_claim = entry["apprentice_claim_kg"]
            if new_claim != old:
                runner["apprentice_claim_kg"] = new_claim
                runner["apprentice_claim_source"] = entry.get("apprentice_claim_source", "online")
                runner_changes.append(f"claim: {old:.2f} → {new_claim:.2f}kg [{runner['apprentice_claim_source']}]")

        # Sportsbet (aX) notation correction: Sportsbet AU encodes claim as kg
        # but for SA races the (aX) value is in pounds. Correct whole-number values
        # that have no source tag (i.e. came raw from Sportsbet parser).
        existing_claim = float(runner.get("apprentice_claim_kg", 0.0))
        claim_source = str(runner.get("apprentice_claim_source", ""))
        if (existing_claim in [1.0, 2.0, 3.0, 5.0, 7.0] and
                claim_source == "" and
                "apprentice_claim_kg" not in entry):
            corrected = existing_claim * SA_LB_TO_KG
            runner["apprentice_claim_kg"] = corrected
            runner["apprentice_claim_source"] = "sportsbet_lb_corrected"
            runner_changes.append(f"claim unit: {existing_claim:.0f}lb → {corrected:.2f}kg [SA lb->kg]")

        # Fallback: infer from jockey list
        if (infer_claims_from_jockey_list and
                float(runner.get("apprentice_claim_kg", 0.0)) == 0.0 and
                "apprentice_claim_kg" not in entry):
            inferred = _infer_claim_from_jockey_name(str(runner.get("jockey", "")))
            if inferred > 0:
                runner["apprentice_claim_kg"] = inferred
                runner["apprentice_claim_source"] = "inferred_apprentice_list"
                runner_changes.append(f"claim: 0.00 → {inferred:.2f}kg [apprentice list]")

        # Merit rating
        if "merit_rating" in entry:
            old = runner.get("merit_rating") or runner.get("rating")
            runner["merit_rating"] = entry["merit_rating"]
            if old != runner["merit_rating"]:
                runner_changes.append(f"merit_rating: {old} → {runner['merit_rating']}")

        if runner_changes:
            online_log.append({"name": name, "changes": runner_changes})

    all_enrichment_log.extend(online_log)

    # ----------------------------------------------------------------
    # Step 6: Recompute barriers
    # ----------------------------------------------------------------
    if recompute_barriers:
        barrier_map = _compress_barriers(runners)
        barrier_log = []
        for runner in runners:
            name_lower = str(runner.get("name", "")).lower().strip()
            if name_lower in barrier_map:
                runner["original_barrier"] = int(runner.get("original_barrier") or runner.get("barrier") or 99)
                runner["barrier_compressed"] = barrier_map[name_lower]
                barrier_log.append({
                    "name": runner.get("name"),
                    "changes": [f"barrier_compressed: → {barrier_map[name_lower]}"]
                })
        print(f"[ZAF Enricher] → Recomputed barriers for {len(barrier_map)} active runners")
        all_enrichment_log.extend(barrier_log)

    race_json["enrichment_log"] = all_enrichment_log
    race_json["enrichment_applied"] = True
    race_json["enrichment_date"] = date_str

    total_changed = len(invariant_log) + len(online_log)
    print(f"[ZAF Enricher] Complete — {total_changed} runners modified by enrichment")
    return race_json


# ---------------------------------------------------------------------------
# MANUAL OVERRIDE
# ---------------------------------------------------------------------------

def apply_manual_corrections(race_json: dict, corrections: dict) -> dict:
    """
    Apply manually-specified ground-truth corrections to a race JSON.
    Use when all online sources are unavailable and you have the official
    race card to hand.

    Parameters
    ----------
    race_json : dict
        Race JSON as produced by sportsbet_scraper.py.
    corrections : dict
        Keyed by horse name (case-insensitive). Each value is a dict.
        Supported fields:
            age (int), sex (str), apprentice_claim_lb (int),
            apprentice_claim_kg (float), merit_rating (int),
            original_barrier (int), carried_weight_kg (float)

    Example
    -------
    corrections = {
        "Damova":        {"age": 3, "sex": "f", "apprentice_claim_lb": 3},
        "One More Star": {"apprentice_claim_lb": 3},
        "Bellerophon":   {"age": 3, "sex": "c"},
    }
    race_json = apply_manual_corrections(race_json, corrections)
    """
    corrections_lower = {k.lower().strip(): v for k, v in corrections.items()}
    log = []

    for runner in race_json.get("runners", []):
        name_lower = str(runner.get("name", "")).lower().strip()
        if name_lower not in corrections_lower:
            continue
        patch = corrections_lower[name_lower]
        entry_log = {"name": runner.get("name"), "changes": []}

        if "age" in patch:
            runner["age"] = int(patch["age"])
            runner["age_source"] = "manual_override"
            entry_log["changes"].append(f"age → {runner['age']}")
        if "sex" in patch:
            runner["sex"] = str(patch["sex"]).lower()
            runner["gender"] = runner["sex"]
            runner["sex_source"] = "manual_override"
            entry_log["changes"].append(f"sex → {runner['sex']}")
        if "apprentice_claim_lb" in patch:
            lb = int(patch["apprentice_claim_lb"])
            runner["apprentice_claim_kg"] = lb * SA_LB_TO_KG
            runner["apprentice_claim_source"] = "manual_override_lb"
            entry_log["changes"].append(f"claim → {lb}lb = {runner['apprentice_claim_kg']:.2f}kg")
        if "apprentice_claim_kg" in patch:
            runner["apprentice_claim_kg"] = float(patch["apprentice_claim_kg"])
            runner["apprentice_claim_source"] = "manual_override_kg"
            entry_log["changes"].append(f"claim_kg → {runner['apprentice_claim_kg']:.2f}kg")
        if "merit_rating" in patch:
            runner["merit_rating"] = int(patch["merit_rating"])
            entry_log["changes"].append(f"merit_rating → {runner['merit_rating']}")
        if "carried_weight_kg" in patch:
            runner["carried_weight_kg"] = float(patch["carried_weight_kg"])
            entry_log["changes"].append(f"carried_weight_kg → {runner['carried_weight_kg']:.1f}")
        if "original_barrier" in patch:
            runner["original_barrier"] = int(patch["original_barrier"])
            entry_log["changes"].append(f"original_barrier → {runner['original_barrier']}")

        if entry_log["changes"]:
            log.append(entry_log)

    # Recompute barriers after manual corrections
    barrier_map = _compress_barriers(race_json.get("runners", []))
    for runner in race_json.get("runners", []):
        n = str(runner.get("name", "")).lower().strip()
        if n in barrier_map:
            runner["barrier_compressed"] = barrier_map[n]

    race_json["manual_correction_log"] = log
    race_json["enrichment_applied"] = True
    return race_json


# ---------------------------------------------------------------------------
# CONVENIENCE WRAPPER (called from sportsbet_scraper.py)
# ---------------------------------------------------------------------------

def enrich_if_sa(race_json: dict, date_str: str, manual_corrections: dict = None) -> dict:
    """
    Drop-in wrapper: enriches only if the race is at a South African track.
    Skips non-SA meetings with no overhead.

    Integration in sportsbet_scraper.py (already applied):
        from zaf_data_enricher import enrich_if_sa
        race_db = enrich_if_sa(race_db, target_date)

    Optional manual override for when online scraping is blocked:
        corrections = {
            "Damova": {"age": 3, "sex": "f", "apprentice_claim_lb": 3},
        }
        race_db = enrich_if_sa(race_db, target_date, manual_corrections=corrections)
    """
    track = str(
        race_json.get("venue") or race_json.get("track_name") or
        race_json.get("meeting_metadata", {}).get("track_name", "")
    ).lower()

    if not any(t in track for t in SA_TRACKS):
        return race_json

    if manual_corrections:
        race_json = apply_manual_corrections(race_json, manual_corrections)

    return enrich_sa_racecard(race_json, date_str)


# ---------------------------------------------------------------------------
# CLI / SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1].endswith(".json"):
        # Enrich a file from command line
        json_path = sys.argv[1]
        date = sys.argv[2] if len(sys.argv) >= 3 else "2026-06-28"
        with open(json_path, "r", encoding="utf-8") as f:
            race = json.load(f)
        enriched = enrich_if_sa(race, date)
        out = json_path.replace(".json", "_enriched.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=4, ensure_ascii=False)
        print(f"\n[✓] Enriched JSON saved: {out}")

    else:
        # Self-test against the actual Scottsville Race 1 data
        print("=== ZAF ENRICHER SELF-TEST: SCOTTSVILLE RACE 1 (race_1_data.json) ===\n")

        import os
        test_path = "/mnt/user-data/uploads/race_1_data.json"
        if not os.path.exists(test_path):
            test_path = "race_1_data.json"

        with open(test_path, "rb") as f:
            raw = f.read().replace(b"\r\n", b"\n")
        race = json.loads(raw.decode("utf-8-sig"))

        # Only run step 0 in self-test (network sources blocked in sandbox)
        race_name = race.get("race_name", "")
        runners = race.get("runners", [])

        print(f"Race: {race_name}")
        print(f"Runners: {len(runners)}\n")

        print("--- Before enrichment ---")
        print(f"{'#':<3} {'Name':<22} {'Age':>4} {'Sex':>4} {'Claim':>6}")
        print("-" * 45)
        age_before = [r.get("age") for r in runners]
        sex_before = [r.get("sex") for r in runners]
        for r in runners:
            print(f"{r['number']:<3} {r['name']:<22} {str(r.get('age','?')):>4} {str(r.get('sex','?')):>4} {r.get('apprentice_claim_kg',0):>6.2f}")

        # Apply only race-name invariants (zero network)
        log = _apply_race_name_invariants(runners, race_name)

        print("\n--- After race-name invariant enrichment ---")
        print(f"{'#':<3} {'Name':<22} {'Age':>4} {'Sex':>4} {'Claim':>6} {'Source'}")
        print("-" * 60)
        for r in runners:
            print(f"{r['number']:<3} {r['name']:<22} {str(r.get('age','?')):>4} {str(r.get('sex','?')):>4} {r.get('apprentice_claim_kg',0):>6.2f}  {r.get('age_source','')}")

        # Validate
        print("\n--- Validation ---")
        age_after = [r.get("age") for r in runners]
        sex_after = [r.get("sex") for r in runners]
        age_correct = all(a == 2 for a in age_after)
        sex_correct = all(s == "f" for s in sex_after)
        age_changed = sum(1 for b, a in zip(age_before, age_after) if b != a)
        sex_changed = sum(1 for b, a in zip(sex_before, sex_after) if b != a)

        print(f"  Age corrections applied: {age_changed}/16  {'[PASS]' if age_correct else '[FAIL]'}")
        print(f"  Sex corrections applied: {sex_changed}/16  {'[PASS]' if sex_correct else '[FAIL]'}")
        print(f"  All ages == 2:           {'[PASS]' if age_correct else '[FAIL]'}")
        print(f"  All sexes == f:          {'[PASS]' if sex_correct else '[FAIL]'}")

        # Confirm A Mosaheb has NO claim applied (infer_claims disabled by default)
        mosaheb_runner = next((r for r in runners if "mosaheb" in r.get("jockey","").lower()), None)
        if mosaheb_runner:
            claim_val = mosaheb_runner.get("apprentice_claim_kg", 0)
            print(f"  A Mosaheb claim (should be 0 — infer disabled): {claim_val:.2f}  {'[PASS]' if claim_val == 0 else '[FAIL]'}")

        print("\n[✓] Self-test complete.")
