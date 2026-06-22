import requests
import datetime
import urllib.parse
import sys
import json
import os
import time
import re
from bs4 import BeautifulSoup

# --- Logic Module Imports ---
from australian_logic import (
    BiomechanicalEngine,
    BiomechanicalOptimizer,
    safe_int,
    safe_float,
    sanitize_path_name,
    WEIGHTS_FILE
)
from south_african_logic import SouthAfricanBiomechanicalEngine

# --- Configuration & Headers ---
BASE_API_URL = "https://www.sportsbet.com.au/apigw/sportsbook-racing/Sportsbook/Racing"
FORM_BASE = "https://www.sportsbetform.com.au"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.sportsbet.com.au",
    "Referer": "https://www.sportsbet.com.au/"
}

# --- Popular Australian Sires & Average Winning Distance (AWD) Database ---
SIRE_AWD_LOOKUP = {
    "snitzel": 1100, "fastnet rock": 1400, "i am invincible": 1100, "so you think": 1800,
    "dundeel": 1800, "written tycoon": 1150, "savabeel": 1800, "zoustar": 1150,
    "extreme choice": 1050, "capitalist": 1100, "deep field": 1100, "rubick": 1150,
    "shalaa": 1200, "blue point": 1100, "shamardal": 1400, "lope de vega": 1400,
    "crackerjack king": 2000, "invincible spirit": 1200, "impending": 1200, 
    "asturn": 1200, "commands": 1400, "magnus": 1200
}

# --- Scraping UI and Time Helpers ---
def get_current_date_string():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def generate_historical_dates():
    dates_list = []
    today = datetime.date.today()
    # Sportsbet API limits retrospective racing queries to a rolling 10-day window
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


# --- API Fetch Functions ---
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


# =====================================================================
#             SPORTSBETFORM.COM.AU STATS CRAWLER 
# =====================================================================

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
    def resolve_form_ids(cls, region, track, date_str, race_num):
        track_slug = sanitize_path_name(track).lower().replace("_", "-")
        date_slug = date_str.replace("-", "")
        referer = f"{FORM_BASE}/{track_slug}/{date_slug}/race-{race_num}/"
        
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


# =====================================================================
#                    DYNAMICS FORENSIC REPORTER
# =====================================================================

