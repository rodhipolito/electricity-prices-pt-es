# dbt transformation layer

Transformation layer for the `electricity-prices-pt-es` pipeline, built with dbt-core and PostgreSQL (Neon).

The Python ingestion pipeline loads raw ENTSO-E day-ahead prices into `public.electricity_prices`. dbt reads that table as a source and builds clean, tested models in a separate schema (`dbt_dev`), so raw data is never modified.

## Lineage

![dbt lineage graph](docs/lineage.png)

## Models

| Layer | Model | Materialization | Description |
|---|---|---|---|
| Source | `entsoe.electricity_prices` | table (raw) | Raw prices, one row per bidding zone per 15-minute period |
| Staging | `stg_entsoe__electricity_prices` | view | Timestamps made explicit as UTC (`timestamptz`), business key `price_id` |

## Data tests

| Column | Tests | Why |
|---|---|---|
| `price_id` | `unique`, `not_null` | One price per bidding zone per delivery period (business key, not the database id) |
| `bidding_zone` | `not_null` | Every row belongs to a zone |
| `period_start_utc` | `not_null` | Every row has a delivery period |
| `price_eur_mwh` | `not_null` | Every row has a price |

## Design decisions

- **Timestamps are UTC.** The raw table stores them as `timestamp without time zone`; the staging model converts them to `timestamptz` and suffixes columns with `_utc` to remove ambiguity.
- **Business key over surrogate key.** Testing `unique` on the auto-increment `id` would always pass. The meaningful check is that no bidding zone has two prices for the same period.
- **Credentials via environment variables.** `profiles.yml` only contains `env_var()` calls, so it is safe to commit and the same file works locally and in CI.
- **Direct Neon connection** (not the pooled endpoint), and a dedicated schema for dbt output.

## Running locally

Requires Python 3.12.

```powershell
# from the repository root
py -3.12 -m venv .venv-dbt
.\.venv-dbt\Scripts\Activate.ps1
pip install -r requirements-dbt.txt

cd dbt
Copy-Item .env.example .env   # fill in the Neon connection values
.\load-env.ps1

dbt debug
dbt build            # runs models and tests
dbt docs generate
dbt docs serve
```

## Known issues

- Some delivery days are missing in the raw data (40 of 47 expected days between 2026-06-29 and 2026-08-14). A completeness test is planned.
- The time zone of `loaded_at` depends on where the ingestion pipeline ran and is kept as-is.
