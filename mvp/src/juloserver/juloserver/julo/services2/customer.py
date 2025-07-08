from builtins import object
import logging
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    PaymentStatusCodes,
)
from juloserver.julo.models import (Application,
                                    CustomerFieldChange,
                                    FDCInquiryLoan,
                                    FDCInquiry)
from cuser.middleware import CuserMiddleware
from ..services2.experiment import (parallel_bypass_experiment,
                                    is_high_score_parallel_bypassed)
from ..services2.high_score import (feature_high_score_full_bypass,
                                    do_high_score_full_bypass)
from juloserver.apiv2.services import check_iti_repeat
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.db.models import ExpressionWrapper, F, IntegerField

logger = logging.getLogger(__name__)


class CustomerServices(object):

    def is_application_skip_pv_dv(self, application_id):
        skip_pv_dv = False
        application = Application.objects.get_or_none(pk=application_id)
        if application:
            customer = application.customer
            if customer.potential_skip_pv_dv:
                applications = customer.application_set.filter(
                    application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
                ).order_by('id')
                application_before = applications.exclude(id__gte=application.id).last()
                if application_before:
                    paid_off_date = application_before.loan.payment_set.last().paid_date
                    if paid_off_date:
                        apply_date = application.cdate
                        range_day = (apply_date.date() - paid_off_date).days
                        if range_day <= 90:
                            skip_pv_dv = True
        return skip_pv_dv

    def do_high_score_full_bypass_or_iti_bypass(self, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        skip_pv_dv = self.is_application_skip_pv_dv(application_id)
        if skip_pv_dv:
            change_reason = "Repeat_Bypass_DV_PV"
            new_status_code = ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
            # check for new parallel high score bypass experiment
            feature = feature_high_score_full_bypass(application)
            if feature:
                do_high_score_full_bypass(application)
                return

            if check_iti_repeat(application_id):
                change_reason = ExperimentConst.REPEATED_HIGH_SCORE_ITI_BYPASS
                new_status_code = ApplicationStatusCodes.DOCUMENTS_VERIFIED

            return {"new_status_code": new_status_code,
                    "change_reason": change_reason}

    def check_risky_customer(self, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        loan = getattr(application, 'loan',  None)
        is_eligible = application.product_line_id in ProductLineCodes.mtl() \
            and loan and loan.status not in LoanStatusCodes.loan_status_not_active()
        is_risky = False

        fdc_inquiry_180 = FDCInquiry.objects.filter(application_id=application.id,
                                                    application_status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                                                    inquiry_status='success').last()
        fdc_inquiry_100 = FDCInquiry.objects.filter(application_id=application.id,
                                                    application_status_code=ApplicationStatusCodes.FORM_CREATED,
                                                    inquiry_status='success').last()

        fdc_ongoing_loan_after_180 = FDCInquiryLoan.objects.filter(
            fdc_inquiry=fdc_inquiry_180,
            status_pinjaman='Outstanding'
        ).exclude(is_julo_loan=True).count()

        fdc_ongoing_loan_after_100 = FDCInquiryLoan.objects.filter(
            fdc_inquiry=fdc_inquiry_100,
            status_pinjaman='Outstanding'
        ).exclude(is_julo_loan=True).count()

        delinquent = FDCInquiryLoan.objects.filter(
            fdc_inquiry=fdc_inquiry_180,
            dpd_terakhir__gt=5
        ).exclude(is_julo_loan=True).last()

        if not is_eligible or not fdc_ongoing_loan_after_180:
            is_risky = None
        elif fdc_ongoing_loan_after_100 and fdc_ongoing_loan_after_180 > fdc_ongoing_loan_after_100 or delinquent:
            is_risky = True

        return is_risky

    def j1_check_risky_customer(self, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        # check if account have ongoing loan
        account = application.account
        if not account:
            return None

        if not account.loan_set.filter(
                loan_status__gte=LoanStatusCodes.CURRENT, loan_status__lt=LoanStatusCodes.PAID_OFF,
        ).exists():
            return None

        fdc_inquiry_190 = FDCInquiry.objects.filter(
            application_id=application.id,
            application_status_code=ApplicationStatusCodes.LOC_APPROVED,
            inquiry_status='success').last()
        fdc_inquiry_100 = FDCInquiry.objects.filter(
            application_id=application.id,
            application_status_code=ApplicationStatusCodes.FORM_CREATED,
            inquiry_status='success').last()

        fdc_ongoing_loan_after_190 = FDCInquiryLoan.objects.filter(
            fdc_inquiry=fdc_inquiry_190,
            status_pinjaman='Outstanding'
        ).exclude(is_julo_loan=True).count()

        fdc_ongoing_loan_after_100 = FDCInquiryLoan.objects.filter(
            fdc_inquiry=fdc_inquiry_100,
            status_pinjaman='Outstanding'
        ).exclude(is_julo_loan=True).count()
        if fdc_ongoing_loan_after_190 > fdc_ongoing_loan_after_100:
            return True

        # Has been delinquent on other loans in FDC
        delinquent = FDCInquiryLoan.objects.filter(
            fdc_inquiry=fdc_inquiry_190,
            dpd_terakhir__gt=5
        ).exclude(is_julo_loan=True).exists()
        if delinquent:
            return True

        return False


class CustomerFieldChangeRecorded(object):
    """
    Record customer field change

    when we create application after we get customer, the phone number will be update by
    application signal, so phone number changed will be not recorded,
    for this situation copy customer as dict before create application and pass it
    """
    def __init__(self, customer, application_id, current_user, customer_dict=None):
        self.application_id = application_id
        self.customer = customer
        self.current_user = current_user
        if customer_dict:
            self.before_dict = customer_dict
        else:
            self.before_dict = dict(customer.__dict__)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        CuserMiddleware.set_user(self.current_user)
        if exc_value:
            logger.error({
                'status' : 'customer_field_change_record_failed',
                'customer_id': self.customer.pk,
                'application_id': self.application_id
            })
            return

        self.customer.refresh_from_db()
        after_dict = dict(self.customer.__dict__)

        field_changes = [key for key in self.before_dict if (
            not key.startswith('_')) and self.before_dict[key] != after_dict[key]]

        field_changes.remove('udate')
        for field_change in field_changes:
            CustomerFieldChange.objects.create(
                customer=self.customer,
                field_name=field_change,
                old_value=self.before_dict[field_change],
                new_value=after_dict[field_change],
                application_id=self.application_id,
                changed_by_id=self.current_user
            )

        logger.info({
            'status': 'customer_field_changed',
            'field_changes': field_changes
        })
