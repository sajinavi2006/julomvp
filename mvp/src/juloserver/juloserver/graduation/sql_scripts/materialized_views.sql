CREATE MATERIALIZED VIEW ops.graduation_regular_customer_accounts AS
SELECT a.account_id, ap.last_graduation_date FROM ops.account a
INNER JOIN ops.application a2 ON a.account_id = a2.account_id
LEFT JOIN ops.account_property ap on a.account_id = ap.account_id
WHERE (
a.status_code = 420 AND a2.product_line_code = 1
AND a2.partner_id IS NULL
AND a2.application_status_code= 190
and ap.is_entry_level is false
)
GROUP BY a.account_id , ap.last_graduation_date

CREATE INDEX account_id_idx ON ops.graduation_regular_customer_accounts (account_id)
