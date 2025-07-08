from typing import Dict
from django.utils import timezone

from datetime import datetime

from juloserver.account.models import AccountProperty, AccountLimit
from juloserver.apiv2.services import remove_fdc_binary_check_that_is_not_in_fdc_threshold
from juloserver.early_limit_release.constants import (
    EarlyReleaseCheckingType,
    PgoodCustomerCheckReasons,
    OdinCustomerCheckReasons,
    RepeatCustomerCheckReasons,
    RegularCustomerCheckReasons,
    UsedLimitCustomerCheckReasons,
    MINIMUM_USED_LIMIT,
    FeatureNameConst,
    LoanDurationsCheckReasons,
    ExperimentationReasons,
    PreRequisiteCheckReasons,
    FDCCustomerCheckReasons,
    PaidOnTimeReasons,
    CreditModelResult,
    ExperimentOption,
    ReleaseTrackingType,
    DEFAULT_DELAY_SECONDS_CALL_FROM_REPAYMENT
)
from juloserver.early_limit_release.exceptions import LoanPaidOffException
from juloserver.early_limit_release.models import (
    EarlyReleaseExperiment,
    EarlyReleaseLoanMapping,
    ReleaseTracking,
    ReleaseTrackingHistory,
    EarlyReleaseCheckingV2,
    EarlyReleaseCheckingHistoryV2,
    OdinConsolidated,
)
from juloserver.julo.models import Payment, PaymentStatusCodes, FeatureSetting, Loan
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loan_refinancing.models import LoanRefinancingRequest
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.account.services.credit_limit import update_account_limit


