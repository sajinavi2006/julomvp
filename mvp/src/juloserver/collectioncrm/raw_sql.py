from builtins import object
class Sqls(object):

    @staticmethod
    def monthly_collection():
        return """
        (select month_start_date,
          sum(due_count) as count_payment,
          case
              when sum(due_count) > 0 then cast(round(cast(sum(not_paid_ontime)/sum(due_count) as decimal), 3) as VARCHAR)
              else '-1'
          end as "np_ontime_percent",
          case
              when sum(due_count) > 0 then cast(round(cast(sum(not_paid_grace)/sum(due_count) as decimal), 3) as VARCHAR)
              else '-1'
          end as "np_grace_percent",
          case
              when sum(due_count) > 0 then cast(round(cast(sum(not_paid_late30)/sum(due_count) as decimal), 3) as VARCHAR)
              else '-1'
          end as "np_late30_percent",
          sum(case
                  when payment_number = 1 then due_count
                  else 0
              end) as count_first_payment,
          case
              when sum(case
                           when payment_number = 1 then due_count
                           else 0
                       end) > 0 then cast(round(cast(sum(case
                                                             when payment_number = 1 then not_paid_ontime
                                                             else 0
                                                         end) / sum(case
                                                                        when payment_number = 1 then due_count
                                                                        else 0
                                                                    end) as decimal), 3) as VARCHAR)
              else '-1'
          end as "fp_np_ontime_percent",
          case
              when sum(case
                           when payment_number = 1 then due_count
                           else 0
                       end) > 0 then cast(round(cast(sum(case
                                                             when payment_number = 1 then not_paid_grace
                                                             else 0
                                                         end) / sum(case
                                                                        when payment_number = 1 then due_count
                                                                        else 0
                                                                    end) as decimal), 3) as VARCHAR)
              else '-1'
          end as "fp_np_grace_percent"
   from
     (select current_date as report_dt,
                             e.month_start_date,
                             e.week_start_date,
                             e.data_date as due_date,
                             left(g.product_line_type,3) as product_type,
                             d.payment_number,
                             case
                                 when d.payment_number = 1 then '1st payment'
                                 when d.payment_number > 1
                                      and h.paid_date <= d.due_date
                                      and h.paid_amount >= (h.installment_principal+h.installment_interest) then 'Non-1st, good prior'
                                 when d.payment_number > 1 then 'Non-1st, bad prior'
                             end as payment_detail,
                             count(d.payment_id) as due_count,
                             sum(case
                                     when d.payment_status_code = 330 then 1
                                     else 0
                                 end) as paid_ontime,
                             sum(case
                                     when d.payment_status_code = 331 then 1
                                     else 0
                                 end) as paid_grace,
                             sum(case
                                     when d.payment_status_code = 332
                                          and d.paid_date-d.due_date <= 30 then 1
                                     else 0
                                 end) as paid_late30,
                             sum(case
                                     when d.payment_status_code = 332
                                          and d.paid_date-d.due_date between 31 and 60 then 1
                                     else 0
                                 end) as paid_late60,
                             sum(case
                                     when d.payment_status_code = 332
                                          and d.paid_date-d.due_date between 61 and 90 then 1
                                     else 0
                                 end) as paid_late90,
                             count(d.payment_id) - sum(case
                                                           when d.payment_status_code = 330 then 1
                                                           else 0
                                                       end) as not_paid_ontime,
                             count(d.payment_id) - sum(case
                                                           when d.payment_status_code in (330,331) then 1
                                                           else 0
                                                       end) as not_paid_grace,
                             count(d.payment_id) - sum(case
                                                           when d.payment_status_code in (330,331,332)
                                                                and d.paid_date-d.due_date <= 30 then 1
                                                           else 0
                                                       end) as not_paid_late30,
                             count(d.payment_id) - sum(case
                                                           when d.payment_status_code in (330,331,332)
                                                                and d.paid_date-d.due_date <= 60 then 1
                                                           else 0
                                                       end) as not_paid_late60,
                             count(d.payment_id) - sum(case
                                                           when d.payment_status_code in (330,331,332)
                                                                and d.paid_date-d.due_date <= 90 then 1
                                                           else 0
                                                       end) as not_paid_late90
      from ops.customer a
      join ops.application b on a.customer_id = b.customer_id
      join ops.loan c on b.application_id = c.application_id
      join ops.payment d on c.loan_id = d.loan_id
      join sb.adri_dates e on d.due_date = e.data_date
      join ops.product_lookup f on c.product_code = f.product_code
      join ops.product_line g on f.product_line_code = g.product_line_code
      left join ops.payment h on d.loan_id = h.loan_id
      and d.payment_number - 1 = h.payment_number
      where lower(b.email) not like '%%julofinance%%'
        and b.application_status_code = 180
        and c.loan_status_code <> 210
        and current_date-d.due_date >= 0
      group by 1,
               2,
               3,
               4,
               5,
               6,
               7
      order by 1,
               2,
               3,
               4,
               5,
               6,
               7) as a
   where (date_part('month', month_start_date) = %s
          and date_part('year', month_start_date) = %s)
    
   group by date_part('month', month_start_date),
            month_start_date
   union select null,
                null,
                '0.165',
                '0.100',
                '0.060',
                null,
                '0.100',
                '0.050'
   order by 1 desc) 
  
        """

    @staticmethod
    def monthly_performance():
        return """
           SELECT *
FROM
  (SELECT due_month AS MONTH,
          sum(denom) AS fp_accumulation,
          sum(fp_paid_grace)+ sum(fp_paid_late_45)+sum(fp_paid_late_90) as fp_total,
          concat((round((round(((sum(fp_paid_grace)+ sum(fp_paid_late_45)+sum(fp_paid_late_90))::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') as fp_total_percent,
          sum(fp_paid_grace) as fp_paid_grace,
          concat((round((round((sum(fp_paid_grace)::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS fp_paid_grace_percent,
          sum(fp_paid_late_45) as fp_paid_late_45,
          concat((round((round((sum(fp_paid_late_45)::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS fp_paid_late_45_percent,
          sum(fp_paid_late_90) as fp_paid_late_90,
          concat((round((round((sum(fp_paid_late_90)::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS fp_paid_late_90_percent
   FROM
     (SELECT y.month_start_date AS due_month -- this is the due_month
,
             username AS agent_name --count below = count all first payments that assigned to that agent
,
             count(*) AS denom,

        (SELECT count(*)
         FROM ops.application a3
         JOIN ops.loan b3 ON a3.application_id=b3.application_id
         JOIN ops.payment c3 ON b3.loan_id=c3.loan_id
         and c3.payment_number=1
         JOIN sb.adri_dates y3 ON c3.paid_date=y3.data_date
         JOIN ops.status_lookup e3 ON c3.payment_status_code=e3.status_code
         LEFT JOIN ops.auth_user d3 ON b3.agent_id=d3.id
         WHERE lower(a3.email) NOT LIKE '%%%%julofinance%%%%'
           AND c3.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND y3.month_start_date=y.month_start_date
           AND c3.payment_status_code =331
           AND d3.username=d.username) AS fp_paid_grace,

        (SELECT count(*)
         FROM ops.application a4
         JOIN ops.loan b4 ON a4.application_id=b4.application_id
         JOIN ops.payment c4 ON b4.loan_id=c4.loan_id
         and c4.payment_number=1
         JOIN sb.adri_dates y4 ON c4.paid_date=y4.data_date
         JOIN ops.status_lookup e4 ON c4.payment_status_code=e4.status_code
         LEFT JOIN ops.auth_user d4 ON b4.agent_id=d4.id
         WHERE lower(a4.email) NOT LIKE '%%%%julofinance%%%%'
           AND c4.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND y4.month_start_date=y.month_start_date
           AND c4.payment_status_code =332
           AND ((c4.paid_date-c4.due_date) BETWEEN 5 AND 45)
           AND d4.username=d.username) AS fp_paid_late_45,

        (SELECT count(*)
         FROM ops.application a5
         JOIN ops.loan b5 ON a5.application_id=b5.application_id
         JOIN ops.payment c5 ON b5.loan_id=c5.loan_id
         and c5.payment_number=1
         JOIN sb.adri_dates y5 ON c5.paid_date=y5.data_date
         JOIN ops.status_lookup e5 ON c5.payment_status_code=e5.status_code
         LEFT JOIN ops.auth_user d5 ON b5.agent_id=d5.id
         WHERE lower(a5.email) NOT LIKE '%%%%julofinance%%%%'
           AND c5.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND y5.month_start_date=y.month_start_date
           AND c5.payment_status_code =332
           AND ((c5.paid_date-c5.due_date) BETWEEN 46 AND 90)
           AND d5.username=d.username) AS fp_paid_late_90
      FROM ops.application a
      JOIN ops.loan b ON a.application_id=b.application_id
      JOIN ops.payment c ON b.loan_id=c.loan_id
      and c.payment_number=1
      JOIN sb.adri_dates y ON c.due_date=y.data_date
      JOIN ops.status_lookup e ON c.payment_status_code=e.status_code
      LEFT JOIN ops.auth_user d ON b.agent_id=d.id
      WHERE lower(a.email) NOT LIKE '%%%%julofinance%%%%'
        AND product_line_code NOT IN (50,
                                      51)
        AND c.due_date<CURRENT_DATE
        AND (c.paid_date>c.due_date
             OR c.paid_date IS NULL)
        AND c.payment_status_code NOT IN (310,
                                          311,
                                          312)
        AND d.username NOT LIKE '%%%%+%%%%'
      GROUP BY 1,
               2) final
   group by 1
   ORDER BY 1 DESC,2) AS expr_qry
WHERE  (date_part('month', month)) = %s 
  AND (date_part('year', month)) = %s
        """

    @staticmethod
    def monthly_performance_all():
        return """
         SELECT month AS month,
                accumulation AS accumulation,
                total AS total,
                total_percent AS total_percent,
                paid_grace AS paid_grace,
                paid_grace_percent AS paid_grace_percent,
                paid_late_45 AS paid_late_45,
                paid_late_45_percent AS paid_late_45_percent,
                paid_late_90 AS paid_late_90,
                paid_late_90_percent AS paid_late_90_percent
FROM
  (SELECT due_month as month --, agent_name
,
          sum(denom) as accumulation,
          sum(paid_grace)+sum(paid_late_45)+sum(paid_late_90) AS total,
          concat((round((round(((sum(paid_grace)+sum(paid_late_45)+sum(paid_late_90))::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS total_percent,
          sum(paid_grace) as paid_grace,
          concat((round((round((sum(paid_grace)::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS paid_grace_percent,
          sum(paid_late_45) as paid_late_45,
          concat((round((round((sum(paid_late_45)::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS paid_late_45_percent,
          sum(paid_late_90) as paid_late_90,
          concat((round((round((sum(paid_late_90)::DECIMAL/sum(denom)::DECIMAL),2))*100,0)),'%%') AS paid_late_90_percent
   FROM
     (SELECT y.month_start_date AS due_month -- this is the due_month
,
             username AS agent_name --count below = count all payments that assigned to that agent + count payment that has not been paid from previous months (until 90dpd)
,
             count(*) +
        (SELECT count(*)
         FROM ops.application a2
         JOIN ops.loan b2 ON a2.application_id=b2.application_id
         JOIN ops.payment c2 ON b2.loan_id=c2.loan_id
         JOIN sb.adri_dates y2 ON c2.due_date=y2.data_date
         JOIN ops.status_lookup e2 ON c2.payment_status_code=e2.status_code
         LEFT JOIN ops.auth_user d2 ON b2.agent_id=d2.id
         WHERE lower(a2.email) NOT LIKE '%%%%julofinance%%%%'
           AND c2.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND payment_status_code NOT IN (310,
                                           311,
                                           312,
                                           330,
                                           331,
                                           332)
           AND CURRENT_DATE-c2.due_date <=90
           AND c2.due_date < y.month_start_date
           AND d2.username=d.username) AS denom,

        (SELECT count(*)
         FROM ops.application a3
         JOIN ops.loan b3 ON a3.application_id=b3.application_id
         JOIN ops.payment c3 ON b3.loan_id=c3.loan_id
         JOIN sb.adri_dates y3 ON c3.paid_date=y3.data_date
         JOIN ops.status_lookup e3 ON c3.payment_status_code=e3.status_code
         LEFT JOIN ops.auth_user d3 ON b3.agent_id=d3.id
         WHERE lower(a3.email) NOT LIKE '%%%%julofinance%%%%'
           AND c3.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND y3.month_start_date=y.month_start_date
           AND c3.payment_status_code =331
           AND d3.username=d.username) AS paid_grace,

        (SELECT count(*)
         FROM ops.application a4
         JOIN ops.loan b4 ON a4.application_id=b4.application_id
         JOIN ops.payment c4 ON b4.loan_id=c4.loan_id
         JOIN sb.adri_dates y4 ON c4.paid_date=y4.data_date
         JOIN ops.status_lookup e4 ON c4.payment_status_code=e4.status_code
         LEFT JOIN ops.auth_user d4 ON b4.agent_id=d4.id
         WHERE lower(a4.email) NOT LIKE '%%%%julofinance%%%%'
           AND c4.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND y4.month_start_date=y.month_start_date
           AND c4.payment_status_code =332
           AND ((c4.paid_date-c4.due_date) BETWEEN 5 AND 45)
           AND d4.username=d.username) AS paid_late_45,

        (SELECT count(*)
         FROM ops.application a5
         JOIN ops.loan b5 ON a5.application_id=b5.application_id
         JOIN ops.payment c5 ON b5.loan_id=c5.loan_id
         JOIN sb.adri_dates y5 ON c5.paid_date=y5.data_date
         JOIN ops.status_lookup e5 ON c5.payment_status_code=e5.status_code
         LEFT JOIN ops.auth_user d5 ON b5.agent_id=d5.id
         WHERE lower(a5.email) NOT LIKE '%%%%julofinance%%%%'
           AND c5.due_date<CURRENT_DATE
           AND product_line_code NOT IN (50,
                                         51)
           AND y5.month_start_date=y.month_start_date
           AND c5.payment_status_code =332
           AND ((c5.paid_date-c5.due_date) BETWEEN 46 AND 90)
           AND d5.username=d.username) AS paid_late_90
      FROM ops.application a
      JOIN ops.loan b ON a.application_id=b.application_id
      JOIN ops.payment c ON b.loan_id=c.loan_id
      JOIN sb.adri_dates y ON c.due_date=y.data_date
      JOIN ops.status_lookup e ON c.payment_status_code=e.status_code
      LEFT JOIN ops.auth_user d ON b.agent_id=d.id
      WHERE lower(a.email) NOT LIKE '%%%%julofinance%%%%'
        AND product_line_code NOT IN (50,
                                      51)
        AND c.due_date<CURRENT_DATE
        AND (c.paid_date>c.due_date
             OR c.paid_date IS NULL)
        AND c.payment_status_code NOT IN (310,
                                          311,
                                          312)
        AND d.username NOT LIKE '%%%%+%%%%'
      GROUP BY 1,
               2) final
   group by 1
   ORDER BY 1 DESC,2) AS expr_qry
WHERE  (date_part('month', month)) = %s 
  AND (date_part('year', month)) = %s
LIMIT 50000
        """
