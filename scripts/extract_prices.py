import os
import logging
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# --- Logging setup ---
logging.basicConfig(
    filename="pipeline.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("ENTSOE_API_KEY")
BASE_URL = "https://web-api.tp.entsoe.eu/api"
NAMESPACE = {"ns": "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"}

# Bidding zones to collect (EIC codes) — MIBEL market: PT and ES are usually
# coupled (same price), but decouple during interconnection congestion.
BIDDING_ZONES = {
    "PT": "10YPT-REN------W",
    "ES": "10YES-REE------0",
}

DB_TARGET = os.getenv("DB_TARGET", "local")

if DB_TARGET == "neon":
    DATABASE_URL = os.getenv("DATABASE_URL_NEON")
else:
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT")
    DB_NAME = os.getenv("DB_NAME")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def fetch_day_ahead_prices(domain: str, start_date: str, end_date: str) -> str:
    params = {
        "securityToken": API_KEY,
        "documentType": "A44",
        "in_Domain": domain,
        "out_Domain": domain,
        "periodStart": start_date,
        "periodEnd": end_date,
    }
    response = requests.get(BASE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.text


def parse_prices(xml_text: str, zone_label: str) -> pd.DataFrame:
    """Parses the ENTSO-E XML response into a tidy, gap-free DataFrame for one zone."""
    root = ET.fromstring(xml_text)
    records = []

    for period in root.findall(".//ns:TimeSeries/ns:Period", NAMESPACE):
        start_str = period.find("ns:timeInterval/ns:start", NAMESPACE).text
        end_str = period.find("ns:timeInterval/ns:end", NAMESPACE).text
        resolution = period.find("ns:resolution", NAMESPACE).text

        minutes = int(resolution.replace("PT", "").replace("M", ""))
        period_start = datetime.strptime(start_str, "%Y-%m-%dT%H:%MZ")
        period_end = datetime.strptime(end_str, "%Y-%m-%dT%H:%MZ")

        raw_points = {}
        for point in period.findall("ns:Point", NAMESPACE):
            position = int(point.find("ns:position", NAMESPACE).text)
            price = float(point.find("ns:price.amount", NAMESPACE).text)
            raw_points[position] = price

        total_positions = int((period_end - period_start).total_seconds() / 60 / minutes)

        last_price = None
        for position in range(1, total_positions + 1):
            if position in raw_points:
                last_price = raw_points[position]

            point_start = period_start + timedelta(minutes=(position - 1) * minutes)
            point_end = point_start + timedelta(minutes=minutes)

            records.append({
                "bidding_zone": zone_label,
                "period_start": point_start,
                "period_end": point_end,
                "price_eur_mwh": last_price,
            })

    return pd.DataFrame(records)


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Some ENTSO-E responses contain multiple TimeSeries blocks covering the
    same period (e.g. revisions), which produces duplicate (bidding_zone,
    period_start) pairs within a single fetch. Keep the last occurrence
    (most recently listed in the XML) and log how many rows were affected.
    """
    before = len(df)
    df = df.drop_duplicates(subset=["bidding_zone", "period_start"], keep="last")
    removed = before - len(df)

    if removed > 0:
        logger.warning(f"Removed {removed} duplicate rows before saving (likely revised TimeSeries blocks).")

    return df


def save_to_postgres(df: pd.DataFrame):
    engine = create_engine(DATABASE_URL)
    df.to_sql("staging_prices", engine, if_exists="replace", index=False)

    upsert_query = text("""
        INSERT INTO electricity_prices (bidding_zone, period_start, period_end, price_eur_mwh)
        SELECT bidding_zone, period_start, period_end, price_eur_mwh FROM staging_prices
        ON CONFLICT (bidding_zone, period_start)
        DO UPDATE SET price_eur_mwh = EXCLUDED.price_eur_mwh;
    """)

    with engine.begin() as conn:
        conn.execute(upsert_query)
        conn.execute(text("DROP TABLE staging_prices;"))

    logger.info(f"Saved {len(df)} rows to electricity_prices (target: {DB_TARGET}).")


def run_pipeline():
    try:
        seven_days_ago = datetime.now() - timedelta(days=7)
        today = datetime.now()

        start = seven_days_ago.strftime("%Y%m%d0000")
        end = today.strftime("%Y%m%d0000")

        logger.info(f"Starting pipeline run (target: {DB_TARGET}) for {start} to {end}")

        all_zones_df = []

        for zone_label, domain_code in BIDDING_ZONES.items():
            xml_data = fetch_day_ahead_prices(domain_code, start, end)
            df = parse_prices(xml_data, zone_label)

            if df.empty:
                logger.warning(f"No data returned for zone {zone_label} — skipping.")
                continue

            all_zones_df.append(df)
            logger.info(f"Parsed {len(df)} rows for zone {zone_label}.")

        if not all_zones_df:
            logger.warning("No data returned for any zone — skipping save.")
            return

        combined_df = pd.concat(all_zones_df, ignore_index=True)
        combined_df = deduplicate(combined_df)
        save_to_postgres(combined_df)
        logger.info("Pipeline run completed successfully.")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)


if __name__ == "__main__":
    run_pipeline()