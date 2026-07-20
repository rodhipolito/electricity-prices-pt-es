"""
One-off backfill script: pulls a longer historical window than the daily
pipeline (which only looks back 7 days), so the dataset has enough history
for analysis without waiting weeks for it to accumulate naturally.

Run manually, once (or occasionally, if you want to extend history further back):
    $env:DB_TARGET="neon"; python backfill.py
"""

import pandas as pd
from datetime import datetime, timedelta
from extract_prices import (
    fetch_day_ahead_prices,
    parse_prices,
    deduplicate,
    save_to_postgres,
    BIDDING_ZONES,
    logger,
)

DAYS_BACK = 21  # how far back to backfill


def run_backfill(days_back: int = DAYS_BACK):
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d0000")
    end = datetime.now().strftime("%Y%m%d0000")

    logger.info(f"Starting backfill for {days_back} days ({start} to {end})")

    all_zones_df = []
    for zone_label, domain_code in BIDDING_ZONES.items():
        xml_data = fetch_day_ahead_prices(domain_code, start, end)
        df = parse_prices(xml_data, zone_label)

        if df.empty:
            logger.warning(f"No backfill data for zone {zone_label} — skipping.")
            continue

        all_zones_df.append(df)
        logger.info(f"Backfill parsed {len(df)} rows for zone {zone_label}.")

    if not all_zones_df:
        logger.warning("No backfill data for any zone.")
        return

    combined_df = pd.concat(all_zones_df, ignore_index=True)
    combined_df = deduplicate(combined_df)
    save_to_postgres(combined_df)
    logger.info("Backfill completed successfully.")


if __name__ == "__main__":
    run_backfill()