# ======================================================================================================================================
# START OF FILE: australian_logic.py
# OPERATIONAL ROLE: SYSTEM SCRAPER COGNITIVE ARCHITECTURE & MEETING PARSER PIPELINE
# LANGUAGE VARIATION: BRITISH UK ENGLISH (METRES, NORMALISATION, PRIORITISATION, PENALISE, ANALYSE)
# ======================================================================================================================================

import os
import re
import math
import json
import datetime

# --- Configuration Constants ---
WEIGHTS_FILE = os.path.join("storage", "biomechanical_weights.json")

# --- Defensive Parsing Helpers ---
def safe_int(val, default=0):
    if val is None: 
        return default
    try: 
        return int(float(val))
    except (ValueError, TypeError): 
        return default

def safe_float(val, default=0.0):
    if val is None: 
        return default
    try: 
        return float(val)
    except (ValueError, TypeError): 
        return default

def sanitize_path_name(name):
    if not name: 
        return "Unknown"
    keep = [" ", "-", "_"]
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned.replace(" ", "_")


# =====================================================================
#          PROGRAMMATIC TEXT-TO-NUMBER VECTORISER
# =====================================================================

class BiomechanicalTextVectorizer:
    """
    Transforms unstructured textual representations into pure numeric coordinates.
    Character mapping is performed deterministically to ensure reproducibility.
    """
    @staticmethod
    def text_to_hash_vector(text, dimensions=6):
        if not text:
            return [0.0] * dimensions
        
        cleaned = str(text).lower().strip()
        vector = [0.0] * dimensions
        for idx, char in enumerate(cleaned):
            val = ord(char)
            vector[idx % dimensions] += val * math.sin(idx + 1.25)
            
        magnitude = math.sqrt(sum(v**2 for v in vector))
        if magnitude > 0:
            vector = [round(v / magnitude, 5) for v in vector]
        return vector

    @staticmethod
    def parse_physical_chassis(overview_text):
        if not overview_text:
            return 4.0, 2.0  # Default Chassis: 4YO Gelding
            
        text = str(overview_text).lower()
        
        age = 4.0
        age_match = re.search(r'(\d+)\s*yo', text)
        if age_match:
            age = float(age_match.group(1))
            
        sex_idx = 2.0  # Gelding
        if " filly " in text or " f " in text:
            sex_idx = 1.0
        elif " mare " in text or " m " in text:
            sex_idx = 1.5
        elif " gelding " in text or " g " in text:
            sex_idx = 2.0
        elif " colt " in text or " c " in text:
            sex_idx = 3.0
        elif " entire " in text or " horse " in text or " h " in text:
            sex_idx = 3.5
            
        return age, sex_idx

    @staticmethod
    def parse_race_class_tier(race_name):
        """
        Maps race classifications programmatically to numeric categories.
        """
        name = str(race_name).upper()
        if any(x in name for x in ["MDN", "MAIDEN", "MPLTE", "3YO MDN"]):
            return 1.0
        elif any(x in name for x in ["GROUP", "GP", "G1", "G2", "G3", "LISTED", "LR", "CUP", "STAKES", "OPEN", "BM82"]):
            return 3.0
        return 2.0


# =====================================================================
#             STATIC PARAMETER & UTILITY SYSTEM
# =====================================================================

