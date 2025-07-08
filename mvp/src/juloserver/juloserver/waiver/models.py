from builtins import object
from django.db import models

from juloserver.julocore.data.models import JuloModelManager, TimeStampedModel, GetInstanceMixin
from juloserver.account_payment.models import AccountPayment
from juloserver.loan_refinancing.models import (
    WaiverRequest,
    WaiverApproval,
)


class WaiverAccountPaymentRequestManager(GetInstanceMixin, JuloModelManager):
    pass


class WaiverAccountPaymentRequest(TimeStampedModel):
    id = models.AutoField(db_column='waiver_account_payment_request_id', primary_key=True)
    waiver_request = models.ForeignKey(
        WaiverRequest, on_delete=models.DO_NOTHING,
        blank=True, null=True, db_column='waiver_request_id')
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, db_column='account_payment_id')
    outstanding_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    outstanding_interest_amount = models.BigIntegerField(blank=True, null=True)
    outstanding_principal_amount = models.BigIntegerField(blank=True, null=True)
    total_outstanding_amount = models.BigIntegerField(blank=True, null=True)
    requested_late_fee_waiver_amount = models.BigIntegerField(blank=True, null=True)
    requested_interest_waiver_amount = models.BigIntegerField(blank=True, null=True)
    requested_principal_waiver_amount = models.BigIntegerField(blank=True, null=True)
    total_requested_waiver_amount = models.BigIntegerField(blank=True, null=True)
    remaining_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    remaining_interest_amount = models.BigIntegerField(blank=True, null=True)
    remaining_principal_amount = models.BigIntegerField(blank=True, null=True)
    total_remaining_amount = models.BigIntegerField(blank=True, null=True)
    is_paid_off_after_ptp = models.NullBooleanField()

    objects = WaiverAccountPaymentRequestManager()

    class Meta(object):
        db_table = 'waiver_account_payment_request'


class WaiverAccountPaymentApprovalManager(GetInstanceMixin, JuloModelManager):
    pass


class WaiverAccountPaymentApproval(TimeStampedModel):
    id = models.AutoField(db_column='waiver_account_payment_approval_id', primary_key=True)
    waiver_approval = models.ForeignKey(
        WaiverApproval, on_delete=models.DO_NOTHING,
        blank=True, null=True, db_column='waiver_approval_id')
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, db_column='account_payment_id')
    outstanding_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    outstanding_interest_amount = models.BigIntegerField(blank=True, null=True)
    outstanding_principal_amount = models.BigIntegerField(blank=True, null=True)
    total_outstanding_amount = models.BigIntegerField(blank=True, null=True)
    approved_late_fee_waiver_amount = models.BigIntegerField(blank=True, null=True)
    approved_interest_waiver_amount = models.BigIntegerField(blank=True, null=True)
    approved_principal_waiver_amount = models.BigIntegerField(blank=True, null=True)
    total_approved_waiver_amount = models.BigIntegerField(blank=True, null=True)
    remaining_late_fee_amount = models.BigIntegerField(blank=True, null=True)
    remaining_interest_amount = models.BigIntegerField(blank=True, null=True)
    remaining_principal_amount = models.BigIntegerField(blank=True, null=True)
    total_remaining_amount = models.BigIntegerField(blank=True, null=True)

    objects = WaiverAccountPaymentApprovalManager()

    class Meta(object):
        db_table = 'waiver_account_payment_approval'

    @property
    def requested_late_fee_waiver_amount(self):
        return self.approved_late_fee_waiver_amount

    @property
    def requested_interest_waiver_amount(self):
        return self.approved_interest_waiver_amount

    @property
    def requested_principal_waiver_amount(self):
        return self.approved_principal_waiver_amount

    @property
    def total_requested_waiver_amount(self):
        return self.total_approved_waiver_amount


class MultiplePaymentPTPManager(GetInstanceMixin, JuloModelManager):
    pass


class MultiplePaymentPTP(TimeStampedModel):
    id = models.AutoField(db_column='multiple_payment_ptp_id', primary_key=True)
    waiver_request = models.ForeignKey(
        WaiverRequest, on_delete=models.DO_NOTHING,
        blank=True, null=True, db_column='waiver_request_id')
    sequence = models.IntegerField()
    promised_payment_date = models.DateField()
    promised_payment_amount = models.BigIntegerField()
    paid_amount = models.BigIntegerField(default=0)
    paid_date = models.DateField(blank=True, null=True)
    remaining_amount = models.BigIntegerField()
    is_fully_paid = models.BooleanField(default=False)

    objects = MultiplePaymentPTPManager()

    class Meta(object):
        db_table = 'multiple_payment_ptp'
