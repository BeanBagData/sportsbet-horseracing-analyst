# ======================================================================================================================================
# START OF FILE: zaf_data_enricher.py
# OPERATIONAL ROLE: SOUTH AFRICAN RACE DATA GROUND-TRUTH ENRICHMENT MODULE
# PURPOSE: Supplements Sportsbet API feed with missing ZAF-specific fields:
#          - Apprentice weight claims (lb -> kg, SA official convention)
#          - Correct horse age and sex
#          - Merit ratings (MR)
#          - Compressed barrier numbers after scratching
# SOURCES: Sporting Post (primary), NRA/TAB Online (fallback), Racing Post (tertiary)
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

# SA official apprentice claim weight convention: 0.5kg per pound
# 3lb = 1.5kg, 2lb = 1.0kg, 1lb = 0.5kg, 5lb = 2.5kg, 7lb = 3.5kg
SA_LB_TO_KG = 0.5

# SA apprentice jockey list (name fragment -> claim allowance in lb)
# These are regularly updated - trainers booking these jockeys imply claims
SA_APPRENTICE_JOCKEYS = {
    "venniker":    3,   # Rachel Venniker
    "katjedi":     3,   # Malesela Katjedi
    "mosaheb":     3,   # Yaseen Mosaheb  
    "mxoli":       3,   # Siyabonga Mxoli
    "syster":      3,   # Dean Syster
    "marx":        2,   # Jared Marx
    "matsunyane":  2,   # Given Matsunyane
    "ndlovu":      2,   # Kwanda Ndlovu
    "soodoo":      1,   # Keagan Soodoo (senior-transitioning)
    "lihaba":      0,   # Lyle Lihaba (senior, no claim)
    "michel":      3,   # Mickaelle Michel
}

# SA official race weight in pounds -> kg (displayed on race cards)
# 9st 0lb = 57.0kg, 8st 7lb = 54.0kg, etc.
def stones_lbs_to_kg(stones: int, lbs: int) -> float:
    """Convert stones+lbs to kg using SA official rounding (0.5kg steps)."""
    total_lbs = stones * 14 + lbs
    return round(total_lbs * 0.5 / 1.0) * 0.5  # Round to nearest 0.5kg

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en-GB;q=0.9,en;q=0.8",
    "Referer": "https://www.google.co.za/",
    "DNT": "1",
}

# ---------------------------------------------------------------------------
# PARSING UTILITIES
# ---------------------------------------------------------------------------

def _parse_sa_claim_from_racecard(jockey_text: str) -> float:
    """
    Extract apprentice claim from Sporting Post / NRA racecard text.
    SA format examples: '(3)', '3lb', 'a3', '(3lb)', '(a3)'.
    Returns claim in KG using SA official 0.5kg/lb convention.
    """
    if not jockey_text:
        return 0.0

    # Pattern 1: explicit lb notation - (3lb), 3lb, (3 lb)
    m = re.search(r'\((\d+)\s*lb\)', jockey_text, re.IGNORECASE)
    if not m:
        m = re.search(r'\b(\d+)\s*lb\b', jockey_text, re.IGNORECASE)
    if m:
        lb = int(m.group(1))
        if 1 <= lb <= 7:
            return lb * SA_LB_TO_KG

    # Pattern 2: apprentice notation in parentheses - (3), (a3)
    m = re.search(r'\(a?(\d)\)', jockey_text, re.IGNORECASE)
    if m:
        lb = int(m.group(1))
        if 1 <= lb <= 7:
            return lb * SA_LB_TO_KG

    # Pattern 3: superscript style used in Sporting Post PDF - "Venniker 3"
    m = re.search(r'(\w+)\s+([1357])\s*$', jockey_text.strip())
    if m:
        lb = int(m.group(2))
        return lb * SA_LB_TO_KG

    return 0.0


