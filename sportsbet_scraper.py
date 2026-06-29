

# ======================================================================================================================================
# START OF FILE: sportsbet_scraper.py
# OPERATIONAL ROLE: SYSTEM SCRAPER COGNITIVE ARCHITECTURE & MEETING PARSER PIPELINE (RESTORED INTERFACES)
# LANGUAGE VARIATION: BRITISH UK ENGLISH (METRES, NORMALISATION, PRIORITISATION, PENALISE, ANALYSE)
# ======================================================================================================================================

import requests
import datetime
import urllib.parse
import sys
import json
import os
import time
import re
from bs4 import BeautifulSoup
from zaf_data_enricher import enrich_if_sa

from australian_logic import (
    BiomechanicalEngine,
    BiomechanicalOptimizer,
    BiomechanicalTextVectorizer,
    safe_int,
    safe_float,
    sanitize_path_name
)

BASE_API_URL = "https://www.sportsbet.com.au/apigw/sportsbook-racing/Sportsbook/Racing"
FORM_BASE = "https://www.sportsbetform.com.au"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.sportsbet.com.au",
    "Referer": "https://www.sportsbet.com.au/"
}

SIRE_AWD_LOOKUP = {
    "snitzel": 1100, "fastnet rock": 1400, "i am invincible": 1100, "so you think": 1800,
    "dundeel": 1800, "written tycoon": 1150, "savabeel": 1800, "zoustar": 1150,
    "extreme choice": 1050, "capitalist": 1100, "deep field": 1100, "rubick": 1150,
    "shalaa": 1200, "blue point": 1100, "shamardal": 1400, "lope de vega": 1400,
    "crackerjack king": 2000, "invincible spirit": 1200, "impending": 1200, 
    "asturn": 1200, "commands": 1400, "magnus": 1200
}

def get_current_date_string():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def generate_historical_dates():
    dates_list = []
    today = datetime.date.today()
    for i in range(1, 11):
        past_date = today - datetime.timedelta(days=i)
        date_str = past_date.strftime("%Y-%m-%d")
        day_name = past_date.strftime("%A")
        
        if i == 1:
            label = f"{day_name}, {date_str} (Yesterday)"
        elif i == 10:
            label = f"{day_name}, {date_str} (Maximum historical reach)"
        else:
            label = f"{day_name}, {date_str}"
            
        dates_list.append({
            "date": date_str,
            "label": label
        })
    return dates_list

def resolve_storage_paths(region, track, race_num, target_date):
    if any(x in str(track).lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]) or (region and "south africa" in str(region).lower()):
        region = "South_Africa"

    region_clean = sanitize_path_name(region or "Other")
    track_clean = sanitize_path_name(track or "Unknown_Track")
    race_clean = f"race_{safe_int(race_num, 1)}"
    
    base_dir = os.path.join("storage", target_date, region_clean, track_clean)
    os.makedirs(base_dir, exist_ok=True)
    
    json_path = os.path.join(base_dir, f"{race_clean}_data.json")
    pred_json_path = os.path.join(base_dir, f"{race_clean}_prediction.json")
    report_path = os.path.join(base_dir, f"{race_clean}_report.txt")
    
    return json_path, pred_json_path, report_path

