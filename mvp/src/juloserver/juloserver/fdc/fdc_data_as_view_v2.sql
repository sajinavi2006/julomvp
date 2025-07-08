--DROP VIEW IF EXISTS ops.fdc_data_as_view; using this when changing or adding column name

CREATE OR REPLACE VIEW ops.fdc_data_as_view_v2
AS SELECT row_number() OVER () AS fdc_data_as_view_id
    ,810069 AS id_penyelenggara
    ,0 AS pendanaan_syariah
    ,2 AS tipe_pinjaman
    ,20 AS sub_tipe_pinjaman
    ,0 AS penyelesaian_w_oleh
    ,NULL::text AS reference
    ,c.customer_id AS id_borrower
    ,1 AS jenis_pengguna
    ,a.fullname AS nama_borrower
    ,a.ktp AS no_identitas
    ,NULL::text AS no_npwp
    ,a.application_xid AS id_pinjaman
    ,to_char(COALESCE(sphp_ready."time", l.fund_transfer_ts), 'YYYYMMDD'::text) AS tgl_perjanjian_borrower
    ,    CASE
            WHEN l.fund_transfer_ts > ph.last_due_date THEN to_char((timezone('Asia/Jakarta'::text, sphp_ready."time")::date + 1)::timestamp with time zone, 'YYYYMMDD'::text)
            ELSE to_char(l.fund_transfer_ts, 'YYYYMMDD'::text)
        END AS tgl_penyaluran_dana
    ,l.loan_amount AS nilai_pendanaan
    ,to_char((timezone('Asia/Jakarta'::text, now())::date - 1)::timestamp with time zone, 'YYYYMMDD'::text) AS tgl_pelaporan_data
    ,l.loan_amount::numeric - COALESCE(ph.paid_principal, 0::numeric) AS sisa_pinjaman_berjalan
    ,to_char(timezone('Asia/Jakarta'::text, ph.last_due_date::timestamp with time zone)::date::timestamp with time zone, 'YYYYMMDD'::text) AS tgl_jatuh_tempo_pinjaman
    ,    CASE
            WHEN (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) < 30 THEN 1
            WHEN (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) >= 30 AND (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) <= 90 THEN 2
            WHEN (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) > 90 THEN 3
            ELSE NULL::integer
        END AS id_kualitas_pinjaman
    ,timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date) AS status_pinjaman_dpd
    ,timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.oldest_due_date, timezone('Asia/Jakarta'::text, now())::date) AS status_pinjaman_max_dpd
    ,    CASE
            WHEN l.loan_status_code = ANY (ARRAY[220, 230, 231, 232, 233, 234, 235, 236, 240]) THEN 'O'::text
            WHEN l.loan_status_code = 250 THEN 'L'::text
            WHEN l.loan_status_code = ANY (ARRAY[237, 260]) THEN 'W'::text
            WHEN l.loan_status_code = 210 THEN 'D'::text
            ELSE NULL::text
        END AS status_pinjaman
   FROM ops.customer c
     JOIN ops.application a ON a.customer_id = c.customer_id
                AND a.application_status_code = 180
                AND lower(a.email::text) !~~ '%julofinance%'::text
     JOIN ops.loan l ON l.application_id = a.application_id
            AND l.loan_status_code <> 210
     LEFT JOIN (SELECT application_history.application_id
                ,max(application_history.cdate) AS "time"
              FROM ops.application_history
              WHERE application_history.status_new = ANY (ARRAY[165, 170, 177])
              GROUP BY application_history.application_id
              ) sphp_ready ON sphp_ready.application_id = a.application_id
     LEFT JOIN (SELECT payment.loan_id
                ,sum(CASE WHEN payment.paid_amount >= payment.installment_principal THEN payment.installment_principal
                        WHEN payment.paid_amount < payment.installment_principal THEN payment.paid_amount
                        ELSE NULL::bigint
                      END) AS paid_principal
                ,max(payment.due_date) AS last_due_date
              FROM ops.payment
              WHERE payment.is_restructured = false
              GROUP BY payment.loan_id
              ) ph ON ph.loan_id = l.loan_id
     LEFT JOIN (SELECT payment.loan_id
                ,min(CASE WHEN payment.payment_status_code >= 320 THEN payment.due_date
                        ELSE NULL::date
                      END) AS oldest_due_date
                ,max(CASE WHEN payment.payment_status_code >= 320 THEN payment.due_date
                        ELSE NULL::date
                      END) AS earliest_due_date
              FROM ops.payment
              WHERE payment.payment_status_code < 330 
              AND payment.is_restructured = false
              GROUP BY payment.loan_id
              ) p ON p.loan_id = l.loan_id
     LEFT JOIN (SELECT DISTINCT payment_history.loan_id
              FROM ops.payment_history
              WHERE payment_history.cdate > (timezone('Asia/Jakarta'::text, now())::date - 1) 
              AND payment_history.cdate < timezone('Asia/Jakarta'::text, now())::date
              ) lc ON lc.loan_id = l.loan_id