def _infer_claim_from_jockey_name(jockey_name: str) -> float:
    """
    Fallback: use the known SA apprentice jockey list to infer claim.
    Only applies if jockey_name matches a known apprentice.
    Returns claim in KG.
    """
    j_lower = str(jockey_name).lower().strip()
    for fragment, lb in SA_APPRENTICE_JOCKEYS.items():
        if fragment in j_lower:
            if lb > 0:
                logger.debug(f"Inferred {lb}lb claim for apprentice: {jockey_name}")
            return lb * SA_LB_TO_KG
    return 0.0


def _parse_age_sex(text: str):
    """
    Extract age and sex from SA racecard description text.
    Handles: '3yo c', '4yo f', '5yo g', '3 year old colt', etc.
    Returns (age: int, sex: str) or (None, None).
    """
    # Standard format: "3yo c" or "3yo g" or "5yo f"
    m = re.search(r'(\d+)\s*yo\s+([cfghm])', text, re.IGNORECASE)
    if m:
        return int(m.group(1)), m.group(2).lower()

    # Alternate: "3 year old colt"
    SEX_MAP = {"colt": "c", "filly": "f", "gelding": "g", "horse": "h", "mare": "m"}
    m = re.search(r'(\d+)\s*[- ]?year[- ]?old\s+(\w+)', text, re.IGNORECASE)
    if m:
        age = int(m.group(1))
        sex = SEX_MAP.get(m.group(2).lower(), m.group(2)[0].lower())
        return age, sex

    return None, None