class BiomechanicalOptimizer:
    """
    Provides utility helpers for regional silos, track data extraction,
    and retrieval of static baseline model parameters.
    """
    _cached_training_records = None

    @classmethod
    def clear_cache(cls):
        cls._cached_training_records = None

    @classmethod
    def _get_default_weights_for_surface(cls, surface_type):
        if surface_type == "Synthetic":
            return [60.0, 1.5, 0.85, 1.0, 8.5, 1.5]
        elif surface_type == "Turf_Wet":
            return [60.0, 1.5, 1.35, 1.0, 8.5, 1.5]
        else:
            return [60.0, 1.3, 0.65, 1.0, 8.5, 1.5]

    @classmethod
    def get_weights_for_silo(cls, silo_key):
        """
        Retrieves baseline parameters mapped directly to track surface profile.
        """
        surface_type = "Turf_Dry"
        if "Synthetic" in silo_key:
            surface_type = "Synthetic"
        elif "Turf_Wet" in silo_key:
            surface_type = "Turf_Wet"
        return cls._get_default_weights_for_surface(surface_type)

    @classmethod
    def collect_completed_races(cls, storage_dir="storage", force_reload=False):
        if cls._cached_training_records is not None and not force_reload:
            return cls._cached_training_records

        json_files = []
        for file in os.listdir('.'):
            if file.endswith('.json') and ('race_' in file or 'data' in file):
                json_files.append(os.path.abspath(file))
                
        if os.path.exists(storage_dir):
            for root, _, files in os.walk(storage_dir):
                for file in files:
                    if file.endswith('.json') and 'data' in file:
                        json_files.append(os.path.join(root, file))
                        
        deduped_paths = sorted(list(set([os.path.abspath(p) for p in json_files])))
        
        training_records = []
        for path in deduped_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                results = data.get("race_results", {})
                if results and results.get("status") == "Resulted" and data.get("runners"):
                    data["_source_path"] = os.path.normpath(os.path.relpath(path))
                    training_records.append(data)
            except Exception:
                continue
                
        cls._cached_training_records = training_records
        return training_records

    @classmethod
    def _get_region_name(cls, race_data):
        region = race_data.get("region")
        if not region:
            source_path = race_data.get("_source_path", "")
            if source_path:
                parts = os.path.normpath(source_path).split(os.sep)
                for i, part in enumerate(parts):
                    if part == "storage" and len(parts) > i + 2:
                        region = parts[i+2]
                        break
                    elif re.match(r'^\d{4}-\d{2}-\d{2}$', part) and len(parts) > i + 1:
                        region = parts[i+1]
                        break
        if not region:
            region = "Other"
        return sanitize_path_name(region)

    @classmethod
    def _get_silo_surface(cls, race_data):
        status = str(race_data.get("track_status", race_data.get("track_condition_initial", "Good"))).lower()
        if "synthetic" in status or "poly" in status:
            return "Synthetic"
        elif any(x in status for x in ["soft", "heavy", "7", "8", "9", "10", "yielding"]):
            return "Turf_Wet"
        return "Turf_Dry"

    @classmethod
    def _get_silo_key(cls, race_data):
        region = cls._get_region_name(race_data)
        surface = cls._get_silo_surface(race_data)
        return f"{region}_{surface}"


# =====================================================================
#             SOVEREIGN KINETIC INDEX (SKI) ENGINE v4.4
# =====================================================================

