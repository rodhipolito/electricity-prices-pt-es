"""
Analysis script for the electricity prices article.
Reads data from the database (local or Neon) and explores patterns.
Run manually — not part of the daily automated pipeline.
"""

import os
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

CHARTS_DIR = Path(__file__).resolve().parent.parent / "charts"

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


def load_data() -> pd.DataFrame:
    engine = create_engine(DATABASE_URL)
    query = "SELECT bidding_zone, period_start, price_eur_mwh FROM electricity_prices ORDER BY period_start;"
    df = pd.read_sql(query, engine)
    df["hour"] = df["period_start"].dt.hour
    df["weekday"] = df["period_start"].dt.day_name()
    df["is_weekend"] = df["period_start"].dt.dayofweek >= 5
    return df


def hourly_pattern(df: pd.DataFrame):
    """Question 1: What time of day is electricity cheapest/most expensive?"""
    hourly_avg = (
        df.groupby(["bidding_zone", "hour"])["price_eur_mwh"]
        .mean()
        .reset_index()
    )

    print("\n=== Average price by hour of day ===")
    pivot = hourly_avg.pivot(index="hour", columns="bidding_zone", values="price_eur_mwh")
    print(pivot.round(2))

    pt_hourly = hourly_avg[hourly_avg["bidding_zone"] == "PT"].set_index("hour")["price_eur_mwh"]
    cheapest_hour = pt_hourly.idxmin()
    most_expensive_hour = pt_hourly.idxmax()

    print(f"\nCheapest hour (PT): {cheapest_hour}:00 ({pt_hourly.min():.2f} EUR/MWh)")
    print(f"Most expensive hour (PT): {most_expensive_hour}:00 ({pt_hourly.max():.2f} EUR/MWh)")

    fig, ax = plt.subplots(figsize=(10, 5))
    for zone in pivot.columns:
        ax.plot(pivot.index, pivot[zone], marker="o", label=zone)

    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Average price (EUR/MWh)")
    ax.set_title("Average electricity price by hour of day")
    ax.set_xticks(range(0, 24))
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    out_path = CHARTS_DIR / "chart_hourly_pattern.png"
    plt.savefig(out_path, dpi=150)
    print(f"\nChart saved: {out_path}")


def pt_es_decoupling(df: pd.DataFrame) -> pd.DataFrame:
    """Question 3: When did PT and ES prices diverge (market decoupling)?"""
    pivot = df.pivot_table(index="period_start", columns="bidding_zone", values="price_eur_mwh")
    pivot["price_diff"] = (pivot["PT"] - pivot["ES"]).abs()

    # Two tiers: "residual noise" (small, likely auction rounding) vs
    # "significant decoupling" (large gaps, likely real congestion/oversupply events)
    minor_threshold = 0.5
    major_threshold = 10.0

    minor = pivot[pivot["price_diff"] > minor_threshold]
    major = pivot[pivot["price_diff"] > major_threshold]

    total = len(pivot)
    print(f"\n=== PT vs ES decoupling ===")
    print(f"Total intervals: {total}")
    print(f"Minor differences (> {minor_threshold} EUR/MWh): {len(minor)} ({len(minor)/total*100:.1f}%) — likely auction rounding, not real decoupling")
    print(f"Significant decoupling (> {major_threshold} EUR/MWh): {len(major)} ({len(major)/total*100:.1f}%) — likely real congestion/oversupply events")

    if len(major) > 0:
        print(f"\nTop significant decoupling events:")
        print(major.sort_values("price_diff", ascending=False).head(10)[["PT", "ES", "price_diff"]].round(2))

    return pivot


def decoupling_by_hour(pivot: pd.DataFrame):
    """When during the day does significant decoupling happen? Tests the hypothesis
    that it's concentrated in solar hours, not random noise."""
    major_threshold = 10.0
    major = pivot[pivot["price_diff"] > major_threshold].copy()
    major["hour"] = major.index.hour

    print(f"\n=== When does significant decoupling (> {major_threshold} EUR/MWh) happen? ===")
    hourly_counts = major.groupby("hour").size().reindex(range(24), fill_value=0)
    print(hourly_counts)

    total_by_hour = pivot.groupby(pivot.index.hour).size()
    pct_by_hour = (hourly_counts / total_by_hour * 100).round(1)
    print("\n% of intervals decoupled, by hour:")
    print(pct_by_hour)



def decoupling_by_date(pivot: pd.DataFrame):
    """How many distinct days have significant decoupling — is it concentrated
    in a few days, or spread across the whole period?"""
    major_threshold = 10.0
    major = pivot[pivot["price_diff"] > major_threshold].copy()
    major["date"] = major.index.date

    print(f"\n=== Which days had significant decoupling (> {major_threshold} EUR/MWh)? ===")
    daily_counts = major.groupby("date").size().sort_values(ascending=False)
    print(f"Distinct days affected: {daily_counts.shape[0]} out of {pivot.index.normalize().nunique()} total days")
    print(daily_counts.head(10))


