from builtins import str
from builtins import object
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.core.validators import RegexValidator
from rest_framework.exceptions import ValidationError
from django.contrib.postgres.fields import JSONField

from babel.dates import format_date

from juloserver.julocore.data.models import TimeStampedModel, GetInstanceMixin, JuloModelManager
from juloserver.julo.models import Payment
from juloserver.julo.models import Application, Loan
from juloserver.webapp.models import WebScrapedData
from .constants import (
    LoanRefinancingStatus,
    CovidRefinancingConst,
    GeneralWebsiteConst,
    ApprovalLayerConst,
    WAIVER_COLL_HEAD_APPROVER_GROUP,
    WAIVER_FRAUD_APPROVER_GROUP,
    WAIVER_OPS_TL_APPROVER_GROUP,
    WAIVER_SPV_APPROVER_GROUP,
    WAIVER_B1_CURRENT_APPROVER_GROUP,
    WAIVER_B2_APPROVER_GROUP,
    WAIVER_B3_APPROVER_GROUP,
    WAIVER_B4_APPROVER_GROUP,
    WAIVER_B5_APPROVER_GROUP,
    WAIVER_B6_APPROVER_GROUP,
    WaiverApprovalDecisions,
)
from django.conf import settings
from datetime import timedelta, datetime
from juloserver.account.models import Account
from juloserver.account_payment.models import AccountPayment

from juloserver.julocore.customized_psycopg2.models import BigForeignKey

ascii_validator = RegexValidator(regex='^[ -~]+$', message='characters not allowed')


