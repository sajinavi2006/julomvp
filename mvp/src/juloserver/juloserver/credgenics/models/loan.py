from builtins import object
from juloserver.credgenics.constants.credgenics import CREDGENICS_ALLOCATION_MONTH


class Reference(object):
    name: str
    relationship: str
    contact_number: str

    def __init__(self, name: str, relationship: str, contact_number: str):
        self.name = name
        self.relationship = relationship
        self.contact_number = contact_number

    def to_dict(self):
        return {
            "name": self.name,
            "relationship": self.relationship,
            "contact_number": self.contact_number,
        }


class CredgenicsLoan(object):

    transaction_id: str
    account_id: int
    client_customer_id: int
    customer_due_date: str
    date_of_default: str
    allocation_month: str
    expected_emi_principal_amount: int
    expected_emi_interest_amount: int
    expected_emi: int
    customer_dpd: int
    late_fee: int
    allocation_dpd_value: int
    dpd: int
    total_denda: int
    potensi_cashback: int
    total_seluruh_perolehan_cashback: int
    total_due_amount: int
    total_claim_amount: int
    total_outstanding: int
    tipe_produk: str
    last_pay_amount: int
    activation_amount: int
    zip_code: str
    angsuran_per_bulan: int
    mobile_phone_1: str
    mobile_phone_2: str
    nama_customer: str
    nama_perusahaan: str
    posisi_karyawan: str
    nama_pasangan: str
    nama_kerabat: str
    hubungan_kerabat: str
    alamat: str
    kota: str
    jenis_kelamin: str
    tgl_lahir: str
    tgl_gajian: int
    tujuan_pinjaman: str
    va_bca: str
    va_permata: str
    va_maybank: str
    va_alfamart: str
    va_indomaret: str
    va_mandiri: str
    last_pay_date: str
    partner_name: str
    last_agent: str
    last_call_status: str
    refinancing_status: str
    program_expiry_date: str
    customer_bucket_type: str
    telp_perusahaan: str
    no_telp_pasangan: str
    no_telp_kerabat: str
    uninstall_indicator: str
    fdc_risky: bool
    email: str
    cashback_new_scheme_experiment_group: bool
    va_method_name: str
    va_number: str
    short_ptp_date: str
    ptp_amount: int
    is_j1_customer: bool
    first_name: str
    last_name: str
    month_due_date: str
    year_due_date: str
    due_date_long: str
    age: int
    title: str
    sms_due_date_short: str
    sms_month: int
    sms_firstname: str
    sms_primary_va_name: str
    sms_primary_va_number: str
    sms_payment_details_url: str
    collection_segment: str
    bank_code: str
    bank_code_text: str
    bank_name: str
    cashback_amount: int
    cashback_counter: int
    cashback_due_date_slash: str
    title_long: str
    name_with_title: str
    formatted_due_amount: str
    google_calendar_url: str
    shopee_score_status: str
    shopee_score_list_type: str
    application_similarity_score: float
    mycroft_score: float
    credit_score: str
    active_liveness_score: float
    passive_liveness_score: float
    heimdall_score: float
    orion_score: float
    fpgw: float
    total_loan_amount: int
    late_fee_applied: int
    status_code: int
    is_collection_called: bool
    is_ptp_robocall_active: bool
    is_reminder_called: bool
    is_robocall_active: bool
    is_success_robocall: bool
    ptp_date: str
    ptp_robocall_phone_number: str
    is_restructured: bool
    account_payment_xid: int
    autodebet_retry_count: int
    paid_during_refinancing: bool
    is_paid_within_dpd_1to10: bool
    is_autodebet: bool
    internal_sort_order: float
    sort_order: int
    campaign_due_amount: int
    is_risky: bool
    is_email_blocked: bool
    is_sms_blocked: bool
    is_one_way_robocall_blocked: bool

    def __init__(
        self,
        transaction_id: str = None,
        account_id: int = None,
        client_customer_id: int = None,
        customer_due_date: str = None,
        date_of_default: str = None,
        allocation_month: str = None,
        expected_emi_principal_amount: int = None,
        expected_emi_interest_amount: int = None,
        expected_emi: int = None,
        customer_dpd: int = None,
        late_fee: int = None,
        allocation_dpd_value: int = None,
        dpd: int = None,
        total_denda: int = None,
        potensi_cashback: int = None,
        total_seluruh_perolehan_cashback: int = None,
        total_due_amount: int = None,
        total_claim_amount: int = None,
        total_outstanding: int = None,
        tipe_produk: str = None,
        last_pay_amount: int = None,
        activation_amount: int = None,
        zip_code: str = None,
        angsuran_per_bulan: int = None,
        mobile_phone_1: str = None,
        mobile_phone_2: str = None,
        nama_customer: str = None,
        nama_perusahaan: str = None,
        posisi_karyawan: str = None,
        nama_pasangan: str = None,
        nama_kerabat: str = None,
        hubungan_kerabat: str = None,
        alamat: str = None,
        kota: str = None,
        jenis_kelamin: str = None,
        tgl_lahir: str = None,
        tgl_gajian: int = None,
        tujuan_pinjaman: str = None,
        va_bca: str = None,
        va_permata: str = None,
        va_maybank: str = None,
        va_alfamart: str = None,
        va_indomaret: str = None,
        va_mandiri: str = None,
        last_pay_date: str = None,
        partner_name: str = None,
        last_agent: str = None,
        last_call_status: str = None,
        refinancing_status: str = None,
        program_expiry_date: str = None,
        customer_bucket_type: str = None,
        telp_perusahaan: str = None,
        no_telp_pasangan: str = None,
        no_telp_kerabat: str = None,
        uninstall_indicator: str = None,
        fdc_risky: bool = None,
        email: str = None,
        cashback_new_scheme_experiment_group: bool = None,
        va_method_name: str = None,
        va_number: str = None,
        short_ptp_date: str = None,
        ptp_amount: int = None,
        is_j1_customer: bool = None,
        first_name: str = None,
        last_name: str = None,
        month_due_date: str = None,
        year_due_date: str = None,
        due_date_long: str = None,
        age: int = None,
        title: str = None,
        sms_due_date_short: str = None,
        sms_month: int = None,
        sms_firstname: str = None,
        sms_primary_va_name: str = None,
        sms_primary_va_number: str = None,
        sms_payment_details_url: str = None,
        collection_segment: str = None,
        bank_code: str = None,
        bank_code_text: str = None,
        bank_name: str = None,
        cashback_amount: int = None,
        cashback_counter: int = None,
        cashback_due_date_slash: str = None,
        title_long: str = None,
        name_with_title: str = None,
        formatted_due_amount: str = None,
        google_calendar_url: str = None,
        shopee_score_status: str = None,
        shopee_score_list_type: str = None,
        application_similarity_score: float = None,
        mycroft_score: float = None,
        credit_score: str = None,
        active_liveness_score: float = None,
        passive_liveness_score: float = None,
        heimdall_score: float = None,
        orion_score: float = None,
        fpgw: float = None,
        total_loan_amount: int = None,
        late_fee_applied: int = None,
        status_code: int = None,
        is_collection_called: bool = None,
        is_ptp_robocall_active: bool = None,
        is_reminder_called: bool = None,
        is_robocall_active: bool = None,
        is_success_robocall: bool = None,
        ptp_date: str = None,
        ptp_robocall_phone_number: str = None,
        is_restructured: bool = None,
        account_payment_xid: int = None,
        autodebet_retry_count: int = None,
        paid_during_refinancing: bool = None,
        is_paid_within_dpd_1to10: bool = None,
        is_autodebet: bool = None,
        internal_sort_order: float = None,
        campaign_due_amount: int = None,
        is_risky: bool = None,
        is_email_blocked: bool = None,
        is_sms_blocked: bool = None,
        is_one_way_robocall_blocked: bool = None,
    ):
        self.transaction_id = transaction_id
        self.account_id = account_id
        self.client_customer_id = client_customer_id
        self.customer_due_date = customer_due_date
        self.date_of_default = date_of_default
        self.allocation_month = allocation_month
        self.expected_emi_principal_amount = expected_emi_principal_amount
        self.expected_emi_interest_amount = expected_emi_interest_amount
        self.expected_emi = expected_emi
        self.customer_dpd = customer_dpd
        self.late_fee = late_fee
        self.allocation_dpd_value = allocation_dpd_value
        self.dpd = dpd
        self.total_denda = total_denda
        self.potensi_cashback = potensi_cashback
        self.total_seluruh_perolehan_cashback = total_seluruh_perolehan_cashback
        self.total_due_amount = total_due_amount
        self.total_claim_amount = total_claim_amount
        self.total_outstanding = total_outstanding
        self.tipe_produk = tipe_produk
        self.last_pay_amount = last_pay_amount
        self.activation_amount = activation_amount
        self.zip_code = zip_code
        self.angsuran_per_bulan = angsuran_per_bulan
        self.mobile_phone_1 = mobile_phone_1
        self.mobile_phone_2 = mobile_phone_2
        self.nama_customer = nama_customer
        self.nama_perusahaan = nama_perusahaan
        self.posisi_karyawan = posisi_karyawan
        self.nama_pasangan = nama_pasangan
        self.nama_kerabat = nama_kerabat
        self.hubungan_kerabat = hubungan_kerabat
        self.alamat = alamat
        self.kota = kota
        self.jenis_kelamin = jenis_kelamin
        self.tgl_lahir = tgl_lahir
        self.tgl_gajian = tgl_gajian
        self.tujuan_pinjaman = tujuan_pinjaman
        self.va_bca = va_bca
        self.va_permata = va_permata
        self.va_maybank = va_maybank
        self.va_alfamart = va_alfamart
        self.va_indomaret = va_indomaret
        self.va_mandiri = va_mandiri
        self.last_pay_date = last_pay_date
        self.partner_name = partner_name
        self.last_agent = last_agent
        self.last_call_status = last_call_status
        self.refinancing_status = refinancing_status
        self.program_expiry_date = program_expiry_date
        self.customer_bucket_type = customer_bucket_type
        self.telp_perusahaan = telp_perusahaan
        self.no_telp_pasangan = no_telp_pasangan
        self.no_telp_kerabat = no_telp_kerabat
        self.uninstall_indicator = uninstall_indicator
        self.fdc_risky = fdc_risky
        self.email = email
        self.cashback_new_scheme_experiment_group = cashback_new_scheme_experiment_group
        self.va_method_name = va_method_name
        self.va_number = va_number
        self.short_ptp_date = short_ptp_date
        self.ptp_amount = ptp_amount
        self.is_j1_customer = is_j1_customer
        self.first_name = first_name
        self.last_name = last_name
        self.month_due_date = month_due_date
        self.year_due_date = year_due_date
        self.due_date_long = due_date_long
        self.age = age
        self.title = title
        self.sms_due_date_short = sms_due_date_short
        self.sms_month = sms_month
        self.sms_firstname = sms_firstname
        self.sms_primary_va_name = sms_primary_va_name
        self.sms_primary_va_number = sms_primary_va_number
        self.sms_payment_details_url = sms_payment_details_url
        self.collection_segment = collection_segment
        self.bank_code = bank_code
        self.bank_code_text = bank_code_text
        self.bank_name = bank_name
        self.cashback_amount = cashback_amount
        self.cashback_counter = cashback_counter
        self.cashback_due_date_slash = cashback_due_date_slash
        self.title_long = title_long
        self.name_with_title = name_with_title
        self.formatted_due_amount = formatted_due_amount
        self.google_calendar_url = google_calendar_url
        self.shopee_score_status = shopee_score_status
        self.shopee_score_list_type = shopee_score_list_type
        self.application_similarity_score = application_similarity_score
        self.mycroft_score = mycroft_score
        self.credit_score = credit_score
        self.active_liveness_score = active_liveness_score
        self.passive_liveness_score = passive_liveness_score
        self.heimdall_score = heimdall_score
        self.orion_score = orion_score
        self.fpgw = fpgw
        self.total_loan_amount = total_loan_amount
        self.late_fee_applied = late_fee_applied
        self.status_code = status_code
        self.is_collection_called = is_collection_called
        self.is_ptp_robocall_active = is_ptp_robocall_active
        self.is_reminder_called = is_reminder_called
        self.is_robocall_active = is_robocall_active
        self.is_success_robocall = is_success_robocall
        self.ptp_date = ptp_date
        self.ptp_robocall_phone_number = ptp_robocall_phone_number
        self.is_restructured = is_restructured
        self.account_payment_xid = account_payment_xid
        self.autodebet_retry_count = autodebet_retry_count
        self.paid_during_refinancing = paid_during_refinancing
        self.is_paid_within_dpd_1to10 = is_paid_within_dpd_1to10
        self.is_autodebet = is_autodebet
        self.internal_sort_order = internal_sort_order
        self.campaign_due_amount = campaign_due_amount
        self.is_risky = is_risky
        self.is_email_blocked = is_email_blocked
        self.is_sms_blocked = is_sms_blocked
        self.is_one_way_robocall_blocked = is_one_way_robocall_blocked

    def to_dict(self):
        return {
            'transaction_id': self.transaction_id,
            'account_id': self.account_id,
            'client_customer_id': self.client_customer_id,
            'customer_due_date': self.customer_due_date,
            'date_of_default': self.date_of_default,
            'allocation_month': self.allocation_month,
            'expected_emi_principal_amount': self.expected_emi_principal_amount,
            'expected_emi_interest_amount': self.expected_emi_interest_amount,
            'expected_emi': self.expected_emi,
            'customer_dpd': self.customer_dpd,
            'late_fee': self.late_fee,
            'allocation_dpd_value': self.allocation_dpd_value,
            'dpd': self.dpd,
            'total_denda': self.total_denda,
            'potensi_cashback': self.potensi_cashback,
            'total_seluruh_perolehan_cashback': self.total_seluruh_perolehan_cashback,
            'total_due_amount': self.total_due_amount,
            'total_claim_amount': self.total_claim_amount,
            'total_outstanding': self.total_outstanding,
            'tipe_produk': self.tipe_produk,
            'last_pay_amount': self.last_pay_amount,
            'activation_amount': self.activation_amount,
            'zip_code': self.zip_code,
            'angsuran_per_bulan': self.angsuran_per_bulan,
            'mobile_phone_1': self.mobile_phone_1,
            'mobile_phone_2': self.mobile_phone_2,
            'nama_customer': self.nama_customer,
            'nama_perusahaan': self.nama_perusahaan,
            'posisi_karyawan': self.posisi_karyawan,
            'nama_pasangan': self.nama_pasangan,
            'nama_kerabat': self.nama_kerabat,
            'hubungan_kerabat': self.hubungan_kerabat,
            'alamat': self.alamat,
            'kota': self.kota,
            'jenis_kelamin': self.jenis_kelamin,
            'tgl_lahir': self.tgl_lahir,
            'tgl_gajian': self.tgl_gajian,
            'tujuan_pinjaman': self.tujuan_pinjaman,
            'va_bca': self.va_bca,
            'va_permata': self.va_permata,
            'va_maybank': self.va_maybank,
            'va_alfamart': self.va_alfamart,
            'va_indomaret': self.va_indomaret,
            'va_mandiri': self.va_mandiri,
            'last_pay_date': self.last_pay_date,
            'partner_name': self.partner_name,
            'last_agent': self.last_agent,
            'last_call_status': self.last_call_status,
            'refinancing_status': self.refinancing_status,
            'program_expiry_date': self.program_expiry_date,
            'customer_bucket_type': self.customer_bucket_type,
            'telp_perusahaan': self.telp_perusahaan,
            'no_telp_pasangan': self.no_telp_pasangan,
            'no_telp_kerabat': self.no_telp_kerabat,
            'uninstall_indicator': self.uninstall_indicator,
            'fdc_risky': self.fdc_risky,
            'email': self.email,
            'cashback_new_scheme_experiment_group': self.cashback_new_scheme_experiment_group,
            'va_method_name': self.va_method_name,
            'va_number': self.va_number,
            'short_ptp_date': self.short_ptp_date,
            'ptp_amount': self.ptp_amount,
            'is_j1_customer': self.is_j1_customer,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'month_due_date': self.month_due_date,
            'year_due_date': self.year_due_date,
            'due_date_long': self.due_date_long,
            'age': self.age,
            'title': self.title,
            'sms_due_date_short': self.sms_due_date_short,
            'sms_month': self.sms_month,
            'sms_firstname': self.sms_firstname,
            'sms_primary_va_name': self.sms_primary_va_name,
            'sms_primary_va_number': self.sms_primary_va_number,
            'sms_payment_details_url': self.sms_payment_details_url,
            'collection_segment': self.collection_segment,
            'bank_code': self.bank_code,
            'bank_code_text': self.bank_code_text,
            'bank_name': self.bank_name,
            'cashback_amount': self.cashback_amount,
            'cashback_counter': self.cashback_counter,
            'cashback_due_date_slash': self.cashback_due_date_slash,
            'title_long': self.title_long,
            'name_with_title': self.name_with_title,
            'formatted_due_amount': self.formatted_due_amount,
            'google_calendar_url': self.google_calendar_url,
            'shopee_score_status': self.shopee_score_status,
            'shopee_score_list_type': self.shopee_score_list_type,
            'application_similarity_score': self.application_similarity_score,
            'mycroft_score': self.mycroft_score,
            'credit_score': self.credit_score,
            'active_liveness_score': self.active_liveness_score,
            'passive_liveness_score': self.passive_liveness_score,
            'heimdall_score': self.heimdall_score,
            'orion_score': self.orion_score,
            'fpgw': self.fpgw,
            'total_loan_amount': self.total_loan_amount,
            'late_fee_applied': self.late_fee_applied,
            'status_code': self.status_code,
            'is_collection_called': self.is_collection_called,
            'is_ptp_robocall_active': self.is_ptp_robocall_active,
            'is_reminder_called': self.is_reminder_called,
            'is_robocall_active': self.is_robocall_active,
            'is_success_robocall': self.is_success_robocall,
            'ptp_date': self.ptp_date,
            'ptp_robocall_phone_number': self.ptp_robocall_phone_number,
            'is_restructured': self.is_restructured,
            'account_payment_xid': self.account_payment_xid,
            'autodebet_retry_count': self.autodebet_retry_count,
            'paid_during_refinancing': self.paid_during_refinancing,
            'is_paid_within_dpd_1to10': self.is_paid_within_dpd_1to10,
            'is_autodebet': self.is_autodebet,
            'sort_order': self.sort_order,
            'campaign_due_amount': self.campaign_due_amount,
            'is_risky': self.is_risky,
            'is_email_blocked': self.is_email_blocked,
            'is_sms_blocked': self.is_sms_blocked,
            'is_one_way_robocall_blocked': self.is_one_way_robocall_blocked,
        }


