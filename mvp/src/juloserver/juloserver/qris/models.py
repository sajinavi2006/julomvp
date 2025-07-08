import uuid

from model_utils import FieldTracker
from django.db import models
from django.contrib.postgres.fields import JSONField

from juloserver.julocore.customized_psycopg2.models import BigAutoField
from juloserver.julocore.data.models import TimeStampedModel
from juloserver.qris.constants import QrisLinkageStatus, QrisTransactionStatus
from juloserver.julo.models import Image as JuloImage


class DokuQrisTransactionScan(TimeStampedModel):
    id = models.AutoField(db_column='doku_qris_transaction_scan_id', primary_key=True)
    customer = models.ForeignKey('julo.Customer',
                                 models.DO_NOTHING,
                                 db_column='customer_id')
    qr_code = models.TextField()
    acquirer_id = models.TextField(null=True, blank=True)
    card_id = models.TextField(null=True, blank=True)
    primary_account_number = models.TextField(null=True, blank=True)
    merchant_criteria = models.TextField(null=True, blank=True)
    acquirer_name = models.TextField(null=True, blank=True)
    terminal_id = models.TextField(null=True, blank=True)
    additional_data_national = models.TextField(null=True, blank=True)
    transaction_id = models.TextField(null=True, blank=True)
    merchant_category_code = models.TextField(null=True, blank=True)
    merchant_city = models.TextField(null=True, blank=True)
    post_entry_mode = models.TextField(null=True, blank=True)
    merchant_country_code = models.TextField(null=True, blank=True)
    merchant_name = models.TextField(null=True, blank=True)
    to_account_type = models.TextField(null=True, blank=True)
    from_account_type = models.TextField(null=True, blank=True)
    amount = models.BigIntegerField(null=True, blank=True)
    response_code = models.TextField(null=True, blank=True)
    response_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'doku_qris_transaction_scan'


class DokuQrisTransactionPayment(TimeStampedModel):
    id = models.AutoField(db_column='doku_qris_transaction_payment_id', primary_key=True)
    loan = models.OneToOneField('julo.Loan',
                                models.DO_NOTHING,
                                db_column='loan_id',
                                null=True,
                                blank=True,
                                related_name='qris_transaction')
    doku_qris_transaction_scan = models.ForeignKey(
        DokuQrisTransactionScan,
        models.DO_NOTHING,
        db_column='doku_qris_transaction_scan_id',
    )
    merchant_name = models.TextField(null=True, blank=True)
    retry_times = models.IntegerField(default=0)
    amount = models.BigIntegerField(null=True, blank=True)
    acquirer_name = models.TextField(null=True, blank=True)
    reference_number = models.TextField(null=True, blank=True)
    invoice = models.TextField(null=True, blank=True, unique=True)
    conveniences_fee = models.TextField(null=True, blank=True)
    nns_code = models.TextField(null=True, blank=True)
    approval_code = models.TextField(null=True, blank=True)
    invoice_acquirer = models.TextField(null=True, blank=True)
    response_code = models.TextField(null=True, blank=True)
    response_message = models.TextField(null=True, blank=True)
    from_account_type = models.TextField(null=True, blank=True)
    transaction_status = models.TextField(
        null=True, blank=True, default=QrisTransactionStatus.PENDING)

    class Meta:
        db_table = 'doku_qris_transaction_payment'


class DokuQrisTopUp(TimeStampedModel):
    id = models.AutoField(db_column='doku_qris_top_up_id', primary_key=True)
    doku_qris_transaction_payment = models.ForeignKey(
        DokuQrisTransactionPayment,
        models.DO_NOTHING,
        db_column='doku_qris_transaction_payment_id',
        related_name='qris_topup')
    doku_id = models.TextField(null=True, blank=True)
    transaction_id = models.TextField(null=True, blank=True, unique=True)
    amount = models.BigIntegerField(null=True, blank=True)
    tracking_id = models.TextField(null=True, blank=True)
    result = models.TextField(null=True, blank=True)
    date_time = models.DateTimeField(null=True, blank=True)
    client_id = models.TextField(null=True, blank=True)
    response_message = models.TextField(null=True, blank=True)
    response_code = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'doku_qris_top_up'


class DokuQrisVoidTopUp(TimeStampedModel):
    id = models.AutoField(db_column='doku_qris_void_top_up_id', primary_key=True)
    doku_qris_top_up = models.OneToOneField(
        DokuQrisTopUp,
        models.DO_NOTHING,
        db_column='doku_qris_top_up_id')
    transaction_id = models.TextField(null=True, blank=True, unique=True)
    amount = models.BigIntegerField(null=True, blank=True)
    tracking_id = models.TextField(null=True, blank=True)
    date_time = models.DateTimeField(null=True, blank=True)
    response_message = models.TextField(null=True, blank=True)
    response_code = models.TextField(null=True, blank=True)

    class Meta():
        db_table = 'doku_qris_void_top_up'