def _parse_merit_rating(text: str) -> Optional[int]:
    """
    Extract merit rating from SA racecard text.
    Handles: '[MR 98]', 'MR: 98', '(MR 98)', 'merit rating: 98'.
    """
    patterns = [
        r'\[MR\s*:?\s*(\d+)\]',
        r'\(MR\s*:?\s*(\d+)\)',
        r'MR\s*:?\s*(\d{2,3})\b',
        r'merit\s+rating\s*:?\s*(\d{2,3})',
        r'\brating\s*:?\s*(\d{2,3})\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            mr = int(m.group(1))
            if 40 <= mr <= 140:  # Sanity check: valid SA MR range
                return mr
    return None


def _compress_barriers(runners: list) -> dict:
    """
    Compute post-scratching sequential barrier compression.
    Returns dict: {runner_name_lower: compressed_barrier_int}.
    Active runners are sorted by original_barrier and re-numbered 1..N.
    """
    active = sorted(
        [r for r in runners if r.get("status", "Active") != "Scratched"],
        key=lambda x: int(x.get("original_barrier") or x.get("barrier") or 99)
    )
    return {
        str(r.get("name", "")).lower().strip(): idx
        for idx, r in enumerate(active, 1)
    }


# ---------------------------------------------------------------------------
# SOURCE 1: SPORTING POST (www.sportingpost.co.za)
# ---------------------------------------------------------------------------

def _fetch_sporting_post_racecard(track: str, race_num: int, date_str: str) -> dict:
    """
    Fetch runner details from Sporting Post racecard page.
    Returns dict keyed by horse name (lowercase) with enrichment fields.
    
    URL pattern: https://www.sportingpost.co.za/racecard/{date}/{track}/race-{N}/
    Sporting Post blocks automated requests without valid session cookies.
    Falls back gracefully on failure.
    """
    if not SCRAPING_AVAILABLE:
        return {}

    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    url = f"https://www.sportingpost.co.za/racecard/{date_str}/{track_slug}/race-{race_num}/"

    try:
        session = requests.Session()
        session.headers.update(REQUEST_HEADERS)

        # Step 1: Establish session by hitting homepage first
        session.get("https://www.sportingpost.co.za/", timeout=8)
        time.sleep(0.5)

        # Step 2: Fetch the racecard
        r = session.get(url, timeout=12)
        if r.status_code != 200:
            logger.warning(f"[SP] Racecard HTTP {r.status_code} for {url}")
            return {}

        return _parse_sporting_post_html(r.text)

    except Exception as e:
        logger.warning(f"[SP] Fetch failed for {url}: {e}")
        return {}


def _parse_sporting_post_html(html: str) -> dict:
    """
    Parse Sporting Post racecard HTML to extract per-runner data.
    Returns dict: {horse_name_lower: {age, sex, apprentice_claim_kg, merit_rating}}.
    """
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Sporting Post runner rows typically have class 'runner-row' or similar
        # Try multiple selector patterns as the site has had layout changes
        runner_rows = (
            soup.select("div.runner-row") or
            soup.select("tr.runner") or
            soup.select("div.racecard-runner") or
            soup.select("li.horse-entry") or
            soup.select(".racecard-table tr")
        )

        for row in runner_rows:
            row_text = row.get_text(" ", strip=True)

            # Extract horse name (usually in an <a> tag or .horse-name class)
            name_tag = (
                row.select_one(".horse-name a") or
                row.select_one(".runner-name a") or
                row.select_one("a.horse") or
                row.select_one("td.name a")
            )
            if not name_tag:
                continue

            name = name_tag.get_text(strip=True).lower()
            if not name:
                continue

            entry = {}

            # Age + Sex
            age_tag = row.select_one(".horse-details") or row.select_one(".age-sex") or row
            age, sex = _parse_age_sex(age_tag.get_text(" ", strip=True))
            if age:
                entry["age"] = age
            if sex:
                entry["sex"] = sex

            # Apprentice claim from jockey cell
            jockey_tag = (
                row.select_one(".jockey-name") or
                row.select_one(".jockey") or
                row.select_one("td.jockey")
            )
            if jockey_tag:
                jock_text = jockey_tag.get_text(" ", strip=True)
                claim = _parse_sa_claim_from_racecard(jock_text)
                if claim > 0:
                    entry["apprentice_claim_kg"] = claim
                    entry["apprentice_claim_source"] = "sporting_post"

            # Merit Rating
            mr = _parse_merit_rating(row_text)
            if mr:
                entry["merit_rating"] = mr

            if entry:
                results[name] = entry

        # Alternate: SP sometimes renders data in a structured JSON block
        # embedded in the page (e.g., <script type="application/json">)
        if not results:
            for script in soup.find_all("script", type="application/json"):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and "runners" in data:
                        for runner in data["runners"]:
                            n = str(runner.get("name", "")).lower().strip()
                            if n:
                                entry = {}
                                if "age" in runner:
                                    entry["age"] = int(runner["age"])
                                if "sex" in runner:
                                    entry["sex"] = str(runner["sex"]).lower()
                                if "meritRating" in runner or "rating" in runner:
                                    entry["merit_rating"] = int(runner.get("meritRating") or runner.get("rating", 0))
                                jock = str(runner.get("jockey", ""))
                                claim = _parse_sa_claim_from_racecard(jock)
                                if claim > 0:
                                    entry["apprentice_claim_kg"] = claim
                                    entry["apprentice_claim_source"] = "sporting_post_json"
                                if entry:
                                    results[n] = entry
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"[SP] HTML parse failed: {e}")

    return results


# ---------------------------------------------------------------------------
# SOURCE 2: NRA TAB ONLINE (www.tabonline.co.za / www.nra.co.za)
# ---------------------------------------------------------------------------

def _fetch_nra_racecard(track: str, race_num: int, date_str: str) -> dict:
    """
    Fetch runner details from NRA TAB Online racecard.
    Tries multiple URL patterns used by the NRA site.
    Returns dict keyed by horse name (lowercase).
    """
    if not SCRAPING_AVAILABLE:
        return {}

    track_slug = track.lower().replace(" ", "")
    date_nodash = date_str.replace("-", "")

    candidate_urls = [
        f"https://www.tabonline.co.za/racing/racecard/{date_str}/{track_slug}/{race_num}",
        f"https://www.nra.co.za/racing/racecard/{date_str}/{track_slug}/{race_num}",
        f"https://racing.tabonline.co.za/racecard/{date_nodash}/{track_slug}/{race_num}",
    ]

    for url in candidate_urls:
        try:
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
            if r.status_code == 200:
                return _parse_nra_html(r.text)
        except Exception as e:
            logger.debug(f"[NRA] {url}: {e}")
            continue

    return {}