class LoanRefinancingMainReason(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_main_reason_id', primary_key=True)
    reason = models.TextField(blank=True, null=True)
    is_active = models.BooleanField()

    class Meta(object):
        db_table = 'loan_refinancing_main_reason'


class LoanRefinancingSubReason(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_sub_reason_id', primary_key=True)
    reason = models.TextField(blank=True, null=True)
    loan_refinancing_main_reason = models.ForeignKey(
        LoanRefinancingMainReason,
        models.DO_NOTHING,
        db_column='loan_refinancing_main_reason_id',
        blank=True,
        null=True)
    is_active = models.BooleanField()

    class Meta(object):
        db_table = 'loan_refinancing_sub_reason'


class LoanRefinancing(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_id', primary_key=True)
    loan = models.ForeignKey(
        Loan,
        models.DO_NOTHING,
        db_column='loan_id',
        blank=True,
        null=True)
    original_tenure = models.IntegerField(default=0)
    tenure_extension = models.IntegerField(default=0)
    new_installment = models.BigIntegerField(default=0)
    refinancing_request_date = models.DateField()
    refinancing_active_date = models.DateField(blank=True, null=True)
    status = models.IntegerField()
    total_latefee_discount = models.BigIntegerField(default=0)
    loan_level_dpd = models.IntegerField(default=0)
    additional_reason = models.TextField(blank=True, null=True)
    loan_refinancing_main_reason = models.ForeignKey(
        LoanRefinancingMainReason,
        models.DO_NOTHING,
        db_column='loan_refinancing_reason_id',
        blank=True,
        null=True)
    loan_refinancing_sub_reason = models.ForeignKey(
        LoanRefinancingSubReason,
        models.DO_NOTHING,
        db_column='loan_refinancing_sub_reason_id',
        blank=True,
        null=True)

    class Meta(object):
        db_table = 'loan_refinancing'

    def change_status(self, status):
        if status == LoanRefinancingStatus.ACTIVE:
            today = timezone.localtime(timezone.now()).date()
            self.refinancing_active_date = today

        self.status = status


class LoanRefinancingRequest(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_request_id', primary_key=True)
    loan = models.ForeignKey(
        Loan,
        models.DO_NOTHING,
        blank=True, null=True,
        db_column='loan_id')
    affordability_value = models.FloatField(blank=True, null=True)
    status = models.TextField(default=CovidRefinancingConst.STATUSES.requested)
    prerequisite_amount = models.BigIntegerField(blank=True, null=True)
    total_latefee_discount = models.BigIntegerField(default=0)
    product_type = models.TextField(blank=True, null=True)
    expire_in_days = models.IntegerField(default=10)
    loan_duration = models.IntegerField(default=0)
    uuid = models.TextField(blank=True, null=True)
    new_income = models.BigIntegerField(blank=True, null=True)
    new_expense = models.BigIntegerField(blank=True, null=True)
    offer_activated_ts = models.DateTimeField(blank=True, null=True)
    form_submitted_ts = models.DateTimeField(blank=True, null=True)
    form_viewed_ts = models.DateTimeField(blank=True, null=True)
    loan_refinancing_main_reason = models.ForeignKey(
        LoanRefinancingMainReason,
        models.DO_NOTHING,
        db_column='loan_refinancing_main_reason_id',
        blank=True,
        null=True)
    loan_refinancing_sub_reason = models.ForeignKey(
        LoanRefinancingSubReason,
        models.DO_NOTHING,
        db_column='loan_refinancing_sub_reason_id',
        blank=True,
        null=True)
    url = models.TextField(blank=True, null=True)
    request_date = models.DateField(blank=True, null=True)
    initial_paid_principal = models.BigIntegerField(blank=True, null=True)
    initial_paid_interest = models.BigIntegerField(blank=True, null=True)
    comms_channel_1 = models.TextField(blank=True, null=True)
    comms_channel_2 = models.TextField(blank=True, null=True)
    comms_channel_3 = models.TextField(blank=True, null=True)
    channel = models.TextField(default='Reactive')
    last_retrigger_comms = models.DateField(blank=True, null=True)
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')
    is_multiple_ptp_payment = models.NullBooleanField(default=False)
    is_gpw = models.NullBooleanField()
    source = models.TextField(blank=True, null=True)
    source_detail = JSONField(null=True)

    class Meta(object):
        db_table = 'loan_refinancing_request'

    def change_status(self, status):
        self.status = status

    @property
    def last_prerequisite_amount(self):
        from .services.refinancing_product_related import (
            get_due_date, get_first_payment_due_date, get_prerequisite_amount_has_paid)

        if not self.prerequisite_amount:
            return 0

        if self.product_type in CovidRefinancingConst.waiver_products():
            return self.prerequisite_amount

        if self.product_type in CovidRefinancingConst.reactive_products():
            paid_amount = get_prerequisite_amount_has_paid(
                self,
                get_due_date(self)
            )
        else:
            paid_amount = get_prerequisite_amount_has_paid(
                self,
                get_first_payment_due_date(self)
            )

        return self.prerequisite_amount - paid_amount

    def comms_channel_list(self):
        channel_list = [self.comms_channel_1, self.comms_channel_2, self.comms_channel_3]
        channel_list = [channel for channel in channel_list if channel is not None]
        return channel_list

    def get_status_ts(self):
        status_date = self.form_submitted_ts or self.cdate

        if self.is_waiver and self.status in [
            CovidRefinancingConst.STATUSES.approved,
            CovidRefinancingConst.STATUSES.activated,
        ]:
            waiver_request = self.waiverrequest_set.last()
            if waiver_request:
                waiver_approval = waiver_request.waiverapproval_set.last()
                status_date = waiver_approval.cdate if waiver_approval else waiver_request.cdate

        if self.status == CovidRefinancingConst.STATUSES.activated:
            status_date = self.offer_activated_ts or status_date

        return status_date

    @property
    def expire_date(self):
        date_ref = self.form_submitted_ts or self.request_date or self.cdate

        if self.status in (CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_email,
                           CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit):
            date_ref = self.request_date or self.cdate
            if type(date_ref) == datetime:
                date_ref = timezone.localtime(date_ref).date()
            return date_ref + timedelta(
                days=CovidRefinancingConst.PROACTIVE_STATUS_EXPIRATION_IN_DAYS[
                    CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_submit]
            )

        if self.status in (CovidRefinancingConst.STATUSES.offer_selected,
                           CovidRefinancingConst.STATUSES.approved):

            offer_accepted_date = None
            loan_refinancing_offer = self.loanrefinancingoffer_set.filter(is_accepted=True).last()
            if loan_refinancing_offer and loan_refinancing_offer.offer_accepted_ts:
                offer_accepted_date = loan_refinancing_offer.offer_accepted_ts.date()
            date_ref = offer_accepted_date or self.request_date or self.cdate
            if type(date_ref) == datetime:
                date_ref = timezone.localtime(date_ref).date()
            return date_ref + timedelta(days=self.expire_in_days)

        if self.status in CovidRefinancingConst.STATUSES.offer_generated:
            if type(date_ref) == datetime:
                date_ref = timezone.localtime(date_ref).date()
            return date_ref + timedelta(
                days=CovidRefinancingConst.PROACTIVE_STATUS_EXPIRATION_IN_DAYS[
                    CovidRefinancingConst.NEW_PROACTIVE_STATUSES.proposed_offer]
            )
        if type(date_ref) == datetime:
            date_ref = timezone.localtime(date_ref).date()
        return date_ref + timedelta(days=self.expire_in_days)

    @property
    def first_due_date(self):
        from .services.refinancing_product_related import (
            get_due_date, get_first_payment_due_date)
        if self.product_type in CovidRefinancingConst.reactive_products():
            first_payment_due_date = get_due_date(self)
        else:
            first_payment_due_date = get_first_payment_due_date(self)

        return first_payment_due_date

    @property
    def is_julo_one(self):
        if self.account:
            return True
        return False

    @property
    def is_reactive(self):
        return self.product_type in CovidRefinancingConst.reactive_products()

    @property
    def is_waiver(self):
        return self.product_type in CovidRefinancingConst.waiver_products()

class WaiverRequestManager(GetInstanceMixin, JuloModelManager):
    pass


class WaiverRequest(TimeStampedModel):
    id = models.AutoField(db_column='waiver_request_id', primary_key=True)
    loan = models.ForeignKey(
        Loan,
        models.DO_NOTHING,
        null=True,
        blank=True,
        db_column='loan_id')
    agent_name = models.TextField(null=True, blank=True)
    bucket_name = models.TextField(blank=True, null=True)
    program_name = models.TextField(blank=True, null=True)
    is_covid_risky = models.BooleanField()
    outstanding_amount = models.BigIntegerField(blank=True, default=0)
    unpaid_principal = models.BigIntegerField(blank=True, default=0)
    unpaid_interest = models.BigIntegerField(blank=True, default=0)
    unpaid_late_fee = models.BigIntegerField(blank=True, default=0)
    waived_payment_count = models.IntegerField(blank=True, null=True, default=0)
    last_payment_number = models.IntegerField(blank=True, null=True, default=0)
    unrounded_requested_late_fee_waiver_percentage = models.FloatField(
        blank=True, null=True)
    requested_late_fee_waiver_percentage = models.TextField(blank=True, null=True)
    requested_late_fee_waiver_amount = models.BigIntegerField(blank=True, default=0)
    unrounded_requested_interest_waiver_percentage = models.FloatField(
        blank=True, null=True)
    requested_interest_waiver_percentage = models.TextField(blank=True, null=True)
    requested_interest_waiver_amount = models.BigIntegerField(blank=True, default=0)
    unrounded_requested_principal_waiver_percentage = models.FloatField(
        blank=True, null=True)
    requested_principal_waiver_percentage = models.TextField(blank=True, null=True)
    requested_principal_waiver_amount = models.BigIntegerField(blank=True, default=0)
    waiver_validity_date = models.DateField(blank=True, null=True)
    reason = models.TextField(blank=True, null=True)
    ptp_amount = models.BigIntegerField(blank=True, default=0)
    is_need_approval_tl = models.BooleanField(default=False)
    is_need_approval_supervisor = models.BooleanField(default=False)
    is_need_approval_colls_head = models.BooleanField(default=False)
    is_need_approval_ops_head = models.BooleanField(default=False)
    partner_product = models.TextField(blank=True, null=True)
    is_automated = models.BooleanField(default=False)
    loan_refinancing_request = models.ForeignKey(
        LoanRefinancingRequest,
        models.DO_NOTHING,
        blank=True,
        null=True,
        db_column='loan_refinancing_request_id')
    first_waived_payment = models.ForeignKey(
        Payment, models.DO_NOTHING, null=True, blank=True, related_name='first_waived_payment')
    last_waived_payment = models.ForeignKey(
        Payment, models.DO_NOTHING, null=True, blank=True, related_name='last_waived_payment')
    agent_notes = models.TextField(blank=True, null=True)
    waiver_recommendation = models.ForeignKey(
        'WaiverRecommendation',
        models.DO_NOTHING,
        blank=True,
        null=True,
        db_column='waiver_recommendation_id')
    requested_waiver_amount = models.BigIntegerField(blank=True, null=True)
    remaining_amount_for_waived_payment = models.BigIntegerField(blank=True, null=True)

    is_approved = models.NullBooleanField()
    final_approved_waiver_amount = models.BigIntegerField(blank=True, null=True)
    final_approved_waiver_program = models.TextField(blank=True, null=True)
    final_approved_remaining_amount = models.BigIntegerField(blank=True, null=True)
    final_approved_waiver_validity_date = models.DateField(blank=True, null=True)
    refinancing_status = models.TextField(blank=True, null=True)
    approval_layer_state = models.TextField(blank=True, null=True)
    waiver_type = models.TextField(blank=True, null=True)
    is_j1 = models.BooleanField(default=False)
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')
    first_waived_account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, related_name='first_waived_account_payment')
    last_waived_account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, related_name='last_waived_account_payment')
    waived_account_payment_count = models.IntegerField(blank=True, null=True, default=0)
    is_multiple_ptp_payment = models.NullBooleanField(default=False)
    number_of_multiple_ptp_payment = models.IntegerField(blank=True, null=True)

    class Meta(object):
        db_table = 'waiver_request'

    objects = WaiverRequestManager()

    @property
    def approver_group_name(self):
        if self.approval_layer_state == ApprovalLayerConst.TL:
            return WAIVER_SPV_APPROVER_GROUP

        if self.approval_layer_state == ApprovalLayerConst.SPV:
            return WAIVER_COLL_HEAD_APPROVER_GROUP

        if self.approval_layer_state == ApprovalLayerConst.COLLS_HEAD:
            return WAIVER_OPS_TL_APPROVER_GROUP

        return None

    @property
    def waiver_payment_request(self):
        return self.waiverpaymentrequest_set

    @property
    def waiver_account_payment_request(self):
        return self.waiveraccountpaymentrequest_set

    @property
    def multiple_payment_ptp(self):
        return self.multiplepaymentptp_set

    @property
    def payment_number_list_str(self):
        waiver_payments = self.waiver_payment_request.order_by("payment__payment_number")
        if waiver_payments:
            payment_ids = []
            for waiver_payment in waiver_payments:
                payment_ids.append("Payment %s" % str(waiver_payment.payment.payment_number))
            return ", ".join(payment_ids)

        return None

    @property
    def account_payment_list_str(self):
        waiver_account_payments = self.waiver_account_payment_request.order_by(
            "account_payment__due_date")
        if waiver_account_payments:
            account_payment_ids = []
            for waiver_account_payment in waiver_account_payments:
                date_str = format_date(
                    waiver_account_payment.account_payment.due_date,
                    'MMMM yyyy', locale='id_ID'
                )
                account_payment_ids.append(date_str)
            return ", ".join(account_payment_ids)

        return None

    @property
    def need_to_pay(self):
        if self.program_name.upper() == CovidRefinancingConst.PRODUCTS.r4:
            outstanding_amount = self.outstanding_amount
        else:
            outstanding_amount = self.ptp_amount + self.requested_waiver_amount
        return outstanding_amount - self.final_approved_waiver_amount

    @property
    def total_approved_late_fee_waiver(self):
        return self.waiver_payment_request.aggregate(
            total_amount=Sum("requested_late_fee_waiver_amount"))['total_amount'] or 0

    @property
    def total_account_payment_approved_late_fee_waiver(self):
        return self.waiver_account_payment_request.aggregate(
            total_amount=Sum("requested_late_fee_waiver_amount"))['total_amount'] or 0

    def ordered_multiple_payment_ptp(self):
        return self.multiple_payment_ptp.order_by('sequence')

    def unpaid_multiple_payment_ptp(self):
        return self.ordered_multiple_payment_ptp().filter(is_fully_paid=False)

    def get_next_approval_layer(self):
        if not self.approval_layer_state:
            return ApprovalLayerConst.TL
        elif self.approval_layer_state == ApprovalLayerConst.TL:
            return ApprovalLayerConst.SPV
        elif self.approval_layer_state == ApprovalLayerConst.SPV:
            return ApprovalLayerConst.COLLS_HEAD
        elif self.approval_layer_state == ApprovalLayerConst.COLLS_HEAD:
            return ApprovalLayerConst.OPS_HEAD
        else:
            raise ValidationError('previous approval_layer_state not valid')

    def is_last_approval_layer(self, waiver_approval):
        if waiver_approval.decision == WaiverApprovalDecisions.REJECTED:
            self.update_safely(is_approved=False)
            return False

        def update_last_approval():
            self.update_safely(
                is_approved=True,
                final_approved_waiver_amount=waiver_approval.approved_waiver_amount,
                final_approved_waiver_program=waiver_approval.approved_program,
                final_approved_remaining_amount=waiver_approval.approved_remaining_amount,
                final_approved_waiver_validity_date=waiver_approval.approved_waiver_validity_date)

        if self.approval_layer_state == ApprovalLayerConst.TL \
                and not self.is_need_approval_supervisor:
            update_last_approval()
            return True
        if self.approval_layer_state == ApprovalLayerConst.SPV \
                and not self.is_need_approval_colls_head:
            update_last_approval()
            return True
        if self.approval_layer_state == ApprovalLayerConst.COLLS_HEAD \
                and not self.is_need_approval_ops_head:
            update_last_approval()
            return True
        if self.approval_layer_state == ApprovalLayerConst.OPS_HEAD:
            update_last_approval()
            return True
        return False

    def update_approval_layer_state(self, user_groups):
        granted = False
        top_level_role_needed = None
        last_approval = self.waiverapproval_set.last()

        if last_approval:
            if last_approval.approver_type == ApprovalLayerConst.TL:
                granted = WAIVER_SPV_APPROVER_GROUP in user_groups
                top_level_role_needed = WAIVER_SPV_APPROVER_GROUP
            elif last_approval.approver_type == ApprovalLayerConst.SPV:
                granted = WAIVER_COLL_HEAD_APPROVER_GROUP in user_groups
                top_level_role_needed = WAIVER_COLL_HEAD_APPROVER_GROUP
            elif last_approval.approver_type == ApprovalLayerConst.COLLS_HEAD:
                granted = WAIVER_OPS_TL_APPROVER_GROUP in user_groups
                top_level_role_needed = WAIVER_OPS_TL_APPROVER_GROUP


        else:
            if self.bucket_name in ['Current', '1', 'Bucket 0', 'current', 'Bucket 1']:
                granted = WAIVER_B1_CURRENT_APPROVER_GROUP in user_groups
            elif self.bucket_name in ['2', 'Bucket 2']:
                granted = WAIVER_B2_APPROVER_GROUP in user_groups
            elif self.bucket_name in ['3', 'Bucket 3']:
                granted = WAIVER_B3_APPROVER_GROUP in user_groups
            elif self.bucket_name in ['4', 'Bucket 4']:
                granted = WAIVER_B4_APPROVER_GROUP in user_groups
            elif self.bucket_name in ['5', 'Bucket 5']:
                granted = WAIVER_B5_APPROVER_GROUP in user_groups
        if not granted:
            top_level_role_needed_msg = ''
            if top_level_role_needed:
                top_level_role_needed_msg = \
                    'dan Role %s untuk melakukan approval' % top_level_role_needed
            raise ValidationError(
                'User anda butuh hak akses sebagai approver waiver bucket %s %s' % (
                    self.bucket_name, top_level_role_needed_msg))

        last_approval_layer = self.get_next_approval_layer()
        self.update_safely(approval_layer_state=last_approval_layer)
        return last_approval_layer


class LoanRefinancingOfferManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanRefinancingOffer(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_offer_id', primary_key=True)
    loan_refinancing_request = models.ForeignKey(
        LoanRefinancingRequest,
        models.DO_NOTHING,
        db_column='loan_refinancing_request_id')
    product_type = models.TextField()
    prerequisite_amount = models.BigIntegerField()
    total_latefee_discount = models.BigIntegerField(default=0)
    total_interest_discount = models.BigIntegerField(default=0)
    total_principal_discount = models.BigIntegerField(default=0)
    loan_duration = models.IntegerField(default=0)
    offer_accepted_ts = models.DateTimeField(blank=True, null=True)
    is_accepted = models.NullBooleanField()
    validity_in_days = models.IntegerField(default=0)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, blank=True, null=True,
        db_column='generated_by_id', related_name='%(class)s_generated_by')
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, blank=True, null=True,
        db_column='selected_by_id', related_name='%(class)s_selected_by')
    is_latest = models.BooleanField(default=False)
    interest_discount_percentage = models.TextField(blank=True, null=True)
    latefee_discount_percentage = models.TextField(blank=True, null=True)
    principal_discount_percentage = models.TextField(blank=True, null=True)
    recommendation_order = models.IntegerField(null=True, blank=True)
    is_proactive_offer = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'loan_refinancing_offer'

    objects = LoanRefinancingOfferManager()


class CollectionOfferEligibility(TimeStampedModel):
    id = models.AutoField(db_column='collection_offer_eligibility_id', primary_key=True)
    mobile_phone = models.CharField(
        max_length=50, blank=True, null=True,
        validators=[ascii_validator, RegexValidator(
            regex=GeneralWebsiteConst.MOBILE_PHONE_REGEX,
            message='mobile phone has to be 10 to 14 numeric digits')]
    )
    status = models.TextField(blank=True, null=True)
    application = models.ForeignKey(
        Application, models.DO_NOTHING, db_column='application_id', null=True, blank=True)
    loan = models.ForeignKey(Loan, models.DO_NOTHING, db_column='loan_id', null=True, blank=True)
    web_scraped_data = models.ForeignKey(
        WebScrapedData, models.DO_NOTHING, db_column='web_scraped_data_id', null=True, blank=True)

    class Meta(object):
        db_table = 'collection_offer_eligibility'


class CollectionOfferExtensionConfiguration(TimeStampedModel):
    id = models.AutoField(db_column='collection_offer_extension_configuration_id', primary_key=True)
    product_type = models.TextField()
    remaining_payment = models.IntegerField()
    max_extension = models.IntegerField()
    date_start = models.DateField()
    date_end = models.DateField()

    class Meta(object):
        db_table = 'collection_offer_extension_configuration'


class WaiverRecommendationManager(GetInstanceMixin, JuloModelManager):
    pass


class WaiverRecommendation(TimeStampedModel):
    id = models.AutoField(db_column='waiver_recommendation_id', primary_key=True)
    bucket_name = models.TextField(blank=True, null=True)
    program_name = models.TextField(blank=True, null=True)
    is_covid_risky = models.BooleanField(default=False)
    partner_product = models.TextField()
    late_fee_waiver_percentage = models.DecimalField(max_digits=15, decimal_places=2)
    interest_waiver_percentage = models.DecimalField(max_digits=15, decimal_places=2)
    principal_waiver_percentage = models.DecimalField(max_digits=15, decimal_places=2)
    total_installments = models.IntegerField(blank=True, null=True)

    objects = WaiverRecommendationManager()

    class Meta(object):
        db_table = 'waiver_recommendation'


class WaiverPaymentRequest(TimeStampedModel):
    id = models.AutoField(db_column='waiver_payment_request_id', primary_key=True)
    waiver_request = models.ForeignKey(WaiverRequest, on_delete=models.DO_NOTHING, blank=True,
                                       null=True,
                                       db_column='waiver_request_id')
    payment = models.ForeignKey(Payment, models.DO_NOTHING, db_column='payment_id', null=True,
                                blank=True)
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
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, db_column='account_payment_id')

    class Meta(object):
        db_table = 'waiver_payment_request'


