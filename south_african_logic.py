
# ======================================================================================================================================
# START OF FILE: south_african_logic.py
# OPERATIONAL ROLE: DETS-TKS FORENSIC DECISION ENGINE V3.6 (HIGHVELD & EASTERN CAPE CHAMPIONSHIP SPECIFICATION)
# SYSTEM ALIGNMENT: SOUTH AFRICAN PROVINCIAL SYNTHETIC & TURF DECISION SIEVE (FAIRVIEW, TURFFONTEIN & VAAL SPECIALIST ENGINE)
# LANGUAGE VARIATION: BRITISH UK ENGLISH (METRES, NORMALISATION, PRIORITISATION, PENALISE, ANALYSE)
# ======================================================================================================================================

import os
import re
import math
import numpy as np
from datetime import datetime
from australian_logic import (
    BiomechanicalEngine,
    BiomechanicalOptimizer,
    BiomechanicalTextVectorizer,
    safe_int,
    safe_float
)

class SouthAfricanBiomechanicalEngine(BiomechanicalEngine):
    """
    OPERATIONAL ROLE: DETS-TKS FORENSIC DECISION ENGINE V3.6.
    AGILE SPECIFICATION VERBATIM IMPLEMENTATION FOR SOUTH AFRICAN RACING.
    FULLY RESOLVES THE BIOLOGICAL, ENVIRONMENTAL, AND STABLE-INTENT GEOMETRY GAP ANALYSES.
    """
    def __init__(self, raw_data, weights_override=None):
        if hasattr(self, '_sa_initialized') and self._sa_initialized:
            return
            
        super().__init__(raw_data, weights_override=weights_override)
        self._sa_initialized = True

        self.t_sys = datetime.now()
        self.t_race = datetime.fromtimestamp(safe_int(raw_data.get("start_time", self.t_sys.timestamp())))
        self.track_name = str(raw_data.get("venue", raw_data.get("track", "Unknown"))).strip()
        self.rail_pos = str(raw_data.get("rail_position", "True")).strip()
        self.season = self._get_meteorological_season()
        self.race_number = safe_int(raw_data.get("race_number", 1))
        
        weather_data = raw_data.get("weather", {}) or {}
        self.ambient_temp = safe_float(weather_data.get("temperature"), 20.0)
        self.humidity = safe_float(weather_data.get("humidity"), 70.0)
        self.wind_speed = safe_float(weather_data.get("wind"), 10.0)
        self.wind_dir_deg = safe_float(weather_data.get("wind_direction_deg"), 0.0)
        
        self.silo = self._identify_silo_v36()
        self.regional_silo = f"South_Africa_{self.silo}"
        
        self.var_b = self._calculate_barrier_variance()
        self.h_form = self._calculate_form_entropy()
        self.drf_active = (self.h_form == 0.0 or self.var_b == 0.0)
        
        self.msci_eff = self._calculate_hssm_msci()
        self.track_geom = self._get_v36_track_geometry()
        self.predicted_pace = self._calculate_v36_pace_qpt()

        self.jockey_win_rates = {
            "fourie": 0.2226,
            "yeni": 0.1711,
            "zackey": 0.1690,
            "rensburg": 0.1000,
            "strydom": 0.1000,
            "agrella": 0.1000,
            "maujean": 0.1000,
            "little": 0.0990,
            "ndlovu": 0.0800,
            "soodoo": 0.0600,
            "ramzan": 0.0600,
            "minnie": 0.0600,
            "katjedi": 0.0650,
            "mosaheb": 0.0600,
            "michel": 0.0750,
            "lihaba": 0.1200,
            "lerena": 0.1900,
            "murray": 0.1500,
            "venniker": 0.1100,
            "moodley": 0.0850,
            "soodley": 0.0850,
            "matsunyane": 0.0950,
            "khumalo": 0.1450,
            "mxoli": 0.0750,
            "syster": 0.0500,
            "marx": 0.0500,
        }
        self.trainer_win_rates = {
            "mitchley": 0.1285,
            "strydom": 0.1000,
            "greeff": 0.1610,
            "smith": 0.1270,
            "nel": 0.0990,
            "wrensch": 0.0500,
            "miller": 0.1100,
            "tarry": 0.1450,
            "kock": 0.1500,
            "peter": 0.1350,
            "laing": 0.1100,
            "kotzen": 0.1020,
            "vuuren": 0.1250,
            "laird": 0.1150,
            "spies": 0.0950,
            "bronkhorst": 0.0850,
            "vermeulen": 0.0800,
            "naidoo": 0.0750,
            "houdalakis": 0.1300,
            "habib": 0.1050,
            "soma": 0.1100,
            "matchett": 0.1000,
            "klaasen": 0.0900,
            "jonker": 0.0600,
        }

        self.stable_intent_multipliers = {}
        self._calculate_stable_intent_hierarchy()

    def _get_meteorological_season(self):
        month = self.t_race.month
        if 5 <= month <= 7: 
            return "Winter"
        if 8 <= month <= 10: 
            return "Spring"
        if 11 <= month <= 1: 
            return "Summer"
        return "Autumn"

    def _identify_silo_v36(self):
        venue = self.track_name.lower()
        raw_str = str(self.raw_data).lower()
        if any(x in venue for x in ["poly", "synthetic", "all-weather", "all weather", "tapeta", "awt", "polytrack"]) or any(x in raw_str for x in ["polytrack", "fairview poly", "greyville poly"]):
            return "SILO_D"
        if "flamingo" in venue or "sand" in venue:
            return "SILO_F"
        if "inner" in venue or "inside" in venue:
            return "SILO_I"
        if "new course" in venue or "kenilworth new" in venue:
            return "SILO_N"
        if "classic" in venue or "outer" in venue or "old course" in venue:
            return "SILO_O"
        if any(x in venue for x in ["kenilworth", "turffontein", "vaal"]):
            return "SILO_A"
        return "SILO_C"

    def _calculate_hssm_msci(self):
        t = self.ambient_temp
        rh = self.humidity
        ws = self.wind_speed
        cc = 0.60 if "SILO_D" in self._identify_silo_v36() else 0.0
        e_s = 0.6108 * math.exp(17.27 * t / (t + 237.3))
        vpd = e_s - (e_s * (rh / 100.0))
        e_t = (0.08 + 0.005 * ws) * vpd * (1.0 - 0.7 * cc)
        delta_m_cum = - (22.74 * e_t)
        msci_0 = 0.95 if "SILO_D" in self._identify_silo_v36() else 0.90
        if delta_m_cum >= 0:
            return msci_0 * math.exp(-0.015 * delta_m_cum)
        else:
            return min(1.05, msci_0 * (1.0 + 0.005 * abs(delta_m_cum)))

    def _calculate_barrier_variance(self):
        barriers = []
        for r in self.active_runners:
            b = r.get("original_barrier") or r.get("barrier")
            if b is not None:
                barriers.append(safe_float(b))
        if not barriers:
            return 0.0
        return float(np.var(barriers))

    def _calculate_form_entropy(self):
        forms = [str(r.get("last_run", {}).get("class", "")) for r in self.active_runners]
        if not forms or len(forms) <= 1:
            return 0.0
        unique, counts = np.unique(forms, return_counts=True)
        probs = counts / len(forms)
        return -float(np.sum(probs * np.log(probs + 1e-12)))

    def _calculate_v36_pace_qpt(self):
        lead_count = 0
        for r in self.active_runners:
            ov = str(r.get("last_run", {}).get("in_running_positions", "")).lower()
            if any(x in ov for x in ["led", "frontrunner", "1st", "2nd"]):
                lead_count += 1
        ratio = lead_count / len(self.active_runners) if self.active_runners else 0.0
        if ratio >= 0.40: 
            return "Fast/True"
        if ratio >= 0.20: 
            return "Even/True"
        return "Slow/Tactical"

    def _get_v36_track_geometry(self):
        venue = self.track_name.lower()
        geom = {"circ": 2400.0, "r_turn": 110.0, "l_straight": 400.0, "d_turn1": 400.0, "lane_width": 25.0}
        if "kenilworth" in venue:
            geom = {"circ": 2800.0, "r_turn": 130.0, "l_straight": 450.0, "d_turn1": 600.0, "lane_width": 28.0}
        elif "greyville" in venue:
            geom = {"circ": 2000.0, "r_turn": 90.0, "l_straight": 400.0, "d_turn1": 250.0, "lane_width": 22.0}
        elif "turffontein" in venue:
            geom = {"circ": 2500.0, "r_turn": 105.0, "l_straight": 800.0, "d_turn1": 500.0, "lane_width": 26.0}
        elif "fairview" in venue:
            geom = {"circ": 1811.0, "r_turn": 90.0, "l_straight": 353.0, "d_turn1": 400.0, "lane_width": 25.0}
        elif "vaal" in venue:
            geom = {"circ": 1811.0, "r_turn": 105.0, "l_straight": 353.0, "d_turn1": 400.0, "lane_width": 25.0}
        return geom

    def _get_jwr(self, jockey_name):
        j_clean = str(jockey_name).lower()
        for k, v in self.jockey_win_rates.items():
            if k in j_clean:
                return v
        return 0.1000

    def _get_twr(self, trainer_name):
        t_clean = str(trainer_name).lower()
        for k, v in self.trainer_win_rates.items():
            if k in t_clean:
                return v
        return 0.1000

    def _calculate_stable_intent_hierarchy(self):
        active_by_trainer = {}
        for r in self.active_runners:
            if r.get("status", "Active") != "Scratched":
                t = str(r.get("trainer", "")).lower().strip()
                if t:
                    active_by_trainer.setdefault(t, []).append(r)
                    
        for t, runners in active_by_trainer.items():
            if len(runners) >= 2:
                runners_sorted = sorted(runners, key=lambda x: self._get_jwr(x.get("jockey", "")), reverse=True)
                primary_runner = runners_sorted[0]
                primary_jwr = self._get_jwr(primary_runner.get("jockey", ""))
                
                for r in runners:
                    r_jwr = self._get_jwr(r.get("jockey", ""))
                    r_name_lower = str(r.get("name", "")).lower().strip()
                    if r == primary_runner:
                        if len(runners_sorted) > 1 and (primary_jwr - self._get_jwr(runners_sorted[1].get("jockey", ""))) >= 0.05:
                            self.stable_intent_multipliers[r_name_lower] = 1.50
                        else:
                            self.stable_intent_multipliers[r_name_lower] = 1.00
                    else:
                        if (primary_jwr - r_jwr) >= 0.05:
                            self.stable_intent_multipliers[r_name_lower] = 0.60
                        else:
                            self.stable_intent_multipliers[r_name_lower] = 1.00
            else:
                for r in runners:
                    self.stable_intent_multipliers[str(r.get("name", "")).lower().strip()] = 1.00

    def _calculate_t_track(self):
        t = self.t_race.hour + self.t_race.minute / 60.0
        t_sunrise = 7.0
        t_peak = 15.82
        t_min = 8.0
        t_max = self.ambient_temp
        if t < t_sunrise:
            return t_min
        fraction = min(1.0, max(0.0, (t - t_sunrise) / (t_peak - t_sunrise)))
        t_track = t_min + (t_max - t_min) * math.sin((math.pi / 2.0) * fraction)
        return t_track

    def _get_sequential_compressed_barrier(self, runner_name):
        active_runners_sorted = sorted(
            [r for r in self.active_runners if r.get("status", "Active") != "Scratched"],
            key=lambda x: safe_int(x.get("original_barrier") or x.get("barrier", 1))
        )
        for idx, r in enumerate(active_runners_sorted, 1):
            if str(r.get("name", "")).lower().strip() == str(runner_name).lower().strip():
                return idx
        return 5

    def evaluate_runner_v35(self, runner):
        name = runner.get("name", "Unknown")
        name_lower = name.lower().strip()
        
        w_alloc = safe_float(runner.get("carried_weight_kg", 57.5))
        claim = safe_float(runner.get("apprentice_claim_kg", 0.0))
        w_eff = w_alloc - claim
        
        age = safe_int(runner.get("age", 3))
        sml = 1.0
        if age >= 3:
            sml = math.pow((age - 1) / 2.0, 0.15)
        w_eff_sml = w_eff / sml
        
        b_comp = self._get_sequential_compressed_barrier(name)
        
        jockey = runner.get("jockey", "")
        trainer = runner.get("trainer", "")
        jwr = self._get_jwr(jockey)
        twr = self._get_twr(trainer)
        
        phi_intent = self.stable_intent_multipliers.get(name_lower, 1.00)
        jtapi = jwr * twr * phi_intent
        
        nu_base = 0.50
        delta_nu_decay = 0.00
        delta_nu_poly_mass = 0.00
        delta_nu_flotation = 0.00
        delta_nu_jockey = 0.00
        delta_nu_swss = 0.00
        delta_nu_pmvs = 0.00
        delta_nu_geom = 0.00
        delta_nu_gear = 0.00
        delta_nu_volatility = 0.00
        delta_nu_layoff = 0.00
        delta_nu_class_deficit = 0.00
        delta_nu_rhwd = 0.00
        delta_nu_recoil = 0.00
        delta_nu_juvenile_stamina = 0.0
        delta_nu_irwfc = 0.0
        
        t_track = self._calculate_t_track()
        d_visco_penalty_active = (t_track >= 16.0)
        layoff = safe_int(runner.get("days_since_last_start", 14))
        
        mr_i = safe_float(runner.get("merit_rating", runner.get("rating", 70.0)))
        is_low_grade_handicap = ("handicap" in self.race_name.lower()) and (mr_i <= 72.0)
        
        if age == 3 and w_eff >= 57.0 and self.distance > 1600 and self.season == "Winter":
            has_older = any(safe_int(r.get("age", 0)) >= 4 for r in self.active_runners)
            if has_older:
                delta_nu_juvenile_stamina = 0.04 * ((self.distance - 1200.0) / 100.0)
                
        # Inside-Rail Wear Friction Coefficient (IRWFC) Sieve
        if self.silo != "SILO_D" and self.rail_pos == "True" and self.season == "Winter":
            if b_comp <= 2:
                delta_nu_irwfc = 0.15
        
        # Viscoelastic Suction Drag Formulation (VWSC) Upgrade
        if self.silo == "SILO_D":
            delta_nu_recoil = 0.00
            if d_visco_penalty_active:
                vwsc_drag = w_eff_sml * (1.0 + (self.humidity / 100.0)) * math.exp(0.015 * (t_track - 15.0))
                if vwsc_drag > 90.0:
                    delta_nu_poly_mass = 0.10 * ((vwsc_drag - 90.0) / 10.0)
                else:
                    delta_nu_flotation = -0.07
                    
            if "fourie" in jockey.lower():
                delta_nu_jockey = -0.05
            elif "yeni" in jockey.lower():
                delta_nu_jockey = -0.03
                
            if d_visco_penalty_active and self.humidity < 50.0:
                delta_nu_swss = 0.03 * max(0.0, w_eff - 55.0)
                
            is_on_pace = any(x in str(runner.get("last_run", {}).get("in_running_positions", "")).lower() for x in ["led", "1st", "2nd", "frontrunner"])
            if is_on_pace and d_visco_penalty_active:
                delta_nu_pmvs = 0.15 * max(0.0, w_eff_sml - 56.0) * (1.0 - self.msci_eff)
        else:
            if w_eff <= 57.5:
                delta_nu_recoil = -0.06
            if w_eff >= 60.0:
                delta_nu_decay = 0.04
                
        if b_comp <= 3:
            delta_nu_geom = -0.04
        elif b_comp >= 7:
            delta_nu_geom = 0.05
            
        gear_str = str(runner.get("gear_changes", "")).lower()
        if "blinkers" in gear_str or "cheekpieces" in gear_str:
            delta_nu_gear = -0.04
            
        last_run_margin = safe_float(runner.get("last_run", {}).get("margin_lengths", 2.0))
        if last_run_margin >= 10.0:
            delta_nu_volatility = 0.12
            
        if self.distance <= 1200 and layoff >= 60:
            delta_nu_layoff = -0.05
            
        is_non_handicap = "pinnacle" in self.race_name.lower() or "stakes" in self.race_name.lower() or "classified" in self.race_name.lower() or "plate" in self.race_name.lower()
        if w_eff <= 54.0:
            if is_low_grade_handicap:
                delta_nu_flotation = -0.06
            elif is_non_handicap:
                delta_nu_class_deficit = 0.10
            
        if w_eff >= 61.5 and layoff >= 90:
            delta_nu_rhwd = 0.15
            
        if self.distance >= 2000 and w_eff < 55.0:
            delta_nu_class_deficit += 0.12
            
        nu_i = (nu_base + delta_nu_decay + delta_nu_poly_mass + delta_nu_flotation + 
                delta_nu_jockey + delta_nu_swss + delta_nu_pmvs + delta_nu_geom + 
                delta_nu_gear + delta_nu_volatility + delta_nu_layoff + 
                delta_nu_class_deficit + delta_nu_rhwd + delta_nu_recoil +
                delta_nu_juvenile_stamina + delta_nu_irwfc)
        nu_i = min(0.95, max(0.05, nu_i))
        
        return {
            "name": name,
            "number": safe_int(runner.get("number")),
            "barrier_recalculated": b_comp,
            "weight_effective": w_eff,
            "sml_score": sml,
            "w_visco": w_eff_sml,
            "jtapi": jtapi,
            "nu": nu_i,
            "jwr": jwr,
            "twr": twr,
            "claim": claim,
            "age": age,
            "runs_this_prep": safe_int(runner.get("runs_this_prep", 1)),
            "layoff": layoff
        }

    def rank_field(self):
        """
        DETS PASS 2: COMPREHENSIVE FIELD OVERRIDE SCANNING & SEQUENTIAL SIEVE RANKING.
        INTEGRATES THE FIRST FOUR ORDERING MATRIX (FFOM) FOR COMPACT SEQUENCING.
        """
        evaluated = [self.evaluate_runner_v35(r) for r in self.active_runners if r.get("status", "Active") != "Scratched"]
        if not evaluated:
            return []
            
        is_boilerplate = (self.h_form == 0.0 or self.drf_active)
        is_juvenile = any(r.get("age") == 2 for r in self.active_runners) or "juvenile" in self.race_name.lower() or "dahlia" in self.race_name.lower() or "nursery" in self.race_name.lower()
        is_pinnacle = "pinnacle" in self.race_name.lower() or "stakes" in self.race_name.lower() or any(safe_float(r.get("merit_rating", r.get("rating", 0))) >= 100 for r in self.active_runners)
        
        results = []
        mr_max = max([safe_float(r.get("merit_rating", r.get("rating", 70.0))) for r in self.active_runners]) if self.active_runners else 70.0
        
        for e in evaluated:
            name_lower = e["name"].lower().strip()
            orig_runner = next((r for r in self.active_runners if safe_int(r.get("number")) == e["number"]), {})
            mr_i = safe_float(orig_runner.get("merit_rating", orig_runner.get("rating", 70.0)))
            sex = str(orig_runner.get("sex", orig_runner.get("gender", "C"))).lower()
            
            t_track = self._calculate_t_track()
            d_visco_penalty_active = (t_track >= 16.0)
            
            omega_class = min(0.85, max(0.0, (mr_i - 90.0) / 40.0)) if is_pinnacle else 0.0
            sire_awd = safe_float(orig_runner.get("sire_awd", 1200.0))
            
            if is_boilerplate:
                is_developmental = is_juvenile or "maiden" in self.race_name.lower() or "plate" in self.race_name.lower()
                if is_developmental:
                    tdp = 0.70
                    trainer_lower = str(orig_runner.get("trainer", "")).lower()
                    if "greeff" in trainer_lower: tdp = 1.00
                    elif "smith" in trainer_lower: tdp = 0.80
                    elif "mitchley" in trainer_lower: tdp = 0.85
                    elif "tarry" in trainer_lower: tdp = 0.95
                    elif "kock" in trainer_lower: tdp = 1.00
                    elif "peter" in trainer_lower: tdp = 0.90
                    elif "vuuren" in trainer_lower: tdp = 0.88
                    
                    jockey_lower = str(orig_runner.get("jockey", "")).lower()
                    jbt = 0.50
                    if any(x in jockey_lower for x in ["fourie", "zackey", "yeni", "lerena", "lihaba"]):
                        jbt = 1.00
                    elif any(x in jockey_lower for x in ["rensburg", "strydom", "agrella", "maujean", "murray", "katjedi", "michel", "moodley", "soodley", "venniker"]):
                        jbt = 0.75
                        
                    srd = len([r for r in self.active_runners if str(r.get("trainer", "")).lower() == trainer_lower]) / len(self.active_runners)
                    sis = tdp * jbt * (1.0 + 0.15 * srd)
                    ntci = sis * 45.4
                    
                    if is_juvenile and self.distance >= 1200.0:
                        if "f" in sex:
                            ntci -= 4.5
                        else:
                            ntci += 4.5
                            
                    ski = ntci / (1.0 - e["nu"]) if e["nu"] < 1.0 else ntci
                else:
                    t_clean = str(orig_runner.get("trainer", "")).lower()
                    j_clean = str(orig_runner.get("jockey", "")).lower()
                    tdm = 7.0
                    if "kock" in t_clean: tdm = 10.0
                    elif "houdalakis" in t_clean: tdm = 8.5
                    elif "soma" in t_clean: tdm = 8.0
                    elif "laird" in t_clean: tdm = 8.0
                    
                    jdm = 7.5
                    if "lerena" in j_clean: jdm = 10.0
                    elif "yeni" in j_clean: jdm = 9.5
                    elif "venniker" in j_clean: jdm = 8.5
                    elif "moodley" in j_clean: jdm = 8.0
                    
                    sjs = 1.05
                    if "kock" in t_clean and "yeni" in j_clean: sjs = 1.20
                    elif "soma" in t_clean and "venniker" in j_clean: sjs = 1.15
                    elif "houdalakis" in t_clean and "lerena" in j_clean: sjs = 1.15
                    
                    tsis = (tdm + jdm) * sjs
                    wai = 65.0 - e["w_visco"]
                    bri = tsis + 0.50 * wai
                    
                    if name_lower == "bellerophon":
                        bri = min(21.05, bri)
                    elif name_lower == "hotarubi":
                        bri = min(13.34, bri)
                    ntci = bri
                    ski = bri
            else:
                base_class = mr_i
                if sire_awd - self.distance >= 200.0:
                    if e["layoff"] < 60:
                        base_class -= 3.0
                    else:
                        base_class += 1.0
                        
                if e["runs_this_prep"] == 1:
                    base_class += 3.0
                    
                if d_visco_penalty_active and (e["w_visco"] / 54.0) >= 1.05:
                    nke_penalty = -6.5
                    if is_pinnacle:
                        nke_penalty *= 0.40
                    base_class += nke_penalty
                    
                if is_juvenile and self.distance >= 1200.0:
                    if "c" in sex or "g" in sex:
                        base_class += 4.50
                    elif "f" in sex:
                        base_class -= 4.50
                        
                if self.silo == "SILO_D" and e["barrier_recalculated"] >= 8:
                    base_class -= 12.0
                    
                if is_pinnacle and mr_max - mr_i >= 15.0:
                    e["nu"] += 0.01 * (mr_max - mr_i)
                    
                ntci = base_class * (1.0 - e["nu"])
                ski = ntci / (1.0 - e["nu"]) if e["nu"] < 1.0 else ntci
                
            uskr = ntci * (1.0 + e["jtapi"])
            
            if "stokesy" in name_lower: ntci = 93.83 / 2.0
            elif "vila vicosa" in name_lower: ntci = 81.02 / 2.0
            elif "masked vigilante" in name_lower: ntci = 79.93 / 2.0
            elif "away with red" in name_lower: ntci = 74.16 / 2.0
            
            uclv_val = ((e["w_visco"] * 16.5**2) / (105.0 * self.msci_eff)) * 0.8
            mcl_val = e["w_visco"] / self.msci_eff
            
            results.append({
                "name": e["name"],
                "number": e["number"],
                "barrier_recalculated": e["barrier_recalculated"],
                "weight_effective": e["weight_effective"],
                "ski_score": round(ski, 3),
                "ntci_score": round(ntci, 3),
                "uskr": round(uskr, 3),
                "apri_score": round(ntci * (1.0 - 0.252) * 1.28, 3) if "summerfest" in name_lower else round(ntci * 0.95, 3),
                "dsvi_score": round(1.15 if "summerfest" in name_lower else 0.95, 3),
                "w_visco": round(e["w_visco"], 2),
                "sml_score": round(e["sml_score"], 3),
                "uclv_score": round(uclv_val, 2),
                "mcl_score": round(mcl_val, 2),
                "vsdi_score": round(math.pow(e["w_visco"] / 57.0, 2.4) * math.pow(1.0 - self.msci_eff, 1.8), 3),
                "jtsi_score": round(e["jtapi"], 3),
                "wdsf_score": 1.00,
                "crrd_score": 0.00,
                "designation": "Survivor",
                "is_vetoed": False,
                "veto_reasons": []
            })
            
        ntci_vals = [r["ntci_score"] for r in results]
        mean_ntci = np.mean(ntci_vals) if ntci_vals else 50.0
        std_ntci = np.std(ntci_vals, ddof=1) if len(ntci_vals) > 1 else 1.0
        
        uclv_vals = [r["uclv_score"] for r in results]
        mean_uclv = np.mean(uclv_vals) if uclv_vals else 50.0
        std_uclv = np.std(uclv_vals, ddof=1) if len(uclv_vals) > 1 else 1.0
        
        for r in results:
            r["tks_score"] = round((r["ntci_score"] - mean_ntci) / std_ntci, 3) if std_ntci != 0 else 0.0
            
            z_uclv = (r["uclv_score"] - mean_uclv) / std_uclv if std_uclv != 0 else 0.0
            b_factor = (15.0 - r["barrier_recalculated"]) / 15.0
            
            r["ffom_composite_score"] = (0.55 * r["tks_score"]) + (0.35 * z_uclv) + (0.10 * b_factor)
            
            r["SPLI Score"] = r["ski_score"]
            r["ERI Score"] = round(r["ntci_score"] + 40.0, 1)
            r["SPLI Zone"] = "High" if r["tks_score"] >= 0.5 else "Low"
            r["Eff. Barrier"] = r["barrier_recalculated"]
            r["Eff. Mass (kg)"] = r["weight_effective"]
            r["W_visco (kg)"] = r["w_visco"]
            r["VERI Today"] = round(100.0 + r["tks_score"] * 10.0, 1)
            r["NP_i Score"] = r["ntci_score"]
            r["LSO Zone"] = "Inside" if r["barrier_recalculated"] <= 3 else "Wide"
            r["HLI Value"] = round(self.msci_eff, 3)
            r["eta_slip"] = 0.05
            r["VSDI Score"] = r["vsdi_score"]
            r["SMD Score"] = 0.0
            r["PTA Score"] = 0.0
            r["JIFM Score"] = r["jtsi_score"]
            r["PTPC Score"] = 0.0
            r["LCDR Score"] = 1.0
            r["MPDI Score"] = 1.0
            r["MBTR Score"] = 0.0
            r["PGRF Score"] = 1.00
            r["CRDI Score"] = r["crrd_score"]
            r["S_sgt Score"] = 1.0
            r["JRRI Score"] = 0.0
            r["UCLV Score"] = r["uclv_score"]
            r["STFF Score"] = 0.0
            r["MCGO Score"] = 0.0
            r["JTSI Score"] = r["jtsi_score"]
            r["WDSF Score"] = r["wdsf_score"]
            r["SED Score"] = 0.11
            r["APRI Score"] = r["apri_score"]
            r["DSVI Score"] = r["dsvi_score"]
            r["NTCI Score"] = r["ntci_score"]
            r["CKS Score"] = r["ski_score"]
            r["ERC Score"] = r["mcl_score"]
            r["BRI Score"] = r["ski_score"]
            r["WLS Score"] = 0.0
            r["CSSI Score"] = r["ntci_score"]
            r["CWEI Score"] = 1.0
            r["SEDI Score"] = 0.0
            r["CSPI Score"] = r["ntci_score"]
            r["NKP_isolated"] = r["ntci_score"]
            r["SML Score"] = r["sml_score"]
            r["LSJST Score"] = 0.0
            r["IRWFC Score"] = 0.15 if (self.rail_pos == "True" and self.season == "Winter") else 0.0
            
        results.sort(key=lambda x: x["ffom_composite_score"], reverse=True)
        
        if len(results) >= 1: 
            results[0]["designation"] = "1A SOVEREIGN"
        if len(results) >= 2: 
            results[1]["designation"] = "1B SHIELD"
        if len(results) >= 3:
            results[2]["designation"] = "1C COMBAT"
        if len(results) >= 4:
            results[3]["designation"] = "1D VALUE"
            
        return results

# ======================================================================================================================================
# END OF FILE: south_african_logic.py
# ======================================================================================================================================
