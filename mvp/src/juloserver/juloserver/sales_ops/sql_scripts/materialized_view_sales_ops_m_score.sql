CREATE MATERIALIZED VIEW ops.sales_ops_m_score
TABLESPACE pg_default
AS SELECT datas.account_id,
    datas.latest_account_limit_id,
    datas.available_limit,
    datas.ranking
   FROM ( SELECT al.account_id,
            sol.latest_account_limit_id,
            al.available_limit,
            row_number() OVER (ORDER BY al.available_limit DESC) AS ranking
           FROM ops.sales_ops_lineup sol
             JOIN ops.account_limit al ON sol.latest_account_limit_id = al.account_limit_id
             JOIN ops.application a ON al.account_id = a.account_id AND a.product_line_code = 1
          WHERE sol.is_active = true
          ORDER BY al.available_limit DESC, sol.rpc_count ASC) datas
WITH DATA;