def format_time_status(start_time_unix):
    race_time = datetime.datetime.fromtimestamp(start_time_unix)
    now = datetime.datetime.now()
    time_str = race_time.strftime('%H:%M')
    diff = (race_time - now).total_seconds()
    if diff < -120: return f"{time_str} (Resulted / Past)"
    elif diff < 0:  return f"{time_str} (Jumping Now!)"
    minutes = int(diff // 60)
    return f"{time_str} (< 1 min)" if minutes == 0 else f"{time_str} (in {minutes} mins)"

def print_separator(char="=", length=110):
    return char * length

def parse_stats_string(stat_str):
    if not stat_str or ":" not in stat_str: return 0, 0, 0
    try:
        parts = stat_str.split(":")
        starts = int(parts[0])
        subparts = parts[1].split("-")
        wins = int(subparts[0])
        seconds = int(subparts[1]) if len(subparts) > 1 else 0
        thirds = int(subparts[2]) if len(subparts) > 2 else 0
        places = wins + seconds + thirds
        return starts, wins, places
    except Exception:
        return 0, 0, 0

def clean_float_fallback(value, default=0.0):
    if not value:
        return default
    match = re.search(r'([\d.]+)', str(value))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return default
    return default

def fetch_all_racing(date_str):
    url = f"{BASE_API_URL}/AllRacing/{date_str}"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 400:
            return []
        response.raise_for_status()
        data = response.json()
        if "dates" in data and len(data["dates"]) > 0:
            return data["dates"][0].get("sections", [])
        return []
    except Exception as e:
        print(f"\n[!] Error fetching racing data for {date_str}: {e}")
        return []

def fetch_track_summary(track_name):
    formatted_track = track_name.lower().replace(" ", "-")
    url = f"{BASE_API_URL}/TrackSummaries/{urllib.parse.quote(formatted_track)}"
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            return response.json().get("description", "No description available.")
        return "No description available."
    except Exception:
        return "Failed to retrieve track summary."

def fetch_racecard_with_context(event_id, class_id=None):
    if class_id:
        url = f"{BASE_API_URL}/Events/{event_id}/RacecardWithContext?classId={class_id}"
    else:
        url = f"{BASE_API_URL}/Events/{event_id}/RacecardWithContext"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[!] Error fetching race card: {e}")
        return None

def verify_sa_track_surface_v36(track_name, target_date):
    track_name_lower = str(track_name).lower()
    if not any(x in track_name_lower for x in ["fairview", "greyville", "turffontein", "vaal", "scottsville", "kenilworth"]):
        return track_name
        
    print(f"[*] Running out-of-band South African track surface validation for {track_name}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    try:
        dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        day_str = dt.strftime("%d")
        month_str = dt.strftime("%B").lower()
        day_of_week = dt.strftime("%A").lower()
    except Exception:
        day_str, month_str, day_of_week = "", "", ""
        
    try:
        url = f"https://www.sportingpost.co.za/?s={track_name}+polytrack"
        if "vaal" in track_name_lower or "turffontein" in track_name_lower:
            url = f"https://www.sportingpost.co.za/?s={track_name}+classic"
            
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text().lower()
            
            if "fairview" in track_name_lower:
                phrases = [
                    "switched from the turf to the polytrack",
                    "fairview will be run on the polytrack",
                    "moved from the turf track to the polytrack",
                    "moves to the polytrack",
                    "fairview polytrack"
                ]
                for phrase in phrases:
                    if phrase in page_text:
                        if month_str in page_text or day_of_week in page_text:
                            print("[+] SWITCH DETECTED: Fairview meeting switched to Polytrack via Sporting Post!")
                            return "Fairview Polytrack"
                            
            elif "greyville" in track_name_lower:
                phrases = [
                    "switched from the turf to the polytrack",
                    "greyville will be run on the polytrack",
                    "moved from the turf track to the polytrack",
                    "moves to the polytrack"
                ]
                for phrase in phrases:
                    if phrase in page_text:
                        if month_str in page_text or day_of_week in page_text:
                            print("[+] SWITCH DETECTED: Greyville meeting switched to Polytrack via Sporting Post!")
                            return "Greyville Polytrack"
                            
            elif "turffontein" in track_name_lower or "vaal" in track_name_lower:
                phrases = [
                    "moves to the vaal classic",
                    "vaal classic track",
                    "moved to the vaal classic"
                ]
                for phrase in phrases:
                    if phrase in page_text:
                        if month_str in page_text or day_of_week in page_text:
                            print("[+] SWITCH DETECTED: Meeting switched to Vaal Classic Track via Sporting Post!")
                            return "Vaal Classic Track"
    except Exception as e:
        print(f"[!] Sporting Post out-of-band scrape failed: {e}")
        
    try:
        url = "https://www.goldcircle.co.za/"
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text().lower()
            
            if "fairview" in track_name_lower and "moved to the polytrack due" in page_text:
                if month_str in page_text or day_of_week in page_text:
                    print("[+] SWITCH DETECTED: Fairview Polytrack switch verified via Gold Circle!")
                    return "Fairview Polytrack"
            elif "greyville" in track_name_lower and "moved to the polytrack due" in page_text:
                if month_str in page_text or day_of_week in page_text:
                    print("[+] SWITCH DETECTED: Greyville Polytrack switch verified via Gold Circle!")
                    return "Greyville Polytrack"
    except Exception as e:
        print(f"[!] Gold Circle out-of-band fallback failed: {e}")
        
    try:
        url = "https://www.attheraces.com/results"
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text().lower()
            
            if "fairview" in track_name_lower:
                if any(x in page_text for x in ["fairview polytrack", "fairview (aw)", "fairview aw", "gas centre maiden juvenile plate (polytrack)", "tab dahlia plate (listed) (2yo) (polytrack)"]):
                    print("[+] SWITCH DETECTED: Fairview Polytrack switch verified via At The Races!")
                    return "Fairview Polytrack"
            elif "greyville" in track_name_lower:
                if any(x in page_text for x in ["greyville polytrack", "greyville aw", "greyville (aw)"]):
                    print("[+] SWITCH DETECTED: Greyville Polytrack switch verified via At The Races!")
                    return "Greyville Polytrack"
    except Exception as e:
        print(f"[!] ATR out-of-band scrape failed: {e}")
        
    return track_name


class SportsBetFormCrawler:
    @staticmethod
    def _get_ajax_headers(referer_url):
        return {
            "accept": "*/*",
            "accept-language": "en-GB,en;q=0.9",
            "cookie": "state=yes",
            "referer": referer_url,
            "x-requested-with": "XMLHttpRequest",
            "user-agent": HEADERS["User-Agent"]
        }

    @classmethod
    def resolve_form_ids(cls, sb_form_path):
        referer = f"{FORM_BASE}{sb_form_path}"
        form_ids = {"trainers": {}, "jockeys": {}}
        try:
            resp = requests.get(referer, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    m_t = re.match(r"^/Trainer/(\d+)/?$", href)
                    if m_t:
                        name = a.get_text(strip=True).strip()
                        form_ids["trainers"][name] = int(m_t.group(1))
                    m_j = re.match(r"^/Jockey/(\d+)/?$", href)
                    if m_j:
                        name = a.get_text(strip=True).strip()
                        form_ids["jockeys"][name] = int(m_j.group(1))
        except Exception:
            pass
        return form_ids, referer

    @classmethod
    def fetch_track_and_weather_details(cls, sb_form_path):
        url = f"{FORM_BASE}{sb_form_path}?view=Speedmap"
        details = {
            "track_status": "Unknown",
            "weather": {
                "temperature": None,
                "condition": None,
                "wind": None,
                "humidity": None
            },
            "track_details": {
                "conditions": None,
                "track_name": None,
                "rail_position": "True",
                "straight": "353.0",
                "circumference": "1811.0",
                "straight_metres": 353.0,
                "circumference_metres": 1811.0
            }
        }
        try:
            headers = {"User-Agent": HEADERS["User-Agent"]}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                weather_cond_div = soup.find('div', id='weather-conditions')
                if weather_cond_div:
                    cond_span = weather_cond_div.find('span', class_='head-conditions')
                    if cond_span:
                        text = cond_span.get_text(strip=True)
                        details["track_status"] = text.replace('Track:', '').strip()
                    temp_span = weather_cond_div.find('span', class_='temperature')
                    if temp_span:
                        details["weather"]["temperature"] = temp_span.get_text(strip=True)
                
                track_div = soup.find('div', id='trackDetails')
                if track_div:
                    weather_li = track_div.find('li', class_='weather')
                    if weather_li:
                        temp_span = weather_li.find('span', class_='temperature')
                        cond_span = weather_li.find('span', class_='weartherCondition')
                        if temp_span:
                            details["weather"]["temperature"] = temp_span.get_text(strip=True)
                        if cond_span:
                            details["weather"]["condition"] = cond_span.get_text(strip=True)
                        text_content = weather_li.get_text("\n")
                        wind_match = re.search(r'Wind:\s*(.*)', text_content, re.IGNORECASE)
                        humidity_match = re.search(r'Humidity:\s*(.*)', text_content, re.IGNORECASE)
                        if wind_match:
                            details["weather"]["wind"] = wind_match.group(1).strip()
                        if humidity_match:
                            details["weather"]["humidity"] = humidity_match.group(1).strip()
                    
                    track_li = None
                    for li in track_div.find_all('li'):
                        h3 = li.find('h3')
                        if h3 and "Track Details" in h3.get_text():
                            track_li = li
                            break
                    if track_li:
                        p_tag = track_li.find('p')
                        if p_tag:
                            p_text = p_tag.get_text("\n")
                            cond_match = re.search(r'Conditions:\s*(.*)', p_text, re.IGNORECASE)
                            track_match = re.search(r'Track:\s*(.*)', p_text, re.IGNORECASE)
                            rail_match = re.search(r'Rail Position:\s*(.*)', p_text, re.IGNORECASE)
                            straight_match = re.search(r'Straight:\s*(.*)', p_text, re.IGNORECASE)
                            circum_match = re.search(r'Circumference:\s*(.*)', p_text, re.IGNORECASE)
                            if cond_match:
                                details["track_details"]["conditions"] = cond_match.group(1).strip()
                                details["track_status"] = cond_match.group(1).strip()
                            if track_match:
                                details["track_details"]["track_name"] = track_match.group(1).strip()
                            if rail_match:
                                details["track_details"]["rail_position"] = rail_match.group(1).strip()
                            if straight_match:
                                s_val = straight_match.group(1).strip()
                                details["track_details"]["straight"] = s_val
                                s_digits = re.search(r'([\d.]+)', s_val)
                                if s_digits:
                                    details["track_details"]["straight_metres"] = float(s_digits.group(1))
                            if circum_match:
                                c_val = circum_match.group(1).strip()
                                details["track_details"]["circumference"] = c_val
                                c_digits = re.search(r'([\d.]+)', c_val)
                                if c_digits:
                                    details["track_details"]["circumference_metres"] = float(c_digits.group(1))
        except Exception as e:
            print(f"[!] Warning: Error fetching track & weather details: {e}")
        return details

    @classmethod
    def fetch_stats_profile(cls, entity_id, entity_type, referer_url):
        url = f"{FORM_BASE}/{entity_type}/{entity_id}/"
        profile = {
            "track_cond_sr": 0.10, "first_up_sr": 0.12, "second_up_sr": 0.10, "weight_sr": 0.08, "surface_sr": 0.10
        }
        try:
            resp = requests.get(url, headers=cls._get_ajax_headers(referer_url), timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                tables = soup.find_all("table")
                for table in tables:
                    header = table.find("th", class_="title")
                    if not header: continue
                    title = header.get_text(strip=True).lower()
                    if "spells" in title:
                        for tr in table.find_all("tr"):
                            title_td = tr.find("td", class_="title")
                            if title_td:
                                label = title_td.get_text(strip=True).lower()
                                tds = tr.find_all("td")
                                if len(tds) >= 6:
                                    sr = safe_float(tds[5].get_text(strip=True).replace("%", "")) / 100.0
                                    if "1st up" in label: profile["first_up_sr"] = sr
                                    elif "2nd up" in label: profile["second_up_sr"] = sr
                    elif "track conditions" in title:
                        for tr in table.find_all("tr"):
                            title_td = tr.find("td", class_="title")
                            if title_td:
                                label = title_td.get_text(strip=True).lower()
                                tds = tr.find_all("td")
                                if len(tds) >= 6:
                                    sr = safe_float(tds[5].get_text(strip=True).replace("%", "")) / 100.0
                                    if "heavy" in label: profile["track_cond_sr"] = sr
                    elif "track types" in title:
                        for tr in table.find_all("tr"):
                            title_td = tr.find("td", class_="title")
                            if title_td:
                                label = title_td.get_text(strip=True).lower()
                                tds = tr.find_all("td")
                                if len(tds) >= 6:
                                    sr = safe_float(tds[5].get_text(strip=True).replace("%", "")) / 100.0
                                    if "synthetic" in label: profile["surface_sr"] = sr
        except Exception:
            pass
        return profile


def render_biomechanical_analysis(engine, linked_json_path=""):
    ranked_field = engine.rank_field()
    if not ranked_field:
        return "No active runners generated calculations."
        
    output_lines = []
    is_saf = False
    try:
        from south_african_logic import SouthAfricanBiomechanicalEngine
        if isinstance(engine, SouthAfricanBiomechanicalEngine):
            is_saf = True
    except ImportError:
        pass

    if is_saf:
        output_lines.append("SOUTH AFRICAN EXPERT FORENSIC CALIBRATION REPORT [SAF MASTER PROMPT V3.6 COMPLIANT]")
        output_lines.append(print_separator("="))
        output_lines.append(f"Date: {get_current_date_string()} | Venue: {engine.track_name} Race {engine.race_number}")
        output_lines.append(f"Locked Surface: {engine.silo.upper()} | Expected Pace (QPT): {engine.predicted_pace}")
        output_lines.append(f"Soil MSCI Index: {engine.msci_eff:.3f} | Ambient Temperature: {engine.ambient_temp}°C")
        output_lines.append(print_separator("-"))
        output_lines.append("1. PWG IMMUTABLE MATRIX VERIFICATION")
        output_lines.append(f"  - Calculated Track Temperature: {engine._calculate_t_track():.2f}°C")
        output_lines.append(f"  - Inside-Rail Wear Friction (IRWFC) Status: Active (Capped at 0.15 for low draws)")
        output_lines.append(print_separator("-"))
        if linked_json_path:
            output_lines.append(f"LOCAL DATA ARCHIVE REFERENCE: {os.path.abspath(linked_json_path)}")
        output_lines.append(print_separator("="))

        output_lines.append("\n2. BIOMECHANICAL EFFICIENCY CALCULATIONS")
        output_lines.append(print_separator("-"))
        output_lines.append(f"{'No./Chassis Name':<22} | {'Draw':<6} | {'Mass (kg)':<7} | {'Biomechanical Score':<15} | {'Designation'}")
        output_lines.append(print_separator("-"))
        for item in ranked_field:
            name_trunc = f"#{item['number']} {item['name']}"[:21]
            output_lines.append(f"{name_trunc:<22} | {item['barrier_recalculated']:<6} | {item['weight_effective']:<7.1f} | {item['ski_score']:<15.3f} | {item['designation']}")
        output_lines.append(print_separator("-"))

        output_lines.append("\n3. FINAL SYSTEMIC PREDICTION (FIRST FOUR ORDERING MATRIX - FFOM)")
        output_lines.append(print_separator("-"))
        primary = ranked_field[0]
        output_lines.append(f" Position 1 (1A SOVEREIGN 1st): No. {primary['number']} {primary['name']} (Draw {primary['barrier_recalculated']})")
        if len(ranked_field) >= 2:
            shield = ranked_field[1]
            output_lines.append(f" Position 2 (1B SHIELD 2nd):    No. {shield['number']} {shield['name']} (Draw {shield['barrier_recalculated']})")
        if len(ranked_field) >= 3:
            combat = ranked_field[2]
            output_lines.append(f" Position 3 (1C COMBAT 3rd):    No. {combat['number']} {combat['name']} (Draw {combat['barrier_recalculated']})")
        if len(ranked_field) >= 4:
            val_pick = ranked_field[3]
            output_lines.append(f" Position 4 (1D VALUE 4th):     No. {val_pick['number']} {val_pick['name']} (Draw {val_pick['barrier_recalculated']})")
            
        output_lines.append("\n Betting Playbook Strategy:")
        output_lines.append(f"  - Sovereign Target (Win Priority): WIN on No. {primary['number']} {primary['name']}")
        if len(ranked_field) >= 4:
            p_no = primary['number']
            s_no = ranked_field[1]['number']
            c_no = ranked_field[2]['number']
            v_no = ranked_field[3]['number']
            
            output_lines.append(f"  - Exacta Combo: {p_no} / {s_no}")
            output_lines.append(f"  - Swinger Box:  {p_no}, {s_no}, {c_no}")
            output_lines.append(f"  - Trifecta (Direct Sequence): {p_no} / {s_no} / {c_no}")
            output_lines.append(f"  - Exact First Four (Superfecta Sequence): {p_no} -> {s_no} -> {c_no} -> {v_no}")
            output_lines.append(f"  - Protective First Four Box Strategy: Box {p_no}, {s_no}, {c_no}, {v_no}")
    else:
        matched_runners = [item for item in ranked_field if item.get("matched_dsps")]
        has_matches = len(matched_runners) > 0

        output_lines.append("BIOMECHANICAL CLASSIFIER MODEL FORENSIC OUTPUT v4.4 [Deterministic DSP Mode]")
        output_lines.append(print_separator("-"))
        output_lines.append(f"Date: {get_current_date_string()}")
        output_lines.append(f"TRACK: {engine.track_name} | DISTANCE: {engine.distance}m | MODEL SILO: {engine.regional_silo}")
        
        if has_matches:
            output_lines.append("\n[+] DETERMINISTIC SIGNATURE PATTERN (DSP) MATCH DETECTED!")
            output_lines.append("    Status: ACTIVE PLAY - Bet on the matched contenders.")
        else:
            output_lines.append("\n[!] NO SIGNATURE PATTERNS DETECTED.")
            output_lines.append("    Status: SKIP THIS RACE (No runner satisfies DSP criteria).")
            
        if linked_json_path:
            output_lines.append(f"LOCAL DATA ARCHIVE REFERENCE: {os.path.abspath(linked_json_path)}")
        output_lines.append(print_separator("="))

        output_lines.append("\n2. BIOMECHANICAL EFFICIENCY CALCULATIONS (DSP FOCUS)")
        output_lines.append(print_separator("-"))
        output_lines.append(f"{'No./Chassis Name':<22} | {'Draw':<6} | {'Mass (kg)':<7} | {'Biomechanical Score':<15} | {'Matched DSPs'}")
        output_lines.append(print_separator("-"))
        for item in ranked_field:
            name_trunc = f"#{item['number']} {item['name']}"[:21]
            dsps_str = ", ".join(item.get("matched_dsps", [])) if item.get("matched_dsps") else "None (Skip Selection)"
            output_lines.append(f"{name_trunc:<22} | {item['barrier_recalculated']:<6} | {item['weight_effective']:<7.1f} | {item['ski_score']:<15.3f} | {dsps_str}")
        output_lines.append(print_separator("-"))

        output_lines.append("\n3. FINAL SYSTEMIC PREDICTION")
        output_lines.append(print_separator("-"))
        
        if has_matches:
            primary = matched_runners[0]
            output_lines.append(f" Primary Biomechanical Contender: No. {primary['number']} {primary['name']} (Barrier {primary['barrier_recalculated']})")
            output_lines.append(f" Matched Patterns: {', '.join(primary['matched_dsps'])}")
            
            if len(matched_runners) >= 2:
                cover = matched_runners[1]
                output_lines.append(f" Cover Contender: No. {cover['number']} {cover['name']} (Barrier {cover['barrier_recalculated']})")
                output_lines.append(f" Matched Patterns: {', '.join(cover['matched_dsps'])}")
                
            output_lines.append("\n Betting Playbook Strategy:")
            output_lines.append(f"  - Sovereign Target (Win/Place Priority): WIN on No. {primary['number']} {primary['name']}")
            
            if len(matched_runners) >= 2:
                exacta_legs = [str(m['number']) for m in matched_runners[1:3]]
                output_lines.append(f"  - Protective Cover Exacta: {primary['number']} / {', '.join(exacta_legs)}")
                output_lines.append(f"  - Swinger (Box): {primary['number']}, {matched_runners[1]['number']}")
                output_lines.append(f"  - Systemic Trifecta: {primary['number']} / {', '.join(exacta_legs)} / {', '.join([str(m['number']) for m in matched_runners[1:4]])}")
        else:
            output_lines.append(" Active Recommendation: SKIP THE RACE")
            output_lines.append("  - Reason: Zero runners satisfied the high-probability Deterministic Signature Patterns (DSPs).")
            output_lines.append("  - Strategy: Preserve bankroll capital; wait for next structural play alignment.")
    output_lines.append("=" * 110)

    race_results = engine.raw_data.get("race_results", {"status": "Unresulted", "finishing_order": []})
    if race_results.get("status") == "Resulted":
        output_lines.append("\n4. POST-RACE VALIDATION AUDIT")
        output_lines.append(print_separator("-"))
        order = race_results.get("finishing_order", [])
        order_strs = [f"{o['position']}: No. {o['number']} {o['name']}" for o in order[:3]]
        output_lines.append(" Actual Result: " + " | ".join(order_strs))
        
        primary_no = primary["number"] if (not is_saf and has_matches) else (ranked_field[0]["number"])
        actual_pos = next((o["position"] for o in order if o["number"] == primary_no), None)
        pos_str = f"Rank {actual_pos}" if actual_pos else "Unplaced"
        output_lines.append(f" Primary Pick Position Outcome: {pos_str}")
        output_lines.append("=" * 110)
    return "\n".join(output_lines)


def scan_and_validate_historical_races():
    print("\n" + "="*110)
    print(" INITIATING RECURSIVE DATA ARCHIVE SCAN...")
    print("="*110)
    
    training_set = BiomechanicalOptimizer.collect_completed_races(force_reload=True)
    total_audited = len(training_set)
    
    if total_audited == 0:
        print("[!] Validation aborted: Zero completed races discovered in local storage.")
        print("[*] Retrieve racing data using Option [1] or Option [5] first.")
        return
        
    print(f"[*] Loaded {total_audited} completed races with verified results.")
    print("\n" + "="*110)
    print(f" {'Track / Race Name':<35} | {'Sovereign Pick':<20} | {'Result':<10} | {'Model Classification Strategy'}")
    print(print_separator("-"))
    
    primary_hits = 0
    top2_hits = 0
    top3_hits = 0
    for data in training_set:
        region = data.get("region", "Other")
        track = data.get("venue", data.get("track", "Unknown"))
        if any(x in str(track).lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]) or "south africa" in str(region).lower():
            from south_african_logic import SouthAfricanBiomechanicalEngine
            engine = SouthAfricanBiomechanicalEngine(data)
        else:
            silo_key = BiomechanicalOptimizer._get_silo_key(data)
            silo_weights = BiomechanicalOptimizer.get_weights_for_silo(silo_key)
            engine = BiomechanicalEngine(data, weights_override=silo_weights)
            
        ranked = engine.rank_field()
        if not ranked: continue
        primary_pick = ranked[0]
        primary_no = primary_pick["number"]
        finishing_order = data.get("race_results", {}).get("finishing_order", [])
        actual_pos = None
        for item in finishing_order:
            if item.get("number") == primary_no:
                actual_pos = item.get("position")
                break
        classification = "Category Omega — Field Deceleration"
        if actual_pos == 1:
            primary_hits += 1
            top2_hits += 1
            top3_hits += 1
            classification = "Category Alpha — Sovereign Winner"
        elif actual_pos == 2:
            top2_hits += 1
            top3_hits += 1
            classification = "Category Beta — Cover Protection"
        elif actual_pos == 3:
            top3_hits += 1
            classification = "Category Gamma — Placement Match"
        race_display = f"{data.get('race_name', 'Unknown')}"[:34]
        contender_display = f"#{primary_no} {primary_pick['name']}"[:19]
        pos_display = f"Rank {actual_pos}" if actual_pos else "Unplaced"
        print(f" {race_display:<35} | {contender_display:<20} | {pos_display:<10} | {classification}")
    print(print_separator("="))
    print(" COMPREHENSIVE REPEATABLE PREDICTOR HIT-RATE AUDIT")
    print(print_separator("-"))
    print(f" Total Audited Races: {total_audited}")
    print(f" Biomechanical Sovereign Accuracy (1st Place): {primary_hits} / {total_audited} ({primary_hits/total_audited*100:.1f}%)")
    print(f" Combined Placement Model Match (Top 2): {top2_hits} / {total_audited} ({top2_hits/total_audited*100:.1f}%)")
    print(f" Combined Placement Model Match (Top 3): {top3_hits} / {total_audited} ({top3_hits/total_audited*100:.1f}%)")
    print("="*110 + "\n")


def run_bulk_meeting_analysis(meeting, target_date):
    events = meeting.get("events", [])
    class_id = meeting.get("classId")
    region = meeting.get("regionName")
    track = meeting.get("name")
    if not events:
        print("[!] No active races resolved for this meeting.")
        return
    print("\n" + "="*110)
    print(f" INITIALISING BULK ANALYSIS: {track.upper()} ({region.upper()}) | DATE: {target_date}")
    print("="*110)
    for idx, event in enumerate(events, 1):
        event_id = event["id"]
        race_name = event.get("name", f"Race {event.get('raceNumber')}")
        race_num = event.get("raceNumber", idx)
        print(f"\n[*] Processing Race {race_num}/{len(events)}: {race_name}...")
        json_path, pred_json_path, report_path = resolve_storage_paths(region, track, race_num, target_date)
        extract_and_save_form_guide(
            event_id=event_id,
            class_id=class_id,
            race_name=race_name,
            json_path=json_path,
            pred_json_path=pred_json_path,
            report_path=report_path,
            region=region,
            track=track,
            race_num=race_num,
            target_date=target_date,
            event_data=event
        )
        if not os.path.exists(json_path):
            continue
        with open(json_path, 'r', encoding='utf-8') as f:
            saved_db_data = json.load(f)
        if any(x in str(track).lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]) or (region and "south africa" in str(region).lower()):
            from south_african_logic import SouthAfricanBiomechanicalEngine
            engine = SouthAfricanBiomechanicalEngine(saved_db_data)
        else:
            engine = BiomechanicalEngine(saved_db_data)
            
        report_content = render_biomechanical_analysis(engine, linked_json_path=json_path)
        with open(report_path, "w", encoding="utf-8") as rf:
            rf.write(report_content)
            
        pred_data = {
            "race_name": engine.race_name,
            "silo": engine.regional_silo,
            "weights_applied": engine.weights,
            "predictions": [
                {
                    "number": item["number"],
                    "name": item["name"],
                    "barrier": item["barrier_recalculated"],
                    "weight_kg": item["weight_effective"],
                    "score": item["ski_score"],
                    "designation": item["designation"],
                    "matched_dsps": item.get("matched_dsps", [])
                }
                for item in engine.rank_field()
            ]
        }
        with open(pred_json_path, 'w', encoding='utf-8') as pf:
            json.dump(pred_data, pf, indent=4, ensure_ascii=False)
        print(f"  [+] Saved biomechanical analysis report: {os.path.abspath(report_path)}")


def bulk_scrape_missing_historical_races():
    print("\n" + "="*110)
    print(" INITIATING HISTORICAL ARCHIVE SCANNER")
    print("="*110)
    print(" Select Race Classification to Target:")
    print("  1. Thoroughbred Horses Only (Default)")
    print("  2. Greyhounds Only")
    print("  3. Harness Only")
    print("  4. All Classifications (Horses, Greyhounds, and Harness)")
    print(print_separator("-"))
    choice = input("Enter option (1-4, Default: 1): ").strip()
    
    target_types = ["Horses"]
    if choice == '2':
        target_types = ["Greyhounds"]
    elif choice == '3':
        target_types = ["Harness"]
    elif choice == '4':
        target_types = ["Horses", "Greyhounds", "Harness"]
        
    print(f"\n[*] Targeted classifications: {', '.join(target_types)}")
    history_list = generate_historical_dates()
    today_str = get_current_date_string()
    current_time = time.time()
    
    date_to_day = {}
    discovered_regions = set()
    discovered_days = set()
    
    for item in history_list:
        try:
            dt = datetime.datetime.strptime(item["date"], "%Y-%m-%d")
            day_name = dt.strftime("%A")
            date_to_day[item["date"]] = day_name
            discovered_days.add(day_name)
        except Exception:
            date_to_day[item["date"]] = "Unknown"

    all_meetings_metadata = []
    print("[*] Performing quick metadata scan across 10-day schedule...")
    for i, item in enumerate(history_list, 1):
        target_date = item["date"]
        if target_date == today_str: continue
        sections = fetch_all_racing(target_date)
        if not sections: continue
        filtered_sections = [s for s in sections if s.get("displayName") in target_types]
        for section in filtered_sections:
            meetings = section.get("meetings", [])
            for meeting in meetings:
                region = meeting.get("regionName") or "Other"
                discovered_regions.add(region)
                day_name = date_to_day.get(target_date, "Unknown")
                discovered_days.add(day_name)
                all_meetings_metadata.append({
                    "date": target_date,
                    "day_name": day_name,
                    "region": region,
                    "meeting": meeting
                })

    available_regions = sorted(list(discovered_regions))
    available_days = sorted(list(discovered_days))

    print("\n" + "="*110)
    print(" FILTER BY REGION / COUNTRY")
    print("="*110)
    print(" 0. All Regions")
    for idx, reg in enumerate(available_regions, 1):
        print(f" {idx}. {reg}")
    print(print_separator("-"))
    region_choice = input(f"Select Country/Region filter (0-{len(available_regions)}): ").strip()
    
    selected_region = None
    if region_choice.isdigit():
        r_idx = int(region_choice)
        if 1 <= r_idx <= len(available_regions):
            selected_region = available_regions[r_idx - 1]

    print("\n" + "="*110)
    print(" FILTER BY DAY OF THE WEEK")
    print("="*110)
    print(" 0. All Days")
    for idx, day in enumerate(available_days, 1):
        print(f" {idx}. {day}")
    print(print_separator("-"))
    day_choice = input(f"Select Day of Week filter (0-{len(available_days)}): ").strip()
    
    selected_day = None
    if day_choice.isdigit():
        d_idx = int(day_choice)
        if 1 <= d_idx <= len(available_days):
            selected_day = available_days[d_idx - 1]

    filtered_meetings = []
    for meta in all_meetings_metadata:
        if selected_region and meta["region"] != selected_region: continue
        if selected_day and meta["day_name"] != selected_day: continue
        filtered_meetings.append(meta)

    queue = []
    scraped_count = 0
    skipped_count = 0

    for meta in filtered_meetings:
        target_date = meta["date"]
        meeting = meta["meeting"]
        region = meta["region"]
        track = meeting.get("name")
        events = meeting.get("events", [])
        class_id = meeting.get("classId")
        
        for idx, event in enumerate(events, 1):
            race_num = event.get("raceNumber", idx)
            event_id = event["id"]
            race_name = event.get("name", f"Race {race_num}")
            start_time = event.get("startTime", 0)
            if start_time >= current_time - 600:
                skipped_count += 1
                continue
                
            json_path, pred_json_path, report_path = resolve_storage_paths(region, track, race_num, target_date)
            is_valid = False
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        test_data = json.load(f)
                    runners_list = test_data.get("runners", [])
                    if runners_list: is_valid = True
                except Exception:
                    pass
            if is_valid:
                scraped_count += 1
            else:
                queue.append({
                    "event_id": event_id,
                    "class_id": class_id,
                    "race_name": race_name,
                    "json_path": json_path,
                    "pred_json_path": pred_json_path,
                    "report_path": report_path,
                    "region": region,
                    "track": track,
                    "race_num": race_num,
                    "target_date": target_date,
                    "event_data": event
                })

    print(f"\n[*] Found {len(queue)} missing runs. Commencing programmatic scrape...")
    for i, task in enumerate(queue, 1):
        print(f"\n[{i}/{len(queue)}] Extracting: {task['race_name']} at {task['track']} ({task['target_date']})")
        extract_and_save_form_guide(
            event_id=task["event_id"],
            class_id=task["class_id"],
            race_name=task["race_name"],
            json_path=task["json_path"],
            pred_json_path=task["pred_json_path"],
            report_path=task["report_path"],
            region=task["region"],
            track=task["track"],
            race_num=task["race_num"],
            target_date=task["target_date"],
            event_data=task.get("event_data")
        )
        time.sleep(0.5)


def bulk_update_missing_results():
    print("\n" + "="*110)
    print(" INITIATING BULK RESULTS SYNCHRONIZATION")
    print("="*110)
    storage_dir = "storage"
    if not os.path.exists(storage_dir):
        print("[!] Storage directory is empty. No local profiles found to evaluate.")
        return

    unresulted_tasks = []
    for root, _, files in os.walk(storage_dir):
        for file in files:
            if file.endswith("_data.json"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    continue
                results = data.get("race_results", {})
                if results.get("status") != "Resulted":
                    norm_path = os.path.normpath(file_path)
                    parts = norm_path.split(os.sep)
                    if len(parts) >= 5:
                        target_date = parts[-4]
                        region = parts[-3]
                        track = parts[-2]
                        match = re.search(r'race_(\d+)', parts[-1])
                        race_num = int(match.group(1)) if match else 1

                        unresulted_tasks.append({
                            "file_path": file_path,
                            "event_id": data.get("event_id"),
                            "race_name": data.get("race_name", f"Race {race_num}"),
                            "target_date": target_date,
                            "region": region,
                            "track": track,
                            "race_num": race_num
                        })

    if not unresulted_tasks:
        print("[*] Local database has no unresulted races. All entries are fully synchronised.")
        return

    print(f"[*] Updating {len(unresulted_tasks)} profiles sequentially...")
    for i, task in enumerate(unresulted_tasks, 1):
        print(f"\n[{i}/{len(unresulted_tasks)}] Checking: {task['race_name']} at {task['track']} ({task['target_date']})")
        extract_and_save_form_guide(
            event_id=task["event_id"],
            class_id=None,
            race_name=task["race_name"],
            json_path=task["file_path"],
            pred_json_path=task["file_path"].replace("_data.json", "_prediction.json"),
            report_path=task["file_path"].replace("_data.json", "_report.txt"),
            region=task["region"],
            track=task["track"],
            race_num=task["race_num"],
            target_date=task["target_date"]
        )
        time.sleep(0.5)


def fetch_scratched_from_html(region, track, race_num, event_id):
    if any(x in str(track).lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]) or (region and "south africa" in str(region).lower()):
        region = "South_Africa"
    region_slug = "australia-nz"
    if region:
        r_lower = region.lower()
        if any(x in r_lower for x in ["australia", "nz", "new zealand"]):
            region_slug = "australia-nz"
        elif any(x in r_lower for x in ["south_africa", "south africa"]):
            region_slug = "south-africa"
        elif any(x in r_lower for x in ["asia", "japan", "hong kong"]):
            region_slug = "asia-racing"
    track_slug = sanitize_path_name(track).lower().replace("_", "-")
    url = f"https://www.sportsbet.com.au/horse-racing/{region_slug}/{track_slug}/race-{race_num}-{event_id}"
    scratched_names = set()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            scratched_elements = soup.find_all(attrs={"data-automation-id": "racecard-outcome-scratched"})
            for elem in scratched_elements:
                text = elem.get_text(strip=True)
                cleaned = re.sub(r'^\d+\s*\.\s*', '', text).split('(')[0].strip().lower()
                if cleaned: scratched_names.add(cleaned)
    except Exception:
        pass
    return scratched_names


def parse_positions_from_html_content(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    results_mapping = {}
    rows = soup.find_all(attrs={"data-automation-id": "results-row"}) or soup.find_all(class_=re.compile(r'resultRow_'))
    for idx, row in enumerate(rows, 1):
        ordinal_elem = row.find(attrs={"data-automation-id": "racecard-podium-ordinal"})
        position = None
        if ordinal_elem:
            ord_match = re.search(r'(\d+)', ordinal_elem.get_text(strip=True))
            if ord_match: position = int(ord_match.group(1))
        if not position: position = idx
        name_elem = row.find(attrs={"data-automation-id": "racecard-outcome-name"})
        if name_elem:
            spans = name_elem.find_all("span")
            if len(spans) >= 1:
                full_name_text = spans[0].get_text(strip=True)
                num_match = re.match(r'^(\d+)\s*\.\s*(.*)$', full_name_text)
                if num_match:
                    results_mapping[int(num_match.group(1))] = position
    return results_mapping


def parse_full_results_from_html(html_text):
    if not html_text: return []
    soup = BeautifulSoup(html_text, "html.parser")
    results = []
    rows = soup.find_all(attrs={"data-automation-id": "results-row"}) or soup.find_all(class_=re.compile(r'resultRow_'))
    for idx, row in enumerate(rows, 1):
        ordinal_elem = row.find(attrs={"data-automation-id": "racecard-podium-ordinal"})
        position = None
        if ordinal_elem:
            ord_match = re.search(r'(\d+)', ordinal_elem.get_text(strip=True))
            if ord_match: position = int(ord_match.group(1))
        if not position: position = idx
        saddle_no = None
        horse_name = None
        barrier = None
        name_elem = row.find(attrs={"data-automation-id": "racecard-outcome-name"}) or row.find(attrs={"data-automation-id": "results-row"})
        if name_elem:
            spans = name_elem.find_all("span")
            if len(spans) >= 1:
                full_name_text = spans[0].get_text(strip=True)
                num_match = re.match(r'^(\d+)\s*\.\s*(.*)$', full_name_text)
                if num_match:
                    saddle_no = int(num_match.group(1))
                    horse_name = num_match.group(2).strip()
                else:
                    horse_name = full_name_text
            for span in spans[1:]:
                b_match = re.search(r'^\((\d+)\)$', span.get_text(strip=True))
                if b_match:
                    barrier = int(b_match.group(1))
                    break
        jockey = None
        jockey_elem = row.find(attrs={"data-automation-id": "racecard-outcome-info-jockey"})
        if jockey_elem:
            jockey = jockey_elem.get_text(strip=True).replace("J:", "").strip()
        trainer = None
        trainer_elem = row.find(attrs={"data-automation-id": "racecard-outcome-info-trainer"})
        if trainer_elem:
            trainer = trainer_elem.get_text(strip=True).replace("T:", "").strip()
        margin = None
        margin_elem = row.find(attrs={"data-automation-id": "racecard-outcome-info-margin"})
        if margin_elem:
            margin = margin_elem.get_text(strip=True).replace("Margin:", "").replace("M:", "").strip()
        if saddle_no:
            results.append({
                "position": position,
                "number": saddle_no,
                "name": horse_name or f"Unknown Horse {saddle_no}",
                "barrier": barrier,
                "jockey": jockey,
                "trainer": trainer,
                "margin": margin
            })
    return results


def extract_results_from_json_state(data):
    results_found = {}
    def scan(node):
        if isinstance(node, dict):
            saddle = node.get("runnerNumber") or node.get("runnerNo") or node.get("number")
            if saddle:
                s_no = safe_int(saddle)
                place = node.get("place") or node.get("finishingPosition") or node.get("finishing_position")
                margin = node.get("margin")
                res_obj = node.get("result")
                if isinstance(res_obj, dict):
                    if not place: place = res_obj.get("position") or res_obj.get("place")
                    if not margin: margin = res_obj.get("margin")
                if place:
                    results_found[s_no] = {
                        "position": safe_int(place),
                        "number": s_no,
                        "name": node.get("name"),
                        "barrier": node.get("drawNumber") or node.get("draw") or node.get("barrier"),
                        "jockey": node.get("jockey") or node.get("jockeyName"),
                        "trainer": node.get("trainer") or node.get("trainerName"),
                        "margin": margin
                    }
            for val in node.values(): scan(val)
        elif isinstance(node, list):
            for item in node: scan(item)
    scan(data)
    return list(results_found.values())


def parse_results_from_next_data(html_text):
    if not html_text: return []
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    if not match: return []
    try:
        data = json.loads(match.group(1))
        return extract_results_from_json_state(data)
    except Exception:
        return []


def parse_results_from_all_sources(api_data, html_text):
    results = []
    if api_data:
        results = extract_results_from_json_state(api_data)
        if results: return results
    if html_text:
        results = parse_results_from_next_data(html_text)
        if results: return results
    if html_text:
        results = parse_full_results_from_html(html_text)
        if results: return results
    return []


def parse_scratched_from_html_content(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    scratched_names = set()
    scratched_elements = soup.find_all(attrs={"data-automation-id": "racecard-outcome-scratched"})
    for elem in scratched_elements:
        text = elem.get_text(strip=True)
        cleaned = re.sub(r'^\d+\s*\.\s*', '', text).split('(')[0].strip().lower()
        if cleaned: scratched_names.add(cleaned)
    return scratched_names


def extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, region, track, race_num, target_date, event_data=None):
    try:
        track = verify_sa_track_surface_v36(track, target_date)
        json_path, pred_json_path, report_path = resolve_storage_paths(region, track, race_num, target_date)
        
        data = fetch_racecard_with_context(event_id, class_id)
        if not data or "racecardEvent" not in data: return
        race = data["racecardEvent"]
        
        region_slug = "australia-nz"
        if region:
            r_lower = region.lower()
            if any(x in r_lower for x in ["south_africa", "south africa"]):
                region_slug = "south-africa"
            elif any(x in r_lower for x in ["asia", "japan", "hong kong"]):
                region_slug = "asia-racing"
        
        track_slug = sanitize_path_name(track).lower().replace("_", "-")
        url = f"https://www.sportsbet.com.au/horse-racing/{region_slug}/{track_slug}/race-{race_num}-{event_id}"
        
        html_text = ""
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code == 200: html_text = resp.text
        except Exception:
            pass
            
        sb_form_path = None
        if html_text:
            sb_form_path_match = re.search(r'href="(/[\d]+/[\d]+/)\?view=Speedmap"', html_text)
            if not sb_form_path_match:
                sb_form_path_match = re.search(r'href="(/[\d]+/[\d]+/)"', html_text)
            if sb_form_path_match: sb_form_path = sb_form_path_match.group(1)
                
        if not sb_form_path:
            sb_form_path = f"/{track_slug}/{target_date.replace('-', '')}/race-{race_num}/"
            
        web_details = SportsBetFormCrawler.fetch_track_and_weather_details(sb_form_path)
        temp_c = clean_float_fallback(web_details["weather"].get("temperature"), 20.0)
        humidity_pct = clean_float_fallback(web_details["weather"].get("humidity"), 70.0)
        wind_kph = clean_float_fallback(web_details["weather"].get("wind"), 10.0)
        wind_dir = "N"
        if web_details["weather"].get("wind"):
            parts = str(web_details["weather"].get("wind")).split(" ")
            if parts: wind_dir = parts[0]
            
        race_db = {
            "event_id": event_id,
            "region": region or "Other",
            "venue": track or "Unknown",
            "track": track or "Unknown",
            "race_name": race.get("name"),
            "distance": race.get("distance"),
            "track_status": web_details["track_status"] if web_details["track_status"] != "Unknown" else race.get("trackStatus", "Unknown"),
            "start_time": race.get("startTime"),
            "scraped_at": datetime.datetime.now().isoformat(),
            "weather": web_details["weather"],
            "track_details": web_details["track_details"],
            "meeting_metadata": {
                "track_name": track or "Unknown",
                "rail_position": web_details["track_details"].get("rail_position", "True"),
                "straight_length_metres": web_details["track_details"].get("straight_metres", 353.0),
                "circumference_metres": web_details["track_details"].get("circumference_metres", 1811.0),
                "weather_forecast_hourly": [{
                    "temperature_celsius": temp_c,
                    "humidity_percentage": humidity_pct,
                    "wind_speed_kph": wind_kph,
                    "wind_direction": wind_dir
                }]
            },
            "runners": []
        }
        
        markets = race.get("markets", [])
        selections = []
        primary_market = next((m for m in markets if m.get("name") in ["Win or Place", "Win"]), None)
        if primary_market and primary_market.get("selections"):
            selections = primary_market["selections"]
        if not selections and race.get("runners"):
            selections = race["runners"]
            
        if selections:
            form_ids, referer_url = SportsBetFormCrawler.resolve_form_ids(sb_form_path)
            for index, item in enumerate(selections, 1):
                name = item.get("name", "Unknown")
                saddle_no = safe_int(item.get("saddleNumber", item.get("number", index)))
                barrier = safe_int(item.get("barrier") or 8)
                weight = safe_float(item.get("weight") or item.get("carried_weight_kg") or 56.0)
                age = safe_float(item.get("age") or 0.0)
                sex = str(item.get("sex") or item.get("gender") or "").upper().strip()
                overview = str(item.get("overview") or "")
                
                if (age == 0.0 or not sex) and overview:
                    parsed_age, parsed_sex_idx = BiomechanicalTextVectorizer.parse_physical_chassis(overview)
                    if age == 0.0: age = parsed_age
                    if not sex: sex = "F" if parsed_sex_idx in [1.0, 1.5] else "G"
                
                jockey_name = item.get("jockey") or item.get("jockeyName") or ""
                apprentice_claim = safe_float(item.get("apprenticeClaim") or 0.0)
                sire_name = str(item.get("sire", "")).lower().strip()
                sire_awd = SIRE_AWD_LOOKUP.get(sire_name, 1200)
                
                j_sr = safe_float(item.get("jockey_win_rate_pct", 10.0)) / 100.0
                t_sr = safe_float(item.get("trainer_win_rate_pct", 10.0)) / 100.0
                
                runner_record = {
                    "number": saddle_no,
                    "original_barrier": barrier,
                    "carried_weight_kg": weight,
                    "apprentice_claim_kg": apprentice_claim,
                    "name": name,
                    "jockey": jockey_name,
                    "jockey_wet_win_rate_pct": j_sr * 100,
                    "trainer": item.get("trainer", ""),
                    "trainer_wet_win_rate_pct": t_sr * 100,
                    "sire": item.get("sire", "Unknown Sire"),
                    "sire_awd": sire_awd,
                    "days_since_last_start": safe_int(item.get("daysSinceLastStart", 14)),
                    "gear_changes": item.get("gearChanges", []),
                    "runs_this_prep": safe_int(item.get("runsThisPrep", 1)),
                    "age": age if age > 0.0 else 4.0,
                    "sex": sex if sex else "G",
                    "career_stats": {
                        "starts": safe_int(item.get("careerStarts", 0)),
                        "wins": safe_int(item.get("careerWins", 0)),
                        "places": safe_int(item.get("careerPlaces", 0))
                    },
                    "last_run": {
                        "class": item.get("last_run_class", "BM58"),
                        "margin_lengths": safe_float(item.get("last_run_margin", 2.0)),
                        "finishing_position": safe_int(item.get("last_run_finishing_position", 4)),
                        "track_condition": item.get("last_run_track_condition", "Good"),
                        "distance_metres": safe_int(item.get("last_run_distance_metres", 1200)),
                        "in_running_positions": item.get("last_run_in_running_positions", "800m 6th")
                    },
                    "status": "Active"
                }
                race_db["runners"].append(runner_record)
        
        if html_text:
            html_scratched = parse_scratched_from_html_content(html_text)
            for r_entry in race_db["runners"]:
                if r_entry["name"].strip().lower() in html_scratched:
                    r_entry["status"] = "Scratched"
                        
            rich_results = parse_results_from_all_sources(data, html_text)
            for res in rich_results:
                r_num = safe_int(res["number"])
                for r_entry in race_db["runners"]:
                    if safe_int(r_entry["number"]) == r_num:
                        r_entry["finishing_position"] = res["position"]
                        r_entry["margin"] = res["margin"]
        
        results_order = []
        for r_data in race_db["runners"]:
            pos = r_data.get("finishing_position")
            if pos and pos > 0 and r_data.get("status") != "Scratched":
                results_order.append({
                    "position": safe_int(pos),
                    "number": safe_int(r_data["number"]),
                    "name": r_data["name"]
                })
        results_order.sort(key=lambda x: x["position"])
        race_db["race_results"] = {
            "status": "Resulted" if len(results_order) > 0 else "Unresulted",
            "finishing_order": results_order
        }
        
        race_db = enrich_if_sa(race_db, target_date)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(race_db, f, indent=4, ensure_ascii=False)
        BiomechanicalOptimizer.clear_cache()
    except Exception as e:
         print(f"[!] Critical parsing error: {e}")


def display_quick_overview(selected_event, meeting, target_date):
    event_id = selected_event["id"]
    class_id = meeting.get("classId")
    data = fetch_racecard_with_context(event_id, class_id)
    if not data: return None
    race = data.get("racecardEvent", {})
    race_name = race.get("name", f"Event_{event_id}")
    race_num = race.get("raceNumber", 1)
    
    print(print_separator())
    print(f" RACE: {race_name} | DIST: {race.get('distance', 'N/A')}m | TRACK: {race.get('trackStatus', 'Unknown')}")
    print(print_separator())
    print("Select Action:")
    print(" [S] - Extract & Save Full Form Guide JSON")
    print(" [A] - Run Dynamic Biomechanical Engine Prediction (FFOM FIRST FOUR)")
    print(" [B] - Run BULK Analysis for ALL races at this meeting")
    print(" [0] - Go Back")
    print(" [M] - My Profile Options")
    print(" [E] - Exit Terminal")
    print(print_separator("-"))
    
    action = input("Enter choice: ").strip().upper()
    if action == 'E':
        print("Exiting terminal session. Goodbye!")
        sys.exit(0)
    elif action == 'M':
        return "GO_MAIN"
    elif action == '0':
        return "GO_BACK"
    
    json_path, pred_json_path, report_path = resolve_storage_paths(
        meeting.get("regionName"), meeting.get("name"), race_num, target_date
    )
    if action == 'S':
        extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, meeting.get("regionName"), meeting.get("name"), race_num, target_date, selected_event)
    elif action == 'A':
        extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, meeting.get("regionName"), meeting.get("name"), race_num, target_date, selected_event)
        with open(json_path, 'r', encoding='utf-8') as f:
            saved_db_data = json.load(f)
        region = meeting.get("regionName")
        track = meeting.get("name")
        if any(x in str(track).lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]) or "south africa" in str(region).lower():
            from south_african_logic import SouthAfricanBiomechanicalEngine
            engine = SouthAfricanBiomechanicalEngine(saved_db_data)
        else:
            engine = BiomechanicalEngine(saved_db_data)
            
        report_content = render_biomechanical_analysis(engine, linked_json_path=json_path)
        with open(report_path, "w", encoding="utf-8") as rf:
            rf.write(report_content)
            
        print(report_content)
        input("\nPress Enter to continue...")
    return None


