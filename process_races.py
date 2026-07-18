import os
import json
import sqlite3
from pathlib import Path

# --- CONFIGURATION ---
STORAGE_DIR = r"C:\Users\Sam\Documents\Horse Racing\Scraper\storage"
DB_FILE = "horse_racing_data.db"

def setup_database(cursor):
    """Creates the necessary tables and updates them if the schema changes."""
    
    # 1. Create Races Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS races (
            event_id INTEGER PRIMARY KEY,
            region TEXT,
            venue TEXT,
            track TEXT,
            race_name TEXT,
            distance INTEGER,
            track_status TEXT,
            start_time INTEGER,
            scraped_at TEXT,
            weather_temperature REAL,
            weather_condition TEXT,
            weather_wind TEXT,
            weather_humidity REAL,
            straight_metres REAL,
            circumference_metres REAL,
            rail_position TEXT,
            race_status TEXT,
            weather_forecast_hourly_json TEXT,
            finishing_order_json TEXT
        )
    ''')

    # 2. Schema Migration Check (If user ran the older script, add the new columns automatically)
    cursor.execute("PRAGMA table_info(races)")
    existing_columns = [col[1] for col in cursor.fetchall()]
    
    if 'weather_forecast_hourly_json' not in existing_columns:
        cursor.execute("ALTER TABLE races ADD COLUMN weather_forecast_hourly_json TEXT")
    if 'finishing_order_json' not in existing_columns:
        cursor.execute("ALTER TABLE races ADD COLUMN finishing_order_json TEXT")

    # 3. Create Runners Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS runners (
            event_id INTEGER,
            number INTEGER,
            original_barrier INTEGER,
            carried_weight_kg REAL,
            apprentice_claim_kg REAL,
            name TEXT,
            jockey TEXT,
            jockey_wet_win_rate_pct REAL,
            trainer TEXT,
            trainer_wet_win_rate_pct REAL,
            sire TEXT,
            sire_awd REAL,
            days_since_last_start INTEGER,
            runs_this_prep INTEGER,
            age REAL,
            sex TEXT,
            career_starts INTEGER,
            career_wins INTEGER,
            career_places INTEGER,
            status TEXT,
            gear_changes TEXT,
            last_run_json TEXT,
            PRIMARY KEY (event_id, number),
            FOREIGN KEY (event_id) REFERENCES races(event_id)
        )
    ''')

def process_files(storage_dir, cursor):
    """Finds all relevant JSON files and inserts them into the database."""
    
    path = Path(storage_dir)
    json_files = list(path.rglob("*.json"))
    
    files_processed = 0
    files_skipped = 0

    for file_path in json_files:
        # Ignore prediction/report files
        if file_path.name.endswith('_prediction.json') or file_path.name.endswith('_report.json'):
            files_skipped += 1
            continue

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Verify valid race data format
                if 'event_id' not in data:
                    files_skipped += 1
                    continue
                
                insert_race_data(data, cursor)
                files_processed += 1
                
        except json.JSONDecodeError:
            print(f"Error reading JSON from {file_path}")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    return files_processed, files_skipped

def insert_race_data(data, cursor):
    """Parses JSON dictionary and executes INSERT OR REPLACE statements."""
    
    # Extract Race Data
    event_id = data.get('event_id')
    weather = data.get('weather', {})
    track_details = data.get('track_details', {})
    meeting_metadata = data.get('meeting_metadata', {})
    race_results = data.get('race_results', {})
    
    # Dump the newly identified arrays into JSON strings for DB storage
    weather_forecast_str = json.dumps(meeting_metadata.get('weather_forecast_hourly', []))
    finishing_order_str = json.dumps(race_results.get('finishing_order', []))
    
    race_row = (
        event_id,
        data.get('region'),
        data.get('venue'),
        data.get('track'),
        data.get('race_name'),
        data.get('distance'),
        data.get('track_status'),
        data.get('start_time'),
        data.get('scraped_at'),
        weather.get('temperature'),
        weather.get('condition'),
        weather.get('wind'),
        weather.get('humidity'),
        track_details.get('straight_metres'),
        track_details.get('circumference_metres'),
        track_details.get('rail_position'),
        race_results.get('status'),
        weather_forecast_str,
        finishing_order_str
    )

    cursor.execute('''
        INSERT OR REPLACE INTO races (
            event_id, region, venue, track, race_name, distance, track_status, 
            start_time, scraped_at, weather_temperature, weather_condition, 
            weather_wind, weather_humidity, straight_metres, circumference_metres, 
            rail_position, race_status, weather_forecast_hourly_json, finishing_order_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', race_row)

    # Extract Runner Data
    runners = data.get('runners', [])
    for runner in runners:
        career_stats = runner.get('career_stats', {})
        
        gear_changes_str = json.dumps(runner.get('gear_changes', []))
        last_run_str = json.dumps(runner.get('last_run', {}))

        runner_row = (
            event_id,
            runner.get('number'),
            runner.get('original_barrier'),
            runner.get('carried_weight_kg'),
            runner.get('apprentice_claim_kg'),
            runner.get('name'),
            runner.get('jockey'),
            runner.get('jockey_wet_win_rate_pct'),
            runner.get('trainer'),
            runner.get('trainer_wet_win_rate_pct'),
            runner.get('sire'),
            runner.get('sire_awd'),
            runner.get('days_since_last_start'),
            runner.get('runs_this_prep'),
            runner.get('age'),
            runner.get('sex'),
            career_stats.get('starts'),
            career_stats.get('wins'),
            career_stats.get('places'),
            runner.get('status'),
            gear_changes_str,
            last_run_str
        )

        cursor.execute('''
            INSERT OR REPLACE INTO runners (
                event_id, number, original_barrier, carried_weight_kg, apprentice_claim_kg, 
                name, jockey, jockey_wet_win_rate_pct, trainer, trainer_wet_win_rate_pct, 
                sire, sire_awd, days_since_last_start, runs_this_prep, age, sex, 
                career_starts, career_wins, career_places, status, gear_changes, last_run_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', runner_row)

def main():
    print(f"Connecting to database: {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print("Setting up/verifying tables...")
    setup_database(cursor)
    
    print(f"Scanning directory: {STORAGE_DIR}...")
    processed, skipped = process_files(STORAGE_DIR, cursor)
    
    conn.commit()
    conn.close()
    
    print("-" * 30)
    print("Processing Complete!")
    print(f"Valid Race Files Processed: {processed}")
    print(f"Files Skipped (Predictions/Invalid): {skipped}")
    print(f"Data reliably updated into {DB_FILE}.")

if __name__ == "__main__":
    main()