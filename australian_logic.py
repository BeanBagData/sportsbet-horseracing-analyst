import os
import re
import math
import json
import datetime
import random

# --- Configuration ---
WEIGHTS_FILE = os.path.join("storage", "biomechanical_weights.json")

# --- Defensive Parsing Helpers ---
def safe_int(val, default=0):
    if val is None: return default
    try: return int(float(val))
    except Exception: return default

def safe_float(val, default=0.0):
    if val is None: return default
    try: return float(val)
    except Exception: return default

def sanitize_path_name(name):
    if not name: return "Unknown"
    keep = [" ", "-", "_"]
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip()
    return cleaned.replace(" ", "_")


# =====================================================================
#          PROGRAMMATIC TEXT-TO-NUMBER VECTORIZER (No Semantics)
# =====================================================================

class BiomechanicalTextVectorizer:
    """
    Transforms unstructured textual representations into pure numeric coordinates.
    All semantic expressions are ignored. Hashing maps characters deterministically.
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
        if "MDN" in name or "MAIDEN" in name or "MPLTE" in name:
            return 1.0
        elif any(x in name for x in ["GROUP", "GP", "G1", "G2", "G3", "LISTED", "LR", "CUP", "STAKES", "OPEN", "BM82"]):
            return 3.0
        return 2.0


# =====================================================================
#      SUPERVISED PARAMETER OPTIMIZATION SYSTEM (LoRA Adaptor v1.0)
# =====================================================================

class BiomechanicalOptimizer:
    """
    Supervised Parameter Optimization via Low-Rank Adaptation (LoRA).
    Factorizes silo updates into Delta W = B * A to prevent over-fitting,
    retaining pre-trained baseline integrity W_0 while learning on new data.
    """
    _cached_training_records = None
    _cached_silo_weights = {}
    _cached_weights_data = None  # Hot cache for the weights JSON dictionary

    @classmethod
    def clear_cache(cls):
        cls._cached_training_records = None
        cls._cached_silo_weights.clear()
        cls._cached_weights_data = None  # Clear hot cache on calibration runs

    @classmethod
    def _get_default_weights_for_surface(cls, surface_type):
        if surface_type == "Synthetic":
            return [60.0, 1.5, 0.85, 1.0, 8.5, 1.5]
        elif surface_type == "Turf_Wet":
            return [60.0, 1.5, 1.35, 1.0, 8.5, 1.5]
        else:
            return [60.0, 1.3, 0.65, 1.0, 8.5, 1.5]

    @classmethod
    def load_calibrated_weights(cls):
        # Return directly from memory if already parsed
        if cls._cached_weights_data is not None:
            return cls._cached_weights_data

        defaults = {
            "historical_races_trained": 0,
            "trained_race_files": [],
            "A": [
                [random.uniform(-0.5, 0.5) for _ in range(6)]
                for _ in range(2)  # Rank r = 2
            ],
            "B": {}
        }
        if os.path.exists(WEIGHTS_FILE):
            try:
                with open(WEIGHTS_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if "trained_race_files" not in loaded:
                        loaded["trained_race_files"] = []
                    if "A" not in loaded:
                        loaded["A"] = defaults["A"]
                    if "B" not in loaded:
                        loaded["B"] = defaults["B"]
                    cls._cached_weights_data = loaded
                    return loaded
            except Exception:
                pass
        cls._cached_weights_data = defaults
        return defaults

    @classmethod
    def save_calibrated_weights(cls, weights_dict, trained_files):
        os.makedirs(os.path.dirname(WEIGHTS_FILE), exist_ok=True)
        weights_dict["trained_race_files"] = sorted(list(set(trained_files)))
        weights_dict["historical_races_trained"] = len(weights_dict["trained_race_files"])
        weights_dict["last_calibrated"] = datetime.datetime.now().isoformat()
        try:
            with open(WEIGHTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(weights_dict, f, indent=4)
            # Update the hot cache with the latest saved data
            cls._cached_weights_data = weights_dict
        except Exception as e:
            print(f"[!] Error saving weights externally: {e}")

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
                    data["_source_path"] = os.path.relpath(path)
                    training_records.append(data)
            except Exception:
                continue
                
        cls._cached_training_records = training_records
        return training_records

    @classmethod
    def evaluate_lora_on_silo(cls, silo_records, lora_data, silo_key, b_s_override):
        """
        Evaluate candidate adapter vectors on local silo data.
        """
        test_data = {
            "A": lora_data["A"],
            "B": {**lora_data.get("B", {}), silo_key: b_s_override}
        }
        
        sovereign_hits = 0
        total_races = len(silo_records)
        weights = cls.get_weights_for_silo(test_data, silo_key)
        
        for race_data in silo_records:
            engine = BiomechanicalEngine(race_data, weights_override=weights)
            ranked = engine.rank_field()
            if not ranked: continue
            
            top_no = ranked[0]["number"]
            finishing_order = race_data.get("race_results", {}).get("finishing_order", [])
            
            if finishing_order and finishing_order[0].get("number") == top_no:
                sovereign_hits += 1
                
        accuracy = sovereign_hits / total_races if total_races > 0 else 0.0
        return accuracy, total_races

    @classmethod
    def evaluate_global_lora(cls, training_records, lora_data, a_override):
        """
        Calculate total prediction accuracy across the entire history pool using modified A.
        """
        test_data = {
            "A": a_override,
            "B": lora_data.get("B", {})
        }
        
        total_hits = 0
        for race_data in training_records:
            silo_key = cls._get_silo_key(race_data)
            weights = cls.get_weights_for_silo(test_data, silo_key)
            engine = BiomechanicalEngine(race_data, weights_override=weights)
            ranked = engine.rank_field()
            if not ranked: continue
            
            finishing_order = race_data.get("race_results", {}).get("finishing_order", [])
            if finishing_order and finishing_order[0].get("number") == ranked[0]["number"]:
                total_hits += 1
                
        return total_hits

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
        status = str(race_data.get("track_status", "Good")).lower()
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

    @classmethod
    def optimize_silo_parameters(cls, training_records, silo, force_reoptimize=False):
        """
        Supervised training of the local projection B_s and global shared A.
        Optimized iteratively via coordinate descent.
        """
        persistent_data = cls.load_calibrated_weights()
        
        # 1. Zero-initialization for new silos to ensure zero-perturbation initially
        if silo not in persistent_data["B"]:
            persistent_data["B"][silo] = [0.0, 0.0]
            
        filtered_training = [r for r in training_records if cls._get_silo_key(r) == silo]
        if len(filtered_training) < 3:
            # Insufficient local data; fall back to baseline state
            return cls.get_weights_for_silo(persistent_data, silo)

        # 2. Local Adaptor Training (Optimize B_s)
        best_b = list(persistent_data["B"][silo])
        best_local_acc, _ = cls.evaluate_lora_on_silo(filtered_training, persistent_data, silo, best_b)
        
        b_steps = [0.1, 0.25, 0.5, 1.0]
        improved_local = False
        
        for r_idx in range(2): # Rank r = 2
            for step in b_steps:
                for direction in [-1, 1]:
                    test_b = list(best_b)
                    test_b[r_idx] += direction * step
                    acc, _ = cls.evaluate_lora_on_silo(filtered_training, persistent_data, silo, test_b)
                    if acc > best_local_acc:
                        best_local_acc = acc
                        best_b = test_b
                        improved_local = True
                        
        persistent_data["B"][silo] = best_b

        # 3. Global Shared Co-Dependency Training (Optimize A)
        if force_reoptimize or improved_local:
            best_A = [list(row) for row in persistent_data["A"]]
            best_global_score = cls.evaluate_global_lora(training_records, persistent_data, best_A)
            
            a_steps = [0.05, 0.1, 0.2]
            improved_global = False
            
            for r in range(2):
                for d in range(6):
                    for step in a_steps:
                        for direction in [-1, 1]:
                            test_A = [list(row) for row in best_A]
                            test_A[r][d] += direction * step
                            score = cls.evaluate_global_lora(training_records, persistent_data, test_A)
                            if score > best_global_score:
                                best_global_score = score
                                best_A = test_A
                                improved_global = True
                                
            if improved_global:
                persistent_data["A"] = best_A

        # Save and write state updates
        current_paths = [r["_source_path"] for r in training_records if "_source_path" in r]
        cls.save_calibrated_weights(persistent_data, current_paths)
        
        return cls.get_weights_for_silo(persistent_data, silo)

    @classmethod
    def initialize_and_calibrate_all_silos(cls, force=False):
        """
        Forces dynamic baseline calibration using LoRA adaptors.
        Checks for new files first to avoid redundant training on old data.
        """
        training_set = cls.collect_completed_races(force_reload=True)
        persistent_data = cls.load_calibrated_weights()
        
        trained_files = set(persistent_data.get("trained_race_files", []))
        current_files = set([r["_source_path"] for r in training_set if "_source_path" in r])
        
        new_files = current_files - trained_files
        
        if not new_files and not force:
            print("[*] LoRA Calibration: No new completed races discovered. Skipping redundant calibration.")
            return False
            
        print("\n" + "="*80)
        if force:
            print("[*] Force re-calibration requested. scanning all completed races...")
        else:
            print(f"[+] Found {len(new_files)} new completed races! Triggering supervised LoRA calibration...")
            
        discovered_silos = set()
        for r in training_set:
            discovered_silos.add(cls._get_silo_key(r))
            
        for silo_key in sorted(list(discovered_silos)):
            print(f"  - Calibrating LoRA adapter for: {silo_key}...")
            cls.optimize_silo_parameters(training_set, silo_key, force_reoptimize=True)
            
        print("[+] Supervised LoRA calibration complete.")
        print("="*80 + "\n")
        return True


# =====================================================================
#           BIOMECHANICAL CALCULATION & VALIDATION ENGINE v4.1
# =====================================================================

class BiomechanicalEngine:
    """
    Sovereign Kinetic Index (SKI) Engine v4.1.
    """
    def __new__(cls, raw_data, weights_override=None):
        if cls is BiomechanicalEngine:
            region = BiomechanicalOptimizer._get_region_name(raw_data).lower()
            if "south_africa" in region or "south africa" in region:
                from south_african_logic import SouthAfricanBiomechanicalEngine
                return object.__new__(SouthAfricanBiomechanicalEngine)
        return object.__new__(cls)

    def __init__(self, raw_data, weights_override=None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self.raw_data = raw_data
        self.distance = safe_float(raw_data.get("distance", 1200))
        self.track_status = str(raw_data.get("track_status", "Good")).lower()
        self.race_name = str(raw_data.get("race_name", ""))
        
        match = re.search(r'R(\d+)', self.race_name)
        self.race_number = int(match.group(1)) if match else 1

        self.silo = BiomechanicalOptimizer._get_silo_surface(self.raw_data)
        self.region = BiomechanicalOptimizer._get_region_name(self.raw_data)
        self.regional_silo = f"{self.region}_{self.silo}"

        if weights_override:
            self.weights = weights_override
        else:
            if not os.path.exists(WEIGHTS_FILE):
                BiomechanicalOptimizer.initialize_and_calibrate_all_silos()
                
            training_set = BiomechanicalOptimizer.collect_completed_races()
            persistent_data = BiomechanicalOptimizer.load_calibrated_weights()
            trained_files = set(persistent_data.get("trained_race_files", []))
            
            current_files = set([r["_source_path"] for r in training_set if "_source_path" in r])
            new_files = current_files - trained_files
            
            force_recalc = (len(new_files) > 0)
            if force_recalc:
                training_set = BiomechanicalOptimizer.collect_completed_races(force_reload=True)
                persistent_data = BiomechanicalOptimizer.load_calibrated_weights()
                
                # Calibrate LoRA parameters using updated training records
                BiomechanicalOptimizer.optimize_silo_parameters(
                    training_set, 
                    self.regional_silo, 
                    force_reoptimize=True
                )
                persistent_data = BiomechanicalOptimizer.load_calibrated_weights()
            
            self.weights = BiomechanicalOptimizer.get_weights_for_silo(
                persistent_data, 
                self.regional_silo
            )

    def evaluate_runner(self, runner):
        # Destructure calibrated weights: [w_kem, w_turn, w_mass, w_fresh, w_jeopardy, w_text]
        w_kem, w_turn, w_mass, w_fresh, w_jeopardy, w_text = self.weights

        # 1. Physical Chassis & Identity Parameters
        age, sex_idx = BiomechanicalTextVectorizer.parse_physical_chassis(runner.get("overview", ""))
        barrier = safe_float(runner.get("barrier", 8))
        allotted_weight = safe_float(runner.get("weight_kg", 56.0)) if runner.get("weight_kg") else 56.0
        
        # Apprentice Claim Mitigation (ACM) Integration
        jockey_name = str(runner.get("jockey", "")).lower()
        claim_match = re.search(r'\(a(\d+\.?\d*)\)', jockey_name)
        claim = float(claim_match.group(1)) if claim_match else 0.0
        w_eff = max(45.0, allotted_weight - claim)
        
        rct = BiomechanicalTextVectorizer.parse_race_class_tier(self.race_name)
        
        career = runner.get("career_stats", {})
        starts = safe_float(career.get("starts", 0))
        wins = safe_float(career.get("wins", 0))
        places = safe_float(career.get("places", 0))
        
        kem = (wins + 0.5 * places) / (starts + 1.0) if starts > 0 else 0.20
        recent_form = runner.get("recent_form", [])
        
        # 2. Moisture-Compaction Shear Index (MSCI) Mapping
        ts_lower = self.track_status
        is_synthetic = False
        if "synthetic" in ts_lower or "poly" in ts_lower:
            msci = 0.90
            is_synthetic = True
        elif "heavy" in ts_lower or "8" in ts_lower or "9" in ts_lower or "10" in ts_lower:
            msci = 0.40
        elif "soft" in ts_lower or "6" in ts_lower or "7" in ts_lower:
            msci = 0.70 if "5" in ts_lower else 0.60
        else:
            msci = 0.85 # Good / Firm Turf Tracks
            
        # 3. Field Compression Pace Factor (Phi_FC)
        active_field = [r for r in self.raw_data.get("runners", []) if r.get("status") == "Active"]
        n_actual = len(active_field)
        phi_fc = min(1.0, (n_actual / 10.0) ** 1.5) if n_actual > 0 else 1.0

        # 4. Form Parsing: Margins, Distances, and Layoffs
        margins = []
        distances = []
        first_up_wet = False
        first_up_margin = 0.0
        prep_runs = 0
        
        for idx, run in enumerate(recent_form[:3]):
            if not run: continue
            
            if isinstance(run, dict):
                run_str = f"{run.get('margin', '')} {run.get('class', '')} {run.get('track_status', '')}".lower()
            else:
                run_str = str(run).lower()
                
            if "trial" not in run_str:
                prep_runs += 1
                
            margin_match = re.search(r'(\d+\.?\d*)\s*l', run_str)
            if margin_match:
                margins.append(float(margin_match.group(1)))
                if idx == 0: first_up_margin = float(margin_match.group(1))
                
            dist_match = re.search(r'(\d+)m', run_str)
            if dist_match:
                distances.append(float(dist_match.group(1)))
                
            # Track state analysis for prior run
            if idx == 0:
                if "soft" in run_str or "heavy" in run_str or "h8" in run_str or "s6" in run_str:
                    first_up_wet = True

        avg_margin = sum(margins) / len(margins) if margins else 2.5
        avg_prev_dist = sum(distances) / len(distances) if distances else self.distance
        
        # 5. Base Energy Synthesis (KEM & Class Parity)
        if rct == 1.0:
            base_energy = 55.0 + (kem * w_kem * 0.40)
        elif rct == 3.0:
            base_energy = 45.0 + (kem * w_kem * 1.20)
        else:
            base_energy = 50.0 + (kem * w_kem)
            
        # Unraced Metro-to-Regional Class Gravity Coefficient
        if starts == 0 and rct == 1.0:
            base_energy += 12.0 # Protective debutant offset replacing raw zero-cap
            
        # 6. Cardiorespiratory Priming & Recovery Decay Modifiers
        freshness_modifier = 0.0
        assumed_layoff = safe_float(runner.get("days_since_last_run", 0))
        if assumed_layoff == 0:
            assumed_layoff = 120 if prep_runs == 1 else 14
        
        if prep_runs == 1:
            # First-Up Neuromuscular Priming Index (FNPI) - Shielding fresh sprinters
            freshness_modifier = 4.0 * w_fresh
        elif prep_runs == 2:
            # Second-Up Syndrome Logic Core
            if first_up_wet and msci >= 0.85:
                # Cardiorespiratory Conditioning Opener Modifier (Wet first-up to firm second-up)
                freshness_modifier = 6.0 * w_fresh 
            elif first_up_margin > 5.0 and assumed_layoff > 120:
                # Dynamic Cardiorespiratory Flat Risk (CRFR) - Decay applied
                freshness_modifier = -8.0 * w_fresh 
            else:
                freshness_modifier = 2.0 * w_fresh
        elif prep_runs >= 6:
            # Campaign Fatigue Threshold (CFT) on Fast Surfaces
            if msci >= 0.85:
                freshness_modifier = -5.0 * w_fresh * (msci ** 2)
            else:
                freshness_modifier = -3.0 * w_fresh
                
        # Stay-to-Sprint Elasticity Penalty (SSEP)
        dist_drop = avg_prev_dist - self.distance
        if dist_drop >= 300:
            if msci >= 0.85 and self.distance <= 1400:
                # Penalise stayers dropping in distance on firm ground lacking tactical acceleration
                freshness_modifier -= 4.5 * math.log(1.0 + (dist_drop / 100.0))
            else:
                # Let-Up Reinvigoration/Aerobic Advantage holds on wet/slower ground
                freshness_modifier += 3.0

        # 7. Mechanical Drag & Visco-elastic Weight-Tax Hysteresis
        # Firm tracks exponentially reduce the mechanical penalty of heavy top-weights
        gamma_weight = 0.18 * (1.0 - msci) * max(0.0, w_eff - 55.0)**1.5
        mass_damping = gamma_weight * w_mass * 5.0 
        
        turn_loss = barrier * w_turn * phi_fc
        
        if is_synthetic:
            # Track Geometry Paramter Update for Polytracks (Shorter straights)
            straight_ratio = 378.0 / 2000.0
            if straight_ratio >= 0.18:
                turn_loss *= 0.85 
            friction_drag = turn_loss
            biomechanical_score = base_energy + freshness_modifier - friction_drag - mass_damping - (avg_margin * 1.1)
            
        elif msci <= 0.70: # Wet Turf Paths
            outer_lane_bonus = min(9.0, (barrier - 5) * 1.3)
            friction_drag = max(0.0, turn_loss - outer_lane_bonus)
            biomechanical_score = base_energy + freshness_modifier - friction_drag - mass_damping - (avg_margin * 1.4)
            
        else: # Dry/Firm Turf Paths
            friction_drag = turn_loss
            biomechanical_score = base_energy + freshness_modifier - friction_drag - mass_damping - (avg_margin * 0.95)

        # 8. Class Elasticity & Exposed Form Modifiers
        # Firm-Surface Stride-Ceiling Cap
        if rct == 1.0 and starts >= 10 and wins == 0 and msci >= 0.85:
            fssc_decay = 1.0 - (0.04 * starts * (msci - 0.50))
            biomechanical_score *= max(0.5, fssc_decay)
            
        # Class-Elasticity Moisture Interaction (High class dominates firm tracks)
        if rct >= 2.0 and msci >= 0.85:
            biomechanical_score += (msci - 0.70) * 1.20 * 5.0 

        # 9. Semantic Gear Transition Validation Tree
        gear_bonus = 0.0
        gear_str = str(runner.get("gear_changes", [])).lower() + " " + str(runner.get("overview", "")).lower()
        if "blinkers first time" in gear_str or "blinkers on" in gear_str:
            gear_bonus += 4.5 if self.distance <= 1100 else 2.0
        if "cross-over nose band" in gear_str and "first time" in gear_str:
            gear_bonus += 3.5
        if "concussion plates" in gear_str and is_synthetic:
            # Suction vacuum effect penalty on synthetic wax binders
            gear_bonus -= 6.5 * (w_eff / 60.0)
            
        biomechanical_score += gear_bonus

        # 10. Abstract Text Vectorization & Jeopardy Offsets
        jockey_vector = BiomechanicalTextVectorizer.text_to_hash_vector(runner.get("jockey", ""))
        trainer_vector = BiomechanicalTextVectorizer.text_to_hash_vector(runner.get("trainer", ""))
        commentary_vector = BiomechanicalTextVectorizer.text_to_hash_vector(runner.get("overview", ""))
        
        vector_modifier = (sum(jockey_vector) + sum(trainer_vector) + sum(commentary_vector)) * w_text
        biomechanical_score += vector_modifier

        # Double Jeopardy Veto Overlay
        if barrier >= 9 and w_eff >= 58.5:
            penalty_multiplier = 0.50 if rct == 3.0 else 1.50 if rct == 1.0 else 1.00
            biomechanical_score -= (w_jeopardy * penalty_multiplier * phi_fc)

        return round(biomechanical_score, 3)

    def rank_field(self):
        runners = self.raw_data.get("runners", [])
        active_field = [r for r in runners if r.get("status") == "Active"]
        
        ranked = []
        for r in active_field:
            score = self.evaluate_runner(r)
            ranked.append({
                "number": safe_int(r.get("number")),
                "name": r.get("name", "Unknown"),
                "barrier": safe_int(r.get("barrier")),
                "weight_kg": safe_float(r.get("weight_kg")),
                "score": score
            })
            
        ranked.sort(key=lambda x: x["score"], reverse=True)
        
        for idx, item in enumerate(ranked):
            if idx == 0:
                item["designation"] = "1A Sovereign (Primary)"
            elif idx == 1:
                item["designation"] = "1B Shield (Cover)"
            elif idx in [2, 3]:
                item["designation"] = "Exotic Residual"
            else:
                item["designation"] = "Field Chassis"
                
        return ranked