def menu_races(meeting, target_date):
    events = meeting.get("events", [])
    while True:
        print("\n" + "="*110)
        print(f" {meeting.get('name').upper()} ({meeting.get('regionName')}) - RACES | DATE: {target_date}")
        print("="*110)
        for idx, event in enumerate(events, 1):
            time_status = format_time_status(event.get('startTime', 0))
            print(f"{idx:<2}. {event.get('name'):<45} | {event.get('distance'):>4}m | {time_status}")
        print("\nB. Run BULK Analysis for ALL Races at this meeting")
        print("0. Go Back")
        print("M. Go Back to Main Menu")
        print("E. Exit Terminal")
        print(print_separator("-"))
        choice = input("Select a Race, [B], [0], [M], or [E]: ").strip().upper()
        if choice == 'E':
            print("Exiting terminal session. Goodbye!")
            sys.exit(0)
        elif choice == '0':
            return None
        elif choice == 'M':
            return "GO_MAIN"
        elif choice == 'B':
            run_bulk_meeting_analysis(meeting, target_date)
            input("\nPress Enter to return to the race list...")
        elif choice.isdigit() and 1 <= int(choice) <= len(events):
            res = display_quick_overview(events[int(choice) - 1], meeting, target_date)
            if res == "GO_MAIN":
                return "GO_MAIN"
    return None