def weekend_vs_weekday(df: pd.DataFrame):
    """Question 2: Are prices lower on weekends (less industrial demand)?"""
    comparison = (
        df.groupby(["bidding_zone", "is_weekend"])["price_eur_mwh"]
        .agg(["mean", "median", "std"])
        .round(2)
    )

    print(f"\n=== Weekend vs. Weekday prices ===")
    print(comparison)

    # Percentage difference, using PT as reference
    pt_weekday = comparison.loc[("PT", False), "mean"]
    pt_weekend = comparison.loc[("PT", True), "mean"]
    pct_diff = ((pt_weekend - pt_weekday) / pt_weekday) * 100

    print(f"\nPT: weekend is {pct_diff:+.1f}% vs. weekday average")

    # Plot: average price by hour, split weekday vs weekend (PT only, cleaner to read)
    pt_df = df[df["bidding_zone"] == "PT"]
    hourly_split = (
        pt_df.groupby(["hour", "is_weekend"])["price_eur_mwh"]
        .mean()
        .reset_index()
    )
    pivot = hourly_split.pivot(index="hour", columns="is_weekend", values="price_eur_mwh")
    pivot.columns = ["Weekday", "Weekend"]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(pivot.index, pivot["Weekday"], marker="o", label="Weekday")
    ax.plot(pivot.index, pivot["Weekend"], marker="o", label="Weekend")

    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Average price (EUR/MWh)")
    ax.set_title("Portugal: weekday vs. weekend price pattern")
    ax.set_xticks(range(0, 24))
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    out_path = CHARTS_DIR / "chart_weekend_vs_weekday.png"
    plt.savefig(out_path, dpi=150)
    print(f"\nChart saved: {out_path}")



def decoupling_weekend_link(pivot: pd.DataFrame):
    """Follow-up to Q2 and Q3: is significant decoupling more common on weekends,
    consistent with the bigger midday oversupply we saw there?"""
    major_threshold = 10.0
    pivot = pivot.copy()
    pivot["is_weekend"] = pivot.index.dayofweek >= 5
    pivot["is_decoupled"] = pivot["price_diff"] > major_threshold

    summary = pivot.groupby("is_weekend")["is_decoupled"].agg(["sum", "count", "mean"])
    summary.columns = ["decoupled_intervals", "total_intervals", "pct_decoupled"]
    summary["pct_decoupled"] = (summary["pct_decoupled"] * 100).round(1)
    summary.index = ["Weekday", "Weekend"]

    print(f"\n=== Is decoupling more common on weekends? ===")
    print(summary)

def monthly_trend(df: pd.DataFrame):
    """Question 4: Are prices trending up, down, or stable over the period?"""
    daily_avg = (
        df.groupby([df["period_start"].dt.date, "bidding_zone"])["price_eur_mwh"]
        .mean()
        .reset_index()
    )
    daily_avg.columns = ["date", "bidding_zone", "avg_price"]

    print(f"\n=== Daily average price trend ===")
    pivot = daily_avg.pivot(index="date", columns="bidding_zone", values="avg_price")
    print(pivot.round(2))

    # Simple trend check: compare first week vs last week average
    pt_series = pivot["PT"].dropna()
    first_week = pt_series.iloc[:7].mean()
    last_week = pt_series.iloc[-7:].mean()
    pct_change = ((last_week - first_week) / first_week) * 100

    print(f"\nPT — first 7 days avg: {first_week:.2f} EUR/MWh")
    print(f"PT — last 7 days avg: {last_week:.2f} EUR/MWh")
    print(f"Change: {pct_change:+.1f}%")

    # Plot
    fig, ax = plt.subplots(figsize=(12, 5))
    for zone in pivot.columns:
        ax.plot(pivot.index, pivot[zone], marker="o", markersize=4, label=zone)

    ax.set_xlabel("Date")
    ax.set_ylabel("Average daily price (EUR/MWh)")
    ax.set_title("Daily average electricity price over time")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.xticks(rotation=45)

    plt.tight_layout()
    out_path = CHARTS_DIR / "chart_monthly_trend.png"
    plt.savefig(out_path, dpi=150)
    print(f"\nChart saved: {out_path}")


def volatility_analysis(df: pd.DataFrame):
    """Question 5: Which days were most volatile, and what are the most extreme
    price outliers in the whole period?"""

    # --- Daily volatility: max - min price within each day, per zone ---
    daily_range = (
        df.groupby([df["period_start"].dt.date, "bidding_zone"])["price_eur_mwh"]
        .agg(["min", "max", "std"])
        .reset_index()
    )
    daily_range.columns = ["date", "bidding_zone", "day_min", "day_max", "day_std"]
    daily_range["day_range"] = daily_range["day_max"] - daily_range["day_min"]

    print(f"\n=== Most volatile days (PT, by daily price range) ===")
    pt_range = daily_range[daily_range["bidding_zone"] == "PT"].sort_values("day_range", ascending=False)
    print(pt_range[["date", "day_min", "day_max", "day_range"]].head(10).to_string(index=False))

    # --- Statistical outliers: z-score across the whole period, per zone ---
    df = df.copy()
    df["zscore"] = df.groupby("bidding_zone")["price_eur_mwh"].transform(
        lambda x: (x - x.mean()) / x.std()
    )

    outliers = df[df["zscore"].abs() > 3].sort_values("zscore")

    print(f"\n=== Extreme outliers (|z-score| > 3) ===")
    print(f"Total outlier intervals: {len(outliers)}")
    if len(outliers) > 0:
        print(outliers[["bidding_zone", "period_start", "price_eur_mwh", "zscore"]].round(2).to_string(index=False))


if __name__ == "__main__":
    df = load_data()
    print(f"Loaded {len(df)} rows, from {df['period_start'].min()} to {df['period_start'].max()}")

    hourly_pattern(df)
    pivot = pt_es_decoupling(df)
    decoupling_by_hour(pivot)
    decoupling_by_date(pivot)
    weekend_vs_weekday(df)
    decoupling_weekend_link(pivot)
    monthly_trend(df)
    volatility_analysis(df)