UNION ALL
 SELECT row_number() OVER () AS fdc_data_as_view_id
    ,810069 AS id_penyelenggara
    ,0 AS pendanaan_syariah
    ,2 AS tipe_pinjaman
    ,20 AS sub_tipe_pinjaman
    ,0 AS penyelesaian_w_oleh
    ,NULL::text AS reference
    ,c.customer_id AS id_borrower
    ,1 AS jenis_pengguna
    ,a.fullname AS nama_borrower
    ,a.ktp AS no_identitas
    ,NULL::text AS no_npwp
    ,l.loan_xid AS id_pinjaman
    ,to_char(x212."time", 'YYYYMMDD'::text) AS tgl_perjanjian_borrower
    ,    CASE WHEN l.fund_transfer_ts > ph.last_due_date THEN to_char((timezone('Asia/Jakarta'::text, x212."time")::date + 1)::timestamp with time zone, 'YYYYMMDD'::text)
            WHEN l.fund_transfer_ts IS NULL AND x220.loan_id IS NOT NULL THEN to_char((timezone('Asia/Jakarta'::text, x220."time")::date + 1)::timestamp with time zone, 'YYYYMMDD'::text)
            ELSE to_char(l.fund_transfer_ts, 'YYYYMMDD'::text)
          END AS tgl_penyaluran_dana
    ,l.loan_amount AS nilai_pendanaan
    ,to_char((timezone('Asia/Jakarta'::text, now())::date - 1)::timestamp with time zone, 'YYYYMMDD'::text) AS tgl_pelaporan_data
    ,l.loan_amount::numeric - COALESCE(ph.paid_principal, 0::numeric) AS sisa_pinjaman_berjalan
    ,to_char(timezone('Asia/Jakarta'::text, ph.last_due_date::timestamp with time zone)::date::timestamp with time zone, 'YYYYMMDD'::text) AS tgl_jatuh_tempo_pinjaman
    ,    CASE WHEN (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) < 30 THEN 1
            WHEN (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) >= 30 AND (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) <= 90 THEN 2
            WHEN (timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date)) > 90 THEN 3
            ELSE NULL::integer
          END AS id_kualitas_pinjaman
    ,timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.earliest_due_date, timezone('Asia/Jakarta'::text, now())::date) AS status_pinjaman_dpd
    ,timezone('Asia/Jakarta'::text, now())::date - COALESCE(p.oldest_due_date, timezone('Asia/Jakarta'::text, now())::date) AS status_pinjaman_max_dpd
    ,    CASE WHEN l.loan_status_code = ANY (ARRAY[220, 230, 231, 232, 233, 234, 235, 236, 240]) THEN 'O'::text
            WHEN l.loan_status_code = 250 THEN 'L'::text
            WHEN l.loan_status_code = ANY (ARRAY[237, 260]) THEN 'W'::text
            WHEN l.loan_status_code = ANY (ARRAY[210, 214, 215, 216, 217, 219]) THEN 'D'::text
            ELSE NULL::text
          END AS status_pinjaman
   FROM ops.customer c
     JOIN ops.loan l ON l.customer_id = c.customer_id
            AND l.loan_status_code <> 210
     JOIN ops.application a ON a.application_id = l.application_id2 
                AND a.application_status_code = 190
                AND lower(a.email::text) !~~ '%julofinance%'::text
     JOIN ( SELECT loan_history.loan_id
              ,max(loan_history.cdate) AS "time"
            FROM ops.loan_history
            WHERE loan_history.status_new = 212
            GROUP BY loan_history.loan_id
            ) x212 ON x212.loan_id = l.loan_id
     JOIN ( SELECT payment.loan_id
              ,sum(CASE WHEN payment.paid_amount >= payment.installment_principal THEN payment.installment_principal
                      WHEN payment.paid_amount < payment.installment_principal THEN payment.paid_amount
                      ELSE NULL::bigint
                    END) AS paid_principal
              ,max(payment.due_date) AS last_due_date
            FROM ops.payment
            WHERE is_restructured = false
            GROUP BY payment.loan_id
            ) ph ON ph.loan_id = l.loan_id
     LEFT JOIN (SELECT payment.loan_id
                ,min(CASE WHEN payment.payment_status_code >= 320 THEN payment.due_date
                        ELSE NULL::date
                      END) AS oldest_due_date
                ,max(CASE WHEN payment.payment_status_code >= 320 THEN payment.due_date
                        ELSE NULL::date
                      END) AS earliest_due_date
              FROM ops.payment
              WHERE payment.payment_status_code < 330 
              AND payment.is_restructured = false
              GROUP BY payment.loan_id
              ) p ON p.loan_id = l.loan_id
     JOIN ( SELECT loan_history.loan_id
              ,min(loan_history.cdate) AS "time"
            FROM ops.loan_history
            WHERE loan_history.status_new = 220
            GROUP BY loan_history.loan_id
            ) x220 ON x220.loan_id = l.loan_id
     LEFT JOIN (SELECT DISTINCT payment_history.loan_id
              FROM ops.payment_history
              WHERE payment_history.cdate > (timezone('Asia/Jakarta'::text, now())::date - 1) 
              AND payment_history.cdate < timezone('Asia/Jakarta'::text, now())::date
              ) lc ON lc.loan_id = l.loan_id
 ;

-- Permissions

ALTER TABLE ops.fdc_data_as_view_v2 OWNER TO postgres;
GRANT ALL ON TABLE ops.fdc_data_as_view_v2 TO postgres;
GRANT SELECT ON TABLE ops.fdc_data_as_view_v2 TO readonly_users;
GRANT SELECT ON TABLE ops.fdc_data_as_view_v2 TO analytics_users;
GRANT ALL ON TABLE ops.fdc_data_as_view_v2 TO admin_users;
GRANT ALL ON TABLE ops.fdc_data_as_view_v2 TO ops_server;