def menu_meetings(section, target_date):
    meetings = section.get("meetings", [])
    grouped = {}
    for m in meetings:
        region = m.get("regionName", "Other")
        grouped.setdefault(region, []).append(m)
    regions = sorted(grouped.keys())

    while True:
        print("\n" + "="*110)
        print(f" RACE MEETINGS: {section.get('displayName').upper()}")
        print("="*110)
        ordered_meetings = []
        counter = 1
        for region in regions:
            print(f"\n--- {region.upper()} ---")
            for m in grouped[region]:
                print(f"{counter:<2}. {m.get('name')}")
                ordered_meetings.append(m)
                counter += 1
        print("\n0. Go Back")
        print("M. Go Back to Main Menu")
        print("E. Exit Completely")
        print_separator("-")
        choice = input("Select a Meeting, [0], [M], or [E]: ").strip().upper()
        if choice == '0':
            break
        elif choice == 'M':
            return "GO_MAIN"
        elif choice == 'E':
            print("Exiting terminal session. Goodbye!")
            sys.exit(0)
        elif choice.isdigit() and 1 <= int(choice) <= len(ordered_meetings):
            res = menu_races(ordered_meetings[int(choice) - 1], target_date)
            if res == "GO_MAIN":
                return "GO_MAIN"
    return None