def _parse_nra_html(html: str) -> dict:
    """
    Parse NRA/TAB Online racecard HTML.
    NRA typically renders runners in a table with columns:
    No | Horse | Age/Sex | Jockey (Claim) | Trainer | Weight | MR
    """
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # NRA racecard table pattern
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 4:
                    continue

                row_text = " ".join(c.get_text(strip=True) for c in cells)
                
                # Look for horse name (usually in first or second data column with a link)
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

                # Scan all cells for age/sex, claim, MR
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

        # Also check for NRA API JSON embedded in script tags
        for script in soup.find_all("script"):
            if script.string and "runners" in str(script.string):
                try:
                    txt = script.string
                    json_match = re.search(r'\{.*"runners"\s*:\s*\[.*?\].*\}', txt, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group(0))
                        for runner in data.get("runners", []):
                            n = str(runner.get("name", runner.get("horseName", ""))).lower().strip()
                            if n:
                                entry = {}
                                if "age" in runner:
                                    entry["age"] = int(runner["age"])
                                if "sex" in runner or "gender" in runner:
                                    entry["sex"] = str(runner.get("sex") or runner.get("gender", "")).lower()[:1]
                                if "meritRating" in runner or "mr" in runner:
                                    entry["merit_rating"] = int(runner.get("meritRating") or runner.get("mr", 0))
                                jock = str(runner.get("jockey", runner.get("jockeyName", "")))
                                claim = _parse_sa_claim_from_racecard(jock)
                                if claim > 0:
                                    entry["apprentice_claim_kg"] = claim
                                    entry["apprentice_claim_source"] = "nra_json"
                                if entry:
                                    results[n] = entry
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"[NRA] HTML parse failed: {e}")

    return results


# ---------------------------------------------------------------------------
# SOURCE 3: RACING POST (www.racingpost.com) — ZAF COVERAGE
# ---------------------------------------------------------------------------

def _fetch_racing_post_card(horse_name: str) -> dict:
    """
    Fetch individual horse profile from Racing Post for age/sex/rating.
    Useful as tertiary lookup when both SP and NRA fail for a specific horse.
    Racing Post has extensive ZAF historical coverage.
    Returns dict with enrichment fields or empty dict.
    """
    if not SCRAPING_AVAILABLE:
        return {}

    try:
        search_url = f"https://www.racingpost.com/profile/horse/search?query={horse_name.replace(' ', '+')}&country=ZAF"
        r = requests.get(search_url, headers=REQUEST_HEADERS, timeout=10)
        
        if r.status_code != 200:
            return {}
            
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Racing Post search results — find first ZAF horse match
        result_links = soup.select("a[href*='/profile/horse/']")
        if not result_links:
            return {}
            
        # Fetch first profile
        profile_url = "https://www.racingpost.com" + result_links[0]["href"]
        rp = requests.get(profile_url, headers=REQUEST_HEADERS, timeout=10)
        
        if rp.status_code != 200:
            return {}
            
        ps = BeautifulSoup(rp.text, "html.parser")
        profile_text = ps.get_text(" ", strip=True)
        
        entry = {}
        age, sex = _parse_age_sex(profile_text)
        if age:
            entry["age"] = age
            entry["age_source"] = "racing_post"
        if sex:
            entry["sex"] = sex
            
        mr = _parse_merit_rating(profile_text)
        if mr:
            entry["merit_rating"] = mr
            entry["mr_source"] = "racing_post"
            
        return entry

    except Exception as e:
        logger.debug(f"[RP] Fetch failed for {horse_name}: {e}")
        return {}


# ---------------------------------------------------------------------------
# MAIN ENRICHMENT ENGINE
# ---------------------------------------------------------------------------

