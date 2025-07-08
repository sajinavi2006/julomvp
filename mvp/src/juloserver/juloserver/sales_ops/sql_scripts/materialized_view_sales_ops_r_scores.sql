CREATE MATERIALIZED VIEW ops.sales_ops_r_score AS
    with core as (
        select
            datas.account_id
             , greatest(datas.latest_disbursed_date::timestamp,datas.latest_paid_date::timestamp,datas.latest_x190_date::timestamp) as active_dates
        from (
            select
                a.account_id
                , max(case when l.loan_status_code in (220, 230, 231, 232, 233, 234, 235, 236, 237) then l.fund_transfer_ts else null end) as latest_disbursed_date
                , max(case when l.loan_status_code in (250) then ap.paid_date else null end) as latest_paid_date
                , max(ah.cdate) as latest_x190_date
            from ops.application a
            join (
                select
                    ah.application_id
                    , max(ah.cdate) as cdate
                from ops.application_history ah
                where ah.status_new = 190
                and ah.application_id in (select application_id from ops.application where product_line_code = 1)
                group by 1
            ) ah on a.application_id = ah.application_id
            left join ops.loan l on l.application_id2 = a.application_id and a.product_line_code in (1) -- J1 only
            left join ops.account_payment ap on ap.account_id = a.account_id
            group by 1
        ) as datas
    )
    , summary as (
        select
            a.account_id
            , a.active_dates::date as latest_active_dates
            , row_number() over(order by active_dates desc) as ranking
        from core a
        join ops.sales_ops_lineup b on a.account_id = b.account_id
        where a.active_dates is not null and b.is_active = true
    )
    select * from summary