def run_terminal_for_date(target_date):
    sections = fetch_all_racing(target_date)
    if not sections: return
    valid_types = ["Horses", "Greyhounds", "Harness"]
    filtered_sections = [s for s in sections if s.get("displayName") in valid_types]
    while True:
        print("\n" + "="*110)
        print(f" PROGRAM SCHEDULE FOR DATE: {target_date} ")
        print("="*110)
        for idx, section in enumerate(filtered_sections, 1):
            print(f"{idx}. {section.get('displayName')}")
        exit_code = len(filtered_sections) + 1
        print(f"{exit_code}. Go Back")
        print("M. Go Back to Main Menu")
        print("E. Exit Completely")
        print_separator("-")
        choice = input(f"Select a Race Type (1-{exit_code}), [M], or [E]: ").strip().upper()
        if choice == 'M':
            return "GO_MAIN"
        elif choice == 'E':
            print("Exiting terminal session. Goodbye!")
            sys.exit(0)
        elif choice.isdigit():
            choice_idx = int(choice)
            if choice_idx == exit_code:
                break
            elif 1 <= choice_idx <= len(filtered_sections):
                res = menu_meetings(filtered_sections[choice_idx - 1], target_date)
                if res == "GO_MAIN":
                    return "GO_MAIN"
    return None


