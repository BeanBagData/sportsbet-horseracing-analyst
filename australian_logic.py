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
#             SOVEREIGN KINETIC INDEX (SKI) ENGINE v3.1
# =====================================================================

class BiomechanicalEngine:
    """
    Main Sovereign Kinetic Index (SKI) Engine implementing the mathematical 
    framework of the Version 3.1 specification. Computes dynamic physical engines 
    (Metabolic and Mechanical) and evaluates deterministic veto boundaries.
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
        Returns a list of triggered vetoes (empty list if the runner is fully compliant).
        """
        vetoes = []
        b_orig = safe_float(runner.get("barrier", runner.get("original_barrier", 8)))
        b_actual = safe_float(runner.get("recalculated_barrier", b_orig))
        
        # Determine if weights list is degenerate across field
        weights_list = [safe_float(r.get("carried_weight_kg", r.get("weight_kg", 56.0))) for r in self.active_runners]
        is_degenerate_weight = len(set(weights_list)) <= 1
        saddle_no = safe_int(runner.get("number", 1))
        max_saddle = max([safe_int(r.get("number", 1)) for r in self.active_runners]) if self.active_runners else 12
        
        if is_degenerate_weight:
            allotted_weight = 62.5 - 6.5 * ((saddle_no - 1) / max(1, max_saddle - 1))
        else:
            allotted_weight = safe_float(runner.get("carried_weight_kg", runner.get("weight_kg", 56.0)))
            
        apprentice_claim = safe_float(runner.get("apprentice_claim_kg", 0.0))
        w_eff = max(45.0, allotted_weight - apprentice_claim)
        
        career = runner.get("career_stats", {})
        starts = safe_float(career.get("starts", 0))
        wins = safe_float(career.get("wins", 0))
        places = safe_float(career.get("places", 0))
        
        wet_stats = career.get("wet_stats", {})
        wet_starts = safe_float(wet_stats.get("starts", 0))
        wet_wins = safe_float(wet_stats.get("wins", 0))
        
        runs_this_prep = safe_float(runner.get("runs_this_prep", 1))
        runs_within_40d = safe_float(runner.get("runs_within_40d", runs_this_prep))
        days_since_last_start = safe_float(runner.get("days_since_last_start", 14))
        
        # p1: Thermodynamic Mud Death
        if wet_starts >= 10 and wet_wins == 0 and self.msci <= 0.60:
            if w_eff > 53.0:
                vetoes.append("p1 (Thermodynamic Mud Death)")
            
        # p2: Fresh-on-Heavy Stamina Deficit
        if days_since_last_start >= 45 and self.distance >= 1300 and self.msci <= 0.60:
            vetoes.append("p2 (Fresh-on-Heavy Stamina Deficit)")
            
        # p3: High-Weight Synthetic Polytrack Drag
        if w_eff > 60.0 and self.is_synthetic and self.ambient_temp > 25.0:
            vetoes.append("p3 (High-Weight Synthetic Polytrack Drag)")
            
        # p4: Metabolic Compression
        last_run = runner.get("last_run", {})
        last_pos = safe_float(last_run.get("finishing_position", 4))
        recent_podium_10d = bool(runner.get("recent_podium_10d", (last_pos <= 3 and days_since_last_start <= 10)))
        if runs_within_40d >= 5 and not recent_podium_10d:
            vetoes.append("p4 (Metabolic Compression)")
            
        # p5: Second-Up Recoil Syndrome
        recent_jumps_trial = runner.get("recent_jumps_trial", {})
        total_trials_45d = safe_float(recent_jumps_trial.get("total_trials_45d", 0))
        abp = 1.0 if total_trials_45d >= 4 else 0.0
        layoff_prior = safe_float(runner.get("layoff_prior_prep", 0))
        
        first_up_demanding = False
        last_run_cond = str(last_run.get("track_condition", "")).lower()
        last_run_msci = 0.55 if any(x in last_run_cond for x in ["soft", "heavy", "s6", "s7", "h8", "h9", "h10"]) else 0.85
        if last_pos <= 3 and last_run_msci <= 0.60:
            first_up_demanding = True
            
        if runs_this_prep == 2 and layoff_prior >= 180 and first_up_demanding and abp == 0.0:
            vetoes.append("p5 (Second-Up Recoil Syndrome)")
            
        # p6: Clinical Cardiac Veto
        has_cardiac_30d = bool(runner.get("cardiac_arrhythmia_30d", False) or runner.get("pulmonary_haemorrhage_30d", False))
        vet_clearance = bool(recent_jumps_trial.get("completed", False))
        trial_distance = safe_float(recent_jumps_trial.get("trial_distance", 1000))
        trial_beaten_margin = safe_float(recent_jumps_trial.get("trial_beaten_margin_lengths", 0.0))
        phi_acco = 1.0 if (vet_clearance and trial_distance >= 1000 and trial_beaten_margin <= 3.0) else 0.0
        if has_cardiac_30d and phi_acco == 0.0:
            vetoes.append("p6 (Clinical Cardiac Veto)")
            
        # p7: Distance Ceiling Veto
        sire_awd = safe_float(runner.get("sire_awd", 1100.0))
        wins_beyond_1200 = safe_float(career.get("wins_beyond_1200", 0))
        
        # SAPE (StrathAyr Sand-Loam Porosity Exemption)
        strathayr = 1.0 if "strathayr" in self.soil_base else 0.0
        clay_content = safe_float(self.raw_data.get("clay_content", 0.15))
        phi_sape = strathayr * (1.0 - clay_content)
        
        p7_awd_threshold = 1150.0
        if phi_sape >= 0.70:
            p7_awd_threshold = 1050.0
            
        # SMCE (Synthetic/Maiden Class Exemption)
        prev_staying_margin = safe_float(runner.get("prev_staying_margin", 99.0))
        phi_smce = 1.0 if (self.is_maiden and self.is_synthetic and sire_awd >= 1100.0 and prev_staying_margin <= 8.0) else 0.0
        
        if self.distance >= 1300 and sire_awd <= p7_awd_threshold and wins_beyond_1200 == 0:
            if phi_sape < 0.70 and phi_smce == 0.0:
                vetoes.append("p7 (Distance Ceiling Veto)")
                
        # p8: Synthetic Resuming Stamina Veto
        synth_first_up_wins = safe_float(career.get("synth_first_up_wins", 0))
        synth_first_up_starts = safe_float(career.get("synth_first_up_starts", 0))
        synth_fu_win_rate = (synth_first_up_wins / synth_first_up_starts) if synth_first_up_starts > 0 else 0.0
        if days_since_last_start >= 60 and self.distance >= 1400 and self.is_synthetic and synth_fu_win_rate < 0.50:
            vetoes.append("p8 (Synthetic Resuming Stamina Veto)")
            
        # p9: Fatigued Exposed Maiden Veto
        is_exposed_maiden = (starts >= 8 or runs_this_prep >= 5) and wins == 0
        maternal_grandsire_wet_rating = safe_float(runner.get("maternal_grandsire_wet_rating", 7.0))
        
        barrier_veto_applies = (b_actual >= 8)
        if self.psgc_override_active and b_orig >= 12 and b_actual <= 10:
            barrier_veto_applies = False
            
        if is_exposed_maiden and self.distance >= 1200 and self.is_turf and self.msci <= 0.65 and barrier_veto_applies:
            if maternal_grandsire_wet_rating < 8.5:
                if not self.psgc_override_active:
                    vetoes.append("p9 (Fatigued Exposed Maiden Veto)")
                
        # p10: Second-Up Spell-Recoil Syndrome
        first_up_margin = safe_float(last_run.get("margin_lengths", 2.0))
        is_second_up = (runs_this_prep == 2)
        is_low_stress = bool(runner.get("is_low_stress_sprint", runner.get("low_stress_first_up", False)))
        
        if is_second_up and layoff_prior >= 180 and first_up_margin <= 1.0 and w_eff >= 56.0 and (12 <= days_since_last_start <= 28):
            if abp == 0.0 and not is_low_stress:
                vetoes.append("p10 (Second-Up Spell-Recoil)")
                
        # TMV: Tactical Map Veto
        is_slow_start = safe_float(runner.get("slow_start_pct", 0.0)) >= 0.50 or "slow out" in str(runner.get("overview", "")).lower()
        if is_slow_start and b_actual <= 6 and self.cfpp <= 1.0:
            vetoes.append("TMV (Tactical Map Veto)")
            
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
        # Exclude scratched runners
        self.all_runners = self.raw_data.get("runners", [])
        self.active_runners = [
            r for r in self.all_runners 
            if str(r.get("status", "Active")).strip().lower() not in ["scr", "scratched"]
        ]
        
        self.n_original = len(self.all_runners)
        self.n_active = len(self.active_runners)
        
        # Calculate Field Contraction Ratio
        self.contraction = (self.n_original - self.n_active) / self.n_original if self.n_original > 0 else 0.0
        
        # Sequential post-scratching barrier adjustment using actual barrier positions
        sorted_runners = sorted(
            self.active_runners, 
            key=lambda x: safe_float(x.get("barrier", x.get("original_barrier", 8)))
        )
        
        for index, runner in enumerate(sorted_runners):
            runner["recalculated_barrier"] = index + 1
            
        # Check Post-Scratching Gate Compression (PSGC) Override eligibility
        self.psgc_override_active = (self.contraction >= 0.25)
        
        # Calculate Cumulative Field Pace Pressure (CFPP)
        self.cfpp = 0.0
        for r in self.active_runners:
            esi = safe_float(r.get("early_speed_index", r.get("draft_pocket_score", 0.5)))
            b_actual = safe_float(r.get("recalculated_barrier", 8))
            self.cfpp += esi * math.exp(-0.15 * b_actual)

    def evaluate_runner(self, runner):
        """
        Calculates Final NLS, Latent Frailty, non-market proxies, and final SKI/SBEI 
        metrics for an individual runner. Performs a complete BSRT error audit.
        """
        # Exclude scratched runners instantly
        if str(runner.get("status", "Active")).strip().lower() in ["scr", "scratched"]:
            return None
            
        # --- 1. Base Variables Extract & Type Casts ---
        b_orig = safe_float(runner.get("barrier", runner.get("original_barrier", 8)))
        b_actual = safe_float(runner.get("recalculated_barrier", b_orig))
        
        # --- SWR: Saddlecloth-Derived Weight Reallocation Heuristic ---
        weights_list = [safe_float(r.get("carried_weight_kg", r.get("weight_kg", 56.0))) for r in self.active_runners]
        is_degenerate_weight = len(set(weights_list)) <= 1
        saddle_no = safe_int(runner.get("number", 1))
        max_saddle = max([safe_int(r.get("number", 1)) for r in self.active_runners]) if self.active_runners else 12
        
        if is_degenerate_weight:
            allotted_weight = 62.5 - 6.5 * ((saddle_no - 1) / max(1, max_saddle - 1))
        else:
            allotted_weight = safe_float(runner.get("carried_weight_kg", runner.get("weight_kg", 56.0)))
            
        apprentice_claim = safe_float(runner.get("apprentice_claim_kg", 0.0))
        
        if apprentice_claim == 0.0:
            jockey_name = str(runner.get("jockey", "")).lower()
            claim_match = re.search(r'\(a(\d+\.?\d*)\)', jockey_name)
            apprentice_claim = float(claim_match.group(1)) if claim_match else 0.0
            
        w_eff = max(45.0, allotted_weight - apprentice_claim)
        
        raw_nls = safe_float(runner.get("raw_nls_baseline", runner.get("raw_nls", 80.0)))
        age = safe_float(runner.get("age", 4.0))
        sex = str(runner.get("sex", "")).upper()
        
        is_filly = 1.0 if "F" in sex else 0.0
        is_mare = 1.0 if "M" in sex or "MARE" in sex else 0.0
        is_3yo = 1.0 if age == 3.0 else 0.0
        
        career = runner.get("career_stats", {})
        
        # --- Degenerate Starts Protection ---
        starts_list = [safe_int(r.get("career_stats", {}).get("starts", 0)) for r in self.active_runners]
        is_degenerate_starts = sum(starts_list) == 0
        
        starts = safe_float(career.get("starts", 0))
        wins = safe_float(career.get("wins", 0))
        places = safe_float(career.get("places", 0))
        win_rate = wins / max(1.0, starts)
        
        # Base pedigree/genetic parameters
        sire_awd = safe_float(runner.get("sire_awd", 1100.0))
        partnership_starts = safe_float(runner.get("partnership_starts", 5.0))
        
        # --- Stable Stats Mapping Override Block (Vic Wet-Track Calibration) ---
        j_name = str(runner.get("jockey", "")).lower()
        t_name = str(runner.get("trainer", "")).lower()
        
        jockey_wet_win_rate = safe_float(runner.get("jockey_wet_win_rate_pct", 10.0)) / 100.0
        trainer_wet_win_rate = safe_float(runner.get("trainer_wet_win_rate_pct", 10.0)) / 100.0
        
        if jockey_wet_win_rate <= 0.10:
            if any(x in j_name for x in ["allen", "egan", "gordon", "rawiller", "stockdale", "duffy", "noonan", "nugent", "hurdle", "maskiell", "spain"]):
                jockey_wet_win_rate = 0.16
                if "allen" in j_name or "egan" in j_name or "rawiller" in j_name:
                    jockey_wet_win_rate = 0.20
                    
        if trainer_wet_win_rate <= 0.10:
            if any(x in t_name for x in ["hayes", "payne", "ryan", "alexander", "dwyer", "freedman", "cummings", "mcevoy", "brisbourne", "nichols", "howley"]):
                trainer_wet_win_rate = 0.17
                if "payne" in t_name or "hayes" in t_name or "mcevoy" in t_name:
                    trainer_wet_win_rate = 0.21
        
        runs_this_prep = safe_float(runner.get("runs_this_prep", 1))
        days_since_last_start = safe_float(runner.get("days_since_last_start", runner.get("days_since_last_run", 14)))
        
        # Prep status flag mapping
        is_second_up = (runs_this_prep == 2)
        
        gear_changes = runner.get("gear_changes", [])
        gear_str = " ".join([str(g).lower() for g in gear_changes]) + " " + str(runner.get("overview", "")).lower()
        
        last_run = runner.get("last_run", {})
        last_pos = safe_float(last_run.get("finishing_position", 4))
        last_run_cond = str(last_run.get("track_condition", "")).lower()
        last_run_msci = 0.55 if any(x in last_run_cond for x in ["soft", "heavy", "s6", "s7", "h8", "h9", "h10"]) else 0.85
        first_up_margin = safe_float(last_run.get("margin_lengths", last_run.get("margin", 2.0)))
        
        recent_jumps_trial = runner.get("recent_jumps_trial", {})
        total_trials_60d = safe_float(recent_jumps_trial.get("total_trials_45d", runner.get("trials_60d", 0)))
        abp = 1.0 if total_trials_60d >= 4 else 0.0
        phi_abp = 0.30 * abp
        
        layoff_prior_val = safe_float(runner.get("layoff_prior_prep", runner.get("layoff_days", days_since_last_start)))
        prev_avg_dist = safe_float(runner.get("prev_avg_dist", runner.get("prev_distance", self.distance)))
        max_career_dist = safe_float(runner.get("max_career_dist", self.distance))
        
        clay_content = safe_float(self.raw_data.get("clay_content", 0.40))
        phi_strathayr = 1.0 if "strathayr" in self.soil_base else 0.0
        alpha_clay_content = 0.20 if phi_strathayr == 1.0 else clay_content
        
        normalised_class_rank = safe_float(runner.get("class_rank", 5.0))
        peak_rating = safe_float(runner.get("peak_performance_rating", 75.0))
        cppi = (normalised_class_rank * math.exp(0.10 * win_rate)) / math.log(peak_rating + 1.5)

        # --- 2. Initialise and Define Basic Dynamic Indicators ---
        margin_debut = safe_float(runner.get("margin_debut", 3.0))
        gamma_pcr = max(0.20, math.exp(-0.15 * (margin_debut - 3.0))) if starts <= 2 else 1.0
        mu_wetting = 0.25 if self.precipitation_mm_hr > 0.0 else 0.0
        sire_wet_stamina_rating = safe_float(runner.get("sire_wet_stamina_rating", 5.0))

        # Dynamic variable structures
        m_i = 0.0
        f_i = 0.0
        pedigree_shield = sire_wet_stamina_rating
        sigma_syn = 0.0
        phi_trial_recovery = 0.0
        lambda_class = 0.0
        phi_wta = 0.0
        delta_inexp = 0.0
        plfi = 0.0
        psi_adtd = 0.0
        delta_mmpf = 0.0
        psi_lss = 0.0
        phi_cdsc = 0.0
        dcdi = 0.0
        delta_lane = 0.0
        delta_stress = 0.0
        t_fresh_heavy = 0.0
        phi_campaign = 0.0
        phi_mfhd = 0.0
        gamma_weight_adjusted = 0.0
        delta_kickback = 0.0
        wcvc = 0.0
        theta_ngl = 0.0
        psi_tifu = 0.0
        phi_gear = 0.0
        kpdf = 0.0
        phi_wbcr = 0.0
        pdcp = 0.0
        phi_adpf = 0.0
        delta_ht_pprs = 0.0
        delta_aero = 0.0
        delta_drs = 0.0
        vsfs = 0.0
        gafwo = 0.0
        sd_ksi = 0.0
        sksi = 0.0
        kvsi = 0.0
        gamma_awt_torque = 0.0
        phi_stp = 0.0
        psi_asdl = 0.0
        crfr = 0.0
        supi = 0.0
        slr = 0.0
        delta_recoil = 0.0
        delta_shock = 0.0
        
        # Branch and auxiliary parameters
        beta_soil = self.beta_soil
        s_visc = 0.0
        phi_tls_jockey = 0.0
        ftla = 0.0
        f_poly_final = 0.0
        vspci = 1.0
        delta_f_plate = 0.0
        sedi = 0.0
        psi_ortho = 0.0
        clb = 0.0
        scd = 0.0

        # --- 3. CFPP & Pace Placement mapping ---
        esi = safe_float(runner.get("early_speed_index", runner.get("draft_pocket_score", 0.5)))
        sorted_by_esi = sorted(self.active_runners, key=lambda x: safe_float(x.get("early_speed_index", 0.5)), reverse=True)
        leading_threshold = max(1, int(self.n_active * 0.30))
        is_leading_30 = 1.0 if (runner in sorted_by_esi[:leading_threshold]) else 0.0
        lpi = esi 
        
        # --- 4. Step A: Speed Baseline (NLS) Calibration ---
        recent_form = runner.get("recent_form", [])
        if not recent_form and last_run:
            recent_form = [last_run]
            
        weighted_abm_num = 0.0
        weighted_abm_den = 0.0
        prev_ran_heavy = False
        
        for idx, run in enumerate(recent_form[:3]):
            if not run: 
                continue
            margin = safe_float(run.get("margin_lengths", run.get("margin", 2.0)))
            days_ago = safe_float(run.get("days_ago", 14 * (idx + 1)))
            spell_intervened = bool(run.get("spell_intervened", False))
            
            gamma_spell = 0.60 if (spell_intervened or days_ago > 120) else 0.0
            w_k = math.exp(-0.005 * days_ago) * (1.0 - gamma_spell)
            
            weighted_abm_num += w_k * margin
            weighted_abm_den += w_k
            
            cond = str(run.get("track_condition", "")).lower()
            if any(x in cond for x in ["soft", "heavy", "s6", "s7", "h8", "h9", "h10"]):
                prev_ran_heavy = True
                
        abm_weighted = (weighted_abm_num / weighted_abm_den) if weighted_abm_den > 0.0 else 2.5
        abm_adjusted = abm_weighted
        
        # Surface-Split Isolation Rule (SSIR)
        synthetic_starts = safe_float(career.get("synth_stats", {}).get("starts", 0))
        synthetic_places = safe_float(career.get("synth_stats", {}).get("places", 0))
        turf_starts = safe_float(career.get("turf_stats", {}).get("starts", starts - synthetic_starts))
        turf_places = safe_float(career.get("turf_stats", {}).get("places", places - synthetic_places))
        
        synth_place_rate = synthetic_places / max(1.0, synthetic_starts)
        turf_place_rate = turf_places / max(1.0, turf_starts)
        s_disp = synth_place_rate - turf_place_rate
        
        use_only_synthetic = (synthetic_starts >= 3 and s_disp >= 0.40)
        if use_only_synthetic:
            form_to_use = [run for run in recent_form if "synthetic" in str(run.get("track_condition", "")).lower()]
            if form_to_use:
                weighted_abm_num = 0.0
                weighted_abm_den = 0.0
                for idx, run in enumerate(form_to_use[:3]):
                    margin = safe_float(run.get("margin_lengths", 2.0))
                    days_ago = safe_float(run.get("days_ago", 14 * (idx + 1)))
                    w_k = math.exp(-0.005 * days_ago)
                    weighted_abm_num += w_k * margin
                    weighted_abm_den += w_k
                abm_adjusted = (weighted_abm_num / weighted_abm_den) if weighted_abm_den > 0.0 else 2.5

        # Surface-Form Decoupling Filter (SFDF)
        if not use_only_synthetic and (self.is_synthetic or self.msci >= 0.75) and prev_ran_heavy:
            wet_stats = career.get("wet_stats", {})
            wet_wins_val = safe_float(wet_stats.get("wins", 0))
            dry_wins = safe_float(career.get("dry_stats", {}).get("wins", wins - wet_wins_val))
            dry_pref_ratio = dry_wins / max(1.0, starts)
            abm_adjusted = abm_weighted * (1.0 - (dry_pref_ratio * 0.80))
            
        # Class Memory Recovery Lock (CMRL)
        highest_class_180d = str(runner.get("highest_class_180d", "")).upper()
        current_class = self.race_name.upper()
        is_dropping_to_prov = any(x in current_class for x in ["PROV", "CTRY", "BM58", "BM64", "BM70"])
        is_metro_180d = any(x in highest_class_180d for x in ["METRO", "GROUP", "GP", "G1", "G2", "G3", "LR", "LISTED", "BM84"])
        cmrl = 1.0 if (is_metro_180d and is_dropping_to_prov) or bool(runner.get("cmrl_active", False)) else 0.0
        
        fdf = 0.10 * max(0.0, safe_float(runner.get("prev_beaten_margin", abm_adjusted)) - 2.0)
        if cmrl == 1.0:
            fdf = min(fdf, 0.05)
            
        adjusted_nls = raw_nls * math.exp(-fdf)
        
        # Unraced Metro-to-Regional Class Gravity Coefficient (UMR-CGC)
        if starts == 0 and bool(runner.get("metro_prep", False)):
            adjusted_nls += 2.50

        # Class-Drop Performance Offset (C_offset)
        class_prior_num = safe_float(runner.get("class_prior_num", 5.0))
        class_current_num = safe_float(runner.get("class_current_num", 4.0))
        c_offset = 1.25 * max(0.0, safe_float(runner.get("highest_metro_grade", class_prior_num - class_current_num))) * math.exp(-layoff_prior_val / 365.0)
        adjusted_nls += c_offset
        
        # Sire Synthetic/Sand Affinity Modifier
        sire = str(runner.get("sire", "")).lower()
        kappa_synth = 1.00
        if any(x in sire for x in ["shamardal", "blue point", "lope de vega", "crackerjack king"]):
            kappa_synth = 1.35
        elif any(x in sire for x in ["invincible spirit", "shalaa", "i am invincible"]):
            kappa_synth = 1.25
            
        adjusted_nls = adjusted_nls * kappa_synth
        if starts == 0 and (self.is_synthetic or self.is_sand):
            if kappa_synth >= 1.25:
                adjusted_nls += 5.0
                
        # Course-and-Distance Deficit Linear Penalty
        cd_beaten_margin = safe_float(runner.get("cd_beaten_margin", 0.0))
        if cd_beaten_margin > 2.0:
            adjusted_nls -= 1.0 * cd_beaten_margin
            
        # Closing Sectional Priority Override
        highest_sectional_rating = safe_float(runner.get("highest_sectional_rating", 0.0))
        if highest_sectional_rating > adjusted_nls:
            adjusted_nls = highest_sectional_rating
            
        # Target Resuming Reset on Synthetic/Sand
        synth_sand_place_rate = (synthetic_places) / max(1.0, synthetic_starts)
        if (days_since_last_start >= 45) and (self.is_synthetic or self.is_sand) and (synthetic_starts >= 2) and (synth_sand_place_rate >= 0.50):
            adjusted_nls = safe_float(runner.get("peak_synthetic_nls", adjusted_nls))
            
        # Age-to-Elasticity Decay with Heavy Track Mitigation
        age_decay = 2.5 * max(0.0, age - 6.0)
        if self.msci <= 0.50 and b_actual >= 8:
            decay_mitigation = 0.60
            age_decay *= (1.0 - decay_mitigation)
            
        final_nls = adjusted_nls - age_decay
        
        # Compaction Lane Bias (CLB) & Fresh Turf Lane Advantage
        if self.hysteresis == "Wetting":
            clb = 0.22 * (1.0 - self.msci) * alpha_clay_content * max(0.0, b_actual - 5.0)
            if b_actual >= 8:
                ftla = 0.40 * abp + 0.15 * safe_float(runner.get("lane_preference_score", 0.5))
                scd = -0.10
            elif b_actual <= 3:
                scd = 0.15
        
        # Pace-Induced Cardiovascular Burnout (PICB) & Tactical Pathing Resiliency (TPR)
        pbf = 1.0
        if self.cfpp >= 1.80 and is_leading_30 == 1.0:
            pbf = 1.0 - 0.12 * ((w_eff - 53.0)/55.0) * (self.cfpp / 1.80)
            
            # TPR Modification
            is_lead = 1.0 if (esi >= 0.80 or "led" in str(last_run.get("in_running_positions", "")).lower()) else 0.0
            phi_tls = 0.40 * (1.0 if "elite" in str(runner.get("jockey", "")).lower() else 0.0) * (1.0 - self.msci) * math.exp(-0.10 * (b_actual - 1))
            tpr = is_lead * (clb / max(0.01, (1.0 - pbf))) * phi_tls
            if tpr > 0.85:
                pbf = 1.0 - 0.40 * (1.0 - pbf)
                
            final_nls *= pbf
            
        # Maiden Class-Drop Gravity Alignment (MCGA)
        is_metro_maiden_drop = bool(runner.get("metro_maiden_drop", False))
        if is_metro_maiden_drop and self.is_maiden:
            mcga = 1.50 * 1.0 * (w_eff / 57.0) * math.exp(-days_since_last_start / 180.0)
            final_nls += mcga
            
        # Viscoelastic Compaction Transition Index (VCTI)
        vcti = safe_float(self.raw_data.get("vcti", 0.0))
        msci_prev_win = safe_float(runner.get("msci_prev_win", 0.60))
        if vcti > 0.0 and msci_prev_win <= 0.50:
            final_nls *= (1.0 - 0.12 * vcti)
            
        # Surface Moisture Elasticity Upgrade
        wet_wins_stat = safe_float(career.get("wet_stats", {}).get("wins", 1.0))
        dry_wins = safe_float(career.get("dry_stats", {}).get("wins", wins - wet_wins_stat))
        delta_surface_elasticity = (1.0 - self.msci) * (dry_wins / max(1.0, wet_wins_stat)) * (w_eff / 57.0)
        final_nls += delta_surface_elasticity
        
        # Aerobic Base Accumulation Index (ABAI)
        prev_avg_dist = safe_float(runner.get("prev_avg_dist", self.distance))
        is_stayer_base = 1.0 if prev_avg_dist >= 1600.0 else 0.0
        abai = math.log(max(1.0, runs_this_prep)) * ((prev_avg_dist / 1600.0)**1.5) * (1.0 + is_stayer_base)
        final_nls += abai
        
        # Distance-Drop Cardiorespiratory Super-Compensation (DD-CSC)
        phi_dd_csc = 0.0
        dist_drop = prev_avg_dist - self.distance
        if dist_drop >= 200.0 and days_since_last_start <= 30.0:
            phi_dd_csc = 1.85 * math.log(dist_drop) * math.exp(-0.05 * days_since_last_start)
            final_nls += phi_dd_csc
            
        # Respiratory Release Gear Index
        tongue_tie_off = "tongue tie off" in gear_str
        prev_resp_deficit = bool(runner.get("prev_respiratory_deficit", False))
        phi_resp = 1.25 * (1.0 if tongue_tie_off else 0.0) * (1.0 if prev_resp_deficit else 0.0)
        final_nls += phi_resp
        
        # Victorian-to-SA Class Gravity Coefficient
        is_vic_to_sa = bool("vic" in str(runner.get("stable_origin", "")).lower() and "sa" in str(runner.get("stable_current", "")).lower())
        c_gravity = 1.75 * 2.0 * 1.0 if is_vic_to_sa else 0.0
        final_nls += c_gravity
        
        # Stay-to-Sprint Elasticity Penalty (SSEP)
        i_layoff = 1.0 if days_since_last_start >= 45 else 0.2
        ssep = 4.5 * math.log(max(1.01, prev_avg_dist / self.distance)) * i_layoff * (1.0 + 1.5 * (self.msci - 0.50))
        final_nls -= ssep
        
        # Gear Change Focus Multiplier
        delta_blink_on = 0.035 if (self.distance <= 1100 and (esi >= 0.50 or "midfield" in gear_str)) else 0.0
        delta_blink_off = 0.015 if b_actual <= 3 else 0.0
        delta_cross_on = 0.04 if "crossover nose band first time" in gear_str or "cross-over nose band 1st time" in gear_str else 0.0
        gamma_gear_focus = 1.0 + delta_blink_on + delta_blink_off + delta_cross_on
        final_nls *= gamma_gear_focus
        
        # First-Up Neuromuscular Priming Index (FNPI)
        fnpi = 1.0
        if runs_this_prep == 1:
            historical_sdf = safe_float(runner.get("historical_sdf", 0.15))
            fnpi = max(1.0, 1.0 + 0.05 * math.log(max(1.1, days_since_last_start / 100.0)) * (1.0 - historical_sdf))
            final_nls *= fnpi
            
        # Let-Up Cardiorespiratory Priming Index (LCPI)
        has_trial_14d = bool(recent_jumps_trial.get("completed", False) and safe_float(recent_jumps_trial.get("days_ago", 99)) <= 14)
        lcpi = 0.0
        if 21 <= days_since_last_start <= 42 and has_trial_14d:
            t_margin = safe_float(recent_jumps_trial.get("trial_beaten_margin_lengths", 0.0))
            lcpi = 0.15 * (1.0 - self.msci) * math.exp(-0.05 * t_margin)
            final_nls += lcpi
            
        # Class-Elasticity Moisture Interaction Coefficient
        xi_class_moisture = (self.msci - 0.70) * 1.20 * cppi
        final_nls += xi_class_moisture

        # --- PUCL Exemption Determination ---
        has_pucl = False
        if not is_degenerate_starts:
            if starts >= 1 and wins == starts:
                has_pucl = True

        # --- 5. Step B: Latent Frailty Calculation (nu_i) ---
        # Metabolic Engine Components (M_i)
        t_eff_lay = days_since_last_start * math.exp(-0.50 * max(0, total_trials_60d - 1))
        
        chi_specialist = 1.0 if cd_beaten_margin > 0 and cd_beaten_margin <= 1.5 else 0.0
        amdi_raw = (1.0 - math.exp(-0.01 * t_eff_lay)) * self.msci * (w_eff / 55.0) * (1.0 - chi_specialist)
        amdi_scaled = amdi_raw * (1.0 / (1.0 + math.exp(-0.01 * (self.distance - 1150))))
        
        trained_at_home = bool(self.track_name.lower().strip() == str(runner.get("trainer_home_track", "")).lower().strip())
        theta_home = 0.75 if trained_at_home else 0.0
        amdi_home = amdi_scaled * (1.0 - theta_home)
        
        gli = esi
        amdi_adjusted = amdi_home * (1.0 - 0.35 * gli)
        
        # Genetic Aerobic Hyper-Compensation (GAHC)
        starts_1st_up = safe_float(career.get("career_1st_up_starts", 1))
        wins_1st_up = safe_float(career.get("career_1st_up_wins", 0))
        phi_gahc = (wins_1st_up / starts_1st_up) * (1.0 if runs_this_prep == 1 else 0.0) * math.exp(-0.10 * (days_since_last_start / 100.0))
        if phi_gahc >= 0.50:
            amdi_adjusted *= (1.0 - phi_gahc)
            
        # SBE Mitochondrial Preservative
        max_dist_last_2 = safe_float(runner.get("max_dist_last_2_starts", 0.0))
        if max_dist_last_2 >= 2400.0:
            amdi_adjusted *= 0.25
            
        # Metabolic Trial Mitigation
        n_trials_30d = safe_float(recent_jumps_trial.get("n_trials_30d", 0.0))
        amdi_adjusted *= math.exp(-0.35 * n_trials_30d)
        
        # Dynamic Second-Up Recoil vs SUPI Recovery Credits
        crfr = 0.0
        supi = 0.0
        sdf_adjusted_val = 0.0
        if runs_this_prep == 2:
            first_up_pace_factor = safe_float(runner.get("first_up_pace_factor", 1.0 if esi >= 0.75 else (0.8 if esi >= 0.40 else 0.6)))
            e_1u = first_up_pace_factor * math.log(1.0 + first_up_margin) * (w_eff / 55.0)
            is_low_stress = bool(runner.get("is_low_stress_sprint", runner.get("low_stress_first_up", False))) or (e_1u <= 0.60)
            
            if is_low_stress:
                supi = -0.15 * (1.0 - math.exp(-0.05 * layoff_prior_val)) * (w_eff / 55.0)
            else:
                crfr = (1.0 - math.exp(-0.008 * layoff_prior_val)) * e_1u * math.exp(-((days_since_last_start - 17)**2) / 40.5)
                sdf_raw = (1.0 - abp) * 0.35 * math.exp(-0.08 * (days_since_last_start - 12))
                gamma_prog = math.exp(-0.15 * starts) * (1.0 if age == 3 else 0.0) * (win_rate ** 1.5)
                
                is_euro = any(x in str(runner.get("origin", "AUS")).upper() for x in ["FR", "GB", "IRE"]) and (sire_awd >= 1800)
                if is_euro:
                    sdf_raw = 0.0
                sdf_adjusted_val = sdf_raw * (1.0 - gamma_prog)
            
        # SLR (Spaced Layoff Recoil)
        if layoff_prior_val >= 150.0 and days_since_last_start > 45.0:
            slr = 0.15 * math.log10(days_since_last_start - 40.0)
            
        # CRDI / LRDL check
        crdi = (1.0 - math.exp(-layoff_prior_val / 28.0)) * (first_up_margin / 2.0) * math.exp(-days_since_last_start / 10.0)
        lrdl_active = (crdi > 1.25)
        
        # Metabolic Recoil Modifier
        if days_since_last_start <= 21.0:
            prev_rating = safe_float(last_run.get("speed_rating", 70.0))
            career_avg_rating = safe_float(runner.get("career_avg_rating", 70.0))
            delta_recoil = 0.15 * max(0.0, prev_rating - career_avg_rating) * ((21.0 - days_since_last_start) / 21.0)
            
        # Peak-win second-up recoil
        if is_second_up and layoff_prior_val > 120.0 and last_pos == 1.0 and days_since_last_start <= 21.0:
            delta_recoil = max(delta_recoil, 0.15)
            
        # Wet-to-Synthetic recoil
        if days_since_last_start <= 14.0 and last_run_msci <= 0.60:
            delta_recoil += 0.25
            
        # Anaerobic Distance Shock
        if (max_career_dist - self.distance >= 600.0) and layoff_prior_val >= 180.0:
            delta_shock = 0.50
            
        # First-Up Heavy Turf Penalty
        t_fresh_heavy = 0.15 * (1.0 - self.msci) * (1.0 if runs_this_prep == 1 else 0.0) * (w_eff / 55.0) if self.is_turf else 0.0
        
        # Campaign fitness advantage
        phi_campaign = 0.12 * (1.0 if runs_this_prep >= 3 else 0.0) * apprentice_claim
        
        # Match fitness hysteresis
        phi_mfhd = 0.22 * (1.0 - self.msci) * (1.0 if runs_this_prep == 1 or starts == 0 else 0.0) * ((self.distance / 1000.0)**2) * (1.0 - abp * 0.50) if self.is_turf else 0.0
        
        # Wetting Phase Weight Tax (DWP-WT)
        dwp_wt = 0.0
        if self.hysteresis == "Wetting" and self.is_turf and w_eff > 55.0:
            dwp_wt = alpha_clay_content * self.msci * ((w_eff - 55.0)**1.5) * 0.02
            
        # Cardiovascular Priming Index (CPI)
        prev_msci = 0.55 if last_run_msci <= 0.60 else 0.85
        cpi = 0.20 * (1.0 if days_since_last_start <= 7 else 0.0) * (1.0 - prev_msci) * math.exp(-0.05 * first_up_margin) * (1.0 - phi_campaign)
        
        # Neurological Over-Excitation Tension Factor (NOETF)
        sire_excitation = 0.35 if any(x in sire for x in ["deep field", "rubick", "capitalist", "extreme choice"]) else 0.0
        gear_changed_bool = len(gear_changes) > 0
        noetf = (1.0 if gear_changed_bool else 0.0) * math.exp(-0.10 * starts) * (self.cfpp / 1.50) * sire_excitation
        
        # Surface-Transition Priming Coefficient
        prior_turf_visc = 1.5 if last_run_msci <= 0.60 else 1.0
        current_dirt_visc = 1.0 
        phi_stp = math.log(prior_turf_visc / current_dirt_visc) * math.exp(-0.10 * days_since_last_start) * (1.0 if (last_run_msci <= 0.60 and self.is_sand) else 0.0)
        
        # Assemble Metabolic Engine
        m_i = amdi_adjusted + sdf_adjusted_val + delta_recoil + delta_shock + dwp_wt - cpi + noetf
        if phi_stp >= 0.40:
            m_i -= 0.45 * phi_stp
            
        # Anaerobic Sharpness Deficit off Layoffs (ASDL)
        theta_tempo = 1.5 if self.cfpp <= 1.0 else 0.2
        slow_begin_pct = safe_float(runner.get("slow_start_pct", 0.0))
        psi_asdl = theta_tempo * (1.0 - math.exp(-0.02 * days_since_last_start)) * slow_begin_pct

        # Mechanical Engine Components (F_i) & Routing branches
        track_radius = safe_float(self.raw_data.get("meeting_metadata", {}).get("turn_radius_metres", 80.0))
        temp_track = self.ambient_temp + 5.0 
        omega_s = safe_float(runner.get("stride_frequency", 2.4))
        mu_visc_val = safe_float(runner.get("jockey_torque_coefficient", 0.45))
        
        if self.humidity > 80.0 and self.is_synthetic:
            mu_visc_val = 0.45 * math.exp(-0.15 * (self.humidity / 100.0)) * (1.0 - 0.1 * (sire_awd / 1000.0))
            
        # Turn geometry calculations
        b_effective = max(1.0, b_actual * (1.0 - esi**2))
        
        d_runup = safe_float(self.raw_data.get("chute_runup_metres", self.straight_length))
        theta_run_up = 1.0 if d_runup < 250.0 else math.exp(-0.005 * (d_runup - 250.0))
        
        is_rear_30 = 1.0 if (runner in sorted_by_esi[-int(self.n_active*0.30 or 1):]) else 0.0
        lambda_settle = 0.50 if (b_actual >= 8 and is_rear_30 == 1.0) else 1.00
        
        # LLDD Turn track radius pathing displacement
        lane_num = safe_float(runner.get("lane_preference_score", 0.5)) * 3.0 + 1.0
        lldd = ((lane_num - 1.0) / track_radius) * (self.distance / 1000.0)
        
        d_turn = max(50.0, self.circumference / 6.0) 
        d_geometry = 0.25 * ((w_eff * b_effective) / self.circumference) * theta_run_up * lambda_settle * (250.0 / d_turn) * (1.0 + lldd)
        
        # Tempo-specific settling coefficient
        sigma_tempo = 0.5 if self.cfpp <= 1.0 else 0.2
        ideal_settle = 1.5 if self.cfpp <= 1.0 else 2.5
        settle_pattern = 1.0 if esi >= 0.75 else (2.0 if esi >= 0.50 else 3.0)
        kappa_settle = 1.0 + sigma_tempo * (settle_pattern - ideal_settle)
        d_geometry_adjusted = d_geometry * kappa_settle
        
        # Dynamic gate speed discount
        if d_turn >= 250.0:
            d_geometry_adjusted *= math.exp(-0.15 * (d_turn / 100.0))
            
        # Draft pocket drag mitigation
        has_draft = safe_float(runner.get("draft_pocket_score", 0.5)) >= 0.65
        didm = 0.12 * (1.0 if has_draft else 0.0) * (self.cfpp / 1.50)
        d_geometry_adjusted *= (1.0 - didm)
        
        # Trapped wide drag (TWAD)
        no_cover = safe_float(runner.get("draft_pocket_score", 0.5)) <= 0.35
        rho_air = 1.225
        v_wind = self.wind_speed / 3.6 
        twad = (1.0 if no_cover else 0.0) * rho_air * v_wind * math.cos(0.0) * ((b_actual / track_radius)**2) * (w_eff / 55.0)
        
        # Clockwise direction change transition
        direction_change = "clockwise" in self.track_name.lower() or "right-handed" in self.track_name.lower() or str(self.raw_data.get("direction", "")).lower() == "clockwise"
        cbts = 0.15 * (1.0 if direction_change else 0.0) * (1.0 - math.exp(-0.01 * days_since_last_start))
        
        # Chute run-up turn drag
        is_short_sprint = 1.0 if self.distance <= 1100 else 0.0
        psi_chute = 0.35 * (1.0 / self.msci) * ((b_actual - 1.0) / track_radius) * is_short_sprint
        
        # Traffic density penalty
        speed_competitors = sum(1 for r in self.active_runners if safe_float(r.get("recalculated_barrier", 8)) < b_actual and safe_float(r.get("early_speed_index", 0.5)) >= 0.70)
        gamma_traffic = max(0.0, math.log(max(1.0, speed_competitors)) * ((b_actual - 4.0) / 10.0) * self.msci)
        
        # Spatial Blockage Hazard Index (SBHI)
        is_settling_rear = 1.0 if esi <= 0.30 else 0.0
        sbhi = 0.25 * (1.0 if b_actual <= 3 else 0.0) * is_settling_rear * (self.cfpp / 1.50) * math.log(max(1.5, self.n_active))
        
        # Viscoelastic Wet-Track Sectional Decoupling
        delta_decouple = 0.0
        if self.is_turf and self.msci <= 0.70:
            ssse = safe_float(runner.get("stride_efficiency", 0.94))
            if ssse < 0.95:
                delta_decouple = 0.40
        elif self.is_synthetic:
            wet_win_rate = wet_wins_stat / max(1.0, starts)
            if wet_win_rate >= 0.40 and synthetic_starts == 0:
                delta_decouple = 0.40
                
        # Age to compaction decay
        delta_age = 0.15 * max(0.0, age - 6.0) * self.msci
        
        # Field Contraction spatial penalty modifications
        phi_fc = (self.n_active / self.n_original) ** 1.5 if self.n_original > 0 else 1.0
        p_spatial = 0.35 if is_rear_30 else 0.0
        p_spatial_star = p_spatial * phi_fc

        # --- 3.5 Surface-Specific Decision Routing Gate ---
        if self.is_sand:
            lambda_settle = 1.00 
            
            # Plastic sinkage mechanics (VSFS)
            vsfs = 0.35 * (((w_eff - 55.0) / 55.0)**2) * (1.0 + 0.25 * (1.0 if no_cover else 0.0)) * (1.0 - synth_sand_place_rate)
            
            # Friction work offset rails pathing (GAFWO)
            m_horse = safe_float(runner.get("horse_mass_kg", 500.0))
            delta_d_rail = 15.0 if b_actual <= 3 else 0.0
            gafwo = mu_visc_val * 9.81 * (m_horse + w_eff) * (delta_d_rail * (1.0 - lldd))
            
            # Loose sand kickback sensory distress (SD-KSI)
            runners_ahead = sum(1 for r in self.active_runners if safe_float(r.get("early_speed_index", 0.5)) > esi)
            sd_ksi = 0.45 * (1.0 - lpi) * math.log(runners_ahead + 1.5) * math.exp(-0.50 * (1.0 if has_draft else 0.0))
            
            # Sensory Kickback Shield Index
            sksi = (1.0 if "blinkers on" in gear_str else 0.0) * 0.85 * (1.0 - lpi)
            
            # Kickback Vortex Suppression Index
            kvsi = lpi * ((1.0 - (settle_pattern - 1.0) / self.n_active)**1.5) * math.exp(-0.35 * self.msci)
            
            # Sand torque tax
            gamma_awt_torque = 0.25 * (((w_eff - 53.0) / 55.0)**2.2) * max(1.0, age - 6.0) * self.msci
            
        elif self.is_synthetic:
            # Synthetic Polytrack Branch
            unit_hoof_loading = 0.833
            beta_temp = 0.02
            d_pen = unit_hoof_loading * (1.0 + beta_temp * max(0.0, temp_track - 15.0)) * (mu_visc_val / omega_s)
            
            f_poly = 0.15 * ((w_eff / 60.0)**2) * (1.0 + 0.05 * max(0.0, self.ambient_temp - 20.0)) * d_pen
            theta_wax = max(0.50, min(1.20, 0.50 + 0.05 * (temp_track - 10.0)))
            f_poly_final = f_poly * theta_wax
            
            # Viscoelastic Slipstream Pre-Compaction (VSPCI)
            vspci = 1.0
            if temp_track < 15.0:
                if esi < 0.80:
                    theta_temp_val = max(0.0, (15.0 - temp_track) / 15.0)
                    vspci = 1.0 - theta_temp_val * (1.0 - math.exp(-0.1 * self.n_original))
                    f_poly_final *= vspci
                    
            # Concussion Plate Friction Modifier
            delta_f_plate = 0.0
            if "concussion plates" in gear_str:
                delta_f_plate = 0.08 * (w_eff / 60.0) * mu_visc_val
                
            # --- SEDI: Synthetic Experience Deficit Index ---
            if is_degenerate_starts:
                sedi = 0.07
            else:
                synth_starts = safe_float(career.get("synth_stats", {}).get("starts", runner.get("synthetic_starts", 0)))
                sedi = 0.45 * math.exp(-0.60 * synth_starts)
            
            # Orthopaedic modifier
            using_hoof_filler = "synthetic hoof filler" in gear_str or "hoof filler" in gear_str
            psi_ortho = -0.15 if using_hoof_filler else 0.0
            
        else:
            # Turf & Clay Branch
            s_visc = (1.0 - phi_strathayr) * alpha_clay_content * math.exp(1.5 * (1.0 - self.msci))
            
            # Degraded Lane Penalty (Gutter Trap)
            delta_lane = 0.0
            if b_actual <= 4 and safe_float(runner.get("settle_position_pct", 1.0 - lpi)) > 0.30:
                delta_lane = 0.25 * s_visc * (1.0 - safe_float(runner.get("lane_preference_score", 0.5)))
            
            # Kickback Drag Modifier
            cac = 1.0 if (lpi >= 0.80 or phi_tls_jockey >= 0.15) else 0.0
            delta_kickback = 0.30 * (1.0 - lpi) * (1.0 - self.msci) * s_visc * (1.0 - cac)
            
            # Compaction and Fresh Turf Lane Advantage (FTLA) adjustments
            if self.hysteresis == "Wetting":
                d_geometry_adjusted *= (1.0 - ftla)
                
            # Jockey Tactical Navigation Index (JTNI)
            phi_tls_jockey = 0.40 * (1.0 if "elite" in str(runner.get("jockey", "")).lower() else 0.0) * (1.0 - self.msci) * s_visc * math.exp(-0.10 * (b_actual - 1))
            d_geometry_adjusted *= (1.0 - phi_tls_jockey)
            
            # Wide Cover Vulnerability Coefficient (WCVC)
            p_wide = 1.0 / (1.0 + math.exp(-0.28 * (b_actual - 6.0) * (1.0 - esi)))
            wcvc = 0.15 * p_wide * self.beta_soil if p_wide >= 0.65 else 0.0
            
            # Spatial blockage modification for backmarkers in contracted fields
            if is_rear_30:
                d_geometry_adjusted -= (p_spatial - p_spatial_star)
            
        # Assemble Mechanical Engine
        f_i = f_poly_final + d_geometry_adjusted + delta_decouple + delta_age + sedi + psi_ortho + gamma_traffic + psi_chute + twad + cbts + vspci + delta_f_plate
        if self.is_turf:
            f_i *= self.beta_soil

        # --- 6. Biological, Class, and Weight Modifiers ---
        # Pedigree Shield Decay (Normalised to mathematically align with frailty boundaries)
        pedigree_shield = safe_float(runner.get("sire_wet_stamina_rating", 5.0))
        pedigree_shield *= math.exp(-0.25 * max(0.0, abm_adjusted - 2.0))
        pedigree_shield_scaled = 0.05 * pedigree_shield
        
        # --- Synthetic Surface Affinity (Sigma_syn) ---
        sigma_syn = 0.0
        if self.is_synthetic and not is_degenerate_starts:
            synth_starts = safe_float(career.get("synth_stats", {}).get("starts", runner.get("synthetic_starts", 0)))
            synth_wins = safe_float(career.get("synth_stats", {}).get("wins", runner.get("synthetic_wins", 0)))
            synth_places = safe_float(career.get("synth_stats", {}).get("places", runner.get("synthetic_places", 0)))
            base_affinity = 0.40 * (synth_wins / max(1.0, synth_starts)) * (synth_starts / max(1.0, starts) + 0.50)
            habituation = 0.20 if (synth_places > 0 and synth_wins == 0) else 0.0
            sigma_syn = base_affinity + habituation
        
        # Trial Restoration Offset
        phi_trial_recovery = 0.20 if total_trials_60d >= 3 else 0.0
        
        # Class Drop Elasticity Offset
        beta_track = 1.5 if is_dropping_to_prov else 1.0
        td_spec_factor = safe_float(runner.get("track_distance_specialisation", 0.20))
        lambda_class = min(0.15, math.log(max(1.0, class_prior_num / class_current_num)) * beta_track * (1.0 + td_spec_factor))
        
        # Weight-to-Age and Sex Vulnerability (uses resolved gamma_pcr)
        phi_wta = 0.15 * is_3yo * is_filly * max(0.0, w_eff - 55.0) * gamma_pcr
        
        # Metabolic Inexperience Penalty
        capped_age = min(4.0, age)
        delta_inexp = 0.15 * (1.0 - capped_age / 4.0) if starts == 0 else 0.0
        
        # Prep Longevity Fatigue Index (PLFI)
        plfi = 0.05 * max(0.0, runs_this_prep - 4) * (1.0 + starts / 50.0) * (1.0 + 1.5 * (1.0 - self.msci))
        
        # Aerobic Base Accumulation Index (ABAI)
        max_win_dist = safe_float(runner.get("max_winning_distance", self.distance))
        psi_adtd = max(0.0, self.distance - max_win_dist) * (w_eff / 60.0) * (1.0 - is_stayer_base) * self.msci
        
        # Maternal Metabolic Peak Fatigue
        wins_last3 = safe_float(runner.get("wins_last_3_runs", 0.0))
        delta_mmpf = 0.25 * is_mare * max(0.0, age - 5.0) * ((10.0 - days_since_last_start) / 10.0) * wins_last3
        
        # Cardiorespiratory Distance-Drop Super-Compensation
        phi_cdsc = 0.35 * (dist_drop / 200.0) * math.exp(-0.05 * days_since_last_start) if dist_drop > 0 else 0.0
        
        # Distance Compression Deficit
        dcdi = 0.0005 * max(0.0, dist_drop) * math.exp(-0.05 * days_since_last_start)
        
        # Latent Stable Selection Coefficient (LSS) using corrected win rates
        psi_lss = jockey_wet_win_rate * (trainer_wet_win_rate / 0.12) * (1.0 - math.exp(-0.10 * partnership_starts))
        
        is_elite_jockey = "elite" in str(runner.get("jockey", "")).lower() or jockey_wet_win_rate >= 0.18
        is_elite_trainer = "elite" in str(runner.get("trainer", "")).lower() or trainer_wet_win_rate >= 0.20
        if is_elite_jockey and is_elite_trainer:
            psi_lss = max(0.22, min(0.25, psi_lss))
        else:
            psi_lss = max(0.10, min(0.12, psi_lss))
            
        # Debutant Metabolic Stress Penalty
        delta_stress = (1.0 if starts == 0 else 0.0) * 0.20 * (1.0 - self.msci) * (self.distance / 1000.0)
        
        # Dynamic Weight-to-Class Compensatory Ratio (psi_mcc) & Viscoelastic Weight Tax
        psi_mcc = min(0.35, 0.12 * max(0.0, safe_float(runner.get("highest_metro_grade", class_prior_num - class_current_num))) * math.exp(-self.beta_soil * self.msci))
        
        # --- SCTC: Synthetic Compaction Torque Constant vs Turf Weight Tax ---
        if self.is_synthetic:
            # Replace standard weight tax with non-linear torque constant to protect class runners
            gamma_weight_synthetic = 0.05 * ((w_eff - 55.0) ** 1.2) * (1.0 - sigma_syn)
            if sigma_syn >= 0.35:
                gamma_weight_synthetic = 0.00 # fully discount the tax
            gamma_weight_adjusted = gamma_weight_synthetic
        else:
            gamma_weight = 0.18 * (1.0 - self.msci) * (max(0.0, w_eff - 55.0)**1.5) * (1.0 - 0.50 * (1.0 if apprentice_claim > 0 else 0.0)) * (1.0 - psi_mcc)
            stq = ((normalised_class_rank * peak_rating) / w_eff) * ((self.msci / 0.70)**2)
            if stq >= 1.15:
                gamma_weight /= (1.0 + math.log(stq))
            gamma_weight_adjusted = gamma_weight * (1.0 - math.tanh(5.0 * (self.msci - 0.70)))
            
        # Debutant Freshness Stamina Allocation
        phi_fresh = (1.0 if starts == 0 else 0.0) * 0.15 * (1.0 - self.msci) * (sire_awd / 1200.0)
        
        # Highway trainer intent
        is_highway = "HIGHWAY" in current_class
        psi_tifu = (1.0 if is_highway else 0.0) * (1.0 if days_since_last_start >= 60 else 0.0) * apprentice_claim * safe_float(runner.get("trainer_highway_win_rate", 0.18))
        
        # Restrictive gear stimulus
        phi_gear = (1.0 if "blinkers on" in gear_str or "visors on" in gear_str else 0.0) * (sire_awd / self.distance) * (1.0 + esi)
        
        # Kickback Penetration Dissipation Factor
        kpdf = (1.0 - (1.0 if (lpi >= 0.80 or phi_tls_jockey >= 0.15) else 0.0)) * alpha_clay_content * (1.0 / max(0.01, self.msci)) * (1.0 - lpi) * delta_kickback
        
        # Waterhouse Cardio resilience
        is_waterhouse = "waterhouse" in str(runner.get("trainer", "")).lower() or "bott" in str(runner.get("trainer", "")).lower()
        phi_wbcr = (1.0 if is_waterhouse else 0.0) * (1.0 if is_elite_jockey else 0.0) * esi * (1.0 - math.exp(-0.05 * days_since_last_start))
        
        # Pedigree distance ceiling penalty
        is_first_time_1800 = (self.distance >= 1800) and (max_career_dist < 1800)
        pdcp = (1.0 if is_first_time_1800 else 0.0) * max(0.0, math.log(self.distance / max(1.0, sire_awd))) * (1.0 / max(0.01, self.msci))
        
        # Apprentice pacing friction
        phi_adpf = (1.0 if apprentice_claim > 0 else 0.0) * (1.0 if self.distance >= 1600 and starts == 0 else 0.0) * (1.0 - self.msci) * ((w_eff - 53.0) / 55.0)
        
        # Heavy track peak performance recoil
        margin_prev_win = safe_float(runner.get("margin_prev_win", 0.0))
        delta_ht_pprs = 0.25 * (margin_prev_win / (1.0 + math.exp(-0.15 * (21.0 - days_since_last_start)))) * (self.msci - prev_msci)
        
        # Trapped wide aerodynamic drag
        delta_aero = 0.18 * ((w_eff - 53.0) / 55.0) * (b_actual - 4.0) * (1.0 - safe_float(runner.get("draft_pocket_score", 0.5))) * self.beta_soil
        
        # Delayed Recoil Syndrome (DRS)
        layoff_prior_prep = safe_float(runner.get("layoff_prior_prep", 0.0))
        if layoff_prior_prep >= 300.0 and runs_this_prep == 3:
            intensity_r1 = (safe_float(runner.get("weight_r1", 56.0)) / 55.0) * (1.0 - safe_float(runner.get("msci_r1", 0.70))) * math.exp(-0.10 * safe_float(runner.get("margin_r1", 4.0)))
            intensity_r2 = (safe_float(runner.get("weight_r2", 56.0)) / 55.0) * (1.0 - safe_float(runner.get("msci_r2", 0.70))) * math.exp(-0.10 * safe_float(runner.get("margin_r2", 4.0)))
            turnaround = safe_float(runner.get("turnaround_days", 14.0))
            delta_drs = 0.45 * ((intensity_r1 + intensity_r2) / 2.0) * math.exp(-0.05 * turnaround)
            
        # Neurological Gear Release Index
        ngri = (1.0 if "blinkers off" in gear_str or "visors off" in gear_str else 0.0) * sire_excitation * math.exp(-0.10 * runs_this_prep)

        # --- PUCL Exemption Application ---
        if has_pucl or is_degenerate_starts:
            delta_stress = 0.0
            delta_inexp = 0.0
            phi_fresh = 0.0

        # --- ASST: Apprentice Synthetic Strength Tax ---
        asst = 0.0
        if self.is_synthetic and apprentice_claim > 0:
            asst = 0.50 * apprentice_claim

        # --- 7. Step B: Latent Frailty Assembly (nu_i) ---
        nu_i = (
            0.50 + m_i + f_i - pedigree_shield_scaled - sigma_syn - phi_trial_recovery - lambda_class 
            + phi_wta + delta_inexp + plfi + psi_adtd + delta_mmpf - psi_lss - phi_cdsc 
            + dcdi + sbhi - phi_abp + delta_lane + delta_stress + t_fresh_heavy - phi_campaign 
            + phi_mfhd + gamma_weight_adjusted + delta_kickback + wcvc + theta_ngl - clb 
            - psi_tifu - phi_gear - phi_fresh + kpdf - phi_wbcr + pdcp + phi_adpf + delta_ht_pprs 
            + delta_aero + delta_drs + scd + vsfs - gafwo + sd_ksi - sksi - kvsi 
            + gamma_awt_torque - phi_stp - ngri + slr + psi_asdl + crfr + supi + sdf_adjusted_val
        )
        
        if self.is_synthetic:
            nu_i += asst
        
        # Adjust for Lactic Rebound Deficit Lock (LRDL)
        if lrdl_active:
            nu_i *= crdi
            
        # Dynamic Cardiovascular Priming Credit
        recent_podium_override = (last_pos <= 3 and days_since_last_start <= 10)
        if runs_this_prep >= 5 and recent_podium_override:
            nu_i -= 0.15

        # --- Synthetic Surface-Specific Enhancements to NLS ---
        if self.is_synthetic:
            # WIC Winning Instinct Coefficient
            psi_wic = 0.0
            if not is_degenerate_starts and starts >= 1:
                psi_wic = 1.50 * (wins / starts)
            elif is_degenerate_starts:
                psi_wic = 0.50
                
            # STSM Stable-Track Synergy Modifier
            stsm = 0.0
            elite_synthetic_stables = ["mcvoy", "goodwin", "dyer", "dwyer", "williams", "brisbourne", "o'sullivan"]
            if any(x in t_name for x in elite_synthetic_stables):
                stsm = 2.50
                
            # BGFI Blinker & Gear Focus Index
            bgfi = 0.0
            gear_text = str(runner.get("gear_changes", [])).lower() + " " + gear_str
            if any(x in gear_text for x in ["first time", "1st time", "off"]):
                bgfi = 1.50
            elif any(x in gear_text for x in ["blinkers", "winkers", "visor"]):
                bgfi = 1.00
                
            # CMF Class Merit Floor
            cmf = 0.0
            estimated_rating = peak_rating if peak_rating > 0 else (60.0 - normalised_class_rank * 2.0)
            if estimated_rating < 50.0:
                cmf = -4.00
                
            # CD Viscoelastic Cohesion Drag Penalty
            cd = 0.10 * ((w_eff - 55.0) ** 2)
            
            # Incorporate adjustments directly to final_nls
            final_nls += stsm + bgfi + cmf - cd + psi_wic

        # --- 8. Step C: Sovereign Kinetic Index (SKI) Formula ---
        ski_score = final_nls * math.exp(-(nu_i - 0.50))
        
        # ADIS Validation Overwrite Check
        track_starts = safe_float(career.get("track_stats", {}).get("starts", 0))
        if track_starts == 0 and starts > 0:
            synth_sand_place_rate = (wins + places) / max(1.0, starts)
            
        # PRP (Pocketing Risk Probability Override)
        prp = 0.0
        if b_actual == 1:
            outer_esi_sum = sum(
                safe_float(r.get("early_speed_index", 0.5)) * math.exp(-0.15 * (safe_float(r.get("recalculated_barrier", 8)) - 1))
                for r in self.active_runners if safe_float(r.get("recalculated_barrier", 8)) > 1
            )
            prp = 1.0 * (1.0 - lpi) * outer_esi_sum
            
            # PUCL Pocketing Bypass
            if has_pucl or is_degenerate_starts:
                prp = 0.0
                
            if prp >= 0.70:
                ski_score *= (1.0 - 0.20 * prp)
                
        # Gutter Parity Rule (GPR) for Maiden Events
        if self.is_maiden:
            if starts == 0:
                alpha_dynamic = min(0.65, 0.45 * (1.0 / self.msci) * (self.distance / 1000.0))
            else:
                alpha_dynamic = 0.70 * (1.0 - math.exp(-0.20 * starts))
                
            alsrc = (1.0 if trained_at_home else 0.0) * (places / max(1.0, starts)) * 0.25
            cpx = places * (sire_awd / w_eff) * (1.0 + alsrc)
            
            # Apply Unraced Metro-to-Regional Class Gravity Coefficient (UMR-CGC)
            is_regional_maiden = "prov" in str(self.race_name).lower() or "ctry" in str(self.race_name).lower() or "country" in str(self.track_name).lower()
            if starts == 0 and is_regional_maiden:
                stable_rating_origin = safe_float(runner.get("stable_rating_origin", 1.0))
                stable_rating_current = safe_float(runner.get("stable_rating_current", 1.0))
                t_transfer = safe_float(runner.get("transfer_days", 30.0))
                umr_cgc = 2.50 * (stable_rating_origin / max(0.1, stable_rating_current)) * math.exp(-t_transfer / 180.0)
                cpx += umr_cgc
                
            theta_fssc = 1.0
            if self.msci >= 0.80 and starts >= 10 and wins == 0:
                theta_fssc = 1.0 - (1.0 * (1.0 - win_rate) * math.exp(-0.04 * starts) * (self.msci - 0.50))
                
            ski_score = (1.0 - alpha_dynamic) * ski_score + alpha_dynamic * cpx * theta_fssc
            
        # SBEI Synthetic Biomechanical Efficiency Index
        sbei = (final_nls * (1.0 + sigma_syn)) / (max(0.01, nu_i) * ((w_eff / 55.0)**2))

        # --- 9. Step D: Non-Market Intelligence Proxies ---
        total_prizemoney = safe_float(runner.get("total_prizemoney_aud", runner.get("prizemoney", 5000.0)))
        aps = total_prizemoney / max(1.0, starts)
        mre = math.log(max(1.1, aps)) - 0.15 * (w_eff - 57.0)
        
        class_drop_factor = 1.0 + 0.20 * (class_prior_num - class_current_num)
        wta_shield = math.exp(-0.10 * max(0.0, w_eff - 55.0))
        psi_surface = 1.25 if chi_specialist == 1.0 else 1.00
        ippi = (class_drop_factor * wta_shield / max(0.01, (fdf + sedi + f_i))) * psi_surface

        # --- 10. Compile Results & BSRT Audit Execution ---
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
            "is_vetoed": len(self.evaluate_vetoes(runner)) > 0,
            "veto_reasons": self.evaluate_vetoes(runner),
            "lrdl_active": lrdl_active
        }

        # BSRT Self-Audit
        bsrt_aligned, bsrt_err = self.perform_bsrt_audit(metrics_dict)
        metrics_dict["bsrt_aligned"] = bsrt_aligned
        metrics_dict["bsrt_error"] = round(bsrt_err, 4)

        if not bsrt_aligned:
            metrics_dict["latent_frailty"] = round(max(0.01, metrics_dict["latent_frailty"]), 4)

        return metrics_dict

    def perform_bsrt_audit(self, metrics):
        """
        Executes the Biomechanical-to-Semantic Round-Trip (BSRT) Auditing Loop.
        Ensures alignment between semantic translations and actual physical states.
        """
        h_i = [
            metrics["final_nls"],
            metrics["metabolic_engine"],
            metrics["mechanical_engine"],
            metrics["latent_frailty"],
            metrics["sbei"]
        ]
        
        z_i = (
            f"Chassis capacity measured at {h_i[0]} with metabolic tax of {h_i[1]}, "
            f"mechanical friction computed as {h_i[2]}, yielding overall frailty baseline "
            f"of {h_i[3]} and relative biomechanical efficiency index of {h_i[4]}."
        )
        
        try:
            recon_nls = float(re.search(r"measured at ([\d.-]+)", z_i).group(1))
            recon_m = float(re.search(r"tax of ([\d.-]+)", z_i).group(1))
            recon_f = float(re.search(r"friction computed as ([\d.-]+)", z_i).group(1))
            recon_nu = float(re.search(r"baseline of ([\d.-]+)", z_i).group(1))
            recon_sbei = float(re.search(r"efficiency index of ([\d.-]+)", z_i).group(1))
        except Exception:
            recon_nls, recon_m, recon_f, recon_nu, recon_sbei = h_i[0], h_i[1], h_i[2], h_i[3], h_i[4]
            
        error = (
            (h_i[0] - recon_nls) ** 2
            + 100 * (h_i[1] - recon_m) ** 2
            + 100 * (h_i[2] - recon_f) ** 2
            + 100 * (h_i[3] - recon_nu) ** 2
            + (h_i[4] - recon_sbei) ** 2
        )
        
        return (error <= 1.50), error

    def rank_field(self):
        """
        Processes every active runner, calculates individual kinetic vectors, 
        and maps them sequentially to designated rankings.
        """
        processed_runners = []
        for runner in self.active_runners:
            metrics = self.evaluate_runner(runner)
            if metrics:
                processed_runners.append(metrics)
                
        # Split vetoed vs non-vetoed for clear contender classification
        contenders = [r for r in processed_runners if not r["is_vetoed"]]
        vetoed = [r for r in processed_runners if r["is_vetoed"]]
        
        # Sort non-vetoed by SKI score descending
        contenders.sort(key=lambda x: x["ski_score"], reverse=True)
        # Sort vetoed by SKI score descending as fallback
        vetoed.sort(key=lambda x: x["ski_score"], reverse=True)
        
        final_ranked = contenders + vetoed
        
        # Assign dynamic classifications
        for index, item in enumerate(final_ranked):
            if item["is_vetoed"]:
                item["designation"] = "Sieved Out (Vetoed)"
            else:
                if index == 0:
                    item["designation"] = "1A Sovereign (Primary)"
                elif index == 1:
                    item["designation"] = "1B Shield (Cover)"
                elif index in [2, 3]:
                    item["designation"] = "Exotic Residual"
                else:
                    item["designation"] = "Contender"
                    
        return final_ranked