class QrisPartnerLinkage(TimeStampedModel):
    id = models.AutoField(db_column='qris_partner_linkage_id', primary_key=True)

    customer_id = models.BigIntegerField(db_index=True)
    to_partner_user_xid = models.UUIDField(
        default=uuid.uuid4,
        help_text="xid we send our partners",
        editable=False,
    )
    from_partner_user_xid = models.TextField(
        null=True,
        blank=True,
        help_text="xid partners send us",
    )

    partner_id = models.IntegerField(db_index=True, help_text="id from ops.partner")
    partner_callback_payload = JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=50,
        choices=QrisLinkageStatus.ALL,
        default=QrisLinkageStatus.REQUESTED,
    )

    tracker = FieldTracker()

    class Meta:
        db_table = 'qris_partner_linkage'
        unique_together = [
            ('partner_id', 'from_partner_user_xid'),
            ('partner_id', 'customer_id'),
            ('partner_id', 'to_partner_user_xid'),
        ]


class QrisLinkageLenderAgreement(TimeStampedModel):
    """
    A customer linkage can have multiple lenders
    """

    qris_partner_linkage = models.ForeignKey(
        to=QrisPartnerLinkage,
        on_delete=models.DO_NOTHING,
        db_column='qris_partner_linkage_id',
    )
    lender_id = models.IntegerField(db_index=True)
    signature_image_id = models.IntegerField(
        help_text="id from juloserver.julo.models.Image",
    )
    master_agreement_id = models.IntegerField(
        blank=True,
        null=True,
        help_text="id from juloserver.julo.models.Document, not-null once uploaded",
    )

    class Meta:
        db_table = 'qris_linkage_lender_agreement'
        unique_together = [
            ('qris_partner_linkage', 'lender_id'),
        ]


class QrisUserState(TimeStampedModel):
    """
    Store linkage-user-detail related data
    """
    id = models.AutoField(db_column='qris_user_state_id', primary_key=True)
    qris_partner_linkage = models.OneToOneField(
        to=QrisPartnerLinkage,
        on_delete=models.DO_NOTHING,
        db_column='qris_partner_linkage_id',
        related_name='qris_user_state',
    )

    # all signatures will be stored in QrisCustomerLenderAgreement
    signature_image = models.OneToOneField(
        to=JuloImage,
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name='qris_user_state',
    )

    # all agreements will be stored in QrisCustomerLenderAgreement
    master_agreement_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="id from master agreement processing",
    )

    class Meta:
        db_table = 'qris_user_state'


class QrisPartnerLinkageHistory(TimeStampedModel):
    id = BigAutoField(db_column='qris_partner_linkage_history_id', primary_key=True)
    qris_partner_linkage = models.ForeignKey(
        to=QrisPartnerLinkage,
        on_delete=models.DO_NOTHING,
        db_column='qris_partner_linkage_id',
        related_name='histories',
    )

    field = models.CharField(max_length=50)
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()
    change_reason = models.TextField(default='system_triggered')

    class Meta:
        db_table = 'qris_partner_linkage_history'


class QrisPartnerTransaction(TimeStampedModel):
    id = BigAutoField(db_column='qris_partner_transaction_id', primary_key=True)

    loan_id = models.BigIntegerField(db_index=True, unique=True)

    to_partner_transaction_xid = models.UUIDField(default=uuid.uuid4, editable=False)
    from_partner_transaction_xid = models.TextField(
        null=True, blank=True, help_text="xid we received from partner"
    )

    status = models.CharField(
        max_length=20,
        choices=QrisTransactionStatus.ALL,
        default=QrisTransactionStatus.PENDING,
    )
    qris_partner_linkage = models.ForeignKey(
        to=QrisPartnerLinkage,
        on_delete=models.DO_NOTHING,
        db_column='qris_partner_linkage_id',
        related_name='transactions',
    )
    partner_callback_payload = JSONField(null=True, blank=True)
    partner_transaction_request = JSONField(null=True, blank=True)
    merchant_name = models.CharField(null=True, max_length=100, blank=True)
    total_amount = models.IntegerField(null=True, blank=True)

    tracker = FieldTracker()

    class Meta:
        db_table = 'qris_partner_transaction'
        unique_together = [
            ('qris_partner_linkage', 'from_partner_transaction_xid'),
        ]


class QrisPartnerTransactionHistory(TimeStampedModel):
    id = BigAutoField(db_column='qris_partner_transaction_history_id', primary_key=True)

    qris_partner_transaction = models.ForeignKey(
        to=QrisPartnerTransaction,
        on_delete=models.DO_NOTHING,
        db_column='qris_partner_transaction_id',
        related_name='histories',
    )

    field = models.CharField(max_length=50)
    value_old = models.TextField(null=True, blank=True)
    value_new = models.TextField()
    change_reason = models.TextField(default='system_triggered')

    tracker = FieldTracker()

    class Meta:
        db_table = 'qris_partner_transaction_history'