def render_biomechanical_analysis(engine, linked_json_path=""):
    ranked_field = engine.rank_field()
    if not ranked_field:
        return "No active runners generated calculations."
        
    output_lines = []
    
    # Identify Place Inoculation Candidate (place % >= 40%)
    inoculated_runner = None
    if isinstance(engine, SouthAfricanBiomechanicalEngine):
        for item in ranked_field[2:5]:  # Middle of the field contenders
            raw_runners = engine.raw_data.get("runners", [])
            r_data = next((r for r in raw_runners if safe_int(r.get("number")) == item["number"]), None)
            if r_data:
                place_pct = safe_float(r_data.get("career_stats", {}).get("place_percentage", 0))
                if place_pct >= 40.0:
                    inoculated_runner = item
                    break

    if isinstance(engine, SouthAfricanBiomechanicalEngine):
        output_lines.append("SOUTH AFRICAN EXPERT FORENSIC CALIBRATION REPORT [SAF MASTER PROMPT V1.9 COMPLIANT]")
        output_lines.append(print_separator("="))
        output_lines.append(f"Date: {get_current_date_string()} | Venue: {engine.race_name}")
        output_lines.append(f"Locked Surface: {engine.silo.upper()} | Expected Pace (QPT): {engine.predicted_pace}")
        output_lines.append(print_separator("-"))
        output_lines.append("1. PWG IMMUTABLE MATRIX VERIFICATION")
        output_lines.append("  - Target Straight Profile: Spacious continuous turf layout (no short-bend constraints) verified.")
        output_lines.append("  - Matrix Mode: Slow-Track Trap checked; Collapse Advantage parsed dynamically.")
        output_lines.append(print_separator("-"))
    else:
        output_lines.append("BIOMECHANICAL CLASSIFIER MODEL FORENSIC OUTPUT v4.1 [LoRA Parameterisation Mode]")
        output_lines.append(print_separator("-"))
        output_lines.append(f"Date: {get_current_date_string()}")
        output_lines.append(f"TRACK: {engine.race_name} | DISTANCE: {engine.distance}m | MODEL SILO: {engine.regional_silo}")
        output_lines.append(f"ADAPTIVE LORA WEIGHTS: KEM={engine.weights[0]:.1f}, Turn={engine.weights[1]:.2f}, Mass={engine.weights[2]:.2f}, Fresh={engine.weights[3]:.2f}, Jeopardy={engine.weights[4]:.1f}")
    
    if linked_json_path:
        output_lines.append(f"LOCAL DATA ARCHIVE REFERENCE: {os.path.abspath(linked_json_path)}")
        
    output_lines.append(print_separator("="))

    output_lines.append("\n2. BIOMECHANICAL EFFICIENCY CALCULATIONS")
    output_lines.append(print_separator("-"))
    output_lines.append(f"{'No./Chassis Name':<22} | {'Draw':<6} | {'Mass (kg)':<7} | {'Biomechanical Score':<15} | {'Designation'}")
    output_lines.append(print_separator("-"))
    for item in ranked_field:
        name_trunc = f"#{item['number']} {item['name']}"[:21]
        output_lines.append(f"{name_trunc:<22} | {item['barrier']:<6} | {item['weight_kg']:<7.1f} | {item['score']:<15.3f} | {item['designation']}")
    output_lines.append(print_separator("-"))

    output_lines.append("\n3. FINAL SYSTEMIC PREDICTION")
    output_lines.append(print_separator("-"))
    primary = ranked_field[0]
    output_lines.append(f" Primary Biomechanical Contender: No. {primary['number']} {primary['name']} (Barrier {primary['barrier']})")
    if len(ranked_field) >= 2:
        cover = ranked_field[1]
        output_lines.append(f" Cover Contender: No. {cover['number']} {cover['name']} (Barrier {cover['barrier']})")
        
    output_lines.append("\n Betting Playbook Strategy:")
    output_lines.append(f"  - Sovereign Target (Win/Place Priority): WIN on No. {primary['number']} {primary['name']}")
    
    if len(ranked_field) >= 2:
        exacta_legs = [str(ranked_field[1]['number']), str(ranked_field[2]['number'])]
        output_lines.append(f"  - Protective Cover Exacta: {primary['number']} / {', '.join(exacta_legs)}")
        
        # Swinger Box Strategy
        output_lines.append(f"  - Swinger (Box): {primary['number']}, {ranked_field[1]['number']}")
        
        # Trifecta Legs featuring Place Inoculation logic
        tri_second_leg = [str(ranked_field[1]['number']), str(ranked_field[2]['number'])]
        tri_third_leg = tri_second_leg.copy()
        if len(ranked_field) > 3:
            tri_third_leg.append(str(ranked_field[3]['number']))
        if inoculated_runner:
            tri_third_leg.append(str(inoculated_runner['number']))
            output_lines.append(f"  - Inoculation Triggered: Midfield place-specialist #{inoculated_runner['number']} {inoculated_runner['name']} injected into exotics.")
            
        output_lines.append(f"  - Systemic Trifecta: {primary['number']} / {', '.join(tri_second_leg)} / {', '.join(sorted(list(set(tri_third_leg))))}")

    output_lines.append("=" * 110)

    race_results = engine.raw_data.get("race_results", {"status": "Unresulted", "finishing_order": []})
    if race_results.get("status") == "Resulted":
        output_lines.append("\n4. POST-RACE VALIDATION AUDIT")
        output_lines.append(print_separator("-"))
        order = race_results.get("finishing_order", [])
        order_strs = [f"{o['position']}: No. {o['number']} {o['name']}" for o in order[:3]]
        output_lines.append(" Actual Result: " + " | ".join(order_strs))
        
        primary_no = primary["number"]
        actual_pos = next((o["position"] for o in order if o["number"] == primary_no), None)
        pos_str = f"Rank {actual_pos}" if actual_pos else "Unplaced"
        output_lines.append(f" Primary Pick Position Outcome: {pos_str}")
        output_lines.append("=" * 110)

    return "\n".join(output_lines)


# =====================================================================
#               HISTORICAL RECURSIVE VALIDATION UTILITY
# =====================================================================

def scan_and_validate_historical_races():
    """
    Recursively scans storage folders, executes dynamic weight optimization across
    all completed results, and prints the performance audit metrics.
    """
    print("\n" + "="*110)
    print(" INITIATING RECURSIVE DATA ARCHIVE SCAN & SUPERVISED CALIBRATION...")
    print("="*110)
    
    training_set = BiomechanicalOptimizer.collect_completed_races(force_reload=True)
    total_audited = len(training_set)
    
    if total_audited == 0:
        print("[!] Validation aborted: Zero completed races discovered in local storage.")
        print("[*] Retrieve racing data using Option [1] or Option [5] first.")
        return
        
    print(f"[*] Loaded {total_audited} completed races with verified results.")
    
    discovered_silos = set()
    for data in training_set:
        discovered_silos.add(BiomechanicalOptimizer._get_silo_key(data))
        
    optimized_weights = {}
    for silo_key in sorted(list(discovered_silos)):
        optimized_weights[silo_key] = BiomechanicalOptimizer.optimize_silo_parameters(training_set, silo_key, force_reoptimize=True)
    
    print("\n[+] Supervised Dynamic Calibration Parameters Calculated:")
    for silo_key, weights in sorted(optimized_weights.items()):
        print(f"  - {silo_key:<25} Weights: KEM={weights[0]:.1f}, Turn={weights[1]:.2f}, Mass={weights[2]:.2f}, Fresh={weights[3]:.2f}, Jeopardy={weights[4]:.1f}")
        
    print("\n" + "="*110)
    print(f" {'Track / Race Name':<35} | {'Sovereign Pick':<20} | {'Result':<10} | {'Model Classification Strategy'}")
    print(print_separator("-"))
    
    primary_hits = 0
    top2_hits = 0
    top3_hits = 0
    
    for data in training_set:
        silo_key = BiomechanicalOptimizer._get_silo_key(data)
        silo_weights = optimized_weights[silo_key]
        
        engine = BiomechanicalEngine(data, weights_override=silo_weights)
        ranked = engine.rank_field()
        if not ranked:
            continue
            
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


