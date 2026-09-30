with source as (

    select * from {{ source('entsoe', 'electricity_prices') }}

),

cleaned as (

    select
        id                                  as source_row_id,
        upper(trim(bidding_zone))           as bidding_zone,
        -- raw timestamps are UTC stored without time zone; make that explicit
        period_start at time zone 'UTC'     as period_start_utc,
        period_end at time zone 'UTC'       as period_end_utc,
        price_eur_mwh,
        -- time zone of loaded_at depends on where the pipeline ran; kept as-is
        loaded_at

    from source

),

final as (

    select
        -- business key: one price per bidding zone per delivery period
        bidding_zone || '_' || to_char(period_start_utc at time zone 'UTC', 'YYYYMMDD"T"HH24MI') as price_id,
        bidding_zone,
        period_start_utc,
        period_end_utc,
        price_eur_mwh,
        loaded_at,
        source_row_id

    from cleaned

)

select * from final