class BiomechanicalEngine:
    """
    Deterministic Signature Pattern (DSP) Biomechanical Engine.
    Evaluates horse selections strictly against core physical criteria
    to isolate structural performance advantages.
    """
    def __new__(cls, raw_data, weights_override=None):
        if cls is BiomechanicalEngine:
            region = BiomechanicalOptimizer._get_region_name(raw_data).lower()
            if "south_africa" in region or "south africa" in region:
                try:
                    from south_african_logic import SouthAfricanBiomechanicalEngine
                    return object.__new__(SouthAfricanBiomechanicalEngine)
                except ImportError:
                    pass
        return object.__new__(cls)

    def __init__(self, raw_data, weights_override=None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self.raw_data = raw_data
        
        # Parse global layout and metadata
        meta = raw_data.get("meeting_metadata", {})
        self.track_name = str(meta.get("track_name", raw_data.get("track_name", raw_data.get("venue", "Unknown"))))
        self.soil_base = str(meta.get("soil_base", raw_data.get("soil_base", "Unknown"))).lower()
        
        # Support both flat and structured layouts for distance and conditions
        self.distance = safe_float(raw_data.get("distance_metres", raw_data.get("distance", 1200)))
        self.track_status = str(meta.get("track_condition_initial", raw_data.get("track_status", "Good"))).lower()
        self.moisture_index_initial = safe_float(meta.get("moisture_index_initial", raw_data.get("moisture_index_initial", 5.0)))
        self.rail_position = str(meta.get("rail_position", raw_data.get("rail_position", "True")))
        self.straight_length = safe_float(meta.get("straight_length_metres", meta.get("straight_length", 353.0)))
        self.circumference = safe_float(meta.get("circumference_metres", meta.get("circumference", 1811.0)))
        
        # Class and layout parsing
        self.race_name = str(raw_data.get("class", raw_data.get("race_name", "")))
        self.is_maiden = "MDN" in self.race_name.upper() or "MAIDEN" in self.race_name.upper()
        
        # --- SSCT / SSIG automated override logic ---
        track_lower = self.track_name.lower()
        status_lower = self.track_status.lower()
        if "synthetic" in track_lower or "polytrack" in track_lower or "tapeta" in track_lower or "synthetic" in status_lower or "polytrack" in status_lower:
            self.silo = "Synthetic"
            self.is_synthetic = True
        else:
            self.silo = BiomechanicalOptimizer._get_silo_surface(self.raw_data)
            self.is_synthetic = (self.silo == "Synthetic")
            
        self.region = BiomechanicalOptimizer._get_region_name(self.raw_data)
        self.regional_silo = f"{self.region}_{self.silo}"
        
        # Dynamic weather parameters
        self.ambient_temp = 20.0
        self.humidity = 70.0
        self.wind_speed = 10.0
        self.wind_direction = "N"
        self.precipitation_mm_hr = 0.0
        
        forecast = meta.get("weather_forecast_hourly", [])
        if forecast:
            hour = forecast[0]
            self.ambient_temp = safe_float(hour.get("temperature_celsius", 20.0))
            self.humidity = safe_float(hour.get("humidity_percentage", 70.0))
            self.wind_speed = safe_float(hour.get("wind_speed_kph", 10.0))
            self.wind_direction = str(hour.get("wind_direction", "N"))
            self.precipitation_mm_hr = safe_float(hour.get("precipitation_forecast_mm_hr", 0.0))
            
        # Determine tracking compaction level (MSCI)
        self.msci = self._calculate_msci()
        self.is_sand = "sand" in self.soil_base or "dirt" in self.soil_base
        self.is_turf = not (self.is_synthetic or self.is_sand)
        
        # Set viscoelastic hysteresis phase
        if self.precipitation_mm_hr > 0.5:
            self.hysteresis = "Wetting"
        elif "soft" in self.track_status or "heavy" in self.track_status:
            self.hysteresis = "Static"
        else:
            self.hysteresis = "Drying"
            
        # Configure Dynamic Soil Suction Physics
        phi_strathayr = 1.0 if "strathayr" in self.soil_base else 0.0
        mu_moisture = 9.0 if self.msci <= 0.50 else 5.0
        alpha_clay_content = safe_float(raw_data.get("clay_content", 0.40))
        phi_suction = alpha_clay_content * (1.0 - self.msci) * (1.0 - phi_strathayr)
        
        self.beta_soil = (alpha_clay_content * mu_moisture * 
                          (1.0 - 0.75 * phi_strathayr) * (1.0 - phi_suction))
            
        # Apply standard weights matching silo parameters
        if weights_override:
            self.weights = weights_override
        else:
            self.weights = BiomechanicalOptimizer.get_weights_for_silo(self.regional_silo)

        # Field pre-compression rules execution
        self._initialize_and_compress_field()

    def evaluate_vetoes(self, runner):
        """
        Phase 1: Brun's Sieve of Elimination. Evaluates deterministic Veto Primes.
        In DSP mode, traditional vetoes are bypassed if the runner is a confirmed DSP match.
        """
        vetoes = []
        b_orig = safe_float(runner.get("barrier", runner.get("original_barrier", 8)))
        b_actual = safe_float(runner.get("recalculated_barrier", b_orig))
        
        # Determine if weights list is degenerate across field
        weights_list = [safe_float(r.get("carried_weight_kg", r.get("weight_kg", 56.0))) for r in self.active_runners]
        is_degenerate_weight = len(set(weights_list)) <= 1
        saddle_no = safe_int(runner.get("number", 1))
        max_saddle = max([safe_int(r.get("number", 1)) for r in self.active_runners]) if self.active_runners else 12
        
        race_name_upper = self.race_name.upper()
        if "PLATE" in race_name_upper or "MDN-SW" in race_name_upper or "MAIDEN PLATE" in race_name_upper:
            sex = str(runner.get("sex", "G")).upper()
            allotted_weight = 56.0 if ("F" in sex or "M" in sex) else 58.0
        elif is_degenerate_weight:
            if any(x in race_name_upper for x in ["CLASS 4", "BM70", "BM75", "BM78", "BM80"]):
                w_max, w_min = 60.5, 54.0
            elif any(x in race_name_upper for x in ["CLASS 1", "CLASS 2", "BM58", "BM64"]):
                w_max, w_min = 59.5, 54.0
            elif any(x in race_name_upper for x in ["MDN", "MAIDEN", "3YO MDN"]):
                w_max, w_min = 58.0, 54.0
            else:
                w_max, w_min = 61.0, 54.0
                
            if max_saddle > 1:
                allotted_weight = w_max - (w_max - w_min) * ((saddle_no - 1) / (max_saddle - 1))
            else:
                allotted_weight = w_max
        else:
            allotted_weight = safe_float(runner.get("carried_weight_kg", runner.get("weight_kg", 56.0)))
            
        apprentice_claim = safe_float(runner.get("apprentice_claim_kg", 0.0))
        w_eff = max(45.0, allotted_weight - apprentice_claim)
        
        career = runner.get("career_stats", {})
        starts = safe_float(career.get("starts", 0))
        wins = safe_float(career.get("wins", 0))
        
        days_since_last_start = safe_float(runner.get("days_since_last_start", 14))
        
        # Traditional Veto Prime Checks
        if starts >= 10 and wins == 0 and self.msci <= 0.60 and w_eff > 53.0:
            vetoes.append("p1 (Thermodynamic Mud Death)")
            
        if days_since_last_start >= 45 and self.distance >= 1300 and self.msci <= 0.60:
            vetoes.append("p2 (Fresh-on-Heavy Stamina Deficit)")
            
        if w_eff > 60.0 and self.is_synthetic and self.ambient_temp > 25.0:
            vetoes.append("p3 (High-Weight Synthetic Polytrack Drag)")
            
        return vetoes

    def _calculate_msci(self):
        """
        Calculates the Moisture/Compaction Soil Index (MSCI) as a soil resistance proxy.
        """
        status = self.track_status
        if "synthetic" in status or "poly" in status:
            return 0.90
        elif "heavy" in status or "10" in status or "9" in status or "8" in status:
            return 0.40 if "10" in status else 0.50 if "9" in status else 0.58
        elif "soft" in status or "7" in status or "6" in status or "5" in status:
            return 0.60 if "7" in status else 0.65 if "6" in status else 0.70
        else: # Good/Firm/Fast
            return 0.85

    def _initialize_and_compress_field(self):
        """
        Phase 0 execution: Scratching extraction, field density count, 
        barrier recalculation, and contraction mapping.
        """
        self.all_runners = self.raw_data.get("runners", [])
        self.active_runners = [
            r for r in self.all_runners 
            if str(r.get("status", "Active")).strip().lower() not in ["scr", "scratched"]
        ]
        
        self.n_original = len(self.all_runners)
        self.n_active = len(self.active_runners)
        
        self.contraction = (self.n_original - self.n_active) / self.n_original if self.n_original > 0 else 0.0
        
        # Check for degenerate/identical pre-race scraper barrier outputs (e.g. all defaulted to 8)
        barriers_list = [safe_float(r.get("original_barrier", r.get("barrier", 8))) for r in self.active_runners]
        is_degenerate_barrier = len(set(barriers_list)) <= 1
        
        if is_degenerate_barrier:
            # Apply Neutral Barrier Drag Model (NBDM) to remove false barrier advantages on bad data
            b_neutral = (self.n_active + 1) / 2.0
            for runner in self.active_runners:
                runner["recalculated_barrier"] = b_neutral
        else:
            sorted_runners = sorted(
                self.active_runners, 
                key=lambda x: safe_float(x.get("barrier", x.get("original_barrier", 8)))
            )
            for index, runner in enumerate(sorted_runners):
                runner["recalculated_barrier"] = index + 1
            
        self.psgc_override_active = (self.contraction >= 0.25)
        
        self.cfpp = 0.0
        for r in self.active_runners:
            esi = safe_float(r.get("early_speed_index", r.get("draft_pocket_score", 0.5)))
            b_actual = safe_float(r.get("recalculated_barrier", 8))
            self.cfpp += esi * math.exp(-0.15 * b_actual)

    def evaluate_runner(self, runner):
        """
        Core DSP-aligned evaluator. Isolates structural criteria matches for 
        high-probability signature profiling. Incorporates dynamic soil suction (TSSS),
        metabolic spell-recoil depletion (MMRE), and class-gravity sifting (MCG-TEDT).
        """
        if str(runner.get("status", "Active")).strip().lower() in ["scr", "scratched"]:
            return None
            
        b_orig = safe_float(runner.get("barrier", runner.get("original_barrier", 8)))
        b_actual = safe_float(runner.get("recalculated_barrier", b_orig))
        
        # --- Weight and Apprentice Claim extraction & Set Weight Correction ---
        weights_list = [safe_float(r.get("carried_weight_kg", r.get("weight_kg", 56.0))) for r in self.active_runners]
        is_degenerate_weight = len(set(weights_list)) <= 1
        
        saddle_no = safe_int(runner.get("number", 1))
        max_saddle = max([safe_int(r.get("number", 1)) for r in self.active_runners]) if self.active_runners else 12
        
        race_name_upper = self.race_name.upper()
        
        # Set-Weight Correction (SWC)
        if "PLATE" in race_name_upper or "MDN-SW" in race_name_upper or "MAIDEN PLATE" in race_name_upper:
            sex = str(runner.get("sex", "G")).upper()
            if "F" in sex or "M" in sex: # Filly/Mare
                allotted_weight = 56.0
            else:
                allotted_weight = 58.0
        elif is_degenerate_weight:
            # Class-Based Weight Bounds (CBWB)
            if any(x in race_name_upper for x in ["CLASS 4", "BM70", "BM75", "BM78", "BM80"]):
                w_max, w_min = 60.5, 54.0
            elif any(x in race_name_upper for x in ["CLASS 1", "CLASS 2", "BM58", "BM64"]):
                w_max, w_min = 59.5, 54.0
            elif any(x in race_name_upper for x in ["MDN", "MAIDEN", "3YO MDN"]):
                w_max, w_min = 58.0, 54.0
            else:
                w_max, w_min = 61.0, 54.0
                
            if max_saddle > 1:
                allotted_weight = w_max - (w_max - w_min) * ((saddle_no - 1) / (max_saddle - 1))
            else:
                allotted_weight = w_max
        else:
            allotted_weight = safe_float(runner.get("carried_weight_kg", runner.get("weight_kg", 56.0)))
            
        apprentice_claim = safe_float(runner.get("apprentice_claim_kg", 0.0))
        # Fallback regex if claim is 0.0
        if apprentice_claim == 0.0:
            jockey_name = str(runner.get("jockey", "")).lower()
            claim_match = re.search(r'\(a(\d+\.?\d*)\)', jockey_name)
            apprentice_claim = float(claim_match.group(1)) if claim_match else 0.0
            
        # Support apprentice claim database lookup for known jockeys
        if apprentice_claim == 0.0:
            jockey_clean = jockey_name.lower().strip()
            jockey_clean_alpha = re.sub(r'[^a-z\s]', '', jockey_clean).strip()
            APPRENTICE_CLAIMS = {
                "leah martyn": 2.0, "bella youngberry": 2.0, "jett newman": 2.0,
                "olivia kendal": 1.5, "courtney bellamy": 2.0, "benjamin osmond": 1.5,
                "mckenzie apel": 2.0, "b youngberry": 2.0, "j newman": 2.0,
                "o kendal": 1.5, "c bellamy": 2.0, "b osmond": 1.5, "m apel": 2.0,
                "l martyn": 2.0
            }
            for app_name, app_claim in APPRENTICE_CLAIMS.items():
                if app_name in jockey_clean_alpha or app_name in jockey_clean:
                    apprentice_claim = app_claim
                    break
                    
        w_eff = max(45.0, allotted_weight - apprentice_claim)
        
        # --- Base Performance Scoring ---
        raw_nls = safe_float(runner.get("raw_nls_baseline", runner.get("raw_nls", 80.0)))
        age = safe_float(runner.get("age", 4.0))
        sex = str(runner.get("sex", "G")).upper()
        
        career = runner.get("career_stats", {})
        starts = safe_float(career.get("starts", 0))
        wins = safe_float(career.get("wins", 0))
        places = safe_float(career.get("places", 0))
        win_rate = wins / max(1.0, starts)
        
        j_name = str(runner.get("jockey", "")).lower()
        
        m_i = 0.15 * (starts / 10.0)
        f_i = 0.12 * b_actual
        nu_i = 0.50 + m_i + f_i
        
        # Tacky-Surface Suction Surcharge (TSSS)
        tsss = 0.0
        if "soft" in self.track_status or "heavy" in self.track_status:
            w_min = min([max(45.0, safe_float(r.get("carried_weight_kg", r.get("weight_kg", 56.0))) - safe_float(r.get("apprentice_claim_kg", 0.0))) for r in self.active_runners]) if self.active_runners else 50.0
            theta_suction = 0.05
            msci_r = self.msci
            phi_drying = 1.5 if self.hysteresis == "Drying" else 1.0
            tsss = theta_suction * msci_r * phi_drying * max(0.0, w_eff - w_min)
            
        # Multiplicative Metabolic Recoil Engine (MMRE)
        mmre_penalty = 0.0
        runs_this_prep = safe_int(runner.get("runs_this_prep", 1))
        if runs_this_prep == 2:
            last_run = runner.get("last_run", {})
            margin_1u = safe_float(last_run.get("margin_lengths", 2.0))
            track_1u = str(last_run.get("track_condition", "Good")).lower()
            i_heavy = 1.5 if any(x in track_1u for x in ["heavy", "soft", "wet", "5", "6", "7", "8", "9", "10"]) else 1.0
            e_1u = i_heavy * math.log(1.0 + margin_1u)
            surp = 0.65
            gamma_recoil = 0.60
            mmre_factor = (1.0 + surp) * math.exp(gamma_recoil * e_1u)
            mmre_penalty = 5.0 * mmre_factor
            
        # Spaced Layoff Recoil (SLR) Fatigue Multiplier
        slr_penalty = 0.0
        days_since_last_start = safe_float(runner.get("days_since_last_start", 14))
        if days_since_last_start <= 2.0:
            slr_penalty = 6.0
            
        # MCG-TEDT Class-Gravity & Trial-Efficacy Decision Tree
        mcg_bonus = 0.0
        trainer_sr = safe_float(runner.get("trainer_wet_win_rate_pct", 10.0)) / 100.0
        trial_won_30d = bool(runner.get("recent_jumps_trial", {}).get("won_30d", False))
        trial_completed = bool(runner.get("recent_jumps_trial", {}).get("completed", False))
        highest_class = str(runner.get("highest_class_180d", "")).upper()
        last_run = runner.get("last_run", {})
        last_class = str(last_run.get("class", "")).upper()
        last_margin = safe_float(last_run.get("margin_lengths", 99.0))
        
        is_metro_form = any(x in highest_class or x in last_class for x in ["METRO", "GROUP", "GP", "G1", "G2", "G3", "LR", "LISTED", "BM84", "BM78", "BM82", "OPEN", "CUP"])
        
        if is_metro_form and last_margin < 5.0 and starts > 0:
            if w_eff < 55.0:
                mcg_bonus = 5.0  # Golden Class-Drop
            else:
                mcg_bonus = 3.5  # Silver Class-Drop
        elif starts == 0:
            if trainer_sr >= 0.15:
                if trial_won_30d or trial_completed:
                    mcg_bonus = 2.0  # Target Debutant
                else:
                    mcg_bonus = 1.0  # Cover Debutant
            else:
                mcg_bonus = -2.0 # Risk Debutant
        else:
            if last_margin >= 5.0:
                mcg_bonus = -3.0 # Sifted / Low sectional acceleration
                
        # Textual Pedigree Stamina Index (TPSI)
        TPSI_SIRES = {
            "goodfella": 8.5, "fierce impact": 8.2, "king's legacy": 8.0,
            "kings legacy": 8.0, "rothesay": 7.5, "alabama express": 7.0,
            "time to reign": 5.5, "hello youmzain": 5.0
        }
        tpsi = 0.0
        if self.distance >= 1600:
            sire_name = str(runner.get("sire", "")).lower().strip()
            tpsi = 6.5 # Neutral
            for s_name, s_val in TPSI_SIRES.items():
                if s_name in sire_name:
                    tpsi = s_val
                    break
                    
        # Stayers Experience Benefit (SEB)
        seb = 0.0
        if self.distance >= 1800 and self.is_maiden:
            starts_seb = max(1.0, safe_float(career.get("starts", 0)))
            seb = 1.0 + 0.15 * math.log(starts_seb) * (self.distance / 1600.0)
            
        # Final NLS Baseline with age penalty
        final_nls = raw_nls - (1.5 * max(0.0, age - 5.0))
        
        # Calculate Sovereign Kinetic Index (SKI) using continuous physical metrics
        # Standard weight penalty is scaled: - (1.5 * (W_eff - 55.0))
        weight_penalty = 1.5 * (w_eff - 55.0)
        
        # Assemble continuous score
        base_score = final_nls - weight_penalty - tsss - mmre_penalty - slr_penalty + mcg_bonus + tpsi + seb
        
        # Apply standard non-linear friction maps
        sbei = (final_nls * 1.05) / (max(0.01, nu_i) * ((w_eff / 55.0)**2))
        ippi = 1.05 / max(0.01, f_i)
        cppi = 1.0 + win_rate
        mre = math.log(max(1.1, starts * 1000))
        
        # --- Deterministic Signature Pattern (DSP) Pattern Matching ---
        matched_dsps = []
        
        # DSP-1: Local Viscoelastic Habituation Loop (Synthetic Pivot)
        is_synthetic_track = (self.silo == "Synthetic")
        trainer_home_str = str(runner.get("trainer_home_track", "")).lower().strip()
        track_name_clean = self.track_name.lower().strip()
        trained_at_home = (trainer_home_str == track_name_clean) or bool(runner.get("trained_at_home", False))
        
        synth_starts = safe_float(career.get("synth_stats", {}).get("starts", runner.get("synthetic_starts", 0)))
        synth_places = safe_float(career.get("synth_stats", {}).get("places", runner.get("synthetic_places", 0)))
        synth_wins = safe_float(career.get("synth_stats", {}).get("wins", runner.get("synthetic_wins", 0)))
        if synth_starts > 0:
            synth_place_rate = (synth_places + synth_wins) / synth_starts
        else:
            synth_place_rate = (places + wins) / max(1.0, starts)
            
        if is_synthetic_track and trained_at_home and (synth_place_rate >= 0.50):
            matched_dsps.append("DSP-1 (Synthetic Pivot)")
            
        # DSP-2: Compaction-Weight Decoupling Curve (Wet Turf/Clay Pivot)
        is_wet_turf = (self.silo == "Turf_Wet")
        gamma_elastic = 1.0 + 1.5 * (1.0 - self.msci)
        is_lightweight = (w_eff <= 58.0)
        elite_jockeys = ["egan", "coffey", "rawiller", "allen", "stackhouse", "williams", "yendall", "mcdonald", "kah", "lane", "shinn", "clark", "baster"]
        is_elite_jockey = any(j in j_name for j in elite_jockeys)
        ftla_val = 0.45 if (b_actual >= 8 or is_elite_jockey) else 0.0
        
        # DSP Verification Filter (DPTV): damp synthetic DSP matches if input weights are completely degenerate
        if is_degenerate_weight:
            is_lightweight = (w_eff <= 56.5) # tighter lightweight threshold
            
        if is_wet_turf and (gamma_elastic >= 1.45) and (is_lightweight or ftla_val >= 0.45):
            matched_dsps.append("DSP-2 (Wet Turf Pivot)")
            
        # DSP-3: Metropolitan Class Gravity Corridor (Class-Drop Pivot)
        highest_class_180d = str(runner.get("highest_class_180d", "")).upper()
        current_class = self.race_name.upper()
        is_dropping_to_prov = any(x in current_class for x in ["PROV", "CTRY", "BM58", "BM64", "BM70", "MDN", "MAIDEN", "3YO MDN"])
        is_metro_180d = any(x in highest_class_180d for x in ["METRO", "GROUP", "GP", "G1", "G2", "G3", "LR", "LISTED", "BM84", "BM78", "BM82", "OPEN", "CUP"])
        cmrl = 1.0 if (is_metro_180d and is_dropping_to_prov) or bool(runner.get("cmrl_active", False)) else 0.0
        
        class_prior_num = safe_float(runner.get("class_prior_num", 0.0))
        class_current_num = safe_float(runner.get("class_current_num", 0.0))
        if class_prior_num > class_current_num and class_current_num > 0:
            cmrl = 1.0
            
        if cmrl == 1.0:
            matched_dsps.append("DSP-3 (Class-Drop Pivot)")
            
        # DSP-4: Fresh-Rail Kinetic Saving (Firm Turf Pivot)
        is_firm_turf = (self.silo == "Turf_Dry")
        if is_firm_turf and (self.msci >= 0.80) and (b_actual <= 4):
            matched_dsps.append("DSP-4 (Firm Turf Pivot)")
            
        tie_breaker = (wins / max(1.0, starts)) * 10.0 + (1.0 / max(1.0, b_actual)) * 2.0
        
        if matched_dsps:
            # Absolute scores shouldn't overflow, keep them bounded and continuous
            ski_score = base_score + 10.0 * len(matched_dsps) + tie_breaker
            is_vetoed = False
        else:
            ski_score = base_score + tie_breaker
            # Check for Neuromuscular Exhaustion Veto or Standard Vetoes
            vetoes = self.evaluate_vetoes(runner)
            is_vetoed = len(vetoes) > 0
            
        # Neuromuscular Exhaustion Veto Check
        if nu_i >= 0.90:
            is_vetoed = True
            
        metrics_dict = {
            "name": runner.get("name", "Unknown"),
            "number": safe_int(runner.get("number")),
            "barrier_recalculated": int(b_actual),
            "weight_effective": round(w_eff, 1),
            "final_nls": round(final_nls, 3),
            "metabolic_engine": round(m_i, 4),
            "mechanical_engine": round(f_i, 4),
            "latent_frailty": round(nu_i, 4),
            "sbei": round(sbei, 3),
            "mre": round(mre, 3),
            "ippi": round(ippi, 3),
            "cppi": round(cppi, 3),
            "ski_score": round(ski_score, 3),
            "is_vetoed": is_vetoed,
            "veto_reasons": [] if not is_vetoed else self.evaluate_vetoes(runner),
            "matched_dsps": matched_dsps,
            "lrdl_active": False,
            "bsrt_aligned": True,
            "bsrt_error": 0.0
        }
        
        return metrics_dict

    def perform_bsrt_audit(self, metrics):
        """
        Executes legacy self-audit diagnostics. Returns True by default.
        """
        return True, 0.0

    def rank_field(self):
        """
        Processes active runners and splits them based on deterministic matched status.
        DSP matching runners are given sorting priority.
        """
        processed_runners = []
        for runner in self.active_runners:
            metrics = self.evaluate_runner(runner)
            if metrics:
                processed_runners.append(metrics)
                
        # Split into matched vs unmatched categories
        matched = [r for r in processed_runners if r.get("matched_dsps")]
        unmatched = [r for r in processed_runners if not r.get("matched_dsps")]
        
        # Sort both lists by calculated SKI score
        matched.sort(key=lambda x: x["ski_score"], reverse=True)
        unmatched.sort(key=lambda x: x["ski_score"], reverse=True)
        
        final_ranked = matched + unmatched
        
        # Designate roles sequentially
        for index, item in enumerate(final_ranked):
            if item.get("matched_dsps"):
                if index == 0:
                    item["designation"] = "1A Sovereign (Primary DSP Match)"
                elif index == 1:
                    item["designation"] = "1B Shield (Cover DSP Match)"
                else:
                    item["designation"] = "DSP Contender Match"
            else:
                item["designation"] = "Unmatched Runner (Skip)"
                
        return final_ranked