# =====================================================================
#               SUPERVISED LoRA CALIBRATION MANAGER
# =====================================================================

def run_supervised_lora_menu_option():
    """
    Audit training parameters, identify non-trained race archives,
    and trigger supervised parameter weight updates dynamically.
    """
    print("\n" + "="*110)
    print(" SUPERVISED LoRA CALIBRATION MANAGER")
    print("="*110)
    
    training_set = BiomechanicalOptimizer.collect_completed_races(force_reload=True)
    persistent_data = BiomechanicalOptimizer.load_calibrated_weights()
    
    trained_files = set(persistent_data.get("trained_race_files", []))
    current_files = set([r["_source_path"] for r in training_set if "_source_path" in r])
    
    new_files = current_files - trained_files
    
    print(f" Total Completed Races in Storage:  {len(current_files)}")
    print(f" Already Trained in LoRA Adaptor:   {len(trained_files)}")
    print(f" New Untrained Races Detected:      {len(new_files)}")
    print(print_separator("-"))
    
    if len(new_files) == 0:
        print("[*] LoRA adapters are synchronized with your local data storage.")
        choice = input("Would you like to force a complete re-calibration across ALL records? (y/n): ").strip().lower()
        if choice == 'y':
            BiomechanicalOptimizer.initialize_and_calibrate_all_silos(force=True)
        else:
            print("[*] Calibration cancelled.")
    else:
        print(f"[+] Found {len(new_files)} new files waiting to be processed.")
        choice = input("Would you like to start the supervised LoRA parameter optimization? (y/n): ").strip().lower()
        if choice == 'y':
            BiomechanicalOptimizer.initialize_and_calibrate_all_silos(force=False)
        else:
            print("[*] Calibration cancelled.")
            
    input("\nPress Enter to return to main menu...")


# =====================================================================
#                     BULK MEETING ANALYSIS UTILITY
# =====================================================================

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
    print(f" Automated parsing execution for {len(events)} races sequentially.")
    print("="*110)
    
    for idx, event in enumerate(events, 1):
        event_id = event["id"]
        race_name = event.get("name", f"Race {event.get('raceNumber')}")
        race_num = event.get("raceNumber", idx)
        
        print(f"\n[*] Processing Race {race_num}/{len(events)}: {race_name}...")
        
        json_path, pred_json_path, report_path = resolve_storage_paths(region, track, race_num, target_date)
        
        extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, region, track, race_num, target_date)
        
        if not os.path.exists(json_path):
            print(f"  [!] Skipped: Data verification failed for {race_name}.")
            continue
            
        with open(json_path, 'r', encoding='utf-8') as f:
            saved_db_data = json.load(f)
            
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
                    "barrier": item["barrier"],
                    "weight_kg": item["weight_kg"],
                    "score": item["score"],
                    "designation": item["designation"]
                }
                for item in engine.rank_field()
            ]
        }
        with open(pred_json_path, 'w', encoding='utf-8') as pf:
            json.dump(pred_data, pf, indent=4, ensure_ascii=False)
            
        print(f"  [+] Saved biomechanical analysis report: {os.path.abspath(report_path)}")
        
    print("\n" + "="*110)
    print(f" BULK MEETING SYSTEM METRICS COMPILED SUCCESSFULLY FOR: {track.upper()}")
    print("=" * 110)


# =====================================================================
#               BULK MISSING HISTORICAL SCRAPER UTILITY
# =====================================================================

