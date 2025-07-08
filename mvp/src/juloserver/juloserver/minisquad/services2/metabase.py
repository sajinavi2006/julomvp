def query_download_manual_upload_intelix(query_bucket):
    if query_bucket == "Intelix Bucket 1 Low OSP":
        return '''
                with ops_sent_to_dialer as 
                (
                    select 
                        account_id,
                        account_payment_id,
                        loan_id,
                        payment_id,
                        (cdate at time zone 'Asia/Jakarta')::date as tgl_upload,
                        bucket
                    from ops.sent_to_dialer 
                    where (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date and bucket in ('JULO_B1_NON_CONTACTED','JULO_B1') and coalesce(account_id, payment_id) is not null -->> filter datasets
                ), ops_payment_method as 
                (
                    select 
                        customer_id,
                        min(case when payment_method_name = 'Bank BCA' then virtual_account else null end) as va_bca,
                        min(case when payment_method_name = 'PERMATA Bank' then virtual_account else null end) as va_permata,
                        min(case when payment_method_name = 'Bank MAYBANK' then virtual_account else null end) as va_maybank,
                        min(case when payment_method_name = 'ALFAMART' then virtual_account else null end) as va_alfamart,
                        min(case when payment_method_name = 'INDOMARET' then virtual_account else null end) as va_indomaret
                    from ops.payment_method
                    where is_shown = true 
                    and customer_id in (select customer_id from ops.loan where loan_id in (select loan_id from ops_sent_to_dialer)) --> filter datasets from the main table
                    group by 1
                ), ops_skiptrace_history as 
                (
                    select 
                        account_payment_id,
                        payment_id
                    from ops.skiptrace_history 
                    where skiptrace_result_choice_id in (5,6,14,16,17,18,19,20,21,22) and (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date 
                    and (account_payment_id in (select account_payment_id from ops_sent_to_dialer) or payment_id in (select payment_id from ops_sent_to_dialer))
                ), ops_loan_refinancing_request as 
                (
                    select
                        account_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from 
                    (
                        select 
                            account_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by account_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where account_id is not null and account_id in (select distinct account_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), ops_loan_refinancing_request_2 as 
                (
                    select
                        loan_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from
                    (
                        select 
                            loan_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10 
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by loan_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where loan_id is not null and loan_id in (select distinct loan_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), last_paid as 
                (
                    select
                        account_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            account_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by account_id order by paid_date desc, account_payment_id desc) as ranking
                        from ops.account_payment
                        where account_id in (select distinct account_id from ops_sent_to_dialer)
                    ) ap
                    where ap.ranking = 1 and last_pay_date is not null
                ), last_paid_2 as 
                (
                    select
                        loan_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            loan_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by loan_id order by paid_date desc, payment_id desc) as ranking
                        from ops.payment
                        where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    ) p
                    where p.ranking = 1 and last_pay_date is not null
                ), st_j1 as 
                (
                    select 
                        account_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select account_id,
                            concat(due_date::varchar,'; ',status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by account_id order by account_payment_id asc) as ranking
                        from ops.account_payment
                        where due_amount > 0 and account_id in (select account_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), st_non_j1 as 
                (
                    select 
                        loan_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select loan_id,
                            concat(due_date::varchar,'; ',payment_status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by loan_id order by payment_id asc) as ranking
                        from ops.payment
                        where due_amount > 0 and loan_id in (select loan_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), ptp as 
                (
                    select
                        ptp.account_payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            account_payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by account_payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), ptp_2 as 
                (
                    select
                        ptp.payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where payment_id in (select distinct payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), payment_p as 
                (
                    select 
                        account_payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_p_2 as 
                (  
                    select 
                        payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where payment_id in (select distinct payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x as 
                (
                    select 
                        l.account_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    left join ops.loan l on p.loan_id = l.loan_id
                    where l.account_id in (select distinct account_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x_2 as 
                (
                    select 
                        loan_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    group by 1
                ), is_paid as 
                (
                    select 
                        account_payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and account_payment_id in (select account_payment_id from ops_sent_to_dialer)
                ), is_paid_2 as 
                (
                    select 
                        payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and payment_id in (select payment_id from ops_sent_to_dialer)
                ), product_j1 as 
                (
                    select 
                        '' as loan_id,
                        '' as payment_id,
                        std.account_id,
                        std.account_payment_id,
                        TRUE as is_j1,
                        a.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        'J1' as tipe_produk,
                        al.used_limit as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_j1.status_tagihan_1,
                        st_j1.status_tagihan_2,
                        st_j1.status_tagihan_3,
                        st_j1.status_tagihan_4,
                        st_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 1 Low OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.account_limit al on al.account_id = std.account_id
                    left join last_paid lp on lp.account_id = std.account_id
                    left join ops_loan_refinancing_request lrr on lrr.account_id = std.account_id
                    left join st_j1 on st_j1.account_id = std.account_id
                    left join ptp on ptp.account_payment_id = std.account_payment_id
                    left join payment_p p on p.account_payment_id = std.account_payment_id
                    left join ops.application a on a.account_id = std.account_id
                    left join ops_payment_method pm on pm.customer_id = a.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x x on x.account_id = std.account_id
                    where std.account_payment_id not in (select distinct account_payment_id from ops_skiptrace_history)
                    and std.account_payment_id not in (select distinct account_payment_id from is_paid)
                    and a.application_status_code = 190
                    and x.osp < 2500000
                ), product_non_j1 as 
                (
                    select 
                        std.loan_id,
                        std.payment_id,
                        '' as account_id,
                        '' as account_payment_id,
                        FALSE as is_j1,
                        l.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        case when a.product_line_code in (10,11) then 'MTL' else a.product_line_code::char end as tipe_produk,
                        l.loan_amount as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_non_j1.status_tagihan_1,
                        st_non_j1.status_tagihan_2,
                        st_non_j1.status_tagihan_3,
                        st_non_j1.status_tagihan_4,
                        st_non_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 1 Low OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.loan l on l.loan_id = std.loan_id
                    left join last_paid_2 lp on lp.loan_id = std.loan_id
                    left join ops_loan_refinancing_request_2 lrr on lrr.loan_id = std.loan_id
                    left join st_non_j1 on st_non_j1.loan_id = std.loan_id
                    left join ptp_2 ptp on ptp.payment_id = std.payment_id
                    left join payment_p_2 p on p.payment_id = std.payment_id   
                    left join ops.application a on a.application_id = l.application_id2    
                    left join ops_payment_method pm on pm.customer_id = l.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x_2 x on x.loan_id = std.loan_id
                    where std.payment_id not in (select distinct payment_id from ops_skiptrace_history)
                    and std.payment_id not in (select distinct payment_id from is_paid_2)
                    and a.application_status_code = 180
                    and x.osp < 2500000    
                ), union_all as 
                (
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_j1
                    union all 
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_non_j1
                )
                select * from union_all;
            '''

    if query_bucket == "Intelix Bucket 1 High OSP":
        return '''
                with ops_sent_to_dialer as 
                (
                    select 
                        account_id,
                        account_payment_id,
                        loan_id,
                        payment_id,
                        (cdate at time zone 'Asia/Jakarta')::date as tgl_upload,
                        bucket
                    from ops.sent_to_dialer 
                    where (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date and bucket in ('JULO_B1_NON_CONTACTED','JULO_B1') and coalesce(account_id, payment_id) is not null -->> filter datasets
                ), ops_payment_method as 
                (
                    select 
                        customer_id,
                        min(case when payment_method_name = 'Bank BCA' then virtual_account else null end) as va_bca,
                        min(case when payment_method_name = 'PERMATA Bank' then virtual_account else null end) as va_permata,
                        min(case when payment_method_name = 'Bank MAYBANK' then virtual_account else null end) as va_maybank,
                        min(case when payment_method_name = 'ALFAMART' then virtual_account else null end) as va_alfamart,
                        min(case when payment_method_name = 'INDOMARET' then virtual_account else null end) as va_indomaret
                    from ops.payment_method
                    where is_shown = true 
                    and customer_id in (select customer_id from ops.loan where loan_id in (select loan_id from ops_sent_to_dialer)) --> filter datasets from the main table
                    group by 1
                ), ops_skiptrace_history as 
                (
                    select 
                        account_payment_id,
                        payment_id
                    from ops.skiptrace_history 
                    where skiptrace_result_choice_id in (5,6,14,16,17,18,19,20,21,22) and (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date 
                    and (account_payment_id in (select account_payment_id from ops_sent_to_dialer) or payment_id in (select payment_id from ops_sent_to_dialer))
                ), ops_loan_refinancing_request as 
                (
                    select
                        account_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from 
                    (
                        select 
                            account_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by account_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where account_id is not null and account_id in (select distinct account_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), ops_loan_refinancing_request_2 as 
                (
                    select
                        loan_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from
                    (
                        select 
                            loan_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10 
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by loan_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where loan_id is not null and loan_id in (select distinct loan_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), last_paid as 
                (
                    select
                        account_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            account_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by account_id order by paid_date desc, account_payment_id desc) as ranking
                        from ops.account_payment
                        where account_id in (select distinct account_id from ops_sent_to_dialer)
                    ) ap
                    where ap.ranking = 1 and last_pay_date is not null
                ), last_paid_2 as 
                (
                    select
                        loan_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            loan_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by loan_id order by paid_date desc, payment_id desc) as ranking
                        from ops.payment
                        where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    ) p
                    where p.ranking = 1 and last_pay_date is not null
                ), st_j1 as 
                (
                    select 
                        account_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select account_id,
                            concat(due_date::varchar,'; ',status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by account_id order by account_payment_id asc) as ranking
                        from ops.account_payment
                        where due_amount > 0 and account_id in (select account_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), st_non_j1 as 
                (
                    select 
                        loan_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select loan_id,
                            concat(due_date::varchar,'; ',payment_status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by loan_id order by payment_id asc) as ranking
                        from ops.payment
                        where due_amount > 0 and loan_id in (select loan_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), ptp as 
                (
                    select
                        ptp.account_payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            account_payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by account_payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), ptp_2 as 
                (
                    select
                        ptp.payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where payment_id in (select distinct payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), payment_p as 
                (
                    select 
                        account_payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_p_2 as 
                (  
                    select 
                        payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where payment_id in (select distinct payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x as 
                (
                    select 
                        l.account_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    left join ops.loan l on p.loan_id = l.loan_id
                    where l.account_id in (select distinct account_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x_2 as 
                (
                    select 
                        loan_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    group by 1
                ), is_paid as 
                (
                    select 
                        account_payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and account_payment_id in (select account_payment_id from ops_sent_to_dialer)
                ), is_paid_2 as 
                (
                    select 
                        payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and payment_id in (select payment_id from ops_sent_to_dialer)
                ), product_j1 as 
                (
                    select 
                        '' as loan_id,
                        '' as payment_id,
                        std.account_id,
                        std.account_payment_id,
                        TRUE as is_j1,
                        a.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        'J1' as tipe_produk,
                        al.used_limit as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_j1.status_tagihan_1,
                        st_j1.status_tagihan_2,
                        st_j1.status_tagihan_3,
                        st_j1.status_tagihan_4,
                        st_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 1 High OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.account_limit al on al.account_id = std.account_id
                    left join last_paid lp on lp.account_id = std.account_id
                    left join ops_loan_refinancing_request lrr on lrr.account_id = std.account_id
                    left join st_j1 on st_j1.account_id = std.account_id
                    left join ptp on ptp.account_payment_id = std.account_payment_id
                    left join payment_p p on p.account_payment_id = std.account_payment_id
                    left join ops.application a on a.account_id = std.account_id
                    left join ops_payment_method pm on pm.customer_id = a.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x x on x.account_id = std.account_id
                    where std.account_payment_id not in (select distinct account_payment_id from ops_skiptrace_history)
                    and std.account_payment_id not in (select distinct account_payment_id from is_paid)
                    and a.application_status_code = 190
                    and x.osp >= 2500000
                ), product_non_j1 as 
                (
                    select 
                        std.loan_id,
                        std.payment_id,
                        '' as account_id,
                        '' as account_payment_id,
                        FALSE as is_j1,
                        l.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        case when a.product_line_code in (10,11) then 'MTL' else a.product_line_code::char end as tipe_produk,
                        l.loan_amount as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_non_j1.status_tagihan_1,
                        st_non_j1.status_tagihan_2,
                        st_non_j1.status_tagihan_3,
                        st_non_j1.status_tagihan_4,
                        st_non_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 1 High OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.loan l on l.loan_id = std.loan_id
                    left join last_paid_2 lp on lp.loan_id = std.loan_id
                    left join ops_loan_refinancing_request_2 lrr on lrr.loan_id = std.loan_id
                    left join st_non_j1 on st_non_j1.loan_id = std.loan_id
                    left join ptp_2 ptp on ptp.payment_id = std.payment_id
                    left join payment_p_2 p on p.payment_id = std.payment_id   
                    left join ops.application a on a.application_id = l.application_id2    
                    left join ops_payment_method pm on pm.customer_id = l.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x_2 x on x.loan_id = std.loan_id
                    where std.payment_id not in (select distinct payment_id from ops_skiptrace_history)
                    and std.payment_id not in (select distinct payment_id from is_paid_2)
                    and a.application_status_code = 180
                    and x.osp >= 2500000   
                ), union_all as 
                (
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_j1
                    union all 
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_non_j1
                )
                select *
                from union_all;
            '''

    if query_bucket == "Intelix Bucket 2 Low OSP":
        return '''
                with ops_sent_to_dialer as 
                (
                    select 
                        account_id,
                        account_payment_id,
                        loan_id,
                        payment_id,
                        (cdate at time zone 'Asia/Jakarta')::date as tgl_upload,
                        bucket
                    from ops.sent_to_dialer 
                    where (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date and bucket in ('JULO_B2_NON_CONTACTED','JULO_B2') and coalesce(account_id, payment_id) is not null -->> filter datasets
                ), ops_payment_method as 
                (
                    select 
                        customer_id,
                        min(case when payment_method_name = 'Bank BCA' then virtual_account else null end) as va_bca,
                        min(case when payment_method_name = 'PERMATA Bank' then virtual_account else null end) as va_permata,
                        min(case when payment_method_name = 'Bank MAYBANK' then virtual_account else null end) as va_maybank,
                        min(case when payment_method_name = 'ALFAMART' then virtual_account else null end) as va_alfamart,
                        min(case when payment_method_name = 'INDOMARET' then virtual_account else null end) as va_indomaret
                    from ops.payment_method
                    where is_shown = true 
                    and customer_id in (select customer_id from ops.loan where loan_id in (select loan_id from ops_sent_to_dialer)) --> filter datasets from the main table
                    group by 1
                ), ops_skiptrace_history as 
                (
                    select 
                        account_payment_id,
                        payment_id
                    from ops.skiptrace_history 
                    where skiptrace_result_choice_id in (5,6,14,16,17,18,19,20,21,22) and (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date 
                    and (account_payment_id in (select account_payment_id from ops_sent_to_dialer) or payment_id in (select payment_id from ops_sent_to_dialer))
                ), ops_loan_refinancing_request as 
                (
                    select
                        account_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from 
                    (
                        select 
                            account_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by account_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where account_id is not null and account_id in (select distinct account_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), ops_loan_refinancing_request_2 as 
                (
                    select
                        loan_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from
                    (
                        select 
                            loan_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10 
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by loan_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where loan_id is not null and loan_id in (select distinct loan_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), last_paid as 
                (
                    select
                        account_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            account_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by account_id order by paid_date desc, account_payment_id desc) as ranking
                        from ops.account_payment
                        where account_id in (select distinct account_id from ops_sent_to_dialer)
                    ) ap
                    where ap.ranking = 1 and last_pay_date is not null
                ), last_paid_2 as 
                (
                    select
                        loan_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            loan_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by loan_id order by paid_date desc, payment_id desc) as ranking
                        from ops.payment
                        where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    ) p
                    where p.ranking = 1 and last_pay_date is not null
                ), st_j1 as 
                (
                    select 
                        account_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select account_id,
                            concat(due_date::varchar,'; ',status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by account_id order by account_payment_id asc) as ranking
                        from ops.account_payment
                        where due_amount > 0 and account_id in (select account_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), st_non_j1 as 
                (
                    select 
                        loan_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select loan_id,
                            concat(due_date::varchar,'; ',payment_status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by loan_id order by payment_id asc) as ranking
                        from ops.payment
                        where due_amount > 0 and loan_id in (select loan_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), ptp as 
                (
                    select
                        ptp.account_payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            account_payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by account_payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), ptp_2 as 
                (
                    select
                        ptp.payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where payment_id in (select distinct payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), payment_p as 
                (
                    select 
                        account_payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_p_2 as 
                (  
                    select 
                        payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where payment_id in (select distinct payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x as 
                (
                    select 
                        l.account_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    left join ops.loan l on p.loan_id = l.loan_id
                    where l.account_id in (select distinct account_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x_2 as 
                (
                    select 
                        loan_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    group by 1
                ), is_paid as 
                (
                    select 
                        account_payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and account_payment_id in (select account_payment_id from ops_sent_to_dialer)
                ), is_paid_2 as 
                (
                    select 
                        payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and payment_id in (select payment_id from ops_sent_to_dialer)
                ), product_j1 as 
                (
                    select 
                        '' as loan_id,
                        '' as payment_id,
                        std.account_id,
                        std.account_payment_id,
                        TRUE as is_j1,
                        a.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        'J1' as tipe_produk,
                        al.used_limit as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_j1.status_tagihan_1,
                        st_j1.status_tagihan_2,
                        st_j1.status_tagihan_3,
                        st_j1.status_tagihan_4,
                        st_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 2 Low OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.account_limit al on al.account_id = std.account_id
                    left join last_paid lp on lp.account_id = std.account_id
                    left join ops_loan_refinancing_request lrr on lrr.account_id = std.account_id
                    left join st_j1 on st_j1.account_id = std.account_id
                    left join ptp on ptp.account_payment_id = std.account_payment_id
                    left join payment_p p on p.account_payment_id = std.account_payment_id
                    left join ops.application a on a.account_id = std.account_id
                    left join ops_payment_method pm on pm.customer_id = a.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x x on x.account_id = std.account_id
                    where std.account_payment_id not in (select distinct account_payment_id from ops_skiptrace_history)
                    and std.account_payment_id not in (select distinct account_payment_id from is_paid)
                    and a.application_status_code = 190
                    and x.osp < 2100000
                ), product_non_j1 as 
                (
                    select 
                        std.loan_id,
                        std.payment_id,
                        '' as account_id,
                        '' as account_payment_id,
                        FALSE as is_j1,
                        l.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        case when a.product_line_code in (10,11) then 'MTL' else a.product_line_code::char end as tipe_produk,
                        l.loan_amount as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_non_j1.status_tagihan_1,
                        st_non_j1.status_tagihan_2,
                        st_non_j1.status_tagihan_3,
                        st_non_j1.status_tagihan_4,
                        st_non_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 2 Low OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.loan l on l.loan_id = std.loan_id
                    left join last_paid_2 lp on lp.loan_id = std.loan_id
                    left join ops_loan_refinancing_request_2 lrr on lrr.loan_id = std.loan_id
                    left join st_non_j1 on st_non_j1.loan_id = std.loan_id
                    left join ptp_2 ptp on ptp.payment_id = std.payment_id
                    left join payment_p_2 p on p.payment_id = std.payment_id   
                    left join ops.application a on a.application_id = l.application_id2    
                    left join ops_payment_method pm on pm.customer_id = l.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x_2 x on x.loan_id = std.loan_id
                    where std.payment_id not in (select distinct payment_id from ops_skiptrace_history)
                    and std.payment_id not in (select distinct payment_id from is_paid_2)
                    and a.application_status_code = 180
                    and x.osp < 2100000    
                ), union_all as 
                (
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_j1
                    union all 
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_non_j1
                )
                select * from union_all;
            '''

    if query_bucket == "Intelix Bucket 2 High OSP":
        return '''
                with ops_sent_to_dialer as 
                (
                    select 
                        account_id,
                        account_payment_id,
                        loan_id,
                        payment_id,
                        (cdate at time zone 'Asia/Jakarta')::date as tgl_upload,
                        bucket
                    from ops.sent_to_dialer 
                    where (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date and bucket in ('JULO_B2_NON_CONTACTED','JULO_B2') and coalesce(account_id, payment_id) is not null -->> filter datasets
                ), ops_payment_method as 
                (
                    select 
                        customer_id,
                        min(case when payment_method_name = 'Bank BCA' then virtual_account else null end) as va_bca,
                        min(case when payment_method_name = 'PERMATA Bank' then virtual_account else null end) as va_permata,
                        min(case when payment_method_name = 'Bank MAYBANK' then virtual_account else null end) as va_maybank,
                        min(case when payment_method_name = 'ALFAMART' then virtual_account else null end) as va_alfamart,
                        min(case when payment_method_name = 'INDOMARET' then virtual_account else null end) as va_indomaret
                    from ops.payment_method
                    where is_shown = true 
                    and customer_id in (select customer_id from ops.loan where loan_id in (select loan_id from ops_sent_to_dialer)) --> filter datasets from the main table
                    group by 1
                ), ops_skiptrace_history as 
                (
                    select 
                        account_payment_id,
                        payment_id
                    from ops.skiptrace_history 
                    where skiptrace_result_choice_id in (5,6,14,16,17,18,19,20,21,22) and (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date 
                    and (account_payment_id in (select account_payment_id from ops_sent_to_dialer) or payment_id in (select payment_id from ops_sent_to_dialer))
                ), ops_loan_refinancing_request as 
                (
                    select
                        account_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from 
                    (
                        select 
                            account_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by account_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where account_id is not null and account_id in (select distinct account_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), ops_loan_refinancing_request_2 as 
                (
                    select
                        loan_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from
                    (
                        select 
                            loan_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10 
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by loan_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where loan_id is not null and loan_id in (select distinct loan_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), last_paid as 
                (
                    select
                        account_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            account_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by account_id order by paid_date desc, account_payment_id desc) as ranking
                        from ops.account_payment
                        where account_id in (select distinct account_id from ops_sent_to_dialer)
                    ) ap
                    where ap.ranking = 1 and last_pay_date is not null
                ), last_paid_2 as 
                (
                    select
                        loan_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            loan_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by loan_id order by paid_date desc, payment_id desc) as ranking
                        from ops.payment
                        where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    ) p
                    where p.ranking = 1 and last_pay_date is not null
                ), st_j1 as 
                (
                    select 
                        account_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select account_id,
                            concat(due_date::varchar,'; ',status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by account_id order by account_payment_id asc) as ranking
                        from ops.account_payment
                        where due_amount > 0 and account_id in (select account_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), st_non_j1 as 
                (
                    select 
                        loan_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select loan_id,
                            concat(due_date::varchar,'; ',payment_status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by loan_id order by payment_id asc) as ranking
                        from ops.payment
                        where due_amount > 0 and loan_id in (select loan_id from ops_sent_to_dialer)
                    ) st
                    where ranking <= 5
                    group by 1
                ), ptp as 
                (
                    select
                        ptp.account_payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            account_payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by account_payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), ptp_2 as 
                (
                    select
                        ptp.payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where payment_id in (select distinct payment_id from ops_sent_to_dialer) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), payment_p as 
                (
                    select 
                        account_payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where account_payment_id in (select distinct account_payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_p_2 as 
                (  
                    select 
                        payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where payment_id in (select distinct payment_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x as 
                (
                    select 
                        l.account_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    left join ops.loan l on p.loan_id = l.loan_id
                    where l.account_id in (select distinct account_id from ops_sent_to_dialer)
                    group by 1
                ), payment_x_2 as 
                (
                    select 
                        loan_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    where loan_id in (select distinct loan_id from ops_sent_to_dialer)
                    group by 1
                ), is_paid as 
                (
                    select 
                        account_payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and account_payment_id in (select account_payment_id from ops_sent_to_dialer)
                ), is_paid_2 as 
                (
                    select 
                        payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and payment_id in (select payment_id from ops_sent_to_dialer)
                ), product_j1 as 
                (
                    select 
                        '' as loan_id,
                        '' as payment_id,
                        std.account_id,
                        std.account_payment_id,
                        TRUE as is_j1,
                        a.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        'J1' as tipe_produk,
                        al.used_limit as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_j1.status_tagihan_1,
                        st_j1.status_tagihan_2,
                        st_j1.status_tagihan_3,
                        st_j1.status_tagihan_4,
                        st_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 2 High OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.account_limit al on al.account_id = std.account_id
                    left join last_paid lp on lp.account_id = std.account_id
                    left join ops_loan_refinancing_request lrr on lrr.account_id = std.account_id
                    left join st_j1 on st_j1.account_id = std.account_id
                    left join ptp on ptp.account_payment_id = std.account_payment_id
                    left join payment_p p on p.account_payment_id = std.account_payment_id
                    left join ops.application a on a.account_id = std.account_id
                    left join ops_payment_method pm on pm.customer_id = a.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x x on x.account_id = std.account_id
                    where std.account_payment_id not in (select distinct account_payment_id from ops_skiptrace_history)
                    and std.account_payment_id not in (select distinct account_payment_id from is_paid)
                    and a.application_status_code = 190
                    and x.osp >= 2100000
                ), product_non_j1 as 
                (
                    select 
                        std.loan_id,
                        std.payment_id,
                        '' as account_id,
                        '' as account_payment_id,
                        FALSE as is_j1,
                        l.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        std.tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        case when a.product_line_code in (10,11) then 'MTL' else a.product_line_code::char end as tipe_produk,
                        l.loan_amount as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_non_j1.status_tagihan_1,
                        st_non_j1.status_tagihan_2,
                        st_non_j1.status_tagihan_3,
                        st_non_j1.status_tagihan_4,
                        st_non_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Bucket 2 High OSP' as team
                    from ops_sent_to_dialer std
                    left join ops.loan l on l.loan_id = std.loan_id
                    left join last_paid_2 lp on lp.loan_id = std.loan_id
                    left join ops_loan_refinancing_request_2 lrr on lrr.loan_id = std.loan_id
                    left join st_non_j1 on st_non_j1.loan_id = std.loan_id
                    left join ptp_2 ptp on ptp.payment_id = std.payment_id
                    left join payment_p_2 p on p.payment_id = std.payment_id   
                    left join ops.application a on a.application_id = l.application_id2    
                    left join ops_payment_method pm on pm.customer_id = l.customer_id
                    left join ops.partner par on a.partner_id = par.partner_id
                    left join payment_x_2 x on x.loan_id = std.loan_id
                    where std.payment_id not in (select distinct payment_id from ops_skiptrace_history)
                    and std.payment_id not in (select distinct payment_id from is_paid_2)
                    and a.application_status_code = 180
                    and x.osp >= 2100000   
                ), union_all as 
                (
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_j1
                    union all 
                    select loan_id::text, payment_id::text, account_id::text, account_payment_id::text, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_non_j1
                )
                select * from union_all;
            '''

    if query_bucket == "Intelix Risky Bucket - Heimdall v6":
        return '''
                with account_payment as 
                (
                    select 
                        account_id,
                        account_payment_id,
                        due_date,
                        (current_date at time zone 'Asia/Jakarta')::date - due_date as t_minus
                    from ops.account_payment
                    where (current_date at time zone 'Asia/Jakarta')::date - due_date in (-1,-3,-5) and paid_date is null
                ), ops_payment_method as 
                (
                    select 
                        customer_id,
                        min(case when payment_method_name = 'Bank BCA' then virtual_account else null end) as va_bca,
                        min(case when payment_method_name = 'PERMATA Bank' then virtual_account else null end) as va_permata,
                        min(case when payment_method_name = 'Bank MAYBANK' then virtual_account else null end) as va_maybank,
                        min(case when payment_method_name = 'ALFAMART' then virtual_account else null end) as va_alfamart,
                        min(case when payment_method_name = 'INDOMARET' then virtual_account else null end) as va_indomaret
                    from ops.payment_method
                    where is_shown = true 
                    and customer_id in (select distinct customer_id from ops.account where account_id in (select account_id from account_payment)) --> filter datasets from the main table
                    group by 1
                ), ops_skiptrace_history as 
                (
                    select 
                        account_payment_id,
                        payment_id
                    from ops.skiptrace_history 
                    where skiptrace_result_choice_id in (5,6,14,16,17,18,19,20,21,22) and (cdate at time zone 'Asia/Jakarta')::date = (current_date at time zone 'Asia/Jakarta')::date 
                    and account_payment_id in (select account_payment_id from account_payment)
                ), ops_loan_refinancing_request as 
                (
                    select
                        account_id,
                        refin_status as refinancing_status,
                        prerequisite_amount as activation_amount,
                        program_expiry_date
                    from 
                    (
                        select 
                            account_id,
                            concat(product_type,' ',status) as refin_status,
                            prerequisite_amount,
                            case when status = 'Offer Generated' then form_submitted_ts::date + 10
                                when status = 'Offer Selected' or status = 'Approved' then offer_activated_ts::date + expire_in_days 
                                else null 
                            end as program_expiry_date,
                            rank() over (partition by account_id order by loan_refinancing_request_id desc) as ranking
                        from ops.loan_refinancing_request
                        where account_id is not null and account_id in (select distinct account_id from account_payment) --> filter datasets from the main table
                    ) lrr
                    where lrr.ranking = 1
                ), last_paid as 
                (
                    select
                        account_id,
                        last_pay_date,
                        last_pay_amount
                    from
                    (
                        select
                            account_id,
                            paid_date as last_pay_date,
                            paid_amount as last_pay_amount,
                            rank() over (partition by account_id order by paid_date desc, account_payment_id desc) as ranking
                        from ops.account_payment
                        where account_id in (select distinct account_id from account_payment)
                    ) ap
                    where ap.ranking = 1 and last_pay_date is not null
                ), st_j1 as 
                (
                    select 
                        account_id,
                        string_agg(case when ranking = 1 then status_tagihan else null end, '') as status_tagihan_1,
                        string_agg(case when ranking = 2 then status_tagihan else null end, '') as status_tagihan_2,
                        string_agg(case when ranking = 3 then status_tagihan else null end, '') as status_tagihan_3,
                        string_agg(case when ranking = 4 then status_tagihan else null end, '') as status_tagihan_4,
                        string_agg(case when ranking = 5 then status_tagihan else null end, '') as status_tagihan_5
                    from
                    (
                        select account_id,
                            concat(due_date::varchar,'; ',status_code::varchar,'; ',due_amount::varchar) as status_tagihan,
                            rank() over (partition by account_id order by account_payment_id asc) as ranking
                        from ops.account_payment
                        where due_amount > 0 and account_id in (select account_id from account_payment)
                    ) st
                    where ranking <= 5
                    group by 1
                ), ptp as 
                (
                    select
                        ptp.account_payment_id,
                        ag.user_extension as last_agent,
                        ptp.last_call_status
                    from
                    (
                        select 
                            account_payment_id,
                            agent_id,
                            ptp_date as last_call_status,
                            rank() over (partition by account_payment_id order by ptp_id desc) as ranking
                        from ops.ptp
                        where account_payment_id in (select distinct account_payment_id from account_payment) --> filter datasets from the main table
                    ) ptp 
                    left join ops.agent ag on ag.auth_user_id = ptp.agent_id
                    where ptp.ranking = 1
                ), payment_p as 
                (
                    select 
                        account_payment_id,
                        sum(paid_amount + due_amount) as angsuran_per_bulan,
                        max((current_date at time zone 'Asia/Jakarta')::date - due_date) as dpd,
                        sum(late_fee_amount) as denda,
                        sum(due_amount) as outstanding,
                        min(due_date) as tanggal_jatuh_tempo
                    from ops.payment
                    where account_payment_id in (select distinct account_payment_id from account_payment)
                    group by 1
                ), payment_x as 
                (
                    select 
                        l.account_id,
                        sum(installment_principal - paid_principal) as osp 
                    from ops.payment p
                    left join ops.loan l on p.loan_id = l.loan_id
                    where l.account_id in (select distinct account_id from account_payment)
                    group by 1
                ), is_paid as 
                (
                    select 
                        account_payment_id 
                    from ops.payment
                    where payment_status_code in (330,331,332)
                    and account_payment_id in (select account_payment_id from account_payment)
                ), is_dpd as 
                (
                    select distinct account_id
                    from ops.loan
                    where loan_status_code in (230, 231, 232, 233, 234, 235, 236, 237)
                ), pcmr as 
                (
                    select distinct application_id, model_version, pgood
                    from ana.pd_credit_model_result
                    --where ((model_version in ('Heimdall v6') and pgood <= 0.90) or (pgood >= 0.80 and pgood <= 0.90))
                ), product_j1 as 
                (
                    select 
                        '' as loan_id,
                        '' as payment_id,
                        apb.account_id,
                        apb.account_payment_id,
                        TRUE as is_j1,
                        a.customer_id,
                        a.application_id,
                        REPLACE(REPLACE(a.fullname,',',' '),'"',' ') as nama_customer,
                        case when substring(a.mobile_phone_1, 1, 1) = '0' then concat('62', substring(a.mobile_phone_1, 2, length(a.mobile_phone_1))) else a.mobile_phone_1 end as mobile_phone_1,
                        case when substring(a.mobile_phone_2, 1, 1) = '0' then concat('62', substring(a.mobile_phone_2, 2, length(a.mobile_phone_2))) else a.mobile_phone_2 end as mobile_phone_2,
                        REPLACE(REPLACE(a.company_name,',',' '),'"',' ') as nama_perusahaan,
                        REPLACE(REPLACE(a.position_employees,',',' '),'"',' ') as posisi_karyawan,
                        REPLACE(REPLACE(a.company_phone_number,',',' '),'"',' ') as telp_perusahaan,
                        p.dpd,
                        p.angsuran_per_bulan,
                        p.denda,
                        p.outstanding,
                        p.tanggal_jatuh_tempo,
                        REPLACE(REPLACE(a.spouse_name,',',''),'"',' ') as nama_pasangan,
                        a.spouse_mobile_phone as no_telp_pasangan,
                        REPLACE(REPLACE(a.kin_name,',',''),'"',' ') as nama_kerabat,
                        a.kin_mobile_phone as no_telp_kerabat,
                        a.kin_relationship as hubungan_kerabat,
                        REPLACE(REPLACE(concat(a.address_street_num, ' ', a.address_kelurahan, ' ', a.address_kecamatan, ' ', a.address_kabupaten, ' ', a.address_provinsi, ' ', a.address_kodepos),',',' '),'"',' ') as alamat,
                        REPLACE(REPLACE(a.address_kabupaten,',',''),'"',' ') as kota,
                        a.gender as jenis_kelamin,
                        a.dob as tgl_lahir,
                        a.payday as tgl_gajian,
                        a.loan_purpose as tujuan_pinjaman,
                        (current_date at time zone 'Asia/Jakarta')::date::date as tgl_upload,
                        pm.va_bca,
                        pm.va_permata,
                        pm.va_maybank,
                        pm.va_alfamart,
                        pm.va_indomaret,
                        'JULO' as campaign,
                        'J1' as tipe_produk,
                        al.used_limit as jumlah_pinjaman,
                        lp.last_pay_date,
                        lp.last_pay_amount,
                        st_j1.status_tagihan_1,
                        st_j1.status_tagihan_2,
                        st_j1.status_tagihan_3,
                        st_j1.status_tagihan_4,
                        st_j1.status_tagihan_5,
                        null as status_tagihan_6,
                        null as status_tagihan_7,
                        null as status_tagihan_8,
                        null as status_tagihan_9,
                        null as status_tagihan_10,
                        null as status_tagihan_11,
                        null as status_tagihan_12,
                        null as status_tagihan_13,
                        null as status_tagihan_14,
                        null as status_tagihan_15,
                        par.name as partner_name,
                        ptp.last_agent,
                        ptp.last_call_status,
                        lrr.refinancing_status,
                        lrr.activation_amount,
                        lrr.program_expiry_date,
                        null as customer_bucket_type,
                        case when a.is_fdc_risky is true then 'Early Payback (Promo 30%)' else null end as promo_untuk_customer,
                        a.address_kodepos as zipcode,
                        'Intelix Risky Bucket - Heimdall v6' as team
                    from account_payment apb   
                    left join ops.account_limit al on al.account_id = apb.account_id
                    left join last_paid lp on lp.account_id = apb.account_id   
                    left join ops_loan_refinancing_request lrr on lrr.account_id = apb.account_id
                    left join st_j1 on st_j1.account_id = apb.account_id
                    left join ptp on ptp.account_payment_id = apb.account_payment_id
                    left join payment_p p on p.account_payment_id = apb.account_payment_id
                    left join ops.application a on a.account_id = apb.account_id
                    left join pcmr on pcmr.application_id = a.application_id
                    left join ops_payment_method pm on pm.customer_id = a.customer_id     
                    left join ops.partner par on a.partner_id = par.partner_id 
                    left join payment_x x on x.account_id = apb.account_id
                    left join is_dpd on is_dpd.account_id = apb.account_id
                    where apb.account_payment_id not in (select distinct account_payment_id from ops_skiptrace_history)
                    and apb.account_payment_id not in (select distinct account_payment_id from is_paid)
                    and a.application_status_code = 190
                    and is_dpd.account_id is null
                    and ((pcmr.model_version in ('Heimdall v6') and pcmr.pgood <=0.90) or (pcmr.pgood>=0.80 and pcmr.pgood<=0.90))
                ), cleansing_all as 
                (
                    select loan_id, payment_id, account_id, account_payment_id, is_j1, customer_id, application_id, nama_customer, mobile_phone_1, mobile_phone_2, nama_perusahaan, posisi_karyawan, telp_perusahaan, dpd, angsuran_per_bulan, denda, outstanding, tanggal_jatuh_tempo, nama_pasangan, no_telp_pasangan, nama_kerabat, no_telp_kerabat, hubungan_kerabat, alamat, kota, jenis_kelamin, tgl_lahir, tgl_gajian, tujuan_pinjaman, tgl_upload, va_bca, va_permata, va_maybank, va_alfamart, va_indomaret, campaign, tipe_produk, jumlah_pinjaman, last_pay_date, last_pay_amount, status_tagihan_1, status_tagihan_2, status_tagihan_3, status_tagihan_4, status_tagihan_5, status_tagihan_6, status_tagihan_7, status_tagihan_8, status_tagihan_9, status_tagihan_10, status_tagihan_11, status_tagihan_12, status_tagihan_13, status_tagihan_14, status_tagihan_15, partner_name, last_agent, last_call_status, refinancing_status, activation_amount, program_expiry_date, customer_bucket_type, promo_untuk_customer, zipcode, team
                    from product_j1
                )
                select * from cleansing_all;
            '''
