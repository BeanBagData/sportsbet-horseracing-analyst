# Sovereign Kinetic Index (SKI) — Biomechanical Racing Engine

An advanced algorithmic predictive modeling pipeline and data extraction suite for Australian and South African thoroughbred, greyhound, and harness racing. The system combines non-linear physical chassis models, jurisdictional track friction calculations, and automatic parameter calibration using a **Supervised Low-Rank Adaptation (LoRA)** adaptation framework.

---

## 🚀 Key Architectural Features

### 1. Programmatic Biomechanical Feature Extraction
* **Physical Chassis Vectorization**: Transforms unstructured form commentary, age, sex, and horse attributes into deterministic numerical dimensions without relying on semantic APIs.
* **Apprentice Claim Mitigation (ACM)**: Dynamically scales allotted weight profiles based on claim margins to calculate true effective load.
* **Moisture-Compaction Shear Index (MSCI)**: Translates track classifications (Firm/Soft/Heavy/Synthetic) into shear friction coefficients that adjust turn loss and drag.
* **Double Jeopardy Penalty**: Applies non-linear safety offsets to heavy-weight contenders drawn in wide barriers to mitigate high-drag scenarios.

### 2. Supervised LoRA Tiny Adaptor Framework
Instead of directly adjusting the full 6-dimensional weight vector for each localized track/region environment (which causes parameter drift and over-fitting), SKI implements a parameter-efficient fine-tuning (PEFT) framework based on Low-Rank Adaptation (LoRA) [1]:

$$\Delta W = B_s \times A$$

* **Frozen Base Weights ($W_0$)**: Verified physical baseline weights remain untouched (acting as the "pre-trained model").
* **Shared Projection Matrix ($A \in \mathbb{R}^{r \times d}$)**: A rank $r=2$, dimension $d=6$ matrix that captures global cross-dependencies and correlations across the physical metrics.
* **Silo-Specific Adapter ($B_s \in \mathbb{R}^{1 \times r}$)**: A 2-parameter coefficient vector for each individual track surface environment (e.g., `Australia_Turf_Wet`, `South_Africa_Synthetic`).
* **Random-to-Zero Initialization**: As standard in LoRA architectures, matrix $A$ is initialized with small random values, and $B_s$ is initialized to zero. This ensures the initial correction matrix is exactly zero ($\Delta W = 0$) and the system relies entirely on robust base physics until training begins.
* **Calibration Checkpointing**: Prevents duplicate training cycles by comparing the completed files in the `/storage/` directory against a `"trained_race_files"` log stored inside `biomechanical_weights.json`. Training only runs when new completed profiles are detected on disk.

### 3. High-Fidelity Scraping & API Ingestion
* **REST API & HTML Harvesting**: Pulls full card details directly from active REST endpoints and parses scratchings using BeautifulSoup4 HTML page layout traversal.
* **10-Day Historical Cache Alignment**: Matches Sportsbet's rolling 10-day retention window on `/AllRacing/` historical endpoints to prevent server-side `400 Bad Request` exceptions.
* **Results Synchronization**: Retro-actively audits past scheduled events, extracts the final official results order, and updates database records with resolved positions.

---

## 📂 Repository Map

```filepath
├── sportsbet_scraper.py      # Terminal CLI, REST API client, beautifulsoup parsers, and pipeline lifecycle coordinator.
├── australian_logic.py       # Core physical vectorizer, LoRA weights synthesizer, coordinate descent optimizer, and AU prediction engine.
├── south_african_logic.py    # Custom variant logic optimized for South African track structures and distinct pacing profiles.
└── storage/                  # Automated filesystem database storing raw data, predictions, text reports, and JSON configurations.
    ├── biomechanical_weights.json  # Calibrated weights state containing matrices A and B, plus historical checkpoint metrics.
    └── [target_date]/              # Date-grouped regional track directories.
```

---

## 🛠️ Installation & Setup

### Prerequisites
Make sure you have Python 3.8+ installed along with the required dependencies:

```bash
pip install requests beautifulsoup4
```

### Initial Workspace Configuration
When you run the system for the first time, it automatically creates the directory structure and populates your baseline weights file:

```bash
python sportsbet_scraper.py
```

---

## 🖥️ CLI Orchestration Interface

When executing `sportsbet_scraper.py`, you are presented with an interactive terminal interface designed for prediction execution and system maintenance:

```text
==============================================================================================================
 SOVEREIGN KINETIC INDEX (SKI) v4.1 | BIOMECHANICAL AUDIT SYSTEM
==============================================================================================================
 [1] - View Today's Active Program (2026-06-23)
 [2] - Select Historical Date for Results & Auditing (YYYY-MM-DD)
 [3] - Scrape & Analyse a Custom Sportsbet Race URL directly
 [4] - Execute Recursive Archive Search & Biomechanical Model Validation
 [5] - Bulk Scrape & Analyze Missing Historical Archives (Last 10 Days)
 [6] - Bulk Update Missing Results for Existing Archives
 [7] - Run Supervised LoRA Calibration on New/Untrained Archives
 [8] - Exit Terminal
--------------------------------------------------------------------------------------------------------------
Enter option (1-8):
```

### Feature Explanations:
* **Option `[1]` (Real-Time Prediction)**: Pulls active racing sheets for today. When running today's unresulted cards, **inference runs instantly** using the active RAM cache without executing training loops.
* **Option `[5]` & `[6]` (Data Pipelines)**: Bulk harvests missing retrospective data and updates previously scheduled events with final official result records.
* **Option `[7]` (LoRA Calibration)**: Audits your database directory. If new completed races are found, the coordinate-descent optimizer adapts the global shared matrix $A$ and local adapters $B_s$, then appends the files to your checkpoint log to prevent duplicate training on old data.

---

## 📐 Mathematical Formulation of the SKI Optimizer

The physical scorer rates each runner using a composition of calculated kinetic features:

$$\text{Score} = \text{BaseEnergy} + \text{FreshnessModifier} - \text{FrictionDrag} - \text{MassDamping} - (\text{AvgMargin} \times \alpha)$$

Where each component is adjusted by the weights $W$ synthesized from the LoRA parameter matrices:

$$W = \begin{bmatrix} w_{\text{kem}} \\ w_{\text{turn}} \\ w_{\text{mass}} \\ w_{\text{fresh}} \\ w_{\text{jeopardy}} \\ w_{\text{text}} \end{bmatrix} = W_0 + B_s \times A$$

### Step-by-Step Optimization Process (Coordinate Descent):
1. **Local Selection**: The local vector $B_s = [b_{s,1}, b_{s,2}]$ is adjusted in increments of $[0.1, 0.25, 0.5, 1.0]$. The coordinate step that maximizes the sovereign prediction accuracy (first-place selection matching the official result) on that track's historical results is saved.
2. **Global Consolidation**: The global projection matrix $A \in \mathbb{R}^{2 \times 6}$ is tweaked across steps of $[0.05, 0.1, 0.2]$ to find structural parameter relations that improve system-wide accuracy across all combined silos.
3. **Boundary Protection**: Safe threshold bounds are enforced on the final composed $W$ parameters (e.g., preventing kinetic energy parameters from dropping below zero or mass dampening from exceeding physical limits).

---

## ⚖️ License

This project is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. 

* **Commercial Use**: Permitted under GPL-3.0 conditions.
* **Modification**: You may modify the code, but you must document and label any changes.
* **Source Code Availability**: Any work or derivative system that includes this code must make its complete source code available under the same GPL-3.0 license terms.

For more details, see the official [GNU GPL 3.0 License Reference](https://www.gnu.org/licenses/gpl-3.0.html).