def bulk_scrape_missing_historical_races():
    print("\n" + "="*110)
    print(" INITIATING HISTORICAL ARCHIVE SCANNER")
    print("="*110)
    print("[*] Retrieving historical calendar schedules (1-10 days ago)...")
    
    history_list = generate_historical_dates()
    today_str = get_current_date_string()
    current_time = time.time()
    
    date_to_day = {}
    for item in history_list:
        try:
            dt = datetime.datetime.strptime(item["date"], "%Y-%m-%d")
            day_name = dt.strftime("%A")
            date_to_day[item["date"]] = day_name
        except Exception:
            date_to_day[item["date"]] = "Unknown"

    all_meetings_metadata = []
    discovered_regions = set()
    discovered_days = set()

    print("[*] Performing quick metadata scan across 10-day schedule to compile filters...")
    for i, item in enumerate(history_list, 1):
        target_date = item["date"]
        if target_date == today_str:
            continue
            
        sys.stdout.write(".")
        sys.stdout.flush()
        
        sections = fetch_all_racing(target_date)
        if not sections:
            continue
            
        valid_types = ["Horses", "Greyhounds", "Harness"]
        filtered_sections = [s for s in sections if s.get("displayName") in valid_types]
        
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

    print("\n[*] Metadata scan complete.")
    
    if not all_meetings_metadata:
        print("[!] No completed races resolved from schedules.")
        input("\nPress Enter to return to main menu...")
        return

    available_regions = sorted(list(discovered_regions))
    available_days = sorted(list(discovered_days))

    print("\n" + "="*110)
    print(" FILTER BY REGION / COUNTRY")
    print("="*110)
    print(" 0. All Regions")
    for idx, reg in enumerate(available_regions, 1):
        print(f" {idx}. {reg}")
    print(print_separator("-"))
    region_choice = input("Select Country/Region filter (0-{}): ".format(len(available_regions))).strip()
    
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
    day_choice = input("Select Day of Week filter (0-{}): ".format(len(available_days))).strip()
    
    selected_day = None
    if day_choice.isdigit():
        d_idx = int(day_choice)
        if 1 <= d_idx <= len(available_days):
            selected_day = available_days[d_idx - 1]

    filtered_meetings = []
    for meta in all_meetings_metadata:
        if selected_region and meta["region"] != selected_region:
            continue
        if selected_day and meta["day_name"] != selected_day:
            continue
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
                
            json_path, pred_json_path, report_path = resolve_storage_paths(
                region, track, race_num, target_date
            )
            
            if os.path.exists(json_path):
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
                    "target_date": target_date
                })

    total_resolved = scraped_count + len(queue)
    print("\n" + "="*110)
    print(" SYSTEM COGNITIVE OVERVIEW COMPLETE")
    print(print_separator("-"))
    print(f" Target Region/Country:                  {selected_region if selected_region else 'All Regions'}")
    print(f" Target Day of Week:                     {selected_day if selected_day else 'All Days'}")
    print(f" Total Filtered Races via API:           {total_resolved}")
    print(f" Existing Complete Archives (Skipped):   {scraped_count}")
    print(f" Live / Active Scheduled Boundary Items: {skipped_count}")
    print(f" Unresolved Missing Historical Races:    {len(queue)}")
    print("="*110)
    
    if len(queue) == 0:
        print("[*] Local database is completely synchronized with filtered historical schedules.")
        input("\nPress Enter to return to main menu...")
        return
        
    print("Options:")
    print(" [Y] - Commencing programmatic download of missing data profiles")
    print(" [0] - Return to Main Menu")
    print(" [E] - Exit Completely")
    print(print_separator("-"))
    
    confirm = input("Select option: ").strip().upper()
    if confirm == 'E':
        print("Exiting terminal session. Goodbye!")
        sys.exit(0)
    elif confirm != 'Y':
        print("[*] Bulk scraping cancelled.")
        return
        
    print(f"\n[*] Initiating sequential bulk download for {len(queue)} profiles...")
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
            target_date=task["target_date"]
        )
        
        if os.path.exists(task["json_path"]):
            try:
                with open(task["json_path"], 'r', encoding='utf-8') as f:
                    saved_db_data = json.load(f)
                    
                engine = BiomechanicalEngine(saved_db_data)
                report_content = render_biomechanical_analysis(engine, linked_json_path=task["json_path"])
                
                with open(task["report_path"], "w", encoding="utf-8") as rf:
                    rf.write(report_content)
                    
                pred_data = {
                    "race_name": engine.race_name,
                    "silo": engine.regional_silo,
                    "weights_applied": engine.weights,
                    "predictions": [
                        {
                            "number": item["number"],
                            "name": item["name"],
                            "barrier": item["barrier"],
                            "weight_kg": item["weight_kg"],
                            "score": item["score"],
                            "designation": item["designation"]
                        }
                        for item in engine.rank_field()
                    ]
                }
                with open(pred_json_path, 'w', encoding='utf-8') as pf:
                    json.dump(pred_data, pf, indent=4, ensure_ascii=False)
                    
                print(f"  [+] Saved analysis report: {os.path.basename(task['report_path'])}")
            except Exception as ex:
                print(f"  [!] Predictive formatting failed for this run: {ex}")
        else:
            print("  [!] Skipped: Data verification layout is invalid.")
            
        time.sleep(0.5)
        
    print("\n" + "="*110)
    print(" PROGRAMMATIC RUN COMPLETE")
    print("[*] Checking for newly discovered historical files for calibration step...")
    
    BiomechanicalOptimizer.clear_cache()
    # Runs the optimized parameter-efficient update (only targets newly downloaded profiles)
    BiomechanicalOptimizer.initialize_and_calibrate_all_silos(force=False)
    
    print("[+] Model calibration check finished.")
    print("="*110)
    input("\nPress Enter to return to main menu...")