class WaiverApproval(TimeStampedModel):
    id = models.AutoField(db_column='waiver_approval_id', primary_key=True)
    waiver_request = models.ForeignKey(WaiverRequest,
                                       on_delete=models.DO_NOTHING,
                                       blank=True,
                                       null=True,
                                       db_column='waiver_request_id')
    approver_type = models.TextField()
    paid_ptp_amount = models.BigIntegerField(blank=True, null=True)
    decision = models.TextField()
    decision_ts = models.DateTimeField()
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, blank=True, null=True,
        db_column='approved_by_id', related_name='%(class)s_approved_by')

    approved_program = models.TextField()
    approved_late_fee_waiver_percentage = models.DecimalField(
        max_digits=15, decimal_places=2, blank=True, null=True)
    approved_interest_waiver_percentage = models.DecimalField(
        max_digits=15, decimal_places=2, blank=True, null=True)
    approved_principal_waiver_percentage = models.DecimalField(
        max_digits=15, decimal_places=2, blank=True, null=True)
    approved_waiver_amount = models.BigIntegerField()
    approved_remaining_amount = models.BigIntegerField()
    approved_waiver_validity_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    unrounded_approved_late_fee_waiver_percentage = models.FloatField(blank=True, null=True)
    unrounded_approved_interest_waiver_percentage = models.FloatField(blank=True, null=True)
    unrounded_approved_principal_waiver_percentage = models.FloatField(blank=True, null=True)
    approved_reason_type = models.TextField(blank=True, null=True)
    approved_reason = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'waiver_approval'

    @property
    def need_to_pay(self):
        waiver_request = self.waiver_request
        if waiver_request:
            if waiver_request.program_name.upper() == CovidRefinancingConst.PRODUCTS.r4:
                outstanding_amount = waiver_request.outstanding_amount
            else:
                outstanding_amount = waiver_request.ptp_amount + waiver_request.requested_waiver_amount
            return outstanding_amount - self.approved_waiver_amount - self.approved_remaining_amount

        return 0

    @property
    def waiver_payment_approval(self):
        return self.waiverpaymentapproval_set

    @property
    def waiver_account_payment_approval(self):
        return self.waiveraccountpaymentapproval_set

    @property
    def total_approved_late_fee_waiver(self):
        return self.get_total_approved_waiver_amount("approved_late_fee_waiver_amount")

    @property
    def total_account_payment_approved_late_fee_waiver(self):
        return self.get_total_account_payment_approved_waiver_amount(
            "approved_late_fee_waiver_amount")

    def get_total_approved_waiver_amount(self, field):
        return self.waiver_payment_approval.aggregate(
            total_amount=Sum(field))['total_amount'] or 0

    def get_total_account_payment_approved_waiver_amount(self, field):
        return self.waiver_account_payment_approval.aggregate(
            total_amount=Sum(field))['total_amount'] or 0

    @property
    def is_gpw(self):
        return self.approved_program == "General Paid Waiver"