class EarlyLimitReleaseService:
    def __init__(self, payment, loan, account):
        self.payment = payment
        self.loan = loan
        self.account = account
        self.account_property = AccountProperty.objects.filter(account=self.account).last()
        self.customer = self.account.customer
        self.experiment = None
        self.application = self.customer.application_set.last()

        # the order is important
        self.checking_mapping_pair = [
            (EarlyReleaseCheckingType.PRE_REQUISITE, self.check_pre_requisite),
            (EarlyReleaseCheckingType.PAID_ON_TIME, self.check_paid_on_time),
            (EarlyReleaseCheckingType.EXPERIMENTATION, self.check_experimentation),
            (EarlyReleaseCheckingType.LOAN_DURATION, self.check_loan_durations),
            (EarlyReleaseCheckingType.REGULAR, self.check_regular_customer),
            (EarlyReleaseCheckingType.ODIN, self.check_customer_odin),
            (EarlyReleaseCheckingType.PGOOD, self.check_customer_pgood),
            (EarlyReleaseCheckingType.REPEAT, self.check_repeat_customer),
            (EarlyReleaseCheckingType.USED_LIMIT, self.check_used_limit_customer),
            (EarlyReleaseCheckingType.FDC, self.check_fdc_customer),
        ]

        # limit release options
        self.release_options = {
            ExperimentOption.OPTION_2: self.release_option_2,
        }

    def check_customer_pgood(self):
        criteria = self.experiment.criteria
        pgood_criteria = criteria.get('pgood')

        if pgood_criteria is None:
            return None

        result = {'status': True, 'reason': PgoodCustomerCheckReasons.PASSED_CHECK}
        account_property = self.account_property
        pgood = account_property.pgood

        if pgood < float(pgood_criteria):
            result['status'] = False
            result['reason'] = PgoodCustomerCheckReasons.FAILED_LT + f" {pgood} < {pgood_criteria}"

        return result

    def check_customer_odin(self):
        criteria = self.experiment.criteria
        odin_criteria = criteria.get('odin')

        if odin_criteria is None:
            return None

        result = {'status': True, 'reason': OdinCustomerCheckReasons.PASSED_CHECK}
        odin_consolidated = (
            OdinConsolidated.objects.filter(customer_id=self.customer.id).last()
        )

        if not odin_consolidated:
            result['status'] = False
            result['reason'] = OdinCustomerCheckReasons.FAILED_NF

        odin_score = getattr(odin_consolidated, "odin_consolidated", 0.0)
        if odin_score < float(odin_criteria):
            result['status'] = False
            result['reason'] = OdinCustomerCheckReasons.FAILED_LT + f" {odin_score} < {odin_criteria}"

        return result

    def check_all_rules(self):
        result = {}
        pass_all_checks = True
        for checking_type, checking_func in self.checking_mapping_pair:
            res = checking_func()
            if res is None:
                continue

            checking_status = res.get('status', False)
            result[checking_type] = {'status': checking_status}
            if not checking_status:
                result[checking_type]['reason'] = res['reason']
                pass_all_checks = False
                break

        with db_transactions_atomic(DbConnectionAlias.utilization()):
            checking_obj = EarlyReleaseCheckingV2.objects.select_for_update().filter(
                payment_id=self.payment.id
            ).last()
            if checking_obj:
                create_list_early_release_checking_histories(
                    checking_obj, value_new=result
                )
                checking_obj.checking_result = result
                checking_obj.save()
            else:
                EarlyReleaseCheckingV2.objects.create(
                    payment_id=self.payment.id, checking_result=result
                )

        return pass_all_checks

    def release(self):
        loan_option = self.experiment.option
        with db_transactions_atomic(DbConnectionAlias.utilization()):
            AccountLimit.objects.select_for_update().filter(account_id=self.account.pk).last()
            loan = Loan.objects.get(pk=self.loan.id)
            if loan.loan_status_id == LoanStatusCodes.PAID_OFF:
                raise LoanPaidOffException

            release_option_func = self.release_options[loan_option]
            limit_release_amount = release_option_func()
            EarlyReleaseLoanMapping.objects.get_or_create(
                loan_id=self.loan.id,
                experiment=self.experiment,
                payment_id=self.payment.id,
            )
            update_account_limit(limit_release_amount, self.account.pk)
            return limit_release_amount

    def check_pre_requisite(self) -> Dict:
        result = {'status': True, 'reason': PreRequisiteCheckReasons.PASSED_PRE_REQUISITE_CHECK}
        loan_refinancing = LoanRefinancingRequest.objects.filter(
            account=self.account,
            status__in={
                CovidRefinancingConst.STATUSES.approved,
                CovidRefinancingConst.STATUSES.activated,
            },
        ).last()

        if loan_refinancing:
            loan_refinancing_offer = loan_refinancing.loanrefinancingoffer_set.filter(
                is_accepted=True
            ).last()
            offer_accepted_date = (
                loan_refinancing_offer.offer_accepted_ts if loan_refinancing_offer else None
            )
            request_date = (
                datetime.combine(loan_refinancing.request_date, datetime.min.time())
                if loan_refinancing.request_date
                else None
            )
            date_ref = (
                loan_refinancing.offer_activated_ts
                or offer_accepted_date
                or request_date
                or loan_refinancing.cdate
            )
            if timezone.localtime(date_ref) > timezone.localtime(self.loan.cdate):
                result['status'] = False
                result['reason'] = PreRequisiteCheckReasons.FAILED_CUSTOMER_HAS_LOAN_REFINANCING

        return result

    def check_paid_on_time(self):
        result = {'status': True, 'reason': PaidOnTimeReasons.PASSED_PAID_ON_TIME}
        if self.payment.payment_status_id != PaymentStatusCodes.PAID_ON_TIME:
            result['status'] = False
            result['reason'] = PaidOnTimeReasons.FAILED_PAID_ON_TIME
        return result

    def check_experimentation(self):
        result = {'status': False, 'reason': ExperimentationReasons.FAILED_NO_EXPERIMENT_MATCHED}
        account_id_last_2_digits = str(self.account.id)[-2:]
        experiments = EarlyReleaseExperiment.objects.filter(
            is_active=True, is_delete=False
        ).order_by('-pk')
        for experiment in experiments:
            criteria = experiment.criteria
            last_cust_digit = criteria.get('last_cust_digit', {})
            from_last_digit = last_cust_digit.get('from', '100')
            to_last_digit = last_cust_digit.get('to', '-1')
            if int(from_last_digit) <= int(account_id_last_2_digits) <= int(to_last_digit):
                result['status'] = True
                result['reason'] = ExperimentationReasons.PASSED_EXPERIMENTATION_FOUND_MAPPING
                self.experiment = experiment
                return result

        return result

    def check_loan_durations(self):
        result = {'status': False, 'reason': LoanDurationsCheckReasons.MISSING_EXPERIMENT_CONFIG}
        if not self.experiment or not self.experiment.criteria:
            return result

        loan_duration_payment_rules = self.experiment.criteria.get('loan_duration_payment_rules')
        if not loan_duration_payment_rules:
            return result

        loan_duration_key = str(self.loan.loan_duration)
        if not loan_duration_payment_rules.get(loan_duration_key):
            result['reason'] = LoanDurationsCheckReasons.LOAN_DURATION_FAILED
            return result

        min_payment_number = loan_duration_payment_rules.get(loan_duration_key)
        if not min_payment_number or self.payment.payment_number < min_payment_number:
            result['reason'] = LoanDurationsCheckReasons.MIN_PAYMENT_FAILED
            return result

        result['status'] = True
        result['reason'] = LoanDurationsCheckReasons.PASSED_LOAN_DURATION_PAYMENT_RULE

        return result

    def check_regular_customer(self):
        result = {'status': False, 'reason': RegularCustomerCheckReasons.FAILED_REGULAR_CHECK}

        if self.account_property is not None and self.account_property.is_entry_level is False:
            result['status'] = True
            result['reason'] = RegularCustomerCheckReasons.PASSED_REGULAR_CHECK

        return result

    def check_repeat_customer(self):
        result = {'status': False, 'reason': RepeatCustomerCheckReasons.FAILED_REPEAT_CHECK}

        if not self.application or self.application.product_line_code not in [
            ProductLineCodes.J1,
            ProductLineCodes.JULO_STARTER,
        ]:
            result['reason'] = RepeatCustomerCheckReasons.INCORRECT_PRODUCT_LINE
            return result

        earliest_paid_date = (
            Payment.objects.filter(
                loan__customer=self.customer, loan__loan_status__gte=LoanStatusCodes.CURRENT
            )
            .first()
            .paid_date
        )
        if not earliest_paid_date:
            result['reason'] = RepeatCustomerCheckReasons.EMPTY_PAID_DATE
            return result

        # Convert fund transfer ts from UTC to local time
        if timezone.localtime(self.loan.fund_transfer_ts).date() > earliest_paid_date:
            result['status'] = True
            result['reason'] = RepeatCustomerCheckReasons.PASSED_REPEAT_CHECK

        return result

    def check_used_limit_customer(self):
        result = {'status': False, 'reason': UsedLimitCustomerCheckReasons.FAILED_USED_LIMIT_CHECK}
        fs = FeatureSetting.objects.get(feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE)

        if self.loan.loan_amount >= self.account.get_account_limit.set_limit * \
                fs.parameters.get('minimum_used_limit', MINIMUM_USED_LIMIT) / 100:
            result['status'] = True
            result['reason'] = UsedLimitCustomerCheckReasons.PASSED_USED_LIMIT_CHECK

        return result

    def check_fdc_customer(self):
        result = {
            'status': False,
            'reason': FDCCustomerCheckReasons.FAILED_FDC_CHECK
        }
        _, fdc_result = remove_fdc_binary_check_that_is_not_in_fdc_threshold(
            CreditModelResult,
            ['fdc_inquiry_check'],
            self.application
        )
        if fdc_result:
            result['status'] = True
            result['reason'] = FDCCustomerCheckReasons.PASSED_FDC_CHECK

        return result

    def release_option_1(self):
        # FirstTime: current payment + total previous payment
        # SecondTime: Release the installment of current payment number
        first_tracking = ReleaseTracking.objects.filter(loan_id=self.loan.pk).first()
        first_payment = None
        if first_tracking:
            first_payment = Payment.objects.get(pk=first_tracking.payment_id)
        if (
                first_tracking and
                first_payment and
                self.payment.payment_number != first_payment.payment_number
        ):
            tracking = update_or_create_release_tracking(
                self.loan.id, self.account.id, self.payment.installment_principal,
                payment_id=self.payment.id,
                tracking_type=ReleaseTrackingType.EARLY_RELEASE
            )
            limit_release_amount = tracking.limit_release_amount
        else:
            limit_release_amount = 0
            payments = Payment.objects.filter(
                loan_id=self.loan.pk, payment_number__lte=self.payment.payment_number
            ).values('pk', 'installment_principal')
            for payment in payments:
                limit_release_amount += payment['installment_principal']
                update_or_create_release_tracking(
                    self.loan.id, self.account.id, payment['installment_principal'],
                    payment_id=payment['pk'], tracking_type=ReleaseTrackingType.EARLY_RELEASE
                )

        return limit_release_amount

    def release_option_2(self):
        # Release the installment of current payment number
        tracking = update_or_create_release_tracking(
            self.loan.id, self.account.id, self.payment.installment_principal,
            payment_id=self.payment.id,
            tracking_type=ReleaseTrackingType.EARLY_RELEASE
        )
        return tracking.limit_release_amount