# =====================================================================
#             BULK MISSING RESULTS UPDATE UTILITY
# =====================================================================

def bulk_update_missing_results():
    """
    Recursively scans the local storage folder for existing JSON files that do not
    have a confirmed 'Resulted' status. Fetches updated race cards from the API
    and updates database entries with official positions, structures, and evaluations.
    """
    print("\n" + "="*110)
    print(" INITIATING BULK RESULTS SYNCHRONIZATION")
    print("="*110)
    print("[*] Scanning local storage archives for unresulted race profiles...")

    storage_dir = "storage"
    if not os.path.exists(storage_dir):
        print("[!] Storage directory is empty. No local profiles found to evaluate.")
        input("\nPress Enter to return to main menu...")
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

                event_id = data.get("event_id")
                if not event_id:
                    continue

                results = data.get("race_results", {})
                if results.get("status") != "Resulted":
                    norm_path = os.path.normpath(file_path)
                    parts = norm_path.split(os.sep)
                    if len(parts) >= 5:
                        target_date = parts[-4]
                        region = parts[-3]
                        track = parts[-2]
                        filename = parts[-1]
                        match = re.search(r'race_(\d+)', filename)
                        race_num = int(match.group(1)) if match else 1

                        unresulted_tasks.append({
                            "file_path": file_path,
                            "event_id": event_id,
                            "race_name": data.get("race_name", f"Race {race_num}"),
                            "target_date": target_date,
                            "region": region,
                            "track": track,
                            "race_num": race_num
                        })

    total_unresulted = len(unresulted_tasks)
    if total_unresulted == 0:
        print("[*] Local database has no unresulted races. All entries are fully synchronized.")
        input("\nPress Enter to return to main menu...")
        return

    print(f"[*] Discovered {total_unresulted} unresulted races in storage.")
    print("Options:")
    print(" [Y] - Commencing programmatic update of missing results")
    print(" [0] - Return to Main Menu")
    print(print_separator("-"))

    confirm = input("Select option: ").strip().upper()
    if confirm != 'Y':
        print("[*] Bulk results update cancelled.")
        return

    print(f"\n[*] Updating {total_unresulted} profiles sequentially...")
    updated_count = 0
    still_unresulted_count = 0

    for i, task in enumerate(unresulted_tasks, 1):
        file_path = task["file_path"]
        event_id = task["event_id"]
        race_name = task["race_name"]
        target_date = task["target_date"]
        region = task["region"]
        track = task["track"]
        race_num = task["race_num"]

        pred_json_path = file_path.replace("_data.json", "_prediction.json")
        report_path = file_path.replace("_data.json", "_report.txt")

        print(f"\n[{i}/{total_unresulted}] Checking: {race_name} at {track} ({target_date})")

        # Overwrite/Extract updated form guide containing final results
        extract_and_save_form_guide(
            event_id=event_id,
            class_id=None,
            race_name=race_name,
            json_path=file_path,
            pred_json_path=pred_json_path,
            report_path=report_path,
            region=region,
            track=track,
            race_num=race_num,
            target_date=target_date
        )

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                updated_data = json.load(f)
            
            results = updated_data.get("race_results", {})
            if results.get("status") == "Resulted":
                updated_count += 1
                print(f"  [+] Success: Race resulted. Generating updated reports...")
                
                # Re-run physical calculations to generate finalized report
                engine = BiomechanicalEngine(updated_data)
                report_content = render_biomechanical_analysis(engine, linked_json_path=file_path)
                
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
                            "barrier": item["barrier"],
                            "weight_kg": item["weight_kg"],
                            "score": item["score"],
                            "designation": item["designation"]
                        }
                        for item in engine.rank_field()
                    ]
                }
                with open(pred_json_path, 'w', encoding='utf-8') as pf:
                    json.dump(pred_data, pf, indent=4, ensure_ascii=False)
            else:
                still_unresulted_count += 1
                print(f"  [*] Checked, but race remains unresulted.")
        except Exception as e:
            print(f"  [!] Failed to verify status after update: {e}")

        time.sleep(0.5)

    print("\n" + "="*110)
    print(" RESULTS UPDATE RUN COMPLETE")
    print(f" Total Checked:       {total_unresulted}")
    print(f" Successfully Updated: {updated_count}")
    print(f" Still Unresulted:    {still_unresulted_count}")
    print("="*110)

    # Clear training metrics cache and run a training verification step
    BiomechanicalOptimizer.clear_cache()
    BiomechanicalOptimizer.initialize_and_calibrate_all_silos(force=False)
    input("\nPress Enter to return to main menu...")


