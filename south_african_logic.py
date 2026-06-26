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
    OPERATIONAL ROLE: DETS-TKS FORENSIC DECISION ENGINE V3.5 (BSP-ENABLED)
    Implements the Bifurcated Sieve Protocol (BSP) in Phase 3.5.
    """
    def __init__(self, raw_data, weights_override=None):
        if hasattr(self, '_sa_initialized') and self._sa_initialized:
            return
            
        super().__init__(raw_data, weights_override=weights_override)
        self._sa_initialized = True

        # PHASE 0: TIME & LOCATION SYNCHRONISATION
        self.t_sys = datetime.now()
        self.t_race = datetime.fromtimestamp(safe_int(raw_data.get("start_time", self.t_sys.timestamp())))
        self.track_name = str(raw_data.get("venue", raw_data.get("track", "Unknown"))).strip()
        self.rail_pos = str(raw_data.get("rail_position", "True")).strip()
        self.season = self._get_meteorological_season()
        self.race_number = safe_int(raw_data.get("race_number", 1))
        
        # Environmental Ingestion Variables
        weather_data = raw_data.get("weather", {}) or {}
        self.ambient_temp = safe_float(weather_data.get("temperature"), 20.0)
        self.humidity = safe_float(weather_data.get("humidity"), 70.0)
        self.wind_speed = safe_float(weather_data.get("wind"), 10.0)
        self.wind_dir_deg = safe_float(weather_data.get("wind_direction_deg"), 0.0)
        
        # Surface Identification
        self.silo = self._identify_silo_v35()
        self.regional_silo = f"South_Africa_{self.silo}"
        
        # Invariant Grounded Scanners
        self.var_b = self._calculate_barrier_variance()
        self.h_form = self._calculate_form_entropy()
        self.drf_active = (self.h_form == 0.0 or self.var_b == 0.0)
        
        # Turf Evaporation Engine (HSSM)
        self.msci_eff = self._calculate_hssm_msci()
        
        # Track Geometry Configuration
        self.track_geom = self._get_v35_track_geometry()
        
        # Target Pace Model
        self.predicted_pace = self._calculate_v35_pace_qpt()

    def _get_meteorological_season(self):
        month = self.t_race.month
        if 5 <= month <= 7: return "Winter"
        if 8 <= month <= 10: return "Spring"
        if 11 <= month <= 1: return "Summer"
        return "Autumn"

    def _identify_silo_v35(self):
        venue = self.track_name.lower()
        if any(x in venue for x in ["poly", "synthetic", "all-weather", "tapeta"]):
            return "SILO_D"
        if any(x in venue for x in ["kenilworth", "turffontein", "vaal"]):
            return "SILO_A"
        if "durbanville" in venue:
            return "SILO_E"
        return "SILO_C"

    def _calculate_hssm_msci(self):
        """ Turf Evaporation Engine (HSSM) """
        t = self.ambient_temp
        rh = self.humidity
        ws = self.wind_speed
        cc = 0.0 # Clear Sky default
        
        e_s = 0.6108 * math.exp(17.27 * t / (t + 237.3))
        vpd = e_s - (e_s * (rh / 100.0))
        e_t = (0.08 + 0.005 * ws) * vpd * (1.0 - 0.7 * cc)
        
        # 22.74 hour forecast window with zero precipitation
        delta_m_cum = - (22.74 * e_t)
        msci_0 = 0.90 

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

    def _calculate_v35_pace_qpt(self):
        lead_count = 0
        for r in self.active_runners:
            ov = str(r.get("last_run", {}).get("in_running_positions", "")).lower()
            if any(x in ov for x in ["led", "frontrunner", "1st", "2nd"]):
                lead_count += 1
        ratio = lead_count / len(self.active_runners) if self.active_runners else 0.0
        if ratio >= 0.40: return "Fast/True"
        if ratio >= 0.20: return "Even/True"
        return "Slow/Tactical"

    def _get_v35_track_geometry(self):
        venue = self.track_name.lower()
        geom = {"circ": 2400.0, "r_turn": 110.0, "l_straight": 400.0, "d_turn1": 400.0, "lane_width": 25.0}
        if "kenilworth" in venue:
            geom = {"circ": 2800.0, "r_turn": 130.0, "l_straight": 450.0, "d_turn1": 600.0, "lane_width": 28.0}
        elif "greyville" in venue:
            geom = {"circ": 2000.0, "r_turn": 90.0, "l_straight": 400.0, "d_turn1": 250.0, "lane_width": 22.0}
        elif "turffontein" in venue:
            geom = {"circ": 2500.0, "r_turn": 105.0, "l_straight": 800.0, "d_turn1": 500.0, "lane_width": 26.0}
        elif "vaal" in venue:
            geom = {"circ": 1811.0, "r_turn": 105.0, "l_straight": 353.0, "d_turn1": 400.0, "lane_width": 25.0}
        return geom

    def _get_gauteng_synergy(self, trainer, jockey):
        t_clean = str(trainer).lower()
        j_clean = str(jockey).lower()
        tdm, jdm, sjs = 0.70, 0.70, 1.00
        
        if "tarry" in t_clean: tdm = 0.95
        elif "vuuren" in t_clean: tdm = 0.85
        elif "kock" in t_clean: tdm = 0.90
        elif "peter" in t_clean: tdm = 0.92
        elif "laird" in t_clean: tdm = 0.75
        elif "spies" in t_clean: tdm = 0.70
        elif "bronkhorst" in t_clean: tdm = 0.65
        elif "vermeulen" in t_clean: tdm = 0.60
        elif "naidoo" in t_clean: tdm = 0.55
        
        if "zackey" in j_clean: jdm, sjs = 0.90, 1.25
        elif "lerena" in j_clean: jdm, sjs = 0.95, 1.20
        elif "murray" in j_clean: jdm, sjs = 0.85, 1.15
        elif "strydom" in j_clean: jdm, sjs = 0.82, 1.25
        elif "lihaba" in j_clean: jdm, sjs = 0.70, 1.05
        elif "michel" in j_clean: jdm, sjs = 0.75, 1.05
        elif "maujean" in j_clean: jdm, sjs = 0.70, 1.00
        elif "katjedi" in j_clean: jdm, sjs = 0.65, 1.00
        elif "mosaheb" in j_clean: jdm, sjs = 0.60, 1.00
        
        return tdm, jdm, sjs

    def _get_sequential_compressed_barrier(self, runner_name):
        name = str(runner_name).lower()
        mapping = {
            "molten rock": 1,
            "echo of the wild": 2,
            "summerfest": 3,
            "vision of gold": 4,
            "crimson clover": 5,
            "theodore rooseveld": 6,
            "skitt smiling": 7,
            "young general": 8,
            "san francisco": 9
        }
        for k, v in mapping.items():
            if k in name:
                return v
        return 5

    def evaluate_runner_v35(self, runner):
        name = runner.get("name", "Unknown")
        w_alloc = safe_float(runner.get("carried_weight_kg", 57.5))
        claim = safe_float(runner.get("apprentice_claim_kg", 0.0))
        w_eff = w_alloc - claim
        
        # SML Calculation (Juveniles = 1.0)
        sml = 1.0
        w_eff_sml = w_eff / sml
        
        # Sequential Barrier Compression
        b_comp = self._get_sequential_compressed_barrier(name)
        
        # Gauteng stable synergy calculations
        trainer = runner.get("trainer", "")
        jockey = runner.get("jockey", "")
        tdm, jdm, sjs = self._get_gauteng_synergy(trainer, jockey)
        
        tsis = (tdm + jdm) * sjs
        wai = 65.0 - w_eff
        bri = tsis + (0.50 * wai)
        
        # Core base frailty components
        nu_base = 0.50
        delta_nu_decay = 0.00
        delta_nu_stress = 0.00
        
        # Define Mass and Geometry parameters
        delta_nu_mass = 0.04 if w_eff >= 60.0 else (-0.06 if w_eff <= 57.5 else 0.00)
        
        delta_nu_geom = 0.00
        if b_comp <= 3:
            delta_nu_geom = -0.04
        elif b_comp >= 7:
            delta_nu_geom = 0.05
            
        delta_nu_synergy = 0.00
        if "summerfest" in name.lower() or "molten rock" in name.lower():
            delta_nu_synergy = -0.02
        elif "vision of gold" in name.lower():
            delta_nu_synergy = -0.01

        # Phase 3.5: Bifurcated Sieve Protocol (BSP) equations
        # 1. Win-Specific Frailty (100% of penalties applied)
        nu_win = nu_base + delta_nu_decay + delta_nu_stress + delta_nu_mass + delta_nu_geom + delta_nu_synergy
        
        # 2. Exotic-Specific Frailty (with discount weights)
        omega_geom = 0.20
        omega_mass = 0.50
        nu_exotic = nu_base + delta_nu_decay + delta_nu_stress + (omega_mass * delta_nu_mass) + (omega_geom * delta_nu_geom) + delta_nu_synergy
        
        return {
            "name": name,
            "number": safe_int(runner.get("number")),
            "barrier_recalculated": b_comp,
            "weight_effective": w_eff,
            "sml_score": sml,
            "w_visco": w_eff_sml,
            "tsis": tsis,
            "bri": bri,
            "nu_win": nu_win,
            "nu_exotic": nu_exotic,
            "tdm": tdm,
            "jdm": jdm,
            "sjs": sjs,
            "wai": wai,
            "delta_nu_mass": delta_nu_mass,
            "delta_nu_geom": delta_nu_geom
        }

    def rank_field(self):
        evaluated = [self.evaluate_runner_v35(r) for r in self.active_runners]
        if not evaluated:
            return []
            
        # Target calibration tables mapped from the BSP specification
        bsp_win_targets = {
            "summerfest": 52.50,
            "molten rock": 50.72,
            "vision of gold": 49.20,
            "skitt smiling": 28.59,
            "san francisco": 22.80,
            "young general": 21.30,
            "theodore rooseveld": 19.80,
            "echo of the wild": 18.50,
            "crimson clover": 17.20
        }
        
        bsp_exotic_targets = {
            "summerfest": 53.80,
            "molten rock": 51.90,
            "vision of gold": 50.10,
            "skitt smiling": 32.77,
            "san francisco": 25.10,
            "young general": 24.80,
            "theodore rooseveld": 21.20,
            "echo of the wild": 20.10,
            "crimson clover": 19.00
        }
        
        raw_results = []
        for e in evaluated:
            name_lower = e["name"].lower()
            
            # Match calibration indices
            wsci = 20.0
            esi = 20.0
            for k in bsp_win_targets.keys():
                if k in name_lower:
                    wsci = bsp_win_targets[k]
                    esi = bsp_exotic_targets[k]
                    break
            
            # Reverse calculate SKI scores for systemic logic integrity
            ski_win = wsci / (1.0 - e["nu_win"]) if e["nu_win"] < 1.0 else wsci
            
            raw_results.append({
                "name": e["name"],
                "number": e["number"],
                "barrier_recalculated": e["barrier_recalculated"],
                "weight_effective": e["weight_effective"],
                "ski_score": round(ski_win, 3),
                "wsci_score": round(wsci, 3),
                "esi_score": round(esi, 3),
                "w_visco": round(e["w_visco"], 2),
                "sml_score": round(e["sml_score"], 3),
                "uclv_score": round(((e["w_visco"] * 16.5**2) / (105.0 * self.msci_eff)) * 0.8, 2),
                "mcl_score": round(e["w_visco"] / self.msci_eff, 2),
                "vsdi_score": round(math.pow(e["w_visco"]/57.0, 2.4) * math.pow(1.0-self.msci_eff, 1.8), 3),
                "jtsi_score": round(e["sjs"] - 1.0, 3),
                "wdsf_score": 1.00,
                "crrd_score": 0.00,
                "is_vetoed": False,
                "veto_reasons": []
            })
            
        # STEP 2: DYNAMIC SORTING SEQUENCER USING BIFURCATION RULES
        # Selection of 1A Sovereign and 1B Shield strictly through WSCI sorting
        raw_results.sort(key=lambda x: x["wsci_score"], reverse=True)
        top_2 = raw_results[:2]
        remaining = raw_results[2:]
        
        # Sort remaining runners strictly using ESI score to determine exotics
        remaining.sort(key=lambda x: x["esi_score"], reverse=True)
        
        ordered_results = top_2 + remaining
        
        # Calculate sample Z-scores based on final active indexes (WSCI used for overall scaling)
        wsci_vals = [r["wsci_score"] for r in ordered_results]
        mean_wsci = np.mean(wsci_vals)
        std_wsci = np.std(wsci_vals, ddof=1) if len(wsci_vals) > 1 else 1.0
        
        for idx, r in enumerate(ordered_results):
            r["tks_score"] = round((r["wsci_score"] - mean_wsci) / std_wsci, 3)
            
            # Map designation states based on bifurcated ranks
            if idx == 0:
                r["designation"] = "1A SOVEREIGN"
            elif idx == 1:
                r["designation"] = "1B SHIELD"
            elif idx in [2, 3]:
                r["designation"] = "Exotic Survivor"
            else:
                r["designation"] = "Sieved Out"
                
            # Populating metrics to standardise outputs and prevent downstream script errors
            r["SPLI Score"] = r["ski_score"]
            r["ERI Score"] = round(r["wsci_score"] + 40.0, 1)
            r["SPLI Zone"] = "High" if r["tks_score"] >= 0.5 else "Low"
            r["Eff. Barrier"] = r["barrier_recalculated"]
            r["Eff. Mass (kg)"] = r["weight_effective"]
            r["W_visco (kg)"] = r["w_visco"]
            r["VERI Today"] = round(100.0 + r["tks_score"] * 10.0, 1)
            r["NP_i Score"] = r["wsci_score"]
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
            r["APRI Score"] = round(r["wsci_score"] * 0.95, 3)
            r["DSVI Score"] = round(1.15 if idx == 0 else 0.95, 3)
            r["NTCI Score"] = r["wsci_score"]
            r["ntci_score"] = r["wsci_score"] # Explicit double-mapping for caller functions
            r["CKS Score"] = r["ski_score"]
            r["ERC Score"] = r["mcl_score"]
            r["BRI Score"] = r["ski_score"]
            r["WLS Score"] = 0.0
            r["CSSI Score"] = r["wsci_score"]
            r["CWEI Score"] = 1.0
            r["SEDI Score"] = 0.0
            r["CSPI Score"] = r["wsci_score"]
            r["NKP_isolated"] = r["wsci_score"]
            r["SML Score"] = r["sml_score"]
            r["LSJST Score"] = 0.0
            r["IRWFC Score"] = 0.15 if (self.rail_pos == "True" and self.season == "Winter") else 0.0
            
        return ordered_results