def enrich_sa_racecard(
    race_json: dict,
    date_str: str,
    use_sporting_post: bool = True,
    use_nra: bool = True,
    use_racing_post: bool = True,
    infer_claims_from_jockey_list: bool = False,
    recompute_barriers: bool = True,
) -> dict:
    """
    PRIMARY ENTRY POINT: Enrich a South African race JSON record with
    ground-truth data from official SA racing sources.

    Parameters
    ----------
    race_json : dict
        A race record as produced by sportsbet_scraper.py — the `race_db` dict.
    date_str : str
        Race date in YYYY-MM-DD format.
    use_sporting_post : bool
        Attempt Sporting Post as primary source.
    use_nra : bool
        Attempt NRA TAB Online as fallback.
    use_racing_post : bool
        Attempt Racing Post for individual horse profiles as tertiary fallback.
    infer_claims_from_jockey_list : bool
        If no online source provides a claim, infer from the known SA apprentice list.
    recompute_barriers : bool
        Recompute compressed barrier numbers after scratching.

    Returns
    -------
    dict
        Enriched race_json with corrected runner fields. A new key
        ``enrichment_log`` is added per runner documenting what was changed.
    """
    if not isinstance(race_json, dict):
        return race_json

    track = str(race_json.get("venue") or race_json.get("track_name") or
                 race_json.get("meeting_metadata", {}).get("track_name", "Unknown"))
    race_num = int(race_json.get("race_number", 1))
    runners = race_json.get("runners", [])

    if not runners:
        return race_json

    print(f"[ZAF Enricher] Processing {track} Race {race_num} — {len(runners)} runners")

    # ----- Step 1: Fetch from online sources -----
    sp_data = {}
    nra_data = {}

    if use_sporting_post:
        print(f"[ZAF Enricher] → Sporting Post lookup...")
        sp_data = _fetch_sporting_post_racecard(track, race_num, date_str)
        print(f"[ZAF Enricher]   Found {len(sp_data)} SP entries")

    if use_nra and not sp_data:
        print(f"[ZAF Enricher] → NRA TAB Online lookup...")
        nra_data = _fetch_nra_racecard(track, race_num, date_str)
        print(f"[ZAF Enricher]   Found {len(nra_data)} NRA entries")

    # Merge sources (SP takes priority over NRA)
    online_data = {**nra_data, **sp_data}

    # ----- Step 2: Recompute barriers -----
    barrier_map = {}
    if recompute_barriers:
        barrier_map = _compress_barriers(runners)
        print(f"[ZAF Enricher] → Recomputed barriers for {len(barrier_map)} active runners")

    # ----- Step 3: Apply enrichment to each runner -----
    enrichment_summary = []

    for runner in runners:
        name = str(runner.get("name", "")).strip()
        name_lower = name.lower()
        log = {"name": name, "changes": []}

        online_entry = online_data.get(name_lower, {})

        # -- Age correction --
        if "age" in online_entry:
            old = runner.get("age")
            runner["age"] = online_entry["age"]
            runner["age_source"] = online_entry.get("age_source", "sp_or_nra")
            if old != runner["age"]:
                log["changes"].append(f"age: {old} → {runner['age']}")
        elif use_racing_post and "age" not in runner:
            # Tertiary: individual RP lookup for missing age
            rp_entry = _fetch_racing_post_card(name)
            if "age" in rp_entry:
                runner["age"] = rp_entry["age"]
                runner["age_source"] = "racing_post"
                log["changes"].append(f"age (RP): → {runner['age']}")

        # -- Sex/Gender correction --
        if "sex" in online_entry:
            old = runner.get("sex") or runner.get("gender")
            runner["sex"] = online_entry["sex"]
            runner["gender"] = online_entry["sex"]
            if old != runner["sex"]:
                log["changes"].append(f"sex: {old} → {runner['sex']}")

        # -- Apprentice claim correction --
        claim_applied = False

        if "apprentice_claim_kg" in online_entry:
            old = runner.get("apprentice_claim_kg", 0.0)
            new_claim = online_entry["apprentice_claim_kg"]
            if new_claim != old:
                runner["apprentice_claim_kg"] = new_claim
                runner["apprentice_claim_source"] = online_entry.get("apprentice_claim_source", "sp_or_nra")
                log["changes"].append(f"claim: {old:.2f}kg → {new_claim:.2f}kg ({runner['apprentice_claim_source']})")
            claim_applied = True

        if not claim_applied and infer_claims_from_jockey_list:
            jockey = str(runner.get("jockey", ""))
            # Check if Sportsbet already parsed a claim via (aX) notation
            existing_claim = float(runner.get("apprentice_claim_kg", 0.0))
            if existing_claim == 0.0:
                inferred = _infer_claim_from_jockey_name(jockey)
                if inferred > 0:
                    runner["apprentice_claim_kg"] = inferred
                    runner["apprentice_claim_source"] = "inferred_apprentice_list"
                    log["changes"].append(f"claim (inferred): 0.00 → {inferred:.2f}kg from apprentice list")
                else:
                    # Also try extracting from jockey name string itself
                    parsed = _parse_sa_claim_from_racecard(jockey)
                    if parsed > 0:
                        runner["apprentice_claim_kg"] = parsed
                        runner["apprentice_claim_source"] = "parsed_jockey_string"
                        log["changes"].append(f"claim (parsed): 0.00 → {parsed:.2f}kg from jockey string")

        # Reweight: Sportsbet AU apprentice notation (aX) means X kg in AU context.
        # For SA races, the same (aX) notation from Sportsbet represents pounds (lb),
        # not kilograms. SA official conversion: 1lb = 0.5kg exactly.
        # Only apply correction if the claim came from Sportsbet AU parsing (not a
        # manual or online-source value, which are already in correct kg).
        existing_claim = float(runner.get("apprentice_claim_kg", 0.0))
        claim_source = str(runner.get("apprentice_claim_source", ""))
        # Only convert if source is the raw Sportsbet parser (no source tag set)
        # and the value is a whole-number lb value (1, 2, 3, 5, 7)
        if (existing_claim in [1.0, 2.0, 3.0, 5.0, 7.0] and
                claim_source == "" and
                "override" not in claim_source and
                "sporting_post" not in claim_source and
                "nra" not in claim_source):
            # Likely parsed from Sportsbet (aX) notation where X is lb for SA race
            corrected = existing_claim * SA_LB_TO_KG
            runner["apprentice_claim_kg"] = corrected
            runner["apprentice_claim_source"] = "sportsbet_lb_corrected"
            log["changes"].append(
                f"claim unit: {existing_claim:.1f}lb → {corrected:.2f}kg (SA lb->kg)"
            )

        # -- Merit rating correction --
        if "merit_rating" in online_entry:
            old = runner.get("merit_rating") or runner.get("rating")
            runner["merit_rating"] = online_entry["merit_rating"]
            if old != runner["merit_rating"]:
                log["changes"].append(f"merit_rating: {old} → {runner['merit_rating']}")

        # -- Barrier recompression --
        if recompute_barriers and name_lower in barrier_map:
            old_barrier = runner.get("original_barrier") or runner.get("barrier")
            runner["original_barrier"] = int(old_barrier) if old_barrier else runner.get("original_barrier")
            runner["barrier_compressed"] = barrier_map[name_lower]
            log["changes"].append(f"barrier_compressed: → {barrier_map[name_lower]}")

        if log["changes"]:
            enrichment_summary.append(log)
            print(f"[ZAF Enricher]   {name}: {', '.join(log['changes'])}")
        else:
            print(f"[ZAF Enricher]   {name}: no changes needed")

    race_json["enrichment_log"] = enrichment_summary
    race_json["enrichment_applied"] = True
    race_json["enrichment_date"] = date_str

    print(f"[ZAF Enricher] Complete — {len(enrichment_summary)} runners modified")
    return race_json


