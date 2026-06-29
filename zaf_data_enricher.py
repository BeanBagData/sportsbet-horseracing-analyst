# ======================================================================================================================================
# START OF FILE: zaf_data_enricher.py
# OPERATIONAL ROLE: SOUTH AFRICAN RACE DATA GROUND-TRUTH ENRICHMENT MODULE (PUNTERS.COM.AU DEEP PARSER)
# SYSTEM ALIGNMENT: SOUTH AFRICAN PROVINCIAL SYNTHETIC & TURF DECISION SIEVE
# LANGUAGE VARIATION: BRITISH UK ENGLISH (METRES, NORMALISATION, PRIORITISATION, PENALISE, ANALYSE)
# ======================================================================================================================================

import re
import json
import time
import os
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional

logger = logging.getLogger(__name__)

SA_LB_TO_KG = 0.5

SA_TRACKS = [
    "greyville", "kenilworth", "turffontein", "vaal",
    "fairview", "durbanville", "scottsville", "kimberley",
    "flamingo", "east london"
]

SA_APPRENTICE_JOCKEYS = {
    "venniker":     3,
    "mosaheb":      4,
    "lihaba":       2,
    "katjedi":      1.5,
    "soodoo":       2.5,
    "ramzan":       1.5,
    "mxoli":        3,
    "syster":       3,
    "marx":         2,
    "matsunyane":   2,
    "ndlovu":       2,
    "michel":       3,
    "ramkhalawon":  3,
    "mbuto":        3,
    "hlengwa":      3,
    "moodley":      2,
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


class PuntersDataExtractor:
    """
    Forensic Parser for Punters.com.au HTML Pages.
    Extracts structural, breeding, and historical run timeline records.
    """
    @staticmethod
    def parse_race_overview(html_content: str) -> list:
        soup = BeautifulSoup(html_content, "html.parser")
        runners = []
        table = soup.find("table", class_="form-guide-overview-table")
        if not table:
            table = soup.find("table", class_="base-table")
        if not table:
            return runners

        rows = table.find_all("tr", class_="form-guide-overview-selection")
        for row in rows:
            runner = {}
            horse_link = row.find("a", class_=lambda x: x and "horse" in x)
            if not horse_link:
                horse_link = row.find("a", href=lambda x: x and "/horses/" in x)
            
            if horse_link:
                runner["name"] = horse_link.get_text(strip=True)
                runner["profile_url"] = horse_link.get("href", "").strip()

            competitor_div = row.find(class_="selection-runner__competitor")
            if competitor_div:
                comp_text = competitor_div.get_text(" ", strip=True)
                num_match = re.match(r"^(\d+)\s*\.", comp_text)
                if num_match:
                    runner["number"] = int(num_match.group(1))
                barrier_match = re.search(r"\(\s*(\d+)\s*\)\s*$", comp_text)
                if barrier_match:
                    runner["barrier_recalculated"] = int(barrier_match.group(1))

            jockey_div = row.find(class_="selection-runner__jockey")
            if jockey_div:
                jockey_link = jockey_div.find("a", href=lambda x: x and "/jockeys/" in x)
                if jockey_link:
                    runner["jockey"] = jockey_link.get_text(strip=True)
                jock_text = jockey_div.get_text(" ", strip=True)
                weight_match = re.search(r"(\d+\.?\d*)\s*kg", jock_text)
                if weight_match:
                    runner["weight"] = float(weight_match.group(1))
                claim_match = re.search(r"a-?\s*(\d+\.?\d*)", jock_text)
                if claim_match:
                    runner["apprentice_claim_kg"] = float(claim_match.group(1))

            trainer_div = row.find(class_="selection-runner__trainer")
            if trainer_div:
                trainer_link = trainer_div.find("a", href=lambda x: x and "/trainers/" in x)
                if trainer_link:
                    runner["trainer"] = trainer_link.get_text(strip=True)

            cells = row.find_all("td")
            if len(cells) >= 7:
                runner["last_10"] = cells[1].get_text(strip=True)
                runner["career_stats_text"] = cells[2].get_text(strip=True)
                runner["win_pct"] = cells[4].get_text(strip=True)
                runner["place_pct"] = cells[5].get_text(strip=True)
                runner["avg_prize"] = cells[6].get_text(strip=True)

            quick_form_items = row.find_all(class_="selection-quick-form-details__item")
            if quick_form_items:
                runner["quick_form_tags"] = [
                    item.find(class_="selection-quick-form-details__item-head").get_text(strip=True)
                    for item in quick_form_items if item.find(class_="selection-quick-form-details__item-head")
                ]

            if runner.get("name"):
                runners.append(runner)
        return runners

    @classmethod
    def parse_horse_profile(cls, html_content: str) -> dict:
        soup = BeautifulSoup(html_content, "html.parser")
        profile = {
            "earnings": "$0",
            "rating": "-",
            "pedigree": {},
            "stats": {},
            "history_runs": [],
            "training_history": []
        }
        bio_div = soup.find("div", class_="profile-bio")
        if bio_div:
            bio_text = bio_div.get_text(" ", strip=True)
            age_sex_match = re.search(r"is\s+a\s+(\d+)\s*yo\s+(\w+)\s+(\w+)", bio_text, re.I)
            if age_sex_match:
                profile["age"] = int(age_sex_match.group(1))
                profile["sex_colour"] = age_sex_match.group(2)
                profile["sex"] = age_sex_match.group(3)

        details_module = soup.find("div", class_="horse-details-right")
        if details_module:
            table = details_module.find("table")
            if table:
                for tr in table.find_all("tr"):
                    th = tr.find("th")
                    td = tr.find("td")
                    if th and td:
                        key = th.get_text(strip=True).replace(":", "").lower().strip()
                        val = td.get_text(" ", strip=True).strip()
                        if "pedigree" in key:
                            parts = [p.strip() for p in val.split("x")]
                            if len(parts) >= 2:
                                profile["pedigree"]["sire"] = parts[0]
                                profile["pedigree"]["dam"] = parts[1]
                        elif "foaled" in key:
                            profile["foaled_date"] = val
                        elif "owners" in key:
                            profile["owners"] = val
                        elif "earnings" in key:
                            profile["earnings"] = val
                        elif "training history" in key:
                            history_segments = [s.strip() for p in val.split(",") for s in p.split(";") if s.strip()]
                            for segment in history_segments:
                                profile["training_history"].append(segment)

        summary_div = soup.find("div", class_="horse-career-summary")
        if summary_div:
            stat_items = summary_div.find_all(class_="horse-career-summary__stat")
            for item in stat_items:
                label_div = item.find(class_="horse-career-summary__stat-label")
                strong = item.find("strong")
                if label_div and strong:
                    label = label_div.get_text(strip=True).lower().strip()
                    val = strong.get_text(strip=True).strip()
                    full_text = item.get_text(" ", strip=True)
                    detail = full_text.replace(label_div.get_text(strip=True), "").replace(val, "").strip()
                    profile["stats"][label] = {"value": val, "detail": detail}

        timeline_container = soup.find("div", class_="timeline-container")
        if timeline_container:
            timeline_blocks = timeline_container.find_all("ul", class_="timeline")
            for block in timeline_blocks:
                run = {}
                cont = block.find(class_="timeline-cont")
                if cont:
                    pos_span = cont.find(class_="formSummaryPosition")
                    if pos_span:
                        run["position"] = int(re.search(r"\d+", pos_span.get_text(strip=True)).group(0))
                    starters_span = cont.find(class_="starters")
                    if starters_span:
                        run["starters"] = int(starters_span.get_text(strip=True))

                inner_box = block.find(class_="inner-box")
                if inner_box:
                    disc_items = inner_box.find_all(class_="timeline-disc")
                    if len(disc_items) >= 1:
                        header_text = disc_items[0].get_text(" ", strip=True)
                        venue_el = disc_items[0].find(class_="simlight")
                        if venue_el:
                            run["venue"] = venue_el.get_text(strip=True)
                        date_el = disc_items[0].find(class_="date")
                        if date_el:
                            run["date"] = date_el.get_text(strip=True)
                        dist_el = disc_items[0].find(class_="dist")
                        if dist_el:
                            run["distance"] = dist_el.get_text(strip=True)
                        badge_el = disc_items[0].find(class_="badge")
                        if badge_el:
                            run["track_condition"] = badge_el.get_text(strip=True)

                        barrier_match = re.search(r"Barrier\s*(\d+)", header_text, re.I)
                        if barrier_match:
                            run["barrier"] = int(barrier_match.group(1))
                        sp_match = re.search(r"SP\s*:\s*([\d.]+)", header_text, re.I)
                        if sp_match:
                            run["sp"] = float(sp_match.group(1))
                        time_match = re.search(r"Winning\s*Time\s*:\s*([\d:.]+)", header_text, re.I)
                        if time_match:
                            run["winning_time"] = time_match.group(1)
                        class_match = re.search(r"^(.*?)\s*\(\s*of", header_text)
                        if class_match:
                            cleaned_class = class_match.group(1)
                            for junk in [run.get("venue", ""), run.get("date", "")]:
                                cleaned_class = cleaned_class.replace(junk, "")
                            run["class_desc"] = cleaned_class.strip()

                    if len(disc_items) >= 2:
                        placed_el = disc_items[1].find(class_="placed")
                        if placed_el:
                            placed_text = placed_el.get_text(" ", strip=True)
                            margin_match = re.search(r"([\d.]+)\s*L", placed_text, re.I)
                            if margin_match:
                                run["margin_lengths"] = float(margin_match.group(1))
                            else:
                                if "1st" in placed_text or "round-win" in str(placed_el.get("class")):
                                    run["margin_lengths"] = 0.0

                            jock_weight_match = re.search(r"\((.*?)\s+(\d+\.?\d*)\s*kg\)", placed_text)
                            if jock_weight_match:
                                run["jockey"] = jock_weight_match.group(1).strip()
                                run["weight_carried_kg"] = float(jock_weight_match.group(2))
                if run.get("venue"):
                    profile["history_runs"].append(run)
        return profile


def infer_from_race_name(race_name: str) -> dict:
    rn = str(race_name).lower()
    inferences = {}
    if "juvenile" in rn or "2-year" in rn or re.search(r"\b2yo\b", rn):
        inferences["age"] = 2
        inferences["age_basis"] = "race_name:juvenile"
    elif re.search(r"\b3yo\b", rn):
        inferences["age_min"] = 3
        inferences["age_basis"] = "race_name:3yo"
    elif re.search(r"\b4yo\b", rn):
        inferences["age_min"] = 4
        inferences["age_basis"] = "race_name:4yo"
    elif re.search(r"\b5yo\b", rn):
        inferences["age_min"] = 5
        inferences["age_basis"] = "race_name:5yo"

    fillies_match = re.search(r"\bfill?ies\b", rn)
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

    if "maiden" in rn:
        inferences["is_maiden"] = True
        inferences["maiden_basis"] = "race_name:maiden"
    return inferences


def _apply_race_name_invariants(runners: list, race_name: str) -> list:
    invariants = infer_from_race_name(race_name)
    if not invariants:
        return []
    log = []
    for runner in runners:
        runner_changes = []
        if "age" in invariants:
            old = runner.get("age")
            if old != invariants["age"]:
                runner["age"] = invariants["age"]
                runner["age_source"] = invariants["age_basis"]
                runner_changes.append(f"age: {old} → {invariants['age']} [{invariants['age_basis']}]")
        if "sex" in invariants:
            old = runner.get("sex") or runner.get("gender")
            if str(old).upper() != invariants["sex"].upper():
                runner["sex"] = invariants["sex"]
                runner["gender"] = invariants["sex"]
                runner["sex_source"] = invariants["sex_basis"]
                runner_changes.append(f"sex: {old} → {invariants['sex']} [{invariants['sex_basis']}]")
        if invariants.get("is_maiden"):
            runner["is_maiden"] = True
        if runner_changes:
            log.append({"name": runner.get("name"), "changes": runner_changes})
    return log


def _parse_sa_claim_from_racecard(jockey_text: str) -> float:
    if not jockey_text:
        return 0.0
    m = re.search(r"\((\d+)\s*lb\)", jockey_text, re.IGNORECASE)
    if not m:
        m = re.search(r"\b(\d+)\s*lb\b", jockey_text, re.IGNORECASE)
    if m:
        lb = int(m.group(1))
        if 1 <= lb <= 7:
            return lb * SA_LB_TO_KG
    m = re.search(r"\(a?([1357])\)", jockey_text, re.IGNORECASE)
    if m:
        return int(m.group(1)) * SA_LB_TO_KG
    m = re.search(r"(\w+)\s+([1357])\s*$", jockey_text.strip())
    if m:
        return int(m.group(2)) * SA_LB_TO_KG
    return 0.0


def _infer_claim_from_jockey_name(jockey_name: str) -> float:
    j_lower = str(jockey_name).lower().strip()
    for fragment, lb in SA_APPRENTICE_JOCKEYS.items():
        if fragment in j_lower:
            return lb * SA_LB_TO_KG
    return 0.0


def _parse_age_sex(text: str):
    m = re.search(r"(\d+)\s*yo\s+([cfghm])", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), m.group(2).lower()
    SEX_MAP = {"colt": "c", "filly": "f", "gelding": "g", "horse": "h", "mare": "m"}
    m = re.search(r"(\d+)\s*[- ]?year[- ]?old\s+(\w+)", text, re.IGNORECASE)
    if m:
        age = int(m.group(1))
        sex = SEX_MAP.get(m.group(2).lower(), m.group(2)[0].lower())
        return age, sex
    return None, None


def _parse_merit_rating(text: str) -> Optional[int]:
    patterns = [
        r"\[MR\s*:?\s*(\d+)\]",
        r"\(MR\s*:?\s*(\d+)\)",
        r"MR\s*:?\s*(\d{2,3})\b",
        r"merit\s+rating\s*:?\s*(\d{2,3})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            mr = int(m.group(1))
            if 40 <= mr <= 140:
                return mr
    return None


def _compress_barriers(runners: list) -> dict:
    active = sorted(
        [r for r in runners if r.get("status", "Active") != "Scratched"],
        key=lambda x: int(x.get("original_barrier") or x.get("barrier") or 99)
    )
    return {str(r.get("name", "")).lower().strip(): idx for idx, r in enumerate(active, 1)}


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(REQUEST_HEADERS)
    return s


def _fetch_sporting_post_racecard(track: str, race_num: int, date_str: str) -> dict:
    y, m, d = date_str.split("-")
    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    track_slug_nodash = track.lower().replace(" ", "").replace("_", "")
    month_names = ["january","february","march","april","may","june",
                   "july","august","september","october","november","december"]

    url_candidates = [
        f"https://www.sportingpost.co.za/{y}/{m}/{d}/{track_slug}-racecards/",
        f"https://www.sportingpost.co.za/{y}/{m}/{d}/{track_slug}-racecard/",
        f"https://www.sportingpost.co.za/{y}/{m}/{d}/{track_slug_nodash}-racecards/",
        f"https://www.sportingpost.co.za/horse-racing/{track_slug}/{date_str}/race-{race_num}/",
        f"https://www.sportingpost.co.za/horse-racing/racecards/{date_str}/{track_slug}/",
        f"https://www.sportingpost.co.za/racecards/{date_str}/{track_slug}/",
        f"https://www.sportingpost.co.za/racecard/{date_str}/{track_slug}/race-{race_num}/",
        f"https://www.sportingpost.co.za/wp-json/wp/v2/posts?search={track_slug}+racecards+{d}+{month_names[int(m)-1]}&per_page=3",
        f"https://www.sportingpost.co.za/wp-json/wp/v2/posts?search={track_slug}+racecard&per_page=3",
    ]

    session = _make_session()
    try:
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
                    posts = r.json()
                    if isinstance(posts, list) and posts:
                        return _parse_sporting_post_html(posts[0].get("content", {}).get("rendered", ""))
                else:
                    result = _parse_sporting_post_html(r.text)
                    if result:
                        logger.info(f"[SP] Retrieved {len(result)} runners from {url}")
                        return result
        except Exception as e:
            logger.debug(f"[SP] {url}: {e}")
    return {}


def _parse_sporting_post_html(html: str) -> dict:
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
            soup.select("table tr") or
            soup.select("div.entry-content tr")
        )
        for row in runner_rows:
            name_tag = (
                row.select_one(".horse-name a") or
                row.select_one(".runner-name a") or
                row.select_one("a.horse") or
                row.select_one("td.name a") or
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

        if not results:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                if not any(x in href for x in ["/horse/", "/form/", "horse-racing/database"]):
                    continue
                name = a_tag.get_text(strip=True).lower()
                if not name or len(name) < 3:
                    continue
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


def _fetch_nra_racecard(track: str, race_num: int, date_str: str) -> dict:
    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    date_nodash = date_str.replace("-", "")
    url_candidates = [
        f"https://www.tabonline.co.za/racing/race-cards/{date_str}/{track_slug}/{race_num}/",
        f"https://www.tabonline.co.za/racing/race-cards/{date_str}/{track_slug}/race-{race_num}/",
        f"https://www.tabonline.co.za/racing/cards/{track_slug}/{date_str}/race/{race_num}/",
        f"https://www.tabonline.co.za/racing/{track_slug}/{date_str}/race-{race_num}/",
        f"https://www.nra.co.za/racing/racecard/{date_str}/{track_slug}/{race_num}/",
        f"https://www.nra.co.za/racing/{date_str}/{track_slug}/{race_num}/",
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


def _fetch_sporting_life_racecard(track: str, race_num: int, date_str: str) -> dict:
    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    url_candidates = [
        f"https://www.sportinglife.com/racing/racecards/{date_str}/{track_slug}/",
        f"https://www.sportinglife.com/racing/racecards/south-africa/{date_str}/{track_slug}/",
        f"https://www.sportinglife.com/racing/results/south-africa/{date_str}/{track_slug}/",
        f"https://www.sportinglife.com/racing/results/{date_str}/{track_slug}/",
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
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        race_blocks = (
            soup.select(f"[data-race-number='{target_race_num}']") or
            soup.select(".race-card") or
            soup.select(".racecard-race") or
            [soup]
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

        if not results:
            nd = soup.find("script", id="__NEXT_DATA__")
            if nd and nd.string:
                try:
                    page_data = json.loads(nd.string)
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


def _fetch_turf_talk_racecard(track: str, race_num: int, date_str: str) -> dict:
    y, m, d = date_str.split("-")
    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    url_candidates = [
        f"https://turftalk.co.za/{y}/{m}/{d}/{track_slug}-racecards/",
        f"https://turftalk.co.za/{y}/{m}/{d}/{track_slug}-racecard/",
        f"https://turftalk.co.za/racecards/{track_slug}/{date_str}/",
        f"https://turftalk.co.za/race-cards/{track_slug}/{date_str}/race-{race_num}/",
        f"https://turftalk.co.za/races/{track_slug}/{date_str}/",
        f"https://turftalk.co.za/wp-json/wp/v2/posts?search={track_slug}+racecard&per_page=3",
    ]
    for url in url_candidates:
        try:
            r = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    posts = r.json()
                    if isinstance(posts, list) and posts:
                        rendered = posts[0].get("content", {}).get("rendered", "")
                        result = _parse_turf_talk_html(rendered)
                        if result:
                            return result
                else:
                    result = _parse_turf_talk_html(r.text)
                    if result:
                        return result
        except Exception as e:
            logger.debug(f"[TT] {url}: {e}")
    return {}


def _parse_turf_talk_html(html: str) -> dict:
    results = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
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


def _fetch_punters_data_source(track: str, race_num: int, date_str: str) -> dict:
    track_slug = track.lower().replace(" ", "-").replace("_", "-")
    date_nodash = date_str.replace("-", "")
    base_url = "https://www.punters.com.au/form-guide/"
    session = _make_session()
    parsed_runners = {}
    try:
        r = session.get(base_url, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            race_href = None
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if f"horses/{track_slug}-za-{date_nodash}" in href and f"race-{race_num}" in href:
                    race_href = href
                    break
            if not race_href:
                race_href = f"/form-guide/horses/{track_slug}-za-{date_nodash}/race-{race_num}/#Overview"
            
            target_url = f"https://www.punters.com.au{race_href}"
            logger.info(f"[Punters] Fetching Race Card: {target_url}")
            race_resp = session.get(target_url, timeout=12)
            if race_resp.status_code == 200:
                overview_runners = PuntersDataExtractor.parse_race_overview(race_resp.text)
                for runner in overview_runners:
                    name_key = runner["name"].lower().strip()
                    profile_url = runner.get("profile_url")
                    if profile_url:
                        prof_url = f"https://www.punters.com.au{profile_url}"
                        logger.info(f"[Punters] Fetching Profile: {prof_url} ({runner['name']})")
                        prof_resp = session.get(prof_url, timeout=10)
                        if prof_resp.status_code == 200:
                            horse_profile = PuntersDataExtractor.parse_horse_profile(prof_resp.text)
                            runner.update(horse_profile)
                    parsed_runners[name_key] = runner
                    time.sleep(0.4)
    except Exception as e:
        logger.warning(f"[Punters] Scraping pipeline failed: {e}")
    return parsed_runners


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

    invariant_log = _apply_race_name_invariants(runners, race_name)
    if invariant_log:
        all_enrichment_log.extend(invariant_log)

    online_data = {}
    print(f"[ZAF Enricher] → Punters.com.au deep forensic lookup...")
    online_data = _fetch_punters_data_source(track, race_num, date_str)
    if online_data:
        print(f"[ZAF Enricher]   Found {len(online_data)} comprehensive entries on Punters.com.au")

    if not online_data and use_sporting_post:
        online_data = _fetch_sporting_post_racecard(track, race_num, date_str)
    if not online_data and use_nra:
        online_data = _fetch_nra_racecard(track, race_num, date_str)
    if not online_data and use_sporting_life:
        online_data = _fetch_sporting_life_racecard(track, race_num, date_str)
    if not online_data and use_turf_talk:
        online_data = _fetch_turf_talk_racecard(track, race_num, date_str)

    online_log = []
    for runner in runners:
        name = str(runner.get("name", "")).strip()
        name_lower = name.lower()
        entry = online_data.get(name_lower, {})
        runner_changes = []

        if "age" in entry and runner.get("age_source") is None:
            old = runner.get("age")
            runner["age"] = entry["age"]
            runner["age_source"] = "online_source"
            if old != runner["age"]:
                runner_changes.append(f"age: {old} → {runner['age']} [online]")

        if "sex" in entry and runner.get("sex_source") is None:
            old = runner.get("sex") or runner.get("gender")
            runner["sex"] = entry["sex"]
            runner["gender"] = entry["sex"]
            runner["sex_source"] = "online_source"
            if str(old).upper() != str(runner["sex"]).upper():
                runner_changes.append(f"sex: {old} → {runner['sex']} [online]")

        if "apprentice_claim_kg" in entry:
            old = float(runner.get("apprentice_claim_kg", 0.0))
            new_claim = entry["apprentice_claim_kg"]
            if new_claim != old:
                runner["apprentice_claim_kg"] = new_claim
                runner["apprentice_claim_source"] = entry.get("apprentice_claim_source", "online")
                runner_changes.append(f"claim: {old:.2f} → {new_claim:.2f}kg [{runner['apprentice_claim_source']}]")

        existing_claim = float(runner.get("apprentice_claim_kg", 0.0))
        claim_source = str(runner.get("apprentice_claim_source", ""))
        if (existing_claim in [1.0, 2.0, 3.0, 5.0, 7.0] and
                claim_source == "" and
                "apprentice_claim_kg" not in entry):
            corrected = existing_claim * SA_LB_TO_KG
            runner["apprentice_claim_kg"] = corrected
            runner["apprentice_claim_source"] = "sportsbet_lb_corrected"
            runner_changes.append(f"claim unit: {existing_claim:.0f}lb → {corrected:.2f}kg [SA lb->kg]")

        if (infer_claims_from_jockey_list and
                float(runner.get("apprentice_claim_kg", 0.0)) == 0.0 and
                "apprentice_claim_kg" not in entry):
            inferred = _infer_claim_from_jockey_name(str(runner.get("jockey", "")))
            if inferred > 0:
                runner["apprentice_claim_kg"] = inferred
                runner["apprentice_claim_source"] = "inferred_apprentice_list"
                runner_changes.append(f"claim: 0.00 → {inferred:.2f}kg [apprentice list]")

        if "merit_rating" in entry:
            old = runner.get("merit_rating") or runner.get("rating")
            runner["merit_rating"] = entry["merit_rating"]
            if old != runner["merit_rating"]:
                runner_changes.append(f"merit_rating: {old} → {runner['merit_rating']}")

        ped = entry.get("pedigree", {})
        if ped.get("sire"):
            runner["sire"] = ped["sire"]
        if ped.get("dam"):
            runner["dam"] = ped["dam"]

        runs_history = entry.get("history_runs", [])
        if runs_history:
            runner["history_runs"] = runs_history

        if runner_changes:
            online_log.append({"name": name, "changes": runner_changes})

    all_enrichment_log.extend(online_log)

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
        all_enrichment_log.extend(barrier_log)

    race_json["enrichment_log"] = all_enrichment_log
    race_json["enrichment_applied"] = True
    race_json["enrichment_date"] = date_str
    return race_json


def apply_manual_corrections(race_json: dict, corrections: dict) -> dict:
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

    barrier_map = _compress_barriers(race_json.get("runners", []))
    for runner in race_json.get("runners", []):
        n = str(runner.get("name", "")).lower().strip()
        if n in barrier_map:
            runner["barrier_compressed"] = barrier_map[n]
    race_json["manual_correction_log"] = log
    race_json["enrichment_applied"] = True
    return race_json


def enrich_if_sa(race_json: dict, date_str: str, manual_corrections: dict = None) -> dict:
    track = str(
        race_json.get("venue") or race_json.get("track_name") or
        race_json.get("meeting_metadata", {}).get("track_name", "")
    ).lower()
    if not any(t in track for t in SA_TRACKS):
        return race_json
    if manual_corrections:
        race_json = apply_manual_corrections(race_json, manual_corrections)
    return enrich_sa_racecard(race_json, date_str)

# ======================================================================================================================================
# END OF FILE: zaf_data_enricher.py
# ======================================================================================================================================
