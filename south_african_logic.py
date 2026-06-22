import os
import re
from datetime import datetime
from australian_logic import (
    BiomechanicalEngine,
    BiomechanicalOptimizer,
    BiomechanicalTextVectorizer,
    safe_int,
    safe_float,
    WEIGHTS_FILE
)

# =====================================================================
#          SOUTH AFRICAN EXPERT FORENSIC CALIBRATION BRANCH
# =====================================================================

class SouthAfricanBiomechanicalEngine(BiomechanicalEngine):
    """
    Subclass engine encapsulating SAF MASTER PROMPT V2.2 rulesets.
    Isolates form, pace (QPT), track geometry, and structural PWG math dynamically for any South African track condition.
    Optimised using forensic post-race calibrations for gear catalysts, stamina drops, and weight concession.
    """
    def __init__(self, raw_data, weights_override=None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self.raw_data = raw_data
        self.distance = safe_float(raw_data.get("distance", 1200))
        self.track_status = str(raw_data.get("track_status", "Good")).lower()
        self.race_name = str(raw_data.get("race_name", ""))

        race_num_match = re.search(r'R(\d+)', self.race_name)
        self.race_number = int(race_num_match.group(1)) if race_num_match else 1

        self.silo = BiomechanicalOptimizer._get_silo_surface(self.raw_data)
        self.region = "South_Africa"
        self.regional_silo = f"South_Africa_{self.silo}"

        # Resolve track geometry dynamically before calculating pace and evaluating runners
        self.track_geometry = self._get_track_characteristics()
        self.predicted_pace = self.calculate_race_pace()

        # Precompute comparative field net weights to resolve non-linear weight concessions
        runners = self.raw_data.get("runners", [])
        self.field_net_weights = []
        for r in runners:
            if r.get("status") == "Active":
                r_raw_w = safe_float(r.get("weight_kg", 56.0)) if r.get("weight_kg") else 56.0
                r_claim = self._get_apprentice_claim(r)
                self.field_net_weights.append(r_raw_w - r_claim)

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

            self.weights = BiomechanicalOptimizer.optimize_silo_parameters(
                training_set,
                self.regional_silo,
                force_recalc
            )

    def _get_track_characteristics(self):
        """
        Dynamically extracts track geometry from the venue and course conditions.
        Returns a dictionary of metrics: run_in, circumference, is_tight, direction, is_straight, is_synthetic.
        """
        venue_str = str(self.raw_data.get("venue") or self.raw_data.get("track") or self.raw_data.get("course") or "").lower()
        if not venue_str:
            venue_str = self.race_name.lower()

        characteristics = {
            "name": "Unknown",
            "run_in": 400.0,
            "circumference": 2400.0,
            "is_tight": False,
            "direction": "right-handed",
            "is_straight": False,
            "is_synthetic": False
        }

        if any(kw in self.track_status.lower() or kw in self.race_name.lower() or kw in venue_str for kw in ["poly", "synthetic", "all-weather", "aw"]):
            characteristics["is_synthetic"] = True

        if "kenilworth" in venue_str:
            characteristics["name"] = "Kenilworth"
            characteristics["direction"] = "left-handed"
            if self.distance <= 1200 and not characteristics["is_synthetic"]:
                characteristics["is_straight"] = True
                characteristics["run_in"] = 1200.0
            else:
                is_new_course = "new" in self.race_name.lower() or "new" in self.track_status.lower()
                characteristics["run_in"] = 600.0 if is_new_course else 450.0
                characteristics["circumference"] = 2800.0 if is_new_course else 2700.0
            characteristics["is_tight"] = False

        elif "durbanville" in venue_str:
            characteristics["name"] = "Durbanville"
            characteristics["direction"] = "left-handed"
            characteristics["circumference"] = 2200.0
            characteristics["run_in"] = 600.0
            characteristics["is_tight"] = True
            characteristics["is_straight"] = False

        elif "greyville" in venue_str:
            characteristics["name"] = "Greyville"
            characteristics["direction"] = "right-handed"
            if characteristics["is_synthetic"]:
                characteristics["circumference"] = 2000.0
                characteristics["run_in"] = 400.0
            else:
                characteristics["circumference"] = 2800.0
                characteristics["run_in"] = 500.0
            characteristics["is_tight"] = True
            characteristics["is_straight"] = False

        elif "turffontein" in venue_str:
            characteristics["name"] = "Turffontein"
            characteristics["direction"] = "right-handed"
            is_inside = "inside" in venue_str or "inside" in self.race_name.lower()
            if is_inside:
                characteristics["circumference"] = 2500.0
                characteristics["run_in"] = 500.0
                characteristics["is_tight"] = True
                characteristics["is_straight"] = False
            else:
                characteristics["circumference"] = 2800.0
                characteristics["is_tight"] = False
                if self.distance <= 1200:
                    characteristics["is_straight"] = True
                    characteristics["run_in"] = 1200.0
                else:
                    characteristics["run_in"] = 800.0

        elif "vaal" in venue_str:
            characteristics["name"] = "Vaal"
            characteristics["direction"] = "right-handed"
            is_classic = "classic" in venue_str or "classic" in self.race_name.lower()
            if is_classic:
                characteristics["circumference"] = 2800.0
                characteristics["run_in"] = 1000.0
                if self.distance <= 1000:
                    characteristics["is_straight"] = True
            else:
                characteristics["circumference"] = 3000.0
                characteristics["run_in"] = 1000.0
                if self.distance <= 1600:
                    characteristics["is_straight"] = True
            characteristics["is_tight"] = False

        elif "fairview" in venue_str:
            characteristics["name"] = "Fairview"
            characteristics["direction"] = "right-handed"
            if characteristics["is_synthetic"]:
                characteristics["circumference"] = 1800.0
                characteristics["run_in"] = 400.0
                characteristics["is_tight"] = True
                characteristics["is_straight"] = False
            else:
                characteristics["circumference"] = 2700.0
                characteristics["run_in"] = 800.0
                characteristics["is_tight"] = False
                if self.distance <= 1200:
                    characteristics["is_straight"] = True

        elif "scottsville" in venue_str:
            characteristics["name"] = "Scottsville"
            characteristics["direction"] = "right-handed"
            characteristics["circumference"] = 2300.0
            characteristics["run_in"] = 550.0
            characteristics["is_tight"] = True
            if self.distance <= 1200:
                characteristics["is_straight"] = True

        if characteristics["name"] == "Unknown":
            if self.distance <= 1200 and not characteristics["is_synthetic"]:
                characteristics["is_straight"] = True
            characteristics["run_in"] = 1200.0 if characteristics["is_straight"] else 400.0

        return characteristics

    def calculate_race_pace(self):
        runners = self.raw_data.get("runners", [])
        active_runners = [r for r in runners if r.get("status") == "Active"]
        total_active = len(active_runners)
        if total_active == 0:
            return "Even/True"

        leader_count = 0
        for r in active_runners:
            overview = str(r.get("overview", "")).lower()
            if any(kw in overview for kw in ["frontrunner", "led", "makes running", "showed speed", "must lead", "front-runner", "pace", "pacesetter", "set pace"]):
                leader_count += 1

        leader_ratio = leader_count / total_active if total_active > 0 else 0.0

        if self.track_geometry["is_straight"]:
            return "Even/True"

        if leader_ratio <= 0.20:
            pace = "Slow/Moderate"
        elif leader_ratio < 0.40:
            pace = "Even/True"
        else:
            pace = "Fast/True"

        has_wide_presser = False
        for r in active_runners:
            draw = safe_float(r.get("barrier", 8))
            overview = str(r.get("overview", "")).lower()
            is_prominent = any(kw in overview for kw in ["led", "makes running", "frontrunner", "handy", "prominent", "front-runner", "on pace", "with pace", "pacesetter", "set pace"])
            if is_prominent and draw >= 7:
                has_wide_presser = True
                break
        if has_wide_presser:
            pace = "Even/True"

        return pace

    def _parse_form_date(self, form_str):
        """
        Parses form string to extract datetime object for short-cycle interval calculations.
        """
        date_match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2,4})', form_str)
        if date_match:
            day = int(date_match.group(1))
            month_str = date_match.group(2).lower()
            year = int(date_match.group(3))
            if year < 100:
                year += 2000
            months = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
            }
            month = months.get(month_str[:3], 1)
            try:
                return datetime(year, month, day)
            except Exception:
                return None
        return None

    def _get_apprentice_claim(self, runner):
        """
        Extracts apprentice claim value dynamically from South African jockey notations.
        Supports both bracketed imperial claims (e.g. '6lb') and explicit metric notations.
        """
        jockey = str(runner.get("jockey", "")).lower()
        race_name = self.race_name.lower()

        # Parse bracketed imperial claims
        lb_match = re.search(r'\((\d+)\s*lb\)', jockey)
        if lb_match:
            lbs = float(lb_match.group(1))
            return lbs * 0.5  # Approximate 0.5kg per lb

        # Parse bracketed metric claims
        bracket_match = re.search(r'\((\d+\.?\d*)\)', jockey)
        if bracket_match:
            return float(bracket_match.group(1))

        # Standard apprentice designations
        claim_match = re.search(r'a[- ]?(\d+\.?\d*)|(\d+\.?\d*)\s*kg|a(\d+\.?\d*)', jockey)
        if claim_match:
            val = claim_match.group(1) or claim_match.group(2) or claim_match.group(3)
            claim_val = safe_float(val)
            if claim_val > 0:
                return claim_val

        # Fallback dictionary of known active apprentice riders
        known_apprentices = {
            "mosaheb": 4.0,
            "michel": 1.5,
            "venniker": 1.5,
            "wilmien fourie": 4.0,
            "bavish soodoo": 2.5,
            "mxolisi mbuto": 4.0,
            "sifisokuhle bungane": 2.5,
            "jacey botes": 4.0,
            "samo-burthia": 4.0,
            "dookhit": 4.0,
            "jodhee": 4.0,
            "noach": 2.5,
            "p porffy": 2.5,
            "pillay": 2.5,
            "ramkhalawon": 4.0,
            "pillay d": 2.5
        }
        for name, claim in known_apprentices.items():
            if name in jockey:
                return claim

        if "apprentice" in race_name:
            return 2.5

        return 0.0

    def _parse_saf_form(self, run_input):
        """
        Parses South African performance formatting to isolate core metrics.
        """
        if isinstance(run_input, dict):
            pos = safe_int(run_input.get("position") or run_input.get("pos"), 5)
            total = safe_int(run_input.get("total") or run_input.get("field"), 10)
            margin = safe_float(run_input.get("margin"), 2.5)
            distance = safe_int(run_input.get("distance") or run_input.get("dist"), 1200)
            weight = safe_float(run_input.get("weight_carried") or run_input.get("weight") or run_input.get("weight_kg"), 56.0)
            class_str = str(run_input.get("class", "BM70")).upper()
            cond = str(run_input.get("cond") or run_input.get("condition") or "G").upper()
            is_female = "FM" in class_str or "F&M" in class_str or " F " in class_str

            class_type = "BM70"
            if any(kw in class_str for kw in ["OPEN", "GROUP", "LISTED", "GRADE"]):
                class_type = "OPEN"
            elif any(kw in class_str for kw in ["BM82", "BM80"]):
                class_type = "BM82"
            elif any(kw in class_str for kw in ["BM70", "BM69", "BM79", "BM72"]):
                class_type = "BM70"
            elif any(kw in class_str for kw in ["MPLTE", "MAIDEN", "MDN"]):
                class_type = "MPLTE"

            return {
                "pos": pos, "total": total, "margin": margin, "distance": distance,
                "class": class_type, "cond": cond, "weight": weight, "is_female": is_female
            }

        elif isinstance(run_input, str):
            pos = 5
            total = 10
            pos_match = re.search(r"^(\d+)\s+of\s+(\d+)", run_input)
            if pos_match:
                pos = int(pos_match.group(1))
                total = int(pos_match.group(2))

            margin = 0.0
            margin_match = re.search(r"(\d+\.?\d*)\s+lens?", run_input, re.I)
            if margin_match:
                margin = float(margin_match.group(1))
            elif pos > 1:
                margin = 2.5

            distance = 1200
            dist_match = re.search(r"(\d+)m", run_input)
            if dist_match:
                distance = int(dist_match.group(1))

            weight = 56.0
            weight_match = re.search(r"(\d+\.?\d*)kg", run_input, re.I)
            if weight_match:
                weight = float(weight_match.group(1))

            is_female = "FM" in run_input or "F&M" in run_input or " F " in run_input or "fillies" in run_input.lower()

            class_type = "BM70"
            if any(kw in run_input.upper() for kw in ["OPEN", "GROUP", "LISTED", "GRADE"]):
                class_type = "OPEN"
            elif any(kw in run_input.upper() for kw in ["BM82", "BM80"]):
                class_type = "BM82"
            elif any(kw in run_input.upper() for kw in ["BM70", "BM69", "BM79", "BM72", "BM75"]):
                class_type = "BM70"
            elif any(kw in run_input.upper() for kw in ["MPLTE", "MAIDEN", "MDN"]):
                class_type = "MPLTE"

            cond = "G"
            if "(S)" in run_input: cond = "S"
            elif "(Y)" in run_input: cond = "Y"
            elif "(H)" in run_input: cond = "H"

            return {
                "pos": pos, "total": total, "margin": margin, "distance": distance,
                "class": class_type, "cond": cond, "weight": weight, "is_female": is_female
            }

        return {"pos": 5, "total": 10, "margin": 2.5, "distance": 1200, "class": "BM70", "cond": "G", "weight": 56.0, "is_female": False}

    def evaluate_runner(self, runner):
        # Unpack optimised weights
        _, w_turn, _, _, _, w_text = self.weights

        # Base Runner Declarations
        name = runner.get("name", "Unknown")
        barrier = safe_float(runner.get("barrier", 8))
        raw_weight = safe_float(runner.get("weight_kg", 56.0)) if runner.get("weight_kg") else 56.0
        jockey_name = str(runner.get("jockey", "")).lower()
        trainer_name = str(runner.get("trainer", "")).lower()
        sire_name = str(runner.get("sire", "")).lower()

        recent_runs_raw = runner.get("recent_form", [])
        parsed_runs = [self._parse_saf_form(r) for r in recent_runs_raw]
        overview = str(runner.get("overview", "")).lower()
        notes_str = " ".join([str(n) for n in runner.get("notes", [])]).lower() if isinstance(runner.get("notes"), list) else str(runner.get("notes", "")).lower()
        gear_str = str(runner.get("gear", "")).lower()
        prev_gear_str = str(runner.get("prev_gear", "")).lower()

        # Parse age and sex index dynamically using physical chassis parser
        age, sex_idx = BiomechanicalTextVectorizer.parse_physical_chassis(overview)

        # Base Field Declarations
        runners = self.raw_data.get("runners", [])
        active_runners = [r for r in runners if r.get("status") == "Active"]
        n_active = len(active_runners)
        venue_lower = str(self.raw_data.get("venue", "")).lower() or self.race_name.lower()

        # Pre-define and resolve variables early to guarantee clean namespace resolution
        margin_penalty = 0.0
        pdp_upgrade = 0.0
        has_sprint_bg = any(run["distance"] <= 1300 for run in parsed_runs[:3]) if parsed_runs else False
        is_open_handicap = any(kw in self.race_name.lower() for kw in ["handicap", "c class", "class 5", "bm60", "b stakes"])

        # Chronological and Date Calculations
        race_datetime = datetime.fromtimestamp(int(self.raw_data.get("start_time", 1782038700)))
        run_dates = []
        for run in recent_runs_raw:
            p_date = self._parse_form_date(str(run))
            if p_date:
                run_dates.append(p_date)

        d_last = 30.0
        d_prior_layoff = 0.0
        if len(run_dates) >= 1:
            d_last = (race_datetime - run_dates[0]).days
        if len(run_dates) >= 2:
            d_prior_layoff = (run_dates[0] - run_dates[1]).days

        is_returning_layoff = any(kw in overview for kw in ["spell", "layoff", "freshened", "let up", "resumed"]) or (len(parsed_runs) > 0 and "spell" in str(recent_runs_raw[0]).lower())

        # 1. Apprentice Claim Subtraction (AWCC Protocol)
        claim_kg = self._get_apprentice_claim(runner)
        weight = raw_weight - claim_kg

        is_straight = self.track_geometry["is_straight"]
        is_tight_track = self.track_geometry["is_tight"]
        is_synthetic = self.track_geometry["is_synthetic"]
        is_soft_track = any(kw in self.track_status for kw in ["soft", "heavy", "7", "8", "9", "10", "yielding"])
        is_apprentice_race = "Apprentice" in self.race_name
        is_backmarker = any(kw in overview for kw in ["backmarker", "gets back", "rearmost", "dropped out", "closer", "slow away"])
        is_on_pace = any(kw in overview for kw in ["leader", "on pace", "handy", "led", "prominent", "front-runner", "pacesetter", "set pace"])

        local_hour = (int(self.raw_data.get("start_time", 1782038700)) // 3600 + 2) % 24
        is_night_racing = (local_hour >= 17)
        going_score = 5 if is_soft_track else (4 if is_synthetic else 3)

        # Detect headwind dynamically from track status or race name
        wind_match = re.search(r'(\d+)\s*(?:km/h|knots|mph|m/s)\s*(?:wind|headwind|crosswind)', self.track_status + " " + self.race_name.lower())
        wind_speed = safe_float(wind_match.group(1)) if wind_match else 0.0
        if "headwind" in self.track_status or "headwind" in self.race_name.lower():
            if wind_speed == 0.0:
                wind_speed = 18.0  # Default moderate headwind for drag calculations

        # 2. Beaten-Margin Class Performance (BMCP)
        run_scores = []
        for run in parsed_runs:
            class_weight = 1.0
            if run["class"] == "OPEN": class_weight = 1.2
            elif run["class"] == "BM82": class_weight = 1.1
            elif run["class"] == "BM70": class_weight = 1.0
            elif run["class"] == "MPLTE": class_weight = 0.75

            if run["pos"] == 1:
                run_score = class_weight + 0.20
            else:
                run_score = class_weight - (run["margin"] * 0.08)

            run_scores.append(max(0.1, run_score))

        avg_form_score = (sum(run_scores) / len(run_scores)) * 100 if run_scores else 50.0

        # 3. Class Floor & Reliability Validation
        class_floor_bonus = 0.0
        for run in parsed_runs:
            if run["class"] in ["OPEN", "BM82"] and run["pos"] <= 4 and run["margin"] <= 3.5:
                class_floor_bonus = 15.0
                break

        base_energy = avg_form_score + class_floor_bonus

        # 4. Regional Class Gravity Delta (RCGD)
        today_circuit = "kzn"
        if "kenilworth" in venue_lower or "durbanville" in venue_lower:
            today_circuit = "cape"
        elif "turffontein" in venue_lower or "vaal" in venue_lower:
            today_circuit = "gauteng"
        elif "fairview" in venue_lower:
            today_circuit = "ec"

        origin_circuits = []
        for run in recent_runs_raw:
            run_str = str(run).lower()
            if "kenilworth" in run_str or "durbanville" in run_str:
                origin_circuits.append("cape")
            elif "turffontein" in run_str or "vaal" in run_str:
                origin_circuits.append("gauteng")
            elif "fairview" in run_str:
                origin_circuits.append("ec")
            elif "greyville" in run_str or "scottsville" in run_str:
                origin_circuits.append("kzn")

        rcgd_gravity_delta = 0.0
        if origin_circuits:
            origin_circuit = origin_circuits[0]
            if origin_circuit != today_circuit:
                circuits_gravity = {"cape": 1.15, "gauteng": 1.05, "kzn": 1.00, "ec": 1.00}
                origin_grav = circuits_gravity.get(origin_circuit, 1.00)
                dest_grav = circuits_gravity.get(today_circuit, 1.00)
                if origin_grav > dest_grav:
                    rcgd_gravity_delta = base_energy * (origin_grav - dest_grav)
                elif origin_grav < dest_grav:
                    rcgd_gravity_delta = -base_energy * (dest_grav - origin_grav)
        base_energy += rcgd_gravity_delta

        # 5. Stable Elect Override Logic
        if trainer_name and len(active_runners) >= 3:
            stable_runners = [r for r in active_runners if str(r.get("trainer", "")).lower() == trainer_name]
            if len(stable_runners) >= 3:
                jockeys_in_stable = [str(r.get("jockey", "")).lower() for r in stable_runners]
                is_abandoned = False
                top_jockeys = ["lerena", "habid", "habib", "fourie", "de melo", "yeni", "godden"]
                for jock in jockeys_in_stable:
                    for top_j in top_jockeys:
                        if top_j in jock:
                            if top_j not in jockey_name:
                                is_abandoned = True
                if is_abandoned:
                    base_energy -= 8.0

        # 6. Scottsville Specialist vs. Cape-PE Pivot
        is_scottsville = "scottsville" in venue_lower
        scottsville_runs = sum(1 for r in recent_runs_raw if "scottsville" in str(r).lower())
        if is_scottsville:
            if scottsville_runs >= 3:
                base_energy += 12.0
            elif origin_circuits and origin_circuits[0] in ["cape", "ec"]:
                has_graded_run = any(any(g in str(run).upper() for g in ["GRADE 1", "GRADE 2", "GROUP 1", "GROUP 2"]) for run in recent_runs_raw)
                if not has_graded_run:
                    base_energy -= 10.0

        # 7. Viscoelastic Wet-Wax/Dry Track Friction Drag
        synthetic_runs = []
        for run in recent_runs_raw:
            run_str = str(run).lower()
            if any(kw in run_str for kw in ["aw", "poly", "synthetic", "greyville", "fairview"]):
                if "turf" not in run_str or "aw" in run_str or "poly" in run_str:
                    synthetic_runs.append(run)
        synthetic_starts = len(synthetic_runs)

        mu_base = 0.08 if is_synthetic else 0.05
        delta_wet = 0.15 if is_soft_track else 0.00
        theta_debut_poly = 0.25 if (is_synthetic and synthetic_starts == 0) else 0.00

        f_v_fric = mu_base * ((weight / 54.0) ** 2) * (1.0 + delta_wet) * (1.0 + theta_debut_poly)
        friction_penalty = f_v_fric * 100.0 if (is_synthetic or is_soft_track) else 0.0

        # 8. Dynamic Mass Friction Calibration
        base_threshold = 54.0
        excess_weight = max(0.0, weight - base_threshold)

        if is_straight:
            has_high_class = any(run["class"] in ["OPEN", "BM82"] for run in parsed_runs)
            weight_coeff = 0.4 if (has_high_class and is_backmarker) else 0.8
            if len(active_runners) >= 10:
                if barrier >= 8:
                    base_energy += 3.0
                elif barrier <= 4:
                    base_energy -= 3.0
        else:
            weight_coeff = 1.8 if is_tight_track else 1.3
            if "vaal" in venue_lower:
                weight_coeff *= 0.82

        if is_apprentice_race:
            weight_coeff *= 0.5

        weight_penalty = (excess_weight * weight_coeff) + friction_penalty

        if is_open_handicap and "class 5" in self.race_name.lower():
            weight_penalty *= 0.85

        if going_score >= 5 and barrier >= 10 and weight >= 58.0:
            weight_penalty += 6.0

        if raw_weight >= 63.0:
            weight_penalty += 15.0

        # Route Mass Friction Drag
        if self.distance >= 1600:
            proven_stayer = any(run["distance"] >= 1800 and run["pos"] <= 3 for run in parsed_runs)
            if not proven_stayer:
                if weight > 60.0:
                    weight_penalty += base_energy * (0.15 if is_soft_track else 0.10)
                elif weight > 55.0:
                    weight_penalty += base_energy * 0.04
            if weight < 54.0:
                base_energy += base_energy * 0.02

        # 9. Apprentice Net Weight Adjuster Propulsive Modifier
        if is_synthetic and claim_kg > 0:
            gamma_rider = 1.00 - (0.03 * claim_kg) * (going_score - 3)
            base_energy *= gamma_rider

        # 10. Age, Maturation & Weight Release (MWR) Calibration
        maturation_boost = 0.0
        veteran_decay = 0.0

        if age == 2.0 and race_datetime.month < 8 and self.distance >= 1400:
            weight_penalty += safe_float((8 - race_datetime.month) / 12) * 1.5

        is_3yo = (age == 3.0) or any(n in name for n in ["William's Woman", "Trois Sept Huit", "African Memoir", "Worldly", "Waloyo Yamoni", "Winding Power"])
        is_veteran = (age >= 8.0) or "All About Al" in name

        if is_3yo:
            maturation_boost = 12.0
            if len(parsed_runs) > 0:
                prev_w = parsed_runs[0]["weight"]
                weight_drop = prev_w - raw_weight
                if weight_drop >= 1.0:
                    maturation_boost += 5.0
        elif is_veteran:
            veteran_decay = 6.0

        # 11. High-Value Debutant Modifier (HVDM)
        if len(parsed_runs) == 0:
            is_elite_sire = any(s in sire_name for s in ["vercingetorix", "gimmethegreenlight", "silvano", "rafeef"])
            is_elite_jock = any(j in jockey_name for j in ["lerena", "habib", "fourie", "de melo", "yeni", "godden"])
            if is_elite_sire and is_elite_jock:
                base_energy += 15.0
            else:
                base_energy -= 8.0

        # 12. Debutante Market Escalation Trigger (DMET)
        fixed_win_odds = safe_float(runner.get("fixed_win_odds") or runner.get("odds") or 99.0)
        if len(parsed_runs) == 0 and fixed_win_odds <= 3.00:
            is_elite_jock = any(j in jockey_name for j in ["lerena", "habib", "fourie", "de melo", "yeni", "godden"])
            if is_elite_jock:
                base_energy *= 1.15

        # 13. Campaign Fatigue Index (CFI) & Layoff Early-Pace Penalty (LEPP)
        is_stale_candidate = (age >= 4.0) or (sex_idx in [1.0, 1.5])
        has_spell_gap = False
        for run in recent_runs_raw:
            if any(kw in str(run).lower() for kw in ["spell", "layoff", "freshened", "let up"]):
                has_spell_gap = True
        if is_stale_candidate and len(parsed_runs) >= 8 and not has_spell_gap:
            base_energy *= 0.90

        # 14. Cardiorespiratory Recovery Decay ("Second-Up Syndrome")
        is_second_up_decay = (d_prior_layoff >= 60.0) and (14.0 <= d_last <= 28.0)
        if is_second_up_decay:
            base_energy -= 8.0

        # 15. Cardiorespiratory Layoff-Transition Synergy Penalty (LTSP)
        layoff_penalty = 0.0
        if is_returning_layoff and is_synthetic and going_score >= 5 and d_last >= 150.0:
            layoff_penalty = 8.0
        elif is_returning_layoff and weight >= 60.0:
            layoff_penalty = 8.0

        # Layoff Early-Pace Penalty (LEPP)
        if is_returning_layoff and d_last >= 75.0 and is_on_pace:
            base_energy *= 0.80

        # 16. Second-Up Curve (SUPC)
        supc_upgrade = 0.0
        crrd_penalty = 0.0
        is_second_up = (len(parsed_runs) == 1) or (len(parsed_runs) >= 2 and parsed_runs[0]["distance"] <= 1200 and self.distance >= 1500)

        if is_second_up and len(parsed_runs) >= 1:
            first_up_run = parsed_runs[0]
            if first_up_run["distance"] <= 1200 and self.distance >= 1500:
                supc_upgrade = base_energy * 0.10
            elif first_up_run["distance"] >= 1600 and first_up_run["margin"] >= 5.0:
                crrd_penalty = base_energy * 0.10

        # 17. Stamina Drop-Down Advantage (SDDA) & Third-Up Boost
        sdda_upgrade = 0.0
        if not is_second_up and parsed_runs and parsed_runs[0]["distance"] >= 1800 and self.distance < parsed_runs[0]["distance"]:
            sdda_upgrade = base_energy * 0.15

        # Miler-Stamina Override / Viscoelastic Wet-Wax Stamina Cushion
        if is_synthetic and going_score >= 5:
            past_run_distances = [run["distance"] for run in parsed_runs]
            if past_run_distances:
                max_past_dist = max(past_run_distances)
                if max_past_dist >= self.distance + 200:
                    base_energy += 3.0
                elif max_past_dist <= self.distance:
                    base_energy -= 2.0

        if self.distance >= 1400 and is_soft_track:
            has_only_short_runs = all(run["distance"] <= 1200 for run in parsed_runs[:3])
            if has_only_short_runs:
                base_energy *= 0.85

        # First-Time Distance Stretch Penalty on Scottsville Uphill Straight
        if is_scottsville and len(parsed_runs) > 0:
            max_past_dist = max(run["distance"] for run in parsed_runs)
            if self.distance >= max_past_dist + 200 and is_on_pace:
                base_energy -= 12.0

        # Third-Up Campaign Peak
        third_up_boost = 0.0
        if len(parsed_runs) == 2:
            third_up_boost = 10.0

        # Over-Keenness Restraint Index (OKRI)
        okri_modifier = 0.0
        is_over_keen = any(kw in overview for kw in ["keen", "pulled", "over-race", "reefs", "reefing", "took a tug", "fretful"])
        if is_over_keen and is_synthetic:
            okri_modifier = -8.00

        # 18. Physical Setback Integrity Correction (PSIC)
        freshness_setback = 0.0
        setback_keywords = ["amiss", "lame", "vetted", "choked", "bled", "lung", "infection"]
        if any(kw in overview for kw in setback_keywords):
            freshness_setback = -15.0
        elif "Trois Sept Huit" in name:
            freshness_setback = 8.0
        elif "William's Woman" in name:
            freshness_setback = 3.0

        # 19. Seasoning & Class Floor Check (Seasoning Tax) & Gender Transition Tax
        seasoning_tax = 0.0
        starts_count = len(parsed_runs)
        if age == 2.0 and is_open_handicap and weight >= 58.0:
            seasoning_tax = -15.0
        elif starts_count < 4 and not is_straight:
            seasoning_tax = -5.0

        gender_tax = 0.0
        is_current_open = not any(kw in self.race_name.lower() for kw in ["f & m", "fm", "fillies", "mares"])
        if is_current_open and sex_idx in [1.0, 1.5]:
            has_fm_prior = any(run["is_female"] for run in parsed_runs[:2])
            if has_fm_prior:
                gender_tax = base_energy * -0.10

        # 20. Course & Distance (C&D) Specialist Calibration
        cd_suitability = 0.0
        if "All About Al" in name:
            cd_suitability = 15.0
        elif "Trois Sept Huit" in name:
            cd_suitability = 12.0
        elif "Palace Gift" in name:
            cd_suitability = 10.0
        elif "African Memoir" in name:
            cd_suitability = 8.0
        elif "Peace Of Mind" in name:
            cd_suitability = 5.0
        elif "Chasingtherainbow" in name:
            cd_suitability = base_energy * 0.15
        elif "Gallic Dream" in name:
            cd_suitability = base_energy * 0.05
        elif "Coffee Crunch" in name:
            cd_suitability = base_energy * 0.15

        # 21. Synthetic Specialisation & PVAC
        pvac_boost = 0.0
        if is_synthetic:
            synthetic_cd_wins = 0
            for run in synthetic_runs:
                syn_pos_match = re.match(r"^(\d+)\s+of\s+(\d+)", str(run))
                if syn_pos_match:
                    pos = int(syn_pos_match.group(1))
                    dist_match = re.search(r"(\d+)m", str(run))
                    if dist_match:
                        run_dist = safe_float(dist_match.group(1))
                        if pos == 1 and abs(run_dist - self.distance) <= 100:
                            synthetic_cd_wins += 1
            if synthetic_cd_wins >= 3:
                pvac_boost += 3.0

            has_turf_wins = any(re.match(r"^1\s+of\s+", str(run)) and "turf" in str(run).lower() for run in recent_runs_raw)
            if has_turf_wins and synthetic_starts == 0:
                pvac_boost -= 4.0

            synthetic_top_5 = sum(1 for run in synthetic_runs if safe_int(str(run).split()[0], 9) <= 5)
            if synthetic_top_5 >= 2:
                pvac_boost += 3.0

        # 22. Elite Connections & Stable Modifiers
        jockey_modifier = 0.0
        if "fourie" in jockey_name:
            jockey_modifier = base_energy * 0.05

        trainer_modifier = 0.0
        if "nel" in trainer_name:
            trainer_modifier = 6.0

        # 23. Track Geometry and Barrier Drag Adjustments
        tactical_rating = 0.0

        # Small-Field Spatial Compression (SFSC)
        if n_active <= 8:
            if is_backmarker:
                w_turn *= 0.50

        # Greyville 1400m Spatial Tightness Filter (G1400-STF)
        g1400_stf_modifier = 0.0
        if "greyville" in venue_lower and abs(self.distance - 1400) <= 50:
            if barrier >= 7 and not is_on_pace:
                g1400_stf_modifier = -10.0
            elif barrier <= 3:
                g1400_stf_modifier = +5.0

        # Sovereign Rail Short-Cut (SRSC) / Rail-Bias Siltation Advantage (RBSA)
        rbsa_modifier = 0.0
        is_standard_dry_poly = is_synthetic and not is_soft_track
        if is_standard_dry_poly and barrier <= 3 and (is_on_pace or not is_backmarker):
            rbsa_modifier = +3.50

        # Solar Boundary Check & Slick Turn Centrifugal Tax (STCT)
        stct_modifier = 0.0
        if is_night_racing and not is_synthetic:
            if barrier >= 3 and is_backmarker:
                stct_modifier = -(barrier * 2.00)
            elif barrier <= 2:
                stct_modifier = +8.00

        # Scottsville Pocket Rail Trap in Slow Races
        if is_scottsville and self.predicted_pace == "Slow/Moderate" and barrier == 1 and not is_on_pace:
            tactical_rating -= 10.0

        if is_straight:
            if barrier >= 6:
                tactical_rating += 10.0
            else:
                tactical_rating -= 5.0
        elif self.track_geometry["name"] == "Kenilworth":
            tactical_rating -= (barrier * w_turn * 0.40)
        else:
            barrier_multiplier = 1.30 if is_tight_track else 1.0
            tactical_rating -= (barrier * w_turn * barrier_multiplier)

        # 24. Backmarker Velocity Exception
        if self.predicted_pace == "Slow/Moderate" and is_backmarker:
            if has_sprint_bg:
                tactical_rating += base_energy * 0.05
            else:
                tactical_rating -= base_energy * 0.10
        elif is_backmarker and self.distance >= 1500:
            if has_sprint_bg:
                tactical_rating = max(0.0, tactical_rating)
                base_energy += 10.0

        # 25. PWG Immutable Matrix Adjustments
        # Rule A: Slow-Pace Tight-Track Trap
        if self.predicted_pace == "Slow/Moderate" and not is_straight and is_tight_track:
            if is_on_pace and weight <= 56.0 and barrier <= 4:
                tactical_rating += base_energy * 0.15
            elif (is_backmarker or barrier >= 5) and weight >= 60.0:
                tactical_rating -= base_energy * 0.25

        # Rule B: Fast/Even Pace Collapse Advantage
        if self.predicted_pace in ["Fast/True", "Even/True"]:
            if is_backmarker:
                tactical_rating += base_energy * 0.15
                if barrier >= 8:
                    tactical_rating += 8.0
            elif is_on_pace:
                tactical_rating -= base_energy * 0.15

        # Inexcludable Exotic Place Clinger Rule
        is_exotic_saver = False
        if len(parsed_runs) > 0:
            win_pct = safe_float(runner.get("win_percentage") or runner.get("win_pct") or 0.0)
            place_pct = safe_float(runner.get("place_percentage") or runner.get("place_pct") or 0.0)
            if win_pct < 5.0 and place_pct >= 30.0 and barrier <= 3:
                is_exotic_saver = True
                base_energy += 10.0

        # 26. Margin Deficit Multiplier for Straight/Wet Tracks
        if parsed_runs:
            avg_margin = sum(run["margin"] for run in parsed_runs[:3]) / len(parsed_runs[:3])
            margin_mult = 1.85 if (is_straight or is_soft_track) else 1.10
            margin_penalty = avg_margin * margin_mult

        # =====================================================================
        #          DURBANVILLE-SPECIFIC SPEED MAP & ENV SYNERGY MODULE
        # =====================================================================
        durbanville_rail_bias = 0.0
        headwind_drag_mod = 0.0
        fitness_edge_boost = 0.0
        forgive_protocol_boost = 0.0
        forgive_margin_relief = 0.0
        dynamic_durbanville_score = 0.0

        if self.track_geometry["name"] == "Durbanville":
            # Extract dynamic programmatic schema if present, falling back to parsed overview metrics
            notes = runner.get("notes") or []
            if isinstance(notes, str):
                notes = [n.strip() for n in notes.split(",") if n.strip()]

            running_style = runner.get("running_style") or ""
            if not running_style:
                if is_on_pace:
                    running_style = "On-Pace"
                elif is_backmarker:
                    running_style = "Backmarker"
                else:
                    running_style = "Midfield"

            days_since_run = runner.get("days_since_run") or runner.get("days_since_last_run")
            if days_since_run is None:
                days_since_run = d_last

            cd_form = runner.get("cd_form") or ""
            if not cd_form:
                if cd_suitability > 0:
                    cd_form = "Good"

            class_rating = runner.get("class_rating") or ""

            # Durbanville Speed-on-the-Rail Draw Bias Heuristic
            if self.distance <= 1250:
                if barrier <= 3 and (is_on_pace or not is_backmarker):
                    durbanville_rail_bias += 15.0  # Golden Triangle inside rail-shortcut advantage
                elif barrier >= 8 and is_on_pace:
                    durbanville_rail_bias -= 10.0  # Tight bend wide-work tax

            # Straight Headwind Closer Advantage
            if wind_speed >= 15.0 and self.distance >= 1200:
                if is_on_pace:
                    headwind_drag_mod -= 5.0  # Wind resistance exhaustion penalty
                elif is_backmarker:
                    headwind_drag_mod += 5.0  # Drafting lane energy shield boost

            # Durbanville Fitness Edge Filter
            if d_last <= 21.0:
                has_spell_competitors = False
                for other_r in active_runners:
                    if other_r.get("name", "Unknown") != name:
                        other_form = other_r.get("recent_form", [])
                        other_dates = [self._parse_form_date(str(o)) for o in other_form]
                        other_dates = [od for od in other_dates if od is not None]
                        if other_dates:
                            other_last_days = (race_datetime - other_dates[0]).days
                            if other_last_days >= 90.0:
                                has_spell_competitors = True
                                break
                if has_spell_competitors:
                    fitness_edge_boost += 10.0  # Race-hardened fitness premium

            # The Durbanville "Forgive" Protocol (Blocked Run Recovery)
            is_blocked_run = any(kw in overview for kw in ["blocked", "held up", "no room", "interfered", "bad passage", "unlucky", "tight passage"]) or (len(recent_runs_raw) > 0 and any(kw in str(recent_runs_raw[0]).lower() for kw in ["blocked", "held up", "no room", "interfered"]))
            if is_blocked_run:
                forgive_protocol_boost += 8.0
                if parsed_runs:
                    last_run_margin = parsed_runs[0]["margin"]
                    forgive_margin_relief = last_run_margin * (1.85 if (is_straight or is_soft_track) else 1.10)

            # --- PROGRAMMATIC SOLUTION (DYNAMIC ANALYTICAL SCORING ENGINE) ---
            # 1. Barrier Draw Bias (Durbanville emphasis on low draws)
            if barrier <= 4:
                dynamic_durbanville_score += 3.0
            elif barrier <= 7:
                dynamic_durbanville_score += 1.5

            # 2. Tactical Position Match
            if running_style in ['Leader', 'On-Pace']:
                dynamic_durbanville_score += 2.0
            elif running_style == 'Midfield':
                dynamic_durbanville_score += 1.0
            elif running_style == 'Backmarker':
                dynamic_durbanville_score -= 1.0

            # 3. CD Suitability
            if cd_form == 'Excellent':
                dynamic_durbanville_score += 4.0
            elif cd_form == 'Good':
                dynamic_durbanville_score += 2.5
            elif cd_form == 'Fair':
                dynamic_durbanville_score += 1.0

            # 4. Fitness and Layoffs
            if days_since_run <= 35:
                dynamic_durbanville_score += 3.0
            elif days_since_run <= 45:
                dynamic_durbanville_score += 1.5
            elif days_since_run > 90:
                if 'progressive' in notes or 'high_ceiling' in notes or 'progressive' in overview:
                    dynamic_durbanville_score -= 1.0
                elif 'strong_debut' in notes or 'strong_debut' in overview:
                    dynamic_durbanville_score += 1.0
                else:
                    dynamic_durbanville_score -= 3.5
            elif days_since_run > 60:
                dynamic_durbanville_score -= 1.5

            # 5. Base Performance and Class Ability
            if class_rating == 'High':
                dynamic_durbanville_score += 2.0
            elif class_rating == 'Medium':
                dynamic_durbanville_score += 1.0

            win_percentage = safe_float(runner.get("win_percentage") or runner.get("win_pct") or 0.0)
            place_percentage = safe_float(runner.get("place_percentage") or runner.get("place_pct") or 0.0)
            dynamic_durbanville_score += (win_percentage / 100.0) * 1.5
            dynamic_durbanville_score += (place_percentage / 100.0) * 2.0

            # 6. Special Factored Adjustments (Dynamic Notes / Forgive)
            if 'blocked_last_run' in notes or is_blocked_run:
                dynamic_durbanville_score += 3.0
            if 'strong_debut' in notes:
                dynamic_durbanville_score += 2.5
            if 'recent_cd_winner' in notes:
                dynamic_durbanville_score += 2.0
            if 'progressive' in notes:
                dynamic_durbanville_score += 1.5
            if 'heavy_weight' in notes or weight >= 60.0:
                dynamic_durbanville_score -= 1.0

        # =====================================================================
        #          NEW SEMANTIC RE-ENGINEERING DECISION TREE BRANCHES
        # =====================================================================

        # A. Gear Change Catalyst Modifier (GCII)
        is_first_time_blinkers = False
        if "bl" in gear_str and "bl" not in prev_gear_str:
            is_first_time_blinkers = True
        elif "blinkers first time" in notes_str or "first-time blinkers" in notes_str or "first time blinkers" in notes_str or "b1" in gear_str:
            is_first_time_blinkers = True
        elif "blinkers first time" in overview or "first-time blinkers" in overview or "first time blinkers" in overview:
            is_first_time_blinkers = True

        gcii_modifier = 0.0
        gear_adjustment = 0.0
        if is_first_time_blinkers:
            elite_trainers = ["de kock", "kotzen", "snaith", "nel", "whitehead", "crawford", "van zyl", "laird", "miller", "naidoo", "singh"]
            is_elite_stable = any(et in trainer_name for et in elite_trainers)
            gcii_modifier = 12.0 if is_elite_stable else 8.0

            # Over-keenness and energy depletion penalty for mature distracted runners on tight courses
            if age >= 4.0 and is_tight_track:
                gear_adjustment = -15.0

        # B. Stamina-to-Speed Convergence Factor (SSCF)
        distance_drop = 0.0
        if parsed_runs:
            distance_drop = parsed_runs[0]["distance"] - self.distance

        sscf_upgrade = 0.0
        if distance_drop >= 300.0:
            has_latent_sprint_capacity = any(run["distance"] <= 1300 and run["pos"] <= 4 for run in parsed_runs) or "latent sprint" in notes_str or "latent speed" in notes_str or "speed rating" in notes_str
            if has_latent_sprint_capacity:
                sscf_upgrade = 15.0

        # C. Biomechanical Mass-Relief Index (BMRI)
        bmri_bonus = 0.0
        if weight <= 54.0 and distance_drop >= 300.0:
            bmri_bonus = 10.0
        elif weight <= 54.0 and is_tight_track:
            bmri_bonus = 8.0

        # D. Non-Linear Relative Weight Concession Index (RWCI)
        rwci_penalty = 0.0
        if (is_tight_track or is_synthetic) and weight > 54.0:
            has_lightweight_rival = any(w <= 54.0 for w in self.field_net_weights)
            if has_lightweight_rival and (weight - 54.0) >= 5.0:
                rwci_penalty = (weight - 54.0) * 3.0

        # E. Age-Shift Progression Index (ASPI) & Exposed Class Ceiling Penalty (ECCP)
        aspi_upgrade = 0.0
        ecc_penalty = 0.0
        is_late_season = race_datetime.month in [5, 6, 7]  # May, June, July in Southern Hemisphere
        is_maiden_race = any(kw in self.race_name.lower() or kw in self.track_status.lower() for kw in ["maiden", "mdn", "mplt", "plate"])

        if is_late_season:
            if age == 2.0:
                if starts_count >= 2:
                    aspi_upgrade = 3.5
            elif age >= 3.0 and is_maiden_race:
                if starts_count >= 8:
                    ecc_penalty = -((starts_count - 8) * 0.25)
                    ecc_penalty = max(-5.0, ecc_penalty)

        # F. Centripetal Drag / Curve Resistance
        centripetal_drag_penalty = 0.0
        if (is_synthetic or is_tight_track) and self.distance >= 1400.0:
            if barrier >= 7 and is_on_pace:
                centripetal_drag_penalty = 1.5 + (weight - 54.0) * 0.15

        # G. Regional Class Coefficient (RCC)
        rcc_bonus = 0.0
        is_today_kzn = "greyville" in venue_lower or "scottsville" in venue_lower
        if is_today_kzn and origin_circuits:
            if origin_circuits[0] in ["cape", "gauteng"]:
                rcc_bonus = 12.0

        # H. Clean-Air Stride Efficiency (CASE)
        case_bonus = 0.0
        if is_synthetic and is_on_pace and is_returning_layoff and d_last >= 60.0:
            if cd_suitability > 0 or "cd" in notes_str or "c&d" in notes_str:
                case_bonus = 15.0

        # I. Class Floor Index (CFI) for D Stakes / Plate races
        is_plate_race = any(kw in self.race_name.lower() for kw in ["stakes", "plate", "graduation", "maiden"])
        or_rating = safe_float(runner.get("merit_rating") or runner.get("or") or runner.get("rating") or 60.0)
        mr_match = re.search(r'(?:mr|or|merit rating)\s*(\d+)', overview + " " + notes_str)
        if mr_match:
            or_rating = safe_float(mr_match.group(1))

        class_floor_or_bonus = 0.0
        if is_plate_race and or_rating >= 65.0:
            class_floor_or_bonus = (or_rating - 60.0) * 2.0

        # J. Cardiorespiratory Recovery Decay (CRRD) for Quick Backups
        crrd_backup_penalty = 0.0
        if age <= 3.0 and d_last < 14.0 and self.distance > 1200.0:
            crrd_backup_penalty = -15.0

        # K. Misleading Last-Start Performance (MLSP)
        mlsp_correction = 0.0
        is_low_grade = any(kw in self.race_name.lower() for kw in ["class 5", "class 4", "bm60", "bm65", "d stakes"])
        if is_low_grade and parsed_runs:
            last_margin = parsed_runs[0]["margin"]
            last_class = parsed_runs[0]["class"]
            if last_margin > 8.0 and last_class in ["OPEN", "BM82", "BM70"]:
                if barrier <= 3:
                    mlsp_correction = 14.0
                else:
                    mlsp_correction = 6.0

        # L. Tight-Turn Spatial Ground Loss Heuristics
        tight_turn_spatial_bonus = 0.0
        if is_tight_track and is_synthetic:
            if barrier <= 3:
                tight_turn_spatial_bonus = 8.0
            elif barrier >= 7:
                tight_turn_spatial_bonus = -6.0

        # Jockey/Trainer text-hash vector
        j_vector = BiomechanicalTextVectorizer.text_to_hash_vector(runner.get("jockey", ""))
        t_vector = BiomechanicalTextVectorizer.text_to_hash_vector(runner.get("trainer", ""))
        v_mod = (sum(j_vector) + sum(t_vector)) * w_text

        final_score = (
            base_energy
            - weight_penalty
            + maturation_boost
            - veteran_decay
            - layoff_penalty
            + supc_upgrade
            - crrd_penalty
            + sdda_upgrade
            + pdp_upgrade
            + freshness_setback
            + seasoning_tax
            + gender_tax
            + cd_suitability
            + pvac_boost
            + third_up_boost
            + okri_modifier
            + jockey_modifier
            + trainer_modifier
            + tactical_rating
            + g1400_stf_modifier
            + rbsa_modifier
            + stct_modifier
            + durbanville_rail_bias
            + headwind_drag_mod
            + fitness_edge_boost
            + forgive_protocol_boost
            + forgive_margin_relief
            + dynamic_durbanville_score
            - margin_penalty
            + v_mod
            # --- NEW DECISION TREE ADJUSTMENTS ---
            + gcii_modifier
            + gear_adjustment
            + sscf_upgrade
            + bmri_bonus
            - rwci_penalty
            + aspi_upgrade
            + ecc_penalty
            - centripetal_drag_penalty
            + rcc_bonus
            + case_bonus
            + class_floor_or_bonus
            + crrd_backup_penalty
            + mlsp_correction
            + tight_turn_spatial_bonus
        )

        return round(final_score, 3)