class UpdateCredgenicsLoan(object):

    transaction_id: str
    client_customer_id: str
    total_outstanding: int
    last_pay_amount: int
    status_code: int
    total_claim_amount: int
    total_due_amount: int

    def __init__(
        self,
        transaction_id: str = None,
        client_customer_id: str = None,
        total_outstanding: int = None,
        last_pay_amount: int = None,
        status_code: int = None,
        total_claim_amount: int = None,
        total_due_amount: int = None,
    ):
        self.transaction_id = transaction_id
        self.client_customer_id = client_customer_id
        self.last_pay_amount = last_pay_amount
        self.total_outstanding = total_outstanding
        self.total_due_amount = total_due_amount
        self.status_code = status_code
        self.total_claim_amount = total_claim_amount

    def to_dict(self):
        return {
            'transaction_id': self.transaction_id,
            'client_customer_id': self.client_customer_id,
            'last_pay_amount': self.last_pay_amount,
            'total_outstanding': self.total_outstanding,
            'total_due_amount': self.total_due_amount,
            'status_code': self.status_code,
            'total_claim_amount': self.total_claim_amount,
        }


class UpdateCredgenicsLoanRepayment(object):

    transaction_id: str
    client_customer_id: str
    amount_recovered: int
    recovery_date: str
    allocation_month: str

    def __init__(
        self,
        client_customer_id: str = None,
        transaction_id: str = None,
        amount_recovered: int = None,
        recovery_date: str = None,
        allocation_month: str = None,
    ):
        self.client_customer_id = client_customer_id
        self.amount_recovered = amount_recovered
        self.recovery_date = recovery_date
        self.transaction_id = transaction_id
        self.allocation_month = CREDGENICS_ALLOCATION_MONTH.JULY_2024

    def to_dict(self):
        return {
            'client_customer_id': self.client_customer_id,
            'amount_recovered': self.amount_recovered,
            'recovery_date': self.recovery_date,
            'transaction_id': self.transaction_id,
        }
