from datetime import timedelta
import logging
from django.db import transaction
from django.utils import timezone

from juloserver.julo.models import FeatureSetting, Loan
from juloserver.fraud_score.clients import get_bonza_client
from juloserver.julo.constants import FeatureNameConst, ApplicationStatusCodes
from juloserver.fraud_score.constants import BonzaConstants
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.models import ExperimentSetting
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.fraud_score.models import (
    BonzaStoringResult, BonzaExpiredHoldout, TransactionFraudModelAccount)
from juloserver.account.constants import AccountConstant
from juloserver.account.services.account_related import process_change_account_status
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)


def eligible_based_on_bonza_scoring(loan, transaction_method_id=None):
    bonza_eligible = True
    bonza_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BONZA_LOAN_SCORING,
        is_active=True).last()
    if bonza_feature and eligible_for_bonza(loan, 'Loan') is True:
        eligible_transaction_methods = bonza_feature.parameters.get(
            'allowed_transaction_method_ids', [])
        if transaction_method_id in eligible_transaction_methods:
            hard_reject_threshold = bonza_feature.parameters.get(
                'bonza_scoring_threshold_hard_reject',
                BonzaConstants.DEFAULT_BONZA_SCORING_THRESHOLD_HARD_REJECT)
            soft_reject_threshold = bonza_feature.parameters.get(
                'bonza_scoring_threshold_soft_reject',
                BonzaConstants.DEFAULT_BONZA_SCORING_THRESHOLD_SOFT_REJECT)
            bonza_client = get_bonza_client(bonza_feature)
            bonza_eligible = bonza_client.validate_loan(
                loan, hard_reject_threshold, soft_reject_threshold)
            return bonza_eligible, bonza_client.reject_reason
    return bonza_eligible, None


def account_under_bonza_experiment_old(account_id):
    reverse_experiment = ExperimentSetting.objects.filter(
        code=ExperimentConst.BONZA_REVERSE_EXPERIMENT, is_active=True).last()
    if reverse_experiment:
        account_id_last_digits = reverse_experiment.criteria.get('test_group_last_account_id', [])
        account_id_last_digits = list(map(str, account_id_last_digits))
        if str(account_id).endswith(tuple(account_id_last_digits)):
            return True
    return False


def account_under_bonza_reverse_experiment(account_id, validate_control_grp=False, expire_act=True):
    reverse_experiment = ExperimentSetting.objects.filter(
        code=ExperimentConst.BONZA_REVERSE_EXPERIMENT, is_active=True).last()
    under_experiement, in_control_performance_grp = False, False
    if reverse_experiment and \
            not BonzaExpiredHoldout.objects.filter(account_id=account_id).exists():
        account_id_last_digits = reverse_experiment.criteria.get('test_group_last_account_id', [])
        account_id_last_digits = list(map(str, account_id_last_digits))
        if str(account_id).endswith(tuple(account_id_last_digits)):
            under_experiement = True
        if under_experiement and validate_control_grp:
            control_performance_grp_digit_list = reverse_experiment.criteria.get(
                'control_performance_grp_digit_list', [0, 1, 2, 3, 4])
            second_last_digit = int(str(account_id)[len(str(account_id)) - 2])
            if second_last_digit in control_performance_grp_digit_list:
                in_control_performance_grp = True
    if under_experiement:
        act_loans = Loan.objects.filter(account_id=account_id).order_by('cdate')
        if act_loans.count() >= 4:
            if expire_act or act_loans.count() > 4:
                BonzaExpiredHoldout.objects.get_or_create(
                    account_id=account_id,
                    defaults={'expired_date': act_loans[3].cdate})
            if act_loans.count() == 4:
                if not expire_act:
                    under_experiement, in_control_performance_grp = False, False
            if act_loans.count() > 4:
                under_experiement, in_control_performance_grp = False, False
    if validate_control_grp:
        return under_experiement, in_control_performance_grp
    else:
        return under_experiement


def eligible_to_hit_application_storing_api(application):
    eligible_statuses = [ApplicationStatusCodes.FORM_PARTIAL, ApplicationStatusCodes.LOC_APPROVED]
    if application.product_line_id == ProductLineCodes.J1 \
            and application.status in eligible_statuses and hasattr(application, 'creditscore') \
            and application.creditscore.score not in ['C', '--']:
        return True
    return False


def eligible_for_bonza(model_object, model_name):
    # Fetch application from model_object
    try:
        application = None
        if model_name == 'Application':
            application = model_object
        elif model_name == 'Loan':
            application = model_object.account.last_application
        elif model_name == 'Payment':
            application = model_object.loan.account.last_application
    except Exception as exception:
        BonzaStoringResult.objects.create(
            method_name='eligible_for_bonza',
            object_id=model_object.id,
            status=str(exception))
        return True

    allowed_partner_names = ['tokopedia', 'cermati']
    if application and application.product_line_id == ProductLineCodes.J1:
        if not application.partner:
            return True
        if application.partner.name in allowed_partner_names:
            return True
    return False


def process_account_reactivation(account):
    try:
        with transaction.atomic():
            history = process_change_account_status(
                account, AccountConstant.STATUS_CODE.active,
                change_reason='Account moved to active after reverification', manual_change=True)
            bonza_feature = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.BONZA_LOAN_SCORING).last()
            reverify_status_expiry_days = bonza_feature.parameters.get(
                'reverify_status_expiry_days', BonzaConstants.DEFAULT_REVERIFY_EXPIRY_DAYS)
            start_expire_date = timezone.localtime(timezone.now())
            end_expire_date = start_expire_date + timedelta(days=reverify_status_expiry_days)
            TransactionFraudModelAccount.objects.create(
                account=account, account_status_history=history,
                start_expire_date=start_expire_date, end_expire_date=end_expire_date,
                fraud_model='Gotham')
            return True
    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error({
            'method': 'process_account_reactivation',
            'account_id': str(account.id),
            'exception': str(e)})
        return False