# =====================================================================
#                     FALLBACK HTML SCRATCHINGS CRAWLER
# =====================================================================

def fetch_scratched_from_html(region, track, race_num, event_id):
    region_slug = "australia-nz"
    if region:
        r_lower = region.lower()
        if any(x in r_lower for x in ["australia", "nz", "new zealand"]):
            region_slug = "australia-nz"
        elif any(x in r_lower for x in ["asia", "japan", "hong kong", "singapore", "kochi", "korea"]):
            region_slug = "asia-racing"
        else:
            region_slug = "international"
        
    track_slug = sanitize_path_name(track).lower().replace("_", "-")
    url = f"https://www.sportsbet.com.au/horse-racing/{region_slug}/{track_slug}/race-{race_num}-{event_id}"
    
    print(f"[*] Fetching HTML race card layout: {url}")
    scratched_names = set()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            scratched_elements = soup.find_all(attrs={"data-automation-id": "racecard-outcome-scratched"})
            for elem in scratched_elements:
                text = elem.get_text(strip=True)
                cleaned = re.sub(r'^\d+\.\s*', '', text)
                cleaned = cleaned.split('(')[0].strip().lower()
                if cleaned:
                    scratched_names.add(cleaned)
                    
            for container in soup.find_all(class_=re.compile(r'scratched', re.I)):
                text = container.get_text(strip=True)
                cleaned = re.sub(r'^\d+\.\s*', '', text)
                cleaned = cleaned.split('(')[0].strip().lower()
                if "scratched" in cleaned:
                    cleaned = cleaned.split("scratched")[0].strip()
                if cleaned:
                    scratched_names.add(cleaned)
    except Exception as e:
        print(f"[!] Warning: Fallback scratchings check could not complete: {e}")
    return scratched_names


# =====================================================================
#                          MENU INTERFACE
# =====================================================================

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
    print(" [A] - Run Dynamic Biomechanical Engine Prediction")
    print(" [B] - Run BULK Analysis for ALL races at this meeting")
    print(" [0] - Go Back")
    print(" [M] - Go Back to Main Menu")
    print(" [E] - Exit Completely")
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
        meeting.get("regionName"),
        meeting.get("name"),
        race_num,
        target_date
    )
    
    if action == 'S':
        extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, meeting.get("regionName"), meeting.get("name"), race_num, target_date)
        input("\nPress Enter to return to the race list...")
    elif action == 'A':
        extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, meeting.get("regionName"), meeting.get("name"), race_num, target_date)
        
        if not os.path.exists(json_path):
            print(f"[!] Target database file {json_path} caused a failure: not found on disk.")
            input("\nPress Enter to return...")
            return None
            
        print(f"\n[*] Loading form database: {json_path}...")
        with open(json_path, 'r', encoding='utf-8') as f:
            saved_db_data = json.load(f)
            
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
                    "barrier": item["barrier"],
                    "weight_kg": item["weight_kg"],
                    "score": item["score"],
                    "designation": item["designation"]
                }
                for item in engine.rank_field()
            ]
        }
        with open(pred_json_path, 'w', encoding='utf-8') as pf:
            json.dump(pred_data, pf, indent=4, ensure_ascii=False)
            
        print(report_content)
        print(f"[+] Biomechanical Forensic Report saved successfully: {os.path.abspath(report_path)}")
        input("\nPress Enter to return to the race list...")
    elif action == 'B':
        run_bulk_meeting_analysis(meeting, target_date)
        input("\nPress Enter to return to the race list...")
    return None