class WaiverPaymentApproval(TimeStampedModel):
    id = models.AutoField(db_column='waiver_payment_approval_id', primary_key=True)
    waiver_approval = models.ForeignKey(WaiverApproval, on_delete=models.DO_NOTHING,
                                        db_column='waiver_approval_id',
                                        blank=True, null=True)
    payment = models.ForeignKey(Payment, models.DO_NOTHING, db_column='payment_id', null=True,
                                blank=True)
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
    account_payment = models.ForeignKey(
        AccountPayment, models.DO_NOTHING,
        null=True, blank=True, db_column='account_payment_id')

    class Meta(object):
        db_table = 'waiver_payment_approval'

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


class LoanRefinancingRequestCampaignManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanRefinancingRequestCampaign(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_request_campaign_id', primary_key=True)
    loan_id = models.BigIntegerField(null=True, blank=True)
    loan_refinancing_request = models.ForeignKey(
        LoanRefinancingRequest, db_column='loan_refinancing_request_id', null=True)
    campaign_name = models.CharField(max_length=254)
    principal_waiver = models.FloatField(null=True)
    interest_waiver = models.BigIntegerField(null=True)
    late_fee_waiver = models.BigIntegerField(null=True)
    offer = models.CharField(max_length=50, null=True)
    expired_at = models.DateField(null=True)
    status = models.CharField(max_length=50, default='Failed')
    extra_data = JSONField(null=True)
    account = models.ForeignKey(
        Account, models.DO_NOTHING, null=True, blank=True, db_column='account_id')

    class Meta(object):
        db_table = 'loan_refinancing_request_campaign'

    objects = LoanRefinancingRequestCampaignManager()


class RefinancingTenorManager(GetInstanceMixin, JuloModelManager):
    pass


class RefinancingTenor(TimeStampedModel):
    id = models.AutoField(db_column='refinancing_tenor_id', primary_key=True)
    loan_refinancing_request = models.ForeignKey(
        LoanRefinancingRequest, db_column='loan_refinancing_request_id')
    loan = BigForeignKey(Loan, models.DO_NOTHING, db_column='loan_id')
    additional_tenor = models.IntegerField(null=True)

    objects = RefinancingTenorManager()

    class Meta(object):
        db_table = 'refinancing_tenor'


class LoanRefinancingApprovalManager(GetInstanceMixin, JuloModelManager):
    pass


class LoanRefinancingApproval(TimeStampedModel):
    id = models.AutoField(db_column='loan_refinancing_approval_id', primary_key=True)
    loan_refinancing_request = models.ForeignKey(
        LoanRefinancingRequest, models.DO_NOTHING, db_column='loan_refinancing_request_id'
    )
    bucket_name = models.TextField()
    approval_type = models.TextField()
    is_accepted = models.NullBooleanField()
    requestor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        db_column='requestor_id',
        related_name='%(class)s_requestor',
    )
    requestor_reason = models.TextField(blank=True, null=True)
    requestor_notes = models.TextField(blank=True, null=True)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        blank=True,
        null=True,
        db_column='approver_id',
        related_name='%(class)s_approver',
    )
    approver_ts = models.DateTimeField(blank=True, null=True)
    approver_reason = models.TextField(blank=True, null=True)
    approver_notes = models.TextField(blank=True, null=True)
    extra_data = JSONField(null=True)

    class Meta(object):
        db_table = 'loan_refinancing_approval'

    objects = LoanRefinancingApprovalManager()

    def approver_group_name(self):
        next_approval = None
        required_group = None
        if self.approval_type == ApprovalLayerConst.TL:
            next_approval = ApprovalLayerConst.SPV
            if self.bucket_name in ['Current', '1']:
                required_group = WAIVER_B1_CURRENT_APPROVER_GROUP
            elif self.bucket_name == '2':
                required_group = WAIVER_B2_APPROVER_GROUP
            elif self.bucket_name == '3':
                required_group = WAIVER_B3_APPROVER_GROUP
            elif self.bucket_name == '4':
                required_group = WAIVER_B4_APPROVER_GROUP
            elif self.bucket_name == '5':
                required_group = WAIVER_B5_APPROVER_GROUP
            elif self.bucket_name == '6':
                required_group = WAIVER_B6_APPROVER_GROUP
        elif self.approval_type == ApprovalLayerConst.SPV:
            next_approval = ApprovalLayerConst.COLLS_HEAD
            required_group = WAIVER_SPV_APPROVER_GROUP
        elif self.approval_type == ApprovalLayerConst.COLLS_HEAD:
            next_approval = ApprovalLayerConst.OPS_HEAD
            required_group = WAIVER_COLL_HEAD_APPROVER_GROUP
        elif self.approval_type == ApprovalLayerConst.OPS_HEAD:
            required_group = WAIVER_OPS_TL_APPROVER_GROUP

        return required_group, next_approval