def menu_historical_dates():
    history_list = generate_historical_dates()
    while True:
        print("\n" + "="*110)
        print(" SELECT HISTORICAL AUDITING DATE")
        print("="*110)
        for idx, item in enumerate(history_list, 1):
            print(f" {idx}. {item['label']}")
        print("\n 0. Go Back")
        print(" M. Go Back to Main Menu")
        print(" E. Exit Completely")
        print_separator("-")
        choice = input(f"Select option (0-{len(history_list)}), [M], or [E]: ").strip().upper()
        if choice == '0':
            break
        elif choice == 'M':
            return "GO_MAIN"
        elif choice == 'E':
            print("Exiting terminal session. Goodbye!")
            sys.exit(0)
        elif choice.isdigit() and 1 <= int(choice) <= len(history_list):
            selected_item = history_list[int(choice) - 1]
            res = run_terminal_for_date(selected_item["date"])
            if res == "GO_MAIN":
                return "GO_MAIN"
    return None


def parse_sportsbet_race_url(url):
    url = url.strip()
    pattern = r"sportsbet\.com\.au/horse-racing/([^/]+)/([^/]+)/race-(\d+)-(\d+)"
    match = re.search(pattern, url, re.I)
    if match:
        region_slug = match.group(1)
        track_slug = match.group(2)
        race_num = int(match.group(3))
        event_id = int(match.group(4))
        region = "Australia" if region_slug == "australia-nz" else "International"
        if region_slug == "asia-racing": region = "Asia"
        if any(x in track_slug.lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]):
            region = "South_Africa"
        track = track_slug.replace("-", " ").title()
        return region, track, race_num, event_id
    return None