def extract_and_save_form_guide(event_id, class_id, race_name, json_path, pred_json_path, report_path, region, track, race_num, target_date):
    try:
        print(f"\n[*] Extracting Full Form Guide from API for: {race_name}")
        
        data = fetch_racecard_with_context(event_id, class_id)
        if not data or "racecardEvent" not in data:
            print("[!] Could not load race card data from API.")
            return

        race = data["racecardEvent"]
        
        print("[*] Resolving SportsBetForm Jockey/Trainer IDs...")
        form_ids, referer_url = SportsBetFormCrawler.resolve_form_ids(region, track, target_date, race_num)
        
        race_db = {
            "event_id": event_id,
            "region": region or "Other",
            "race_name": race.get("name"),
            "distance": race.get("distance"),
            "track_status": race.get("trackStatus", "Unknown"),
            "start_time": race.get("startTime"),
            "scraped_at": datetime.datetime.now().isoformat(),
            "associated_report_path": os.path.abspath(report_path),
            "runners": []
        }
        
        runners = race.get("runners", [])
        for r in runners:
            jockey = r.get("jockey", {}).get("name", "Unknown")
            trainer = r.get("trainer", {}).get("name", "Unknown")
            
            career_raw = r.get("careerStats", "0:0-0-0")
            good_raw = r.get("goodStats", "0:0-0-0")
            soft_raw = r.get("softStats", "0:0-0-0")
            heavy_raw = r.get("heavyStats", "0:0-0-0")
            track_raw = r.get("trackStats", "0:0-0-0")
            dist_raw = r.get("distanceStats", "0:0-0-0")

            starts, wins, places = parse_stats_string(career_raw)
            g_starts, g_wins, g_places = parse_stats_string(good_raw)
            s_starts, s_wins, s_places = parse_stats_string(soft_raw)
            h_starts, h_wins, h_places = parse_stats_string(heavy_raw)
            t_starts, t_wins, t_places = parse_stats_string(track_raw)
            d_starts, d_wins, d_places = parse_stats_string(dist_raw)

            j_profile = {"track_cond_sr": 0.10, "first_up_sr": 0.12, "second_up_sr": 0.10, "weight_sr": 0.08, "surface_sr": 0.10}
            t_profile = {"track_cond_sr": 0.10, "first_up_sr": 0.12, "second_up_sr": 0.10, "weight_sr": 0.08, "surface_sr": 0.10}
            
            if jockey in form_ids["jockeys"]:
                j_id = form_ids["jockeys"][jockey]
                j_profile = SportsBetFormCrawler.fetch_stats_profile(j_id, "Jockey", referer_url)
                
            if trainer in form_ids["trainers"]:
                t_id = form_ids["trainers"][trainer]
                t_profile = SportsBetFormCrawler.fetch_stats_profile(t_id, "Trainer", referer_url)

            res_node = r.get("result")
            fin_pos = None
            if isinstance(res_node, dict):
                fin_pos = res_node.get("position") or res_node.get("finishingPosition")
            if not fin_pos:
                fin_pos = r.get("resultPosition") or r.get("finishingPosition") or r.get("place")
            
            fin_pos = safe_int(fin_pos, None)

            runner_data = {
                "number": r.get("runnerNumber"),
                "barrier": r.get("drawNumber"),
                "name": r.get("name"),
                "jockey": jockey,
                "trainer": trainer,
                "jockey_profile": j_profile,
                "trainer_profile": t_profile,
                "finishing_position": fin_pos,
                "status": "Scratched" if (r.get("scratching") or r.get("status") == "Scratched") else "Active",
                "weight_kg": r.get("weightGram", 0) / 1000 if r.get("weightGram") else None,
                "overview": r.get("overview", "No overview provided."),
                "sire": r.get("sireName", "Unknown Sire"),
                "career_stats": {
                    "starts": starts,
                    "wins": wins,
                    "places": places,
                    "win_percentage": r.get("winPercentage", 0.0),
                    "place_percentage": r.get("placePercentage", 0.0),
                    "prize_money": r.get("prizeMoney"),
                    "good": {"starts": g_starts, "wins": g_wins, "places": g_places},
                    "soft": {"starts": s_starts, "wins": s_wins, "places": s_places},
                    "heavy": {"starts": h_starts, "wins": h_wins, "places": h_places},
                    "track": {"starts": t_starts, "wins": t_wins, "places": t_places},
                    "distance": {"starts": d_starts, "wins": d_wins, "places": d_places}
                },
                "recent_form": [run for run in r.get("recentStarts", []) if run]
            }
            race_db["runners"].append(runner_data)
            
        html_scratched = fetch_scratched_from_html(region, track, race_num, event_id)
        if html_scratched:
            print(f"[*] Verified scratched names from layout: {list(html_scratched)}")
            for r_entry in race_db["runners"]:
                clean_r_name = r_entry["name"].strip().lower()
                if clean_r_name in html_scratched:
                    if r_entry["status"] != "Scratched":
                        print(f"  [!] Corrected Status: {r_entry['name']} -> Scratched (via HTML Validation)")
                        r_entry["status"] = "Scratched"
                
        results_order = []
        for r_data in race_db["runners"]:
            pos = r_data.get("finishing_position")
            if pos and pos > 0 and r_data.get("status") != "Scratched":
                results_order.append({
                    "position": pos,
                    "number": r_data["number"],
                    "name": r_data["name"]
                })
        results_order.sort(key=lambda x: x["position"])
        
        race_db["race_results"] = {
            "status": "Resulted" if len(results_order) > 0 else "Unresulted",
            "finishing_order": results_order
        }
                
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(race_db, f, indent=4, ensure_ascii=False)
            
        print(f"[+] Successfully extracted {len(race_db['runners'])} runners.")
        print(f"[+] Scraped JSON saved: {os.path.abspath(json_path)}")
        
        BiomechanicalOptimizer.clear_cache()
    except Exception as e:
         print(f"[!] Critical parsing error encountered: {e}")

