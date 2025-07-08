create materialized view ops.sales_ops_graduation AS
	with graduation_data as (
		select
			distinct on (gch.account_id) gch.account_id,
			gch.cdate::date as last_graduation_date,
			cast(alh.value_new as double precision) - cast(alh.value_old as double precision) as limit_amount_increased
		from ops.graduation_customer_history gch
		join ops.account_limit_history alh on gch.set_limit_history_id = alh.account_limit_history_id
		where
            		gch.cdate >= now() - interval '6 months'
			and gch.graduation_type != 'balance_consolidation'
		order by gch.account_id asc, gch.cdate desc
	), loan_data as (
		select
			a.account_id,
			max(l.cdate) as last_loan_cdate
		from ops.account a
		left join ops.loan l on a.account_id = l.account_id
		where l.loan_status_code >= 220
		group by a.account_id
	)
	select
		gd.account_id,
		gd.last_graduation_date,
		gd.limit_amount_increased,
		row_number() over(order by gd.last_graduation_date desc, limit_amount_increased desc) as ranking
	from graduation_data gd
	left join loan_data ld on gd.account_id = ld.account_id
	where ld.last_loan_cdate is null
		or ld.last_loan_cdate <= gd.last_graduation_date