def handle_direct_url_scraping():
    print("\n" + "="*110)
    print(" DIRECT SPORTSBET URL SCRAPER INTERFACE")
    print("="*110)
    print(" Enter complete URL pattern (e.g., https://www.sportsbet.com.au/horse-racing/australia-nz/goulburn/race-1-10608636)")
    url_input = input(" Sportsbet Link: ").strip()
    parsed = parse_sportsbet_race_url(url_input)
    if not parsed:
        print("[!] Format mismatch: URL could not be parsed into event/race details.")
        input("\nPress Enter to return to main menu...")
        return
        
    region, track, race_num, event_id = parsed
    target_date = get_current_date_string()
    print(f"\n[+] Extracted Variables: TRACK: {track} | RACE: #{race_num} | ID: {event_id} | REGION: {region}")
    json_path, pred_json_path, report_path = resolve_storage_paths(region, track, race_num, target_date)
    
    extract_and_save_form_guide(
        event_id=event_id,
        class_id=None,
        race_name=f"Race {race_num} - {track}",
        json_path=json_path,
        pred_json_path=pred_json_path,
        report_path=report_path,
        region=region,
        track=track,
        race_num=race_num,
        target_date=target_date
    )
    
    if not os.path.exists(json_path):
        print("[!] Target database could not be resolved on local disk after scraping.")
        input("\nPress Enter to return...")
        return
        
    print(f"\n[*] Loading database records: {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        saved_db_data = json.load(f)
        
    if any(x in str(track).lower() for x in ["greyville", "kenilworth", "turffontein", "vaal", "fairview", "durbanville", "scottsville"]) or "south africa" in str(region).lower():
        from south_african_logic import SouthAfricanBiomechanicalEngine
        engine = SouthAfricanBiomechanicalEngine(saved_db_data)
    else:
        engine = BiomechanicalEngine(saved_db_data)
        
    report_content = render_biomechanical_analysis(engine, linked_json_path=json_path)
    with open(report_path, "w", encoding="utf-8") as rf:
        rf.write(report_content)
        
    print(report_content)
    print(f"[+] Complete report output file saved: {os.path.abspath(report_path)}")
    input("\nPress Enter to return to main menu...")


def main():
    date_str = get_current_date_string()
    while True:
        print("\n" + "="*110)
        print(" SPORTSBET RACING ANALYSIS | BIOMECHANICAL AUDIT SYSTEM")
        print("="*110)
        print(f" [1] - View Today's Active Program ({date_str})")
        print(" [2] - Select Historical Date for Results & Auditing (YYYY-MM-DD)")
        print(" [3] - Scrape & Analyse a Custom Sportsbet Race URL directly")
        print(" [4] - Execute Recursive Archive Search & Biomechanical Model Validation")
        print(" [5] - Bulk Scrape & Analyze Missing Historical Archives (Last 10 Days)")
        print(" [6] - Bulk Update Missing Results for Existing Archives")
        print(" [7] - Exit Terminal")
        print(print_separator("-"))
        
        menu_choice = input("Enter option (1-7): ").strip()
        if menu_choice == '7':
            print("Exiting terminal session. Goodbye!")
            break
        elif menu_choice == '1': run_terminal_for_date(date_str)
        elif menu_choice == '2': menu_historical_dates()
        elif menu_choice == '3': handle_direct_url_scraping()
        elif menu_choice == '4':
            scan_and_validate_historical_races()
            input("\nPress Enter to return to main menu...")
        elif menu_choice == '5': bulk_scrape_missing_historical_races()
        elif menu_choice == '6': bulk_update_missing_results()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

# ======================================================================================================================================
# END OF FILE: sportsbet_scraper.py
# ======================================================================================================================================