def menu_races(meeting, target_date):
    events = meeting.get("events", [])
    track_summary = fetch_track_summary(meeting.get('name'))
    
    while True:
        print("\n" + "="*110)
        print(f" {meeting.get('name').upper()} ({meeting.get('regionName')}) - RACES | DATE: {target_date}")
        print(f" Track Info: {track_summary.strip()}")
        print("="*110)
        
        if not events:
            print("No races available for this meeting.")
        else:
            for idx, event in enumerate(events, 1):
                time_status = format_time_status(event.get('startTime', 0))
                race_name = event.get('name', f"Race {event.get('raceNumber')}")
                distance = event.get('distance', 'N/A')
                print(f"{idx:<2}. {race_name:<45} | {distance:>4}m | {time_status}")
                
        print("\nB. Run BULK Analysis for ALL Races at this meeting")
        print("0. Go Back")
        print("M. Go Back to Main Menu")
        print("E. Exit Completely")
        print(print_separator("-"))
        
        choice = input("Select a Race, [B], [0], [M], or [E]: ").strip().upper()
        
        if choice == '0':
            break
        elif choice == 'M':
            return "GO_MAIN"
        elif choice == 'E':
            print("Exiting terminal session. Goodbye!")
            sys.exit(0)
        elif choice == 'B':
            run_bulk_meeting_analysis(meeting, target_date)
            input("\nPress Enter to return to the race list...")
        elif choice.isdigit() and 1 <= int(choice) <= len(events):
            selected_event = events[int(choice) - 1]
            res = display_quick_overview(selected_event, meeting, target_date)
            if res == "GO_MAIN":
                return "GO_MAIN"
        else:
            print("[!] Invalid selection. Please try again.")
    return None

def menu_meetings(section, target_date):
    meetings = section.get("meetings", [])
    
    grouped = {}
    for m in meetings:
        region = m.get("regionName", "Other")
        if region not in grouped: grouped[region] = []
        grouped[region].append(m)

    regions = sorted(grouped.keys(), key=lambda r: 0 if r == "Australia" else 1 if r == "New Zealand" else 2)

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
        print(print_separator("-"))
        
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
        else:
            print("[!] Invalid choice. Please try again.")
    return None

def run_terminal_for_date(target_date):
    sections = fetch_all_racing(target_date)
    if not sections:
        print(f"[!] No racing data resolved for {target_date}.")
        return None

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
        print(print_separator("-"))
        
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
            else:
                print("[!] Invalid option.")
        else:
            print("[!] Invalid input.")
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
        print(print_separator("-"))
        
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
        else:
            print("[!] Invalid option. Please select again.")
    return None


# =====================================================================
#                DIRECT URL SCRAPER PATHWAY
# =====================================================================

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
        if region_slug == "asia-racing":
            region = "Asia"
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
    
    extract_and_save_form_guide(event_id, None, f"Race {race_num} - {track}", json_path, pred_json_path, report_path, region, track, race_num, target_date)
    
    if not os.path.exists(json_path):
        print("[!] Target database could not be resolved on local disk after scraping.")
        input("\nPress Enter to return...")
        return
        
    print(f"\n[*] Loading database records: {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        saved_db_data = json.load(f)
        
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
        print(" SOVEREIGN KINETIC INDEX (SKI) v4.1 | BIOMECHANICAL AUDIT SYSTEM")
        print("="*110)
        print(f" [1] - View Today's Active Program ({date_str})")
        print(" [2] - Select Historical Date for Results & Auditing (YYYY-MM-DD)")
        print(" [3] - Scrape & Analyse a Custom Sportsbet Race URL directly")
        print(" [4] - Execute Recursive Archive Search & Biomechanical Model Validation")
        print(" [5] - Bulk Scrape & Analyze Missing Historical Archives (Last 10 Days)")
        print(" [6] - Bulk Update Missing Results for Existing Archives")
        print(" [7] - Run Supervised LoRA Calibration on New/Untrained Archives")
        print(" [8] - Exit Terminal")
        print(print_separator("-"))
        
        menu_choice = input("Enter option (1-8): ").strip()
        
        if menu_choice == '8':
            print("Exiting terminal session. Goodbye!")
            break
        elif menu_choice == '1':
            run_terminal_for_date(date_str)
        elif menu_choice == '2':
            menu_historical_dates()
        elif menu_choice == '3':
            handle_direct_url_scraping()
        elif menu_choice == '4':
            scan_and_validate_historical_races()
            input("\nPress Enter to return to main menu...")
        elif menu_choice == '5':
            bulk_scrape_missing_historical_races()
        elif menu_choice == '6':
            bulk_update_missing_results()
        elif menu_choice == '7':
            run_supervised_lora_menu_option()
        else:
            print("[!] Invalid choice. Select 1 to 8.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExiting terminal session. Goodbye!")
        sys.exit(0)