def calculate_loan_amount_for_early_limit(loan, change_limit_amount):
    if loan.status == LoanStatusCodes.PAID_OFF:
        total_limit_release = ReleaseTracking.objects.get_queryset().total_limit_release(loan.id)
        try:
            change_limit_amount = change_limit_amount - (total_limit_release or 0)
            assert change_limit_amount >= 0
        except AssertionError:
            change_limit_amount = 0
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
    return change_limit_amount


def check_early_limit_fs():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE, is_active=True
    ).exists()


def update_or_create_release_tracking(loan_id, account_id, limit_release_amount, payment_id=None,
                                      tracking_type=None):
    data = {
        'loan_id': loan_id,
        'account_id': account_id,
    }
    if payment_id:
        data['payment_id'] = payment_id
    if tracking_type is not None:
        data['type'] = tracking_type

    release_tracking = ReleaseTracking.objects.filter(**data).last()
    old_limit_release_amount = 0
    if release_tracking:
        release_tracking.update_safely(limit_release_amount=limit_release_amount)
        ReleaseTrackingHistory.objects.create(
            release_tracking=release_tracking,
            value_old=old_limit_release_amount,
            value_new=limit_release_amount,
            field_name='limit_release_amount'
        )
    else:
        release_tracking = ReleaseTracking.objects.create(
            **data, limit_release_amount=limit_release_amount
        )
    return release_tracking


def get_early_release_tracking(payment):
    return ReleaseTracking.objects.get_or_none(
        payment_id=payment.id, type=ReleaseTrackingType.EARLY_RELEASE
    )


def get_last_release_tracking(loan):
    return ReleaseTracking.objects.get_or_none(
        loan_id=loan.id, type=ReleaseTrackingType.LAST_RELEASE
    )


def create_list_early_release_checking_histories(obj, value_new):
    value_old = obj.checking_result
    if value_old != value_new:
        EarlyReleaseCheckingHistoryV2.objects.create(
            checking_id=obj.pk,
            value_old=obj.checking_result,
            value_new=value_new
        )
    return None


def get_delay_seconds_call_from_repayment():
    early_limit_release_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE, is_active=True
    ).first()
    return early_limit_release_fs.parameters.get(
        "delay_seconds_call_from_repayment", DEFAULT_DELAY_SECONDS_CALL_FROM_REPAYMENT
    ) if early_limit_release_fs else DEFAULT_DELAY_SECONDS_CALL_FROM_REPAYMENT