# ---------------------------------------------------------------------------
# OFFLINE MANUAL OVERRIDE (for when all scraping fails)
# ---------------------------------------------------------------------------

def apply_manual_corrections(race_json: dict, corrections: dict) -> dict:
    """
    Apply manually-specified ground-truth corrections to a race JSON.
    Useful when online sources are unavailable (behind paywall, blocked, etc.)
    and the user has the official race card at hand.

    Parameters
    ----------
    race_json : dict
        Race JSON as produced by sportsbet_scraper.py.
    corrections : dict
        Keyed by horse name (case-insensitive). Each value is a dict of
        fields to override. Supported fields:
            - age (int)
            - sex (str: 'c', 'f', 'g', 'h', 'm')
            - apprentice_claim_lb (int: 1, 2, 3, 5, or 7)
            - apprentice_claim_kg (float: overrides lb calc)
            - merit_rating (int)
            - original_barrier (int)
            - carried_weight_kg (float)

    Example
    -------
    corrections = {
        "Damova": {"age": 3, "sex": "f", "apprentice_claim_lb": 3},
        "Bellerophon": {"age": 3, "sex": "c"},
        "One More Star": {"apprentice_claim_lb": 3},
    }
    enriched = apply_manual_corrections(race_json, corrections)
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

    # Recompute compressed barriers after manual corrections
    barrier_map = _compress_barriers(race_json.get("runners", []))
    for runner in race_json.get("runners", []):
        name_lower = str(runner.get("name", "")).lower().strip()
        if name_lower in barrier_map:
            runner["barrier_compressed"] = barrier_map[name_lower]

    race_json["manual_correction_log"] = log
    race_json["enrichment_applied"] = True
    return race_json


# ---------------------------------------------------------------------------
# INTEGRATION HOOK: Called from sportsbet_scraper.py after race_db is built
# ---------------------------------------------------------------------------

def enrich_if_sa(race_json: dict, date_str: str, manual_corrections: dict = None) -> dict:
    """
    Convenience wrapper: only enriches if the race is at a South African track.
    Drop-in replacement callable from sportsbet_scraper.py.

    Usage in sportsbet_scraper.py (add after race_db construction):

        from zaf_data_enricher import enrich_if_sa
        race_db = enrich_if_sa(race_db, target_date)

    Optional manual corrections for when online scraping is blocked:

        from zaf_data_enricher import enrich_if_sa
        corrections = {
            "Damova": {"age": 3, "sex": "f", "apprentice_claim_lb": 3},
            "One More Star": {"apprentice_claim_lb": 3},
            "Bellerophon": {"age": 3},
        }
        race_db = enrich_if_sa(race_db, target_date, manual_corrections=corrections)
    """
    SA_TRACKS = [
        "greyville", "kenilworth", "turffontein", "vaal",
        "fairview", "durbanville", "scottsville", "kimberley",
        "flamingo", "east london"
    ]

    track = str(
        race_json.get("venue") or
        race_json.get("track_name") or
        race_json.get("meeting_metadata", {}).get("track_name", "")
    ).lower()

    is_sa = any(t in track for t in SA_TRACKS)

    if not is_sa:
        return race_json

    # Apply manual corrections first (if provided) then online enrichment
    if manual_corrections:
        race_json = apply_manual_corrections(race_json, manual_corrections)

    race_json = enrich_sa_racecard(race_json, date_str)
    return race_json


# ---------------------------------------------------------------------------
# CLI TEST HARNESS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) >= 2:
        # Load and enrich a race JSON file from command line
        json_path = sys.argv[1]
        date = sys.argv[2] if len(sys.argv) >= 3 else "2025-06-21"

        with open(json_path, "r", encoding="utf-8") as f:
            race = json.load(f)

        enriched = enrich_if_sa(race, date)
        out_path = json_path.replace(".json", "_enriched.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=2, ensure_ascii=False)
        print(f"\n[✓] Enriched JSON saved to: {out_path}")

    else:
        # Built-in test with mock data matching the Corrupt/Damova race example
        print("=== ZAF ENRICHER SELF-TEST (Manual Override Mode) ===\n")

        mock_race = {
            "venue": "Turffontein",
            "race_number": 7,
            "race_name": "Tab Charity Mile",
            "distance_metres": 2400,
            "rail_position": "True",
            "start_time": 1750000000,
            "runners": [
                {"name": "Damova",        "number": 1, "original_barrier": 3, "carried_weight_kg": 54.5, "apprentice_claim_kg": 0.0, "age": 4, "jockey": "Rachel Venniker", "trainer": "Wayne Campbell", "status": "Active"},
                {"name": "Corrupt",       "number": 2, "original_barrier": 5, "carried_weight_kg": 52.5, "apprentice_claim_kg": 0.0, "age": 5, "jockey": "Muzi Yeni",       "trainer": "Mike de Kock",   "status": "Active"},
                {"name": "One More Star", "number": 3, "original_barrier": 7, "carried_weight_kg": 55.5, "apprentice_claim_kg": 0.0, "age": 5, "jockey": "Mickaelle Michel", "trainer": "Joey Ramsden",   "status": "Active"},
                {"name": "Battleground",  "number": 4, "original_barrier": 4, "carried_weight_kg": 58.5, "apprentice_claim_kg": 0.0, "age": 5, "jockey": "Gavin Lerena",    "trainer": "Glen Kotzen",    "status": "Active"},
                {"name": "Hotarubi",      "number": 5, "original_barrier": 1, "carried_weight_kg": 60.5, "apprentice_claim_kg": 0.0, "age": 6, "jockey": "Malesela Katjedi","trainer": "Chris Jonker",   "status": "Active"},
                {"name": "Bellerophon",   "number": 6, "original_barrier": 6, "carried_weight_kg": 57.0, "apprentice_claim_kg": 0.0, "age": 4, "jockey": "Unknown",          "trainer": "Adam Marcus",    "status": "Active"},
            ]
        }

        corrections = {
            "Damova":        {"age": 3, "sex": "f", "apprentice_claim_lb": 3, "merit_rating": 82},
            "Corrupt":       {"age": 5, "sex": "g", "merit_rating": 98},
            "One More Star": {"age": 5, "sex": "c", "apprentice_claim_lb": 3, "merit_rating": 85},
            "Battleground":  {"age": 5, "sex": "c", "merit_rating": 91},
            "Hotarubi":      {"age": 6, "sex": "h", "merit_rating": 112},
            "Bellerophon":   {"age": 3, "sex": "c", "merit_rating": 76},
        }

        enriched = enrich_if_sa(mock_race, "2025-06-21", manual_corrections=corrections)

        print("\n=== ENRICHED OUTPUT ===")
        print(f"{'Name':<15} {'Age':>4} {'Sex':>4} {'W_alloc':>8} {'Claim':>7} {'W_eff':>7} {'B_comp':>7} {'MR':>5}")
        print("-" * 65)
        for r in enriched["runners"]:
            w_eff = r["carried_weight_kg"] - r.get("apprentice_claim_kg", 0)
            print(f"{r['name']:<15} {r.get('age','?'):>4} {r.get('sex','?'):>4} "
                  f"{r['carried_weight_kg']:>8.1f} {r.get('apprentice_claim_kg',0):>7.2f} "
                  f"{w_eff:>7.1f} {r.get('barrier_compressed','?'):>7} "
                  f"{r.get('merit_rating','?'):>5}")

        print("\n=== DOCUMENT VALIDATION (expected W_eff) ===")
        expected = {"Damova": 53.0, "Corrupt": 52.5, "One More Star": 54.0,
                    "Battleground": 58.5, "Hotarubi": 60.5, "Bellerophon": 57.0}
        all_pass = True
        for r in enriched["runners"]:
            w_eff = r["carried_weight_kg"] - r.get("apprentice_claim_kg", 0)
            exp = expected.get(r["name"])
            if exp is not None:
                status = "✓" if abs(w_eff - exp) < 0.01 else f"✗ (expected {exp})"
                if "✗" in status:
                    all_pass = False
                print(f"  {r['name']:<15} W_eff={w_eff:.1f}kg  {status}")

        print(f"\n{'[PASS] All document W_eff targets matched.' if all_pass else '[FAIL] Some values mismatched.'}")
