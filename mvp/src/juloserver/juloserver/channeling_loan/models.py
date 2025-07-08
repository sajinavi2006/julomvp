from builtins import object

from django.core.exceptions import ValidationError
from django.db import models

from juloserver.julo.models import GetInstanceMixin, TimeStampedModel, Loan
from juloserver.julocore.customized_psycopg2.models import (
    BigForeignKey,
    BigAutoField,
)
from juloserver.julocore.data.models import JuloModelManager
from juloserver.channeling_loan.constants import (
    ChannelingStatusConst,
    ChannelingConst,
    ChannelingLenderLoanLedgerConst,
    ChannelingActionTypeConst,
)
from django.contrib.auth.models import User


class ChannelingLoanModelManager(GetInstanceMixin, JuloModelManager):
    pass


class ChannelingLoanModel(TimeStampedModel):
    class Meta(object):
        abstract = True
    objects = ChannelingLoanModelManager()


class ChannelingLoanAPILog(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_api_log_id', primary_key=True)
    channeling_type = models.TextField()
    application = BigForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True)
    loan = BigForeignKey(
        'julo.Loan', models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    request_type = models.TextField()
    http_status_code = models.IntegerField()
    request = models.TextField(null=True, blank=True)
    response = models.TextField()
    error_message = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'channeling_loan_api_log'


class ChannelingLoanHistory(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_history', primary_key=True)
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id')
    old_lender = models.ForeignKey(
        'followthemoney.LenderCurrent', models.DO_NOTHING, db_column='old_lender_id',
        related_name='old_lender', null=True, blank=True)
    new_lender = models.ForeignKey(
        'followthemoney.LenderCurrent', models.DO_NOTHING, db_column='new_lender_id',
        related_name='new_lender', null=True, blank=True)
    channeling_type = models.TextField()
    change_reason = models.TextField(null=True, blank=True)
    date_valid_from = models.DateTimeField(blank=True, null=True)
    date_valid_to = models.DateTimeField(blank=True, null=True)
    is_void = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'channeling_loan_history'


class ChannelingLoanPayment(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_payment_id', primary_key=True)
    payment = BigForeignKey(
        'julo.Payment', models.DO_NOTHING, db_column='payment_id', blank=True, null=True)
    due_date = models.DateField(null=True)
    due_amount = models.BigIntegerField()
    principal_amount = models.BigIntegerField(default=0)
    interest_amount = models.BigIntegerField(default=0)
    channeling_type = models.CharField(
        max_length=50, null=True, blank=True
    )
    actual_daily_interest = models.BigIntegerField(default=0)

    paid_interest = models.BigIntegerField(blank=True, default=0)
    paid_principal = models.BigIntegerField(blank=True, default=0)

    actual_interest_amount = models.BigIntegerField(default=0, blank=True)
    risk_premium_amount = models.BigIntegerField(default=0, blank=True)

    class Meta(object):
        db_table = 'channeling_loan_payment'

    @property
    def outstanding_amount(self):
        return self.outstanding_principal_amount + self.outstanding_interest_amount

    @property
    def outstanding_principal_amount(self):
        return self.principal_amount - self.paid_principal

    @property
    def outstanding_interest_amount(self):
        return self.interest_amount - self.paid_interest

    @property
    def due_principal_amount(self):
        return self.principal_amount - self.paid_principal

    @property
    def due_interest_amount(self):
        return self.interest_amount - self.paid_interest

    @property
    def original_outstanding_amount(self):
        # only outstanding amount for channeling, exclude due interest JULO
        # but NOT include paid amounts
        return self.principal_amount + self.interest_amount


class ChannelingLoanAddress(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_address_id', primary_key=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    address_provinsi = models.CharField(null=True, blank=True, max_length=100)
    address_kabupaten = models.CharField(null=True, blank=True, max_length=100)
    address_kecamatan = models.CharField(null=True, blank=True, max_length=100)
    address_kelurahan = models.CharField(null=True, blank=True, max_length=100)
    address_kodepos = models.CharField(null=True, blank=True, max_length=5)
    version = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'channeling_loan_address'


class ChannelingEligibilityStatusHistory(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_eligibility_status_history_id', primary_key=True)
    application = BigForeignKey('julo.Application', models.DO_NOTHING, db_column='application_id')
    channeling_type = models.TextField()
    eligibility_status = models.CharField(max_length=10)
    version = models.IntegerField(default=0, null=True, blank=True)

    class Meta(object):
        db_table = 'channeling_eligibility_status_history'


class ChannelingEligibilityStatus(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_eligibility_status_id', primary_key=True)
    application = BigForeignKey(
        'julo.Application', models.DO_NOTHING, db_column='application_id', blank=True, null=True
    )
    channeling_type = models.CharField(max_length=10)
    eligibility_status = models.CharField(
        choices=ChannelingStatusConst.ELIGIBILITY_CHOICES, default=ChannelingStatusConst.ELIGIBLE,
        max_length=10
    )
    reason = models.TextField(null=True, blank=True)
    version = models.IntegerField(default=0, null=True, blank=True)

    class Meta(object):
        db_table = 'channeling_eligibility_status'


class ChannelingLoanStatus(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_status_id', primary_key=True)
    channeling_eligibility_status = models.ForeignKey(
        ChannelingEligibilityStatus, models.DO_NOTHING,
        db_column='channeling_eligibility_status_id', blank=True, null=True
    )
    loan = BigForeignKey(
        'julo.Loan', models.DO_NOTHING, db_column='loan_id', blank=True, null=True
    )
    channeling_type = models.CharField(max_length=10)
    channeling_status = models.CharField(
        choices=ChannelingStatusConst.CHOICES, default=ChannelingStatusConst.PENDING,
        max_length=10
    )
    channeling_interest_amount = models.BigIntegerField(default=0)
    channeling_interest_percentage = models.FloatField(default=0, null=True, blank=True)
    actual_interest_percentage = models.FloatField(default=0, null=True, blank=True)
    risk_premium_percentage = models.FloatField(default=0, null=True, blank=True)
    admin_fee = models.FloatField(default=0, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'channeling_loan_status'

    @property
    def channeling_loan_amount(self):
        return self.channeling_interest_amount + self.loan.loan_amount


class ChannelingLoanStatusHistory(ChannelingLoanModel):
    id = BigAutoField(db_column='channeling_loan_status_history_id', primary_key=True)
    channeling_loan_status = models.ForeignKey(
        ChannelingLoanStatus, models.DO_NOTHING, db_column='channeling_loan_status_id'
    )
    old_status = models.CharField(choices=ChannelingStatusConst.CHOICES, max_length=10)
    new_status = models.CharField(choices=ChannelingStatusConst.CHOICES, max_length=10)
    change_by_id = models.IntegerField(blank=True, null=True)
    change_reason = models.TextField(null=True, blank=True)

    class Meta(object):
        db_table = 'channeling_loan_status_history'


class ChannelingLoanThresholdBypassCheckHistory(ChannelingLoanModel):
    id = models.AutoField(
        db_column='channeling_loan_threshold_bypass_check_history_id', primary_key=True
    )
    loan_id = models.BigIntegerField()
    lender_id = models.BigIntegerField()

    class Meta(object):
        db_table = 'channeling_loan_threshold_bypass_check_history'


class ChannelingPaymentEvent(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_payment_event_id', primary_key=True)
    payment_event = models.ForeignKey(
        'julo.PaymentEvent', models.DO_NOTHING, db_column='payment_event_id', unique=True
    )
    payment = BigForeignKey('julo.Payment', models.DO_NOTHING, db_column='payment_id')
    installment_amount = models.BigIntegerField()

    payment_amount = models.BigIntegerField()
    paid_interest = models.BigIntegerField()
    paid_principal = models.BigIntegerField()

    outstanding_amount = models.BigIntegerField()
    outstanding_principal = models.BigIntegerField()
    outstanding_interest = models.BigIntegerField()

    adjusted_principal = models.BigIntegerField(blank=True, null=True, default=0)
    adjusted_interest = models.BigIntegerField(blank=True, null=True, default=0)

    class Meta(object):
        db_table = 'channeling_payment_event'


class ChannelingLoanCityArea(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_city_area_id', primary_key=True)
    city_area = models.CharField(max_length=50, unique=True)
    city_area_code = models.CharField(max_length=20, unique=True)

    class Meta(object):
        db_table = 'channeling_loan_city_area'


class ChannelingLoanSendFileTracking(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_send_file_tracking_id', primary_key=True)
    channeling_type = models.CharField(max_length=10)
    action_type = models.CharField(max_length=20)
    created_by_user_id = models.BigIntegerField(blank=True, null=True, default=None)

    class Meta(object):
        db_table = 'channeling_loan_send_file_tracking'
        index_together = [['channeling_type', 'action_type']]

    def clean(self):
        if self.channeling_type not in dict(ChannelingConst.CHOICES):
            raise ValidationError('Invalid channeling type: {}'.format(self.channeling_type))
        if self.action_type not in dict(ChannelingActionTypeConst.CHOICES):
            raise ValidationError('Invalid action type: {}'.format(self.action_type))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ChannelingLoanApprovalFile(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_loan_approval_file_id', primary_key=True)
    channeling_type = models.CharField(max_length=10)
    file_type = models.CharField(max_length=20)
    is_processed = models.BooleanField(default=False)
    document_id = models.BigIntegerField(blank=True, null=True)
    is_uploaded = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'channeling_loan_approval_file'
        index_together = [['channeling_type', 'file_type']]

    def clean(self):
        if self.channeling_type not in dict(ChannelingConst.CHOICES):
            raise ValidationError('Invalid channeling type: {}'.format(self.channeling_type))
        if self.file_type not in dict(ChannelingActionTypeConst.CHOICES):
            raise ValidationError('Invalid action type: {}'.format(self.file_type))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_processed_succeed(self) -> bool:
        return self.is_processed and self.document_id

    @property
    def is_processed_failed(self) -> bool:
        return self.is_processed and not self.document_id


class LenderOspAccount(ChannelingLoanModel):
    id = models.AutoField(db_column='lender_osp_account_id', primary_key=True)
    lender_account_partner = models.CharField(max_length=100)
    lender_account_name = models.CharField(max_length=100)
    lender_account_note = models.TextField(null=True, blank=True)
    lender_withdrawal_percentage = models.FloatField(default=100)

    balance_amount = models.BigIntegerField(default=0)
    fund_by_lender = models.BigIntegerField(default=0)
    fund_by_julo = models.BigIntegerField(default=0)
    total_outstanding_principal = models.BigIntegerField(default=0)
    priority = models.IntegerField(default=1)

    class Meta(object):
        db_table = 'lender_osp_account'

    def __str__(self):
        """Visual identification"""
        return self.lender_account_name


class LenderOspBalanceHistory(ChannelingLoanModel):
    id = models.AutoField(db_column='lender_osp_balance_history_id', primary_key=True)

    lender_osp_account = models.ForeignKey(
        LenderOspAccount,
        models.DO_NOTHING,
        db_column='lender_osp_account_id',
        null=True,
    )
    old_value = models.CharField(max_length=50, null=True)
    new_value = models.CharField(max_length=50, null=True)
    field_name = models.CharField(max_length=50, null=True)
    reason = models.TextField(default=None, null=True)

    class Meta(object):
        db_table = 'lender_osp_balance_history'


class LenderOspTransaction(ChannelingLoanModel):
    id = models.AutoField(db_column='lender_osp_transaction_id', primary_key=True)
    lender_osp_account = models.ForeignKey(
        LenderOspAccount,
        models.DO_NOTHING,
        db_column='lender_osp_account_id',
    )
    balance_amount = models.BigIntegerField()
    transaction_type = models.CharField(
        max_length=50,
        null=True, blank=True,
        choices=ChannelingLenderLoanLedgerConst.TRANSACTION_TYPE
    )

    class Meta(object):
        db_table = 'lender_osp_transaction'


class LenderLoanLedger(ChannelingLoanModel):
    id = models.AutoField(db_column='lender_loan_ledger_id', primary_key=True)
    lender_osp_account = models.ForeignKey(
        LenderOspAccount,
        models.DO_NOTHING,
        db_column='lender_osp_account_id',
    )
    application_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    loan_xid = models.BigIntegerField(blank=True, null=True, db_index=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    osp_amount = models.BigIntegerField()
    tag_type = models.CharField(
        max_length=50,
        choices=ChannelingLenderLoanLedgerConst.TAG_TYPES
    )
    notes = models.TextField(blank=True, null=True)
    is_fund_by_julo = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'lender_loan_ledger'


class LenderLoanLedgerHistory(ChannelingLoanModel):
    id = models.AutoField(db_column='lender_loan_ledger_history_id', primary_key=True)
    lender_loan_ledger = models.ForeignKey(
        LenderLoanLedger,
        models.DO_NOTHING,
        db_column='lender_loan_ledger_id',
    )
    old_value = models.CharField(max_length=50)
    new_value = models.CharField(max_length=50)
    field_name = models.CharField(max_length=50)

    class Meta(object):
        db_table = 'lender_loan_ledger_history'


class LoanLenderTaggingDpdTemp(TimeStampedModel):
    id = BigAutoField(db_column='loan_lender_tagging_loan_dpd_id', primary_key=True)
    loan = BigForeignKey(
        'julo.Loan', models.DO_NOTHING, db_column='loan_id', blank=True, null=True
    )
    loan_dpd = models.IntegerField(db_index=True)

    class Meta:
        db_table = 'loan_lender_tagging_loan_dpd_temp'


class ChannelingLoanWriteOff(TimeStampedModel):
    id = BigAutoField(db_column='loan_write_off_id', primary_key=True)
    is_write_off = models.BooleanField(default=True)
    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column='user_id',
        blank=True,
        null=True,
    )
    loan = BigForeignKey('julo.Loan', models.DO_NOTHING, db_column='loan_id', blank=True, null=True)
    channeling_type = models.CharField(max_length=20, db_index=True)
    document = models.ForeignKey('julo.Document', db_column='document_id', blank=True, null=True)
    reason = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'channeling_loan_write_off'


class PermataDisbursementAgun(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_disbursement_agun_id', primary_key=True)
    no_pin = models.CharField(max_length=200, blank=True, null=True)
    merk = models.CharField(max_length=200, blank=True, null=True)
    jenis = models.CharField(max_length=200, blank=True, null=True)
    model = models.CharField(max_length=200, blank=True, null=True)
    nopol = models.CharField(max_length=200, blank=True, null=True)
    norang = models.CharField(max_length=200, blank=True, null=True)
    nomes = models.CharField(max_length=200, blank=True, null=True)
    warna = models.CharField(max_length=200, blank=True, null=True)
    tahun_mobil = models.CharField(max_length=200, blank=True, null=True)
    tahun_rakit = models.CharField(max_length=200, blank=True, null=True)
    clinder = models.CharField(max_length=200, blank=True, null=True)
    kelompok = models.CharField(max_length=200, blank=True, null=True)
    penggunaan = models.CharField(max_length=200, blank=True, null=True)
    nilai_score = models.CharField(max_length=200, blank=True, null=True)
    tempat_simpan = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_disbursement_agun"'
        managed = False


class PermataDisbursementCif(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_disbursement_cif_id', primary_key=True)
    loan_id = models.CharField(max_length=200, blank=True, null=True)
    application_id = models.CharField(max_length=200, blank=True, null=True)
    nama = models.CharField(max_length=200, blank=True, null=True)
    nama_rekanan = models.CharField(max_length=200, blank=True, null=True)
    nama_cabang = models.CharField(max_length=200, blank=True, null=True)
    alamat_cbg1 = models.CharField(max_length=200, blank=True, null=True)
    alamat_cbg2 = models.CharField(max_length=200, blank=True, null=True)
    kota = models.CharField(max_length=200, blank=True, null=True)
    usaha = models.CharField(max_length=200, blank=True, null=True)
    alamat_deb1 = models.CharField(max_length=200, blank=True, null=True)
    kota_deb = models.CharField(max_length=200, blank=True, null=True)
    npwp = models.CharField(max_length=200, blank=True, null=True)
    ktp = models.CharField(max_length=200, blank=True, null=True)
    tgl_lahir = models.DateField(blank=True, null=True)
    tgl_novasi = models.CharField(max_length=200, blank=True, null=True)  # ana_db is int
    tmpt_lahir = models.CharField(max_length=200, blank=True, null=True)
    coderk = models.CharField(max_length=200, blank=True, null=True)
    no_rekening = models.CharField(max_length=200, blank=True, null=True)
    tgl_proses = models.DateField(blank=True, null=True)
    kelurahan = models.CharField(max_length=200, blank=True, null=True)
    kecamatan = models.CharField(max_length=200, blank=True, null=True)
    kode_pos = models.CharField(max_length=200, blank=True, null=True)
    status_acc = models.CharField(max_length=200, blank=True, null=True)
    nama_ibu = models.CharField(max_length=200, blank=True, null=True)
    pekerjaan = models.CharField(max_length=200, blank=True, null=True)
    usaha_dimana_bkrj = models.CharField(max_length=200, blank=True, null=True)
    nama_alias = models.CharField(max_length=200, blank=True, null=True)
    status = models.CharField(max_length=200, blank=True, null=True)
    ket_status = models.CharField(max_length=200, blank=True, null=True)
    customer_grouping = models.CharField(max_length=200, blank=True, null=True)
    pasport = models.CharField(max_length=200, blank=True, null=True)
    kodearea = models.CharField(max_length=200, blank=True, null=True)
    telepon = models.CharField(max_length=200, blank=True, null=True)
    jenis_kelamin = models.CharField(max_length=200, blank=True, null=True)
    sandi_pkrj = models.CharField(max_length=200, blank=True, null=True)
    tempat_bekerja = models.CharField(max_length=200, blank=True, null=True)
    bidang_usaha = models.CharField(max_length=200, blank=True, null=True)
    akte_awal = models.CharField(max_length=200, blank=True, null=True)
    tgl_akte_awal = models.CharField(max_length=200, blank=True, null=True)  # ana_db is int
    akte_akhir = models.CharField(max_length=200, blank=True, null=True)
    tgl_akte_akhir = models.CharField(max_length=200, blank=True, null=True)  # ana_db is int
    tgl_berdiri = models.CharField(max_length=200, blank=True, null=True)  # ana_db is int
    dati_debitur = models.CharField(max_length=200, blank=True, null=True)
    hp = models.CharField(max_length=200, blank=True, null=True)
    dati_lahir = models.CharField(max_length=200, blank=True, null=True)
    tmpt_lhr_dati = models.CharField(max_length=200, blank=True, null=True)
    nama_lengkap = models.CharField(max_length=200, blank=True, null=True)
    alamat = models.CharField(max_length=200, blank=True, null=True)
    tlp_rumah = models.CharField(max_length=200, blank=True, null=True)
    kode_jenis_penggunaan_lbu = models.CharField(max_length=200, blank=True, null=True)
    kode_jenis_penggunaan_sid = models.CharField(max_length=200, blank=True, null=True)
    kode_golongan_kredit_umkm_lbu_sid = models.CharField(max_length=200, blank=True, null=True)
    kode_kategori_portfolio_lbu = models.CharField(max_length=200, blank=True, null=True)
    credit_scoring = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_disbursement_cif"'
        managed = False


class PermataDisbursementFin(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_disbursement_fin_id', primary_key=True)
    no_pin = models.CharField(max_length=200, blank=True, null=True)
    tgl_pk = models.DateField(blank=True, null=True)
    tgl_valid = models.DateField(blank=True, null=True)
    tgl_angs1 = models.DateField(blank=True, null=True)
    jmlh_angs = models.CharField(max_length=200, blank=True, null=True)
    cost = models.CharField(max_length=200, blank=True, null=True)
    cost_bank = models.CharField(max_length=200, blank=True, null=True)
    addm = models.CharField(max_length=200, blank=True, null=True)
    ang_deb = models.CharField(max_length=200, blank=True, null=True)
    angs_bank = models.CharField(max_length=200, blank=True, null=True)
    bunga = models.CharField(max_length=200, blank=True, null=True)
    bunga_bank = models.CharField(max_length=200, blank=True, null=True)
    kondisi_agun = models.CharField(max_length=200, blank=True, null=True)
    nilai_agun = models.CharField(max_length=200, blank=True, null=True)
    ptasuran = models.CharField(max_length=200, blank=True, null=True)
    alamat_asur1 = models.CharField(max_length=200, blank=True, null=True)
    alamat_asur2 = models.CharField(max_length=200, blank=True, null=True)
    kota_sur = models.CharField(max_length=200, blank=True, null=True)
    tgl_proses = models.CharField(max_length=200, blank=True, null=True)  # ana_db is int
    premi_asur = models.CharField(max_length=200, blank=True, null=True)
    pembyr_premi = models.CharField(max_length=200, blank=True, null=True)
    asur_cash = models.CharField(max_length=200, blank=True, null=True)
    income = models.CharField(max_length=200, blank=True, null=True)
    nama_ibu = models.CharField(max_length=200, blank=True, null=True)
    selisih_bunga = models.CharField(max_length=200, blank=True, null=True)
    kode_paket = models.CharField(max_length=200, blank=True, null=True)
    biaya_lain = models.CharField(max_length=200, blank=True, null=True)
    cara_biaya = models.CharField(max_length=200, blank=True, null=True)
    periode_byr = models.CharField(max_length=200, blank=True, null=True)
    pokok_awal_pk = models.CharField(max_length=200, blank=True, null=True)
    tenor_awal = models.CharField(max_length=200, blank=True, null=True)
    no_pk = models.CharField(max_length=200, blank=True, null=True)
    net_dp_cash = models.CharField(max_length=200, blank=True, null=True)
    asur_jiwa_ttl = models.CharField(max_length=200, blank=True, null=True)
    asur_jiwa_cash = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_disbursement_fin"'
        managed = False


class PermataDisbursementSipd(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_disbursement_sipd_id', primary_key=True)
    no_pin = models.CharField(max_length=200, blank=True, null=True)
    nama_rekanan = models.CharField(max_length=200, blank=True, null=True)
    alamat_bpr1 = models.CharField(max_length=200, blank=True, null=True)
    alamat_bpr2 = models.CharField(max_length=200, blank=True, null=True)
    kota = models.CharField(max_length=200, blank=True, null=True)
    bukti_kepemilikan = models.CharField(max_length=200, blank=True, null=True)
    no_jaminan = models.CharField(max_length=200, blank=True, null=True)
    tgl = models.DateField(blank=True, null=True)
    nama_pemilik = models.CharField(max_length=200, blank=True, null=True)
    jumlah = models.CharField(max_length=200, blank=True, null=True)
    no_rangka = models.CharField(max_length=200, blank=True, null=True)
    no_mesin = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_disbursement_sipd"'
        managed = False


class PermataDisbursementSlik(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_disbursement_slik_id', primary_key=True)
    loan_id = models.CharField(max_length=200, blank=True, null=True)
    alamat_tempat_bekerja = models.CharField(max_length=200, blank=True, null=True)
    yearly_income = models.CharField(max_length=200, blank=True, null=True)
    jumlah_tanggungan = models.CharField(max_length=200, blank=True, null=True)
    status_perkawinan_debitur = models.CharField(max_length=200, blank=True, null=True)
    nomor_ktp_pasangan = models.CharField(max_length=200, blank=True, null=True)
    nama_pasangan = models.CharField(max_length=200, blank=True, null=True)
    tanggal_lahir_pasangan = models.CharField(
        max_length=200, blank=True, null=True
    )  # ana_db is int
    perjanjian_pisah_harta = models.CharField(max_length=200, blank=True, null=True)
    fasilitas_kredit = models.CharField(max_length=200, blank=True, null=True)
    take_over_dari = models.CharField(max_length=200, blank=True, null=True)
    kode_jenis_pengguna = models.CharField(max_length=200, blank=True, null=True)
    kode_bisa_usaha_slik = models.CharField(
        max_length=200, blank=True, null=True
    )  # should be bidang not bisa
    email = models.CharField(max_length=200, blank=True, null=True)
    alamat_sesuai_domisili = models.CharField(max_length=200, blank=True, null=True)
    kategori_debitur_umkm = models.CharField(max_length=200, blank=True, null=True)
    deskripsi_jenis_pengguna_kredit = models.CharField(max_length=200, blank=True, null=True)
    pembiayaan_produktif = models.CharField(max_length=200, blank=True, null=True)
    monthly_income = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_disbursement_slik"'
        managed = False


class PermataPayment(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_payment_id', primary_key=True)
    loan_id = models.CharField(max_length=200, blank=True, null=True)
    nama = models.CharField(max_length=200, blank=True, null=True)
    tgl_bayar_end_user = models.DateField(blank=True, null=True)
    payment_event_id = models.CharField(max_length=200, blank=True, null=True)
    nilai_angsuran = models.CharField(max_length=200, blank=True, null=True)
    denda = models.CharField(max_length=200, blank=True, null=True)
    diskon_denda = models.CharField(max_length=200, blank=True, null=True)
    tgl_terima_mf = models.DateField(blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_payment"'
        managed = False


class PermataReconciliation(TimeStampedModel):
    id = models.AutoField(db_column='permata_channeling_reconciliation_id', primary_key=True)
    nopin = models.CharField(max_length=200, blank=True, null=True)
    angsuran_ke = models.CharField(max_length=200, blank=True, null=True)
    os_pokok = models.CharField(max_length=200, blank=True, null=True)
    nama = models.CharField(max_length=200, blank=True, null=True)
    dpd = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = '"ana"."permata_channeling_reconciliation"'
        managed = False


class DBSChannelingApplicationJob(TimeStampedModel):
    id = models.AutoField(db_column='dbs_channeling_application_job_id', primary_key=True)
    job_industry = models.CharField(null=True, blank=True, max_length=100)
    job_description = models.CharField(null=True, blank=True, max_length=100)
    is_exclude = models.BooleanField(default=False)
    aml_risk_rating = models.CharField(null=True, blank=True, max_length=6)
    job_code = models.CharField(null=True, blank=True, max_length=2)
    job_industry_code = models.CharField(null=True, blank=True, max_length=2)

    class Meta(object):
        db_table = 'dbs_channeling_application_job'
        index_together = [('job_industry', 'job_description')]


class FAMAChannelingRepaymentApproval(ChannelingLoanModel):
    id = models.AutoField(db_column='fama_channeling_repayment_approval_id', primary_key=True)
    channeling_loan_approval_file = models.ForeignKey(
        ChannelingLoanApprovalFile,
        models.DO_NOTHING,
        db_column='channeling_loan_approval_file_id',
        blank=True,
        null=True,
    )
    loan_id = models.BigIntegerField(blank=True, null=True, db_index=True)
    account_id = models.TextField(blank=True, null=True, db_index=True)
    account_no = models.TextField(blank=True, null=True)
    country_currency = models.CharField(max_length=10, blank=True, null=True)
    payment_type = models.CharField(max_length=10, blank=True, null=True)
    payment_date = models.CharField(max_length=10, blank=True, null=True)
    posting_date = models.CharField(max_length=10, blank=True, null=True)
    partner_payment_id = models.TextField(blank=True, null=True)
    interest_amount = models.BigIntegerField(blank=True, null=True)
    principal_amount = models.BigIntegerField(blank=True, null=True)
    installment_amount = models.BigIntegerField(blank=True, null=True)
    payment_amount = models.BigIntegerField(blank=True, null=True)
    over_payment = models.BigIntegerField(blank=True, null=True)
    term_payment = models.CharField(max_length=10, blank=True, null=True)
    late_charge_amount = models.BigIntegerField(blank=True, null=True)
    early_payment_fee = models.BigIntegerField(blank=True, null=True)
    annual_fee_amount = models.BigIntegerField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'fama_channeling_repayment_approval'


class ARSwitchHistory(TimeStampedModel):
    id = models.AutoField(db_column='ar_switch_history_id', primary_key=True)
    username = models.CharField(max_length=200, blank=True, null=True)
    batch = models.CharField(max_length=200, blank=True, null=True)
    new_lender = models.CharField(max_length=200, blank=True, null=True)
    status = models.CharField(max_length=200, blank=True, null=True)

    class Meta(object):
        db_table = 'ar_switch_history'


class ChannelingBScore(ChannelingLoanModel):
    id = models.AutoField(db_column='channeling_bscore_id', primary_key=True)
    predict_date = models.DateField(null=True, blank=True)
    customer_id = models.BigIntegerField(null=True, blank=True)
    channeling_type = models.CharField(max_length=50, null=True, blank=True)
    model_version = models.CharField(max_length=100, null=True, blank=True)
    pgood = models.FloatField(null=True, blank=True)

    class Meta(object):
        db_table = '"ana"."channeling_bscore"'
        managed = False
