from __future__ import division

import csv
import io
import logging
from typing import Callable, Dict, List, Optional, Union, Tuple, Any

from bulk_update.helper import bulk_update
from dateutil.relativedelta import relativedelta

from django.http import HttpResponse
from past.utils import old_div
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum

from django.db import transaction

from juloserver.account.constants import AccountConstant
from juloserver.account.models import AccountStatusHistory
from juloserver.channeling_loan.clients import SFTPClient, get_fama_sftp_client
from juloserver.apiv2.models import PdBscoreModelResult
from juloserver.channeling_loan.constants.dbs_constants import DBSDisbursementApprovalConst
from juloserver.channeling_loan.constants.fama_constant import FAMADPDRejectionStatusEligibility
from juloserver.channeling_loan.models import (
    ChannelingLoanHistory,
    ChannelingLoanPayment,
    ChannelingEligibilityStatusHistory,
    ChannelingLoanStatus,
    ChannelingLoanStatusHistory,
    ChannelingEligibilityStatus,
    ChannelingLoanSendFileTracking,
    ChannelingLoanApprovalFile,
    ChannelingLoanThresholdBypassCheckHistory,
    ChannelingLoanAPILog,
    ChannelingBScore,
)
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingStatusConst,
    ChannelingConst,
    GeneralIneligible,
    FAMAChannelingConst,
    ChannelingLoanApprovalFileConst,
    FeatureNameConst,
    ChannelingLoanDatiConst,
)
from juloserver.channeling_loan.utils import (
    encrypt_content_with_gpg,
    decrypt_content_with_gpg,
    parse_numbers_only,
    chunk_string,
    response_file,
    calculate_age_by_any_date,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Image,
    Payment,
    FeatureSetting,
    Loan,
    Document,
    Application,
    PaymentEvent,
)
from juloserver.monitors.notifications import get_slack_bot_client
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.utils import (
    get_customer_age,
    get_work_duration_in_month,
    execute_after_transaction_safely,
    upload_file_as_bytes_to_oss,
    get_file_from_oss,
)

from juloserver.followthemoney.constants import (
    LenderTransactionTypeConst,
    SnapshotType,
)
from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderTransactionMapping,
    LenderTransaction,
    LenderTransactionType,
    LenderBalanceCurrent,
    LenderBucket,
)

from datetime import datetime

from juloserver.channeling_loan.exceptions import (
    ChannelingLoanApprovalFileNotFound,
    ChannelingLoanApprovalFileDocumentNotFound,
)
from juloserver.loan.services.loan_related import (
    is_loan_is_zero_interest,
    get_first_payment_date_by_application,
)
from juloserver.promo.services import check_if_loan_has_promo_benefit_type
from juloserver.promo.constants import PromoCodeBenefitConst
from juloserver.personal_data_verification.models import DukcapilResponse
from juloserver.moengage.services.use_cases import \
    send_user_attributes_to_moengage_for_change_lender
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.bpjs.services import check_submitted_bpjs
from juloserver.julocore.python2.utils import py2round
from juloserver.followthemoney.services import get_lender_bucket_xids_by_loans
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.channeling_loan.services.interest_services import (
    ChannelingInterest,
    BNIInterest,
    DBSInterest,
)

from juloserver.channeling_loan.services.feature_settings import CreditScoreConversionSetting

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i: i + n]  # noqa


def send_notification_to_slack(slack_messages, slack_channel):
    slack_bot_client = get_slack_bot_client()

    for slack_message in chunk_string(slack_messages):
        if settings.ENVIRONMENT != "prod":
            slack_message = (
                "Testing Purpose from _*~{}~*_ \n".format(settings.ENVIRONMENT.upper())
                + slack_message
            )

        slack_bot_client.api_call("chat.postMessage", channel=slack_channel, text=slack_message)


def get_channeling_loan_configuration(channeling_type=None, is_active=True):

    filter_params = {
        'feature_name': ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
    }

    if is_active:
        filter_params['is_active'] = True

    all_channeling_feature_setting = FeatureSetting.objects.filter(**filter_params).last()

    if not all_channeling_feature_setting:
        return None

    if not channeling_type:
        return all_channeling_feature_setting.parameters

    if channeling_type in all_channeling_feature_setting.parameters:
        selected_feature_setting = all_channeling_feature_setting.parameters[channeling_type]
        if selected_feature_setting['is_active']:
            return selected_feature_setting

    return None


def is_channeling_lender_dashboard_active(channeling_type):
    # check if lender dashboard is enabled
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)

    if not channeling_loan_config:
        return None

    lender_dashboard = channeling_loan_config.get("lender_dashboard")
    if lender_dashboard["is_active"]:
        return lender_dashboard

    return None


def get_crm_channeling_loan_list():
    channeling_list = []
    all_channeling_donfiguration = get_channeling_loan_configuration()
    if not all_channeling_donfiguration:
        return channeling_list

    for channeling_type, config in all_channeling_donfiguration.items():
        if (
            config['is_active']
            and config['general']['CHANNELING_TYPE'] in ChannelingConst.LIST_CRM_CHANNELING_TYPE
        ):
            channeling_list.append(channeling_type)
    return channeling_list


def get_channeling_loan_priority_list():
    channeling_priority = FeatureSetting.objects.filter(
        feature_name=ChannelingFeatureNameConst.CHANNELING_PRIORITY, is_active=True,
    ).last()
    if channeling_priority and channeling_priority.parameters:
        return channeling_priority.parameters
    return []


def get_selected_channeling_type(loan, now, lender_list=None):
    all_channeling_donfiguration = get_channeling_loan_configuration()
    if not all_channeling_donfiguration:
        return None, None

    if not lender_list:
        channeling_list = get_channeling_loan_priority_list()
        if not channeling_list:
            return None, None
        existing_channeling = ChannelingLoanStatus.objects.filter(
            loan_id=loan.id
        ).values_list('channeling_type', flat=True)
        for channeling_type in channeling_list:
            if channeling_type in existing_channeling:
                channeling_list.remove(channeling_type)
    else:
        channeling_list = []
        for channeling_type, channeling_setting in all_channeling_donfiguration.items():
            if channeling_setting['general']['LENDER_NAME'] in lender_list:
                channeling_list.append(channeling_type)

    selected_channeling_type = []
    for channeling_type in channeling_list:
        if channeling_type not in all_channeling_donfiguration:
            continue

        channeling_loan_setting = all_channeling_donfiguration[channeling_type]
        channeling_whitelist = channeling_loan_setting['whitelist']
        if channeling_whitelist['is_active']:
            application = loan.get_application
            if str(application.id) in channeling_whitelist['APPLICATIONS']:
                selected_channeling_type.append(channeling_type)
            continue

        if not channeling_loan_setting['is_active']:
            continue

        cutoff_config = channeling_loan_setting['cutoff']
        if not cutoff_config['is_active']:
            selected_channeling_type.append(channeling_type)
            continue

        if cutoff_config['CHANNEL_AFTER_CUTOFF']:
            selected_channeling_type.append(channeling_type)
            continue

        today_date = now.date()
        limit = cutoff_config['LIMIT']
        if limit:
            daily_channeling_count = ChannelingLoanStatus.objects.filter(
                channeling_type=channeling_type,
                cdate__date=today_date,
                channeling_status__in=ChannelingStatusConst.COUNT_LIMIT
            ).count()
            if daily_channeling_count > limit:
                continue

        inactive_dates = cutoff_config['INACTIVE_DATE']
        if today_date in (datetime.strptime(x, '%Y/%m/%d').date() for x in inactive_dates):
            continue

        opening_time = now.replace(**cutoff_config["OPENING_TIME"])
        cutoff_time = opening_time.replace(**cutoff_config["CUTOFF_TIME"])
        day_name = now.strftime("%A")
        if day_name not in cutoff_config["INACTIVE_DAY"] and (opening_time <= now <= cutoff_time):
            selected_channeling_type.append(channeling_type)

    if not selected_channeling_type:
        return None, None
    return selected_channeling_type, all_channeling_donfiguration


def get_channeling_loan_status(loan, status=None, extra_params=None):
    if not loan:
        return None

    _filter = {
        "channeling_eligibility_status__application": loan.get_application,
        "channeling_eligibility_status__eligibility_status": ChannelingStatusConst.ELIGIBLE,
        "loan": loan,
    }
    if status:
        _filter['channeling_status'] = status

    if extra_params:
        _filter.update(extra_params)

    return ChannelingLoanStatus.objects.filter(**_filter).last()


def update_channeling_loan_status(
    channeling_loan_status_id, new_status, change_reason="", change_by_id=None
):
    channeling_loan_status = ChannelingLoanStatus.objects.get_or_none(id=channeling_loan_status_id)
    if channeling_loan_status is None:
        logger.error({
            'action': 'channeling_loan.services.update_channeling_loan_status',
            'message': 'channeling_loan_status_not_found',
            'channeling_loan_status_id': channeling_loan_status_id,
            'change_reason': change_reason,
        })
        return

    old_status = channeling_loan_status.channeling_status
    if old_status == new_status:
        logger.error({
            'action': 'channeling_loan.services.update_channeling_loan_status',
            'message': 'status_not_change',
            'channeling_loan_status_id': channeling_loan_status_id,
            'change_reason': change_reason,
        })
        return

    channeling_loan_status.update_safely(channeling_status=new_status, reason=change_reason)
    loan_history_data = {
        'channeling_loan_status': channeling_loan_status,
        'old_status': old_status,
        'new_status': new_status,
        'change_by_id': change_by_id,
        'change_reason': change_reason,
    }
    ChannelingLoanStatusHistory.objects.create(**loan_history_data)


def bulk_update_channeling_loan_status(
    channeling_loan_status_id: List[int],
    new_status: str,
    change_reason: str = "",
    change_by_id: int = None,
) -> None:
    if not channeling_loan_status_id:
        return

    channeling_loan_statuses = ChannelingLoanStatus.objects.filter(id__in=channeling_loan_status_id)

    ChannelingLoanStatusHistory.objects.bulk_create(
        [
            ChannelingLoanStatusHistory(
                channeling_loan_status=channeling_loan_status,
                old_status=channeling_loan_status.channeling_status,
                new_status=new_status,
                change_by_id=change_by_id,
                change_reason=change_reason,
            )
            for channeling_loan_status in channeling_loan_statuses
        ],
        batch_size=300,
    )

    channeling_loan_statuses.update(channeling_status=new_status, reason=change_reason)


def initiate_channeling_loan_status(loan, channeling_type, reason):
    return ChannelingLoanStatus.objects.create(
        loan=loan,
        channeling_type=channeling_type,
        channeling_status=ChannelingStatusConst.INELIGIBLE,
        channeling_interest_amount=0,
        channeling_interest_percentage=0,
        actual_interest_percentage=0,
        risk_premium_percentage=0,
        reason=reason,
    )


def generate_channeling_loan_threshold_bypass_check_history(loan_id, lender_id):
    return ChannelingLoanThresholdBypassCheckHistory.objects.create(
        loan_id=loan_id,
        lender_id=lender_id,
    )


def generate_channeling_loan_status(
    channeling_loan_status,
    channeling_eligibility_status,
    channeling_interest_amount,
    channeling_loan_config=None,
    is_prefund=False,
):
    if not channeling_loan_status:
        return None

    (
        actual_interest_percentage,
        risk_premium_percentage,
        total_interest_percentage
    ) = get_interest_rate_config(
        channeling_eligibility_status.channeling_type, channeling_loan_config
    )
    if not total_interest_percentage:
        return None

    channeling_loan_status.update_safely(
        channeling_eligibility_status=channeling_eligibility_status,
        channeling_interest_amount=channeling_interest_amount,
        channeling_interest_percentage=total_interest_percentage,
        actual_interest_percentage=actual_interest_percentage,
        risk_premium_percentage=risk_premium_percentage,
    )
    update_channeling_loan_status(
        channeling_loan_status_id=channeling_loan_status.id,
        new_status=ChannelingStatusConst.PREFUND if is_prefund else ChannelingStatusConst.PENDING,
    )

    return channeling_loan_status


def get_channeling_eligibility_status(loan, channeling_type, channeling_loan_config):
    if not loan or not channeling_loan_config:
        return None

    application = loan.get_application
    existing_channeling_eligibility_statuses = ChannelingEligibilityStatus.objects.filter(
        application=application,
        channeling_type=channeling_type,
    )
    update_configuration = channeling_loan_config['force_update']
    if not update_configuration['is_active']:
        return existing_channeling_eligibility_statuses.filter(
            eligibility_status=ChannelingStatusConst.ELIGIBLE
        ).last()

    channeling_eligibility_status = existing_channeling_eligibility_statuses.last()
    prev_status, prev_version, is_eligible = "", 0, False
    if channeling_eligibility_status:
        prev_status = channeling_eligibility_status.eligibility_status
        prev_version = channeling_eligibility_status.version
        is_eligible = ChannelingStatusConst.REVERSE_STATUS_MAPPING[prev_status]

    if prev_version < update_configuration['VERSION']:
        is_eligible, reason, version = application_risk_acceptance_ciriteria_check(
            application, channeling_type, channeling_loan_config
        )
        ChannelingEligibilityStatusHistory.objects.create(
            application=application,
            channeling_type=channeling_type,
            eligibility_status=prev_status,
            version=prev_version,
        )
        if not channeling_eligibility_status:
            channeling_eligibility_status = ChannelingEligibilityStatus.objects.create(
                application=application, channeling_type=channeling_type
            )
        channeling_eligibility_status.update_safely(
            eligibility_status=ChannelingStatusConst.STATUS_MAPPING[is_eligible],
            reason=reason,
            version=version,
        )

    return channeling_eligibility_status if is_eligible else None


def generate_channeling_status(application, channeling_type, is_eligible, reason, version):
    return ChannelingEligibilityStatus.objects.create(
        application=application,
        channeling_type=channeling_type,
        eligibility_status=ChannelingStatusConst.STATUS_MAPPING[is_eligible],
        version=version,
        reason=reason,
    )


def application_risk_acceptance_ciriteria_check(
    application, channeling_type, channeling_loan_config=None
):
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_loan_config:
            return False, "RAC not set", ChannelingConst.DEFAULT_VERSION

    customer_age = get_customer_age(application.customer.dob or application.dob)
    work_age = get_work_duration_in_month(application.job_start)
    has_paystub = Image.objects.filter(
        image_source=application.id, image_type='paystub').exists()
    has_bank_statement = Image.objects.filter(
        image_source=application.id, image_type='bank_statement').exists()
    is_bpjs_scrape = check_submitted_bpjs(application)
    has_ktp = Image.objects.filter(
        image_source=application.id, image_type='ktp_self').exists()
    has_selfie = Image.objects.filter(
        image_source=application.id, image_type='selfie').exists()

    rac_configuration = channeling_loan_config['rac']
    version = rac_configuration['VERSION']

    if rac_configuration['MOTHER_MAIDEN_NAME'] and not application.customer_mother_maiden_name:
        return False, "Mother maiden name not set", version

    min_age = rac_configuration['MIN_AGE']
    if min_age and customer_age < min_age:
        return False, "Cannot pass minimum customer age, %s" % (customer_age), version

    max_age = rac_configuration['MAX_AGE']
    if max_age and customer_age > max_age:
        return False, "Cannot pass maximum customer age, %s" % (customer_age), version

    job_types = rac_configuration['JOB_TYPE']
    if job_types and application.job_type not in job_types:
        return False, "%s job_type not accepted" % (application.job_type), version

    min_work_time = rac_configuration['MIN_WORKTIME']
    if min_work_time and work_age < min_work_time:
        return False, "Cannot pass minimum work time, %s" % (work_age), version

    min_income = rac_configuration['MIN_INCOME']
    if min_income and application.monthly_income < min_income:
        return False, "Cannot pass minimum income, %s" % (application.monthly_income), version

    has_income_prove = (is_bpjs_scrape or has_paystub or has_bank_statement)
    if rac_configuration['INCOME_PROVE'] and not has_income_prove:
        return False, "Customer don't have any income prove", version

    has_ktp_or_selfie = (has_ktp and has_selfie)
    if rac_configuration['HAS_KTP_OR_SELFIE'] and not has_ktp_or_selfie:
        return False, "Customer don't have ktp or selfie image", version

    if (
        rac_configuration.get('DUKCAPIL_CHECK') and not DukcapilResponse.objects.filter(
            application=application, name=True, birthdate=True
        ).exists()
    ):
        return False, "Customer don't pass dukcapil check", version

    credit_score_configuration = channeling_loan_config['credit_score']
    if credit_score_configuration['is_active']:
        allowed_score = credit_score_configuration['SCORE']
        score, _ = application.credit_score
        if score not in allowed_score:
            return False, "Credit score not allowed, %s" % score, version

    bscore_configuration = channeling_loan_config['b_score']
    if bscore_configuration['is_active']:
        bscore_model_result = (
            PdBscoreModelResult.objects.filter(
                customer_id=application.customer_id, pgood__isnull=False
            )
            .order_by("cdate")
            .last()
        )

        if not bscore_model_result:
            return False, "B score not provided", version

        b_score = bscore_model_result.pgood

        min_b_score = bscore_configuration["MIN_B_SCORE"]
        if min_b_score and b_score < min_b_score:
            return False, "Cannot pass minimum B score, %s" % b_score, version

        max_b_score = bscore_configuration["MAX_B_SCORE"]
        if max_b_score and b_score > max_b_score:
            return False, "Cannot pass maximum B score, %s" % b_score, version

    return True, "", version


def validate_custom_rac(loan, channeling_type, rac_configuration):
    # any custom RAC based on channeling type
    if channeling_type == ChannelingConst.BNI:
        customer = loan.customer
        detokenize_customers = detokenize_for_model_object(
            PiiSource.CUSTOMER,
            [
                {
                    'object': customer,
                }
            ],
            force_get_local_data=True,
        )
        if not detokenize_customers:
            return False, "Customer not found"

        detokenize_customer = detokenize_customers[0]
        if detokenize_customer.fullname == detokenize_customer.mother_maiden_name:
            return False, "Username same with Mother maiden name"

        if (
            not detokenize_customer.address_kodepos
            or detokenize_customer.address_kodepos == '00000'
            or len(detokenize_customer.address_kodepos) != 5
        ):
            return False, "zipcode is not valid"

        monthly_income = detokenize_customer.monthly_income
        if len(str(monthly_income)) < 7 or len(str(monthly_income)) > 11:
            return False, "monthly_income is not valid"

        phone_number = detokenize_customer.phone
        if len(str(phone_number)) < 12 or len(str(phone_number)) > 15:
            return False, "phone_number is not valid"

        spouse_mobile_phone = detokenize_customer.spouse_mobile_phone
        if detokenize_customer.spouse_name and (
            len(str(spouse_mobile_phone)) < 12 or len(str(spouse_mobile_phone)) > 15
        ):
            return False, "spouse_mobile_phone is not valid"

        kin_mobile_phone = detokenize_customer.kin_mobile_phone
        if detokenize_customer.kin_name and (
            len(str(kin_mobile_phone)) < 12 or len(str(kin_mobile_phone)) > 15
        ):
            return False, "kin_mobile_phone is not valid"

        # make sure first payment is not exceeding 30 days
        first_payment = loan.payment_set.order_by('payment_number').first()
        transfer_date = loan.fund_transfer_ts
        if not transfer_date:
            transfer_date = timezone.now()
        date_diff = (first_payment.due_date - transfer_date.date()).days
        if date_diff > 30:
            return False, "first payment cannot be more than 30 days"

    elif channeling_type == ChannelingConst.SMF:
        # TODO: move this to feature setting
        if loan.product.product_line.product_line_code != ProductLineCodes.J1:
            return False, "Loan is not J1"

    elif channeling_type == ChannelingConst.FAMA:
        customer = loan.customer
        mother_maiden_name = customer.mother_maiden_name

        # Get Feature Setting to get list of exclude mother name FAMA
        get_exclude_mother_maiden_name_fs = FeatureSetting.objects.filter(
            feature_name=ChannelingFeatureNameConst.EXCLUDE_MOTHER_MAIDEN_NAME_FAMA,
            is_active=True).last()

        if get_exclude_mother_maiden_name_fs:
            if not mother_maiden_name:
                return False, "Empty mother maiden name"

            if mother_maiden_name.upper() in get_exclude_mother_maiden_name_fs.parameters:
                return False, "Restricted mother maiden name"

    elif channeling_type == ChannelingConst.BSS:
        return validate_bss_custom_rac(loan, rac_configuration)

    return True, ""


def validate_bss_custom_rac(loan, rac_configuration):
    customer = loan.customer

    gte_current_loans = Loan.objects.filter(
        customer=customer,
        loan_status__gte=LoanStatusCodes.CURRENT,
    ).exclude(pk=loan.id)

    is_ftc = not gte_current_loans.exists()
    loan_ids = gte_current_loans.filter(loan_status__lt=LoanStatusCodes.PAID_OFF).values_list(
        'id', flat=True
    )

    payment_ids = Payment.objects.filter(loan_id__in=loan_ids).values_list('id', flat=True)

    last_due_date = loan.payment_set.last().due_date
    age_by_last_due_date = calculate_age_by_any_date(last_due_date, customer.dob)

    os_loan_amount = ChannelingLoanPayment.objects.filter(
        payment_id__in=payment_ids, channeling_type=ChannelingConst.BSS
    ).aggregate(
        principal_amount=Sum('principal_amount'),
        interest_amount=Sum('interest_amount'),
        paid_principal=Sum('payment__paid_principal'),
        paid_interest=Sum('payment__paid_interest'),
    )

    principal_amount = float(os_loan_amount.get('principal_amount') or 0)
    interest_amount = float(os_loan_amount.get('interest_amount') or 0)
    paid_principal = float(os_loan_amount.get('paid_principal') or 0)
    paid_interest = float(os_loan_amount.get('paid_interest') or 0)

    outstanding_amount = (
        (principal_amount + interest_amount) - (paid_principal + paid_interest) - interest_amount
    ) + loan.loan_amount

    max_age = rac_configuration.get('MAX_AGE', 0)
    if max_age and age_by_last_due_date > max_age:
        return False, "Cannot pass max age, config {}, actual {}".format(
            max_age, age_by_last_due_date
        )

    if is_ftc:
        max_os_amount = rac_configuration.get('MAX_OS_AMOUNT_FTC', 0)
    else:
        max_os_amount = rac_configuration.get('MAX_OS_AMOUNT_REPEAT', 0)

    if isinstance(max_os_amount, int) and outstanding_amount > max_os_amount:
        return False, "Cannot pass max os amount, config {}, actual {}".format(
            max_os_amount, int(outstanding_amount)
        )

    return True, ""


def loan_risk_acceptance_criteria_check(loan, channeling_type, channeling_loan_config=None):
    from juloserver.channeling_loan.services.bss_services import change_city_to_dati_code

    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_loan_config:
            return False, "RAC not set"

    application = loan.get_application
    income_ratio = old_div(float(loan.installment_amount), float(application.monthly_income))

    rac_configuration = channeling_loan_config['rac']
    min_loan = rac_configuration['MIN_LOAN']
    if min_loan and loan.loan_amount < min_loan:
        return False, "Cannot pass minimum loan, %s" % loan.loan_amount

    max_loan = rac_configuration['MAX_LOAN']
    if max_loan and loan.loan_amount > max_loan:
        return False, "Cannot pass maximum loan, %s" % loan.loan_amount

    tenor = rac_configuration['TENOR']
    payment_frequency = loan.product.product_line.payment_frequency
    if tenor and tenor != loan.product.product_line.payment_frequency:
        return False, "Tenor type shouldn't %s" % payment_frequency

    min_tenor = rac_configuration['MIN_TENOR']
    if min_tenor and loan.loan_duration < min_tenor:
        return False, "Cannot pass minimum tenor, %s" % loan.loan_duration

    max_tenor = rac_configuration['MAX_TENOR']
    if max_tenor and loan.loan_duration > max_tenor:
        return False, "Cannot pass maximum tenor, %s" % loan.loan_duration

    max_ratio = rac_configuration['MAX_RATIO']
    if max_ratio and income_ratio > max_ratio:
        return False, "Cannot pass maximum ratio, %s" % income_ratio

    due_date_configuration = channeling_loan_config['due_date']
    if due_date_configuration['is_active']:
        exclusion_day = due_date_configuration['EXCLUSION_DAY']
        if is_payment_due_date_day_in_exclusion_day(loan, exclusion_day):
            return False, "Exclusion by due date, %s" % exclusion_day

    transaction_methods = rac_configuration['TRANSACTION_METHOD']
    if not transaction_methods:
        return False, "Transaction method empty, %s" % loan.transaction_method_id

    if str(loan.transaction_method_id) not in transaction_methods:
        return False, "Transaction method not allowed, %s" % loan.transaction_method_id

    mother_name_fullname_rac = rac_configuration.get('MOTHER_NAME_FULLNAME')
    if (
        mother_name_fullname_rac
        and application.customer_mother_maiden_name.lower() == application.fullname.lower()
    ):
        return False, "Mother name cannot be the same as fullname"

    dati_code = change_city_to_dati_code(application.address_kabupaten)
    if (
        not application.address_kodepos
        or dati_code == ChannelingLoanDatiConst.DEFAULT_NOT_FOUND_CODE
    ):
        return False, "Dati2 code and zip code cannot be empty"

    success, error = validate_custom_rac(loan, channeling_type, rac_configuration)
    return success, error


def filter_loan_adjusted_rate(loan, channeling_type_list, all_channeling_loan_config=None):
    """
    This function used for check if the loan is adjusted or not
    normally, if adjusted channeling process will be blocked, but we have Feature Setting
    INCLUDE_LOAN_ADJUSTED to allow channeling even if loan is adjusted
    with some rule [daily_interest_channeling] from lender
    must be smaller than [daily_interest_loan]
    """

    # Check feature setting if it is need BYPASS loan adjusted check rate
    ineligibilities = get_editable_ineligibilities_config()
    if ineligibilities and not ineligibilities.get(GeneralIneligible.LOAN_ADJUSTED_RATE.name, True):
        return channeling_type_list

    is_adjusted = hasattr(loan, 'loanadjustedrate')
    if not is_adjusted:
        # no need to check anything if loan is not adjusted
        return channeling_type_list

    if not all_channeling_loan_config:
        all_channeling_loan_config = get_channeling_loan_configuration()

    loan_daily_interest = loan.loanadjustedrate.adjusted_monthly_interest_rate / 30 * 100
    channeling_loan_adjusted = []
    for key in channeling_type_list:
        """
        need to check channeling_lender with INCLUDE_LOAN_ADJUSTED
        also need to check if those feature is on
        record result if loan daily_interest is still bigger than the channeling daily_interest
        """
        fs_config = all_channeling_loan_config.get(key)
        if fs_config and fs_config['rac']['INCLUDE_LOAN_ADJUSTED']:
            general_fs_config = fs_config['general']
            interest = general_fs_config['INTEREST_PERCENTAGE']
            days_in_year = general_fs_config['DAYS_IN_YEAR']
            daily_interest = interest / days_in_year
            if daily_interest <= loan_daily_interest:
                channeling_loan_adjusted.append(key)

    return channeling_loan_adjusted


def is_payment_due_date_day_in_exclusion_day(loan, exclusion_day):
    feb_month = 2
    payments = loan.payment_set.normal()
    if payments:
        return (
            payments.filter(due_date__day__in=exclusion_day)
            .exclude(due_date__month=feb_month)
            .exists()
        )

    is_has_exclusion_day = False
    application = loan.get_application
    first_payment_date = get_first_payment_date_by_application(application)

    for payment_number in range(loan.loan_duration):
        due_date = first_payment_date
        if payment_number > 0:
            due_date = first_payment_date + relativedelta(
                months=payment_number, day=application.account.cycle_day
            )

        if str(due_date.day) in exclusion_day and due_date.month != feb_month:
            is_has_exclusion_day = True
            break

    return is_has_exclusion_day


def loan_from_partner(loan):
    return PartnerLoanRequest.objects.filter(loan=loan).exists()


def get_interest_rate_config(channeling_type, channeling_loan_config=None, is_daily=True):
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_loan_config:
            return None, None, None

    general_configuration = channeling_loan_config["general"]
    actual_interest_rate = general_configuration['INTEREST_PERCENTAGE']
    risk_premium_rate = general_configuration['RISK_PREMIUM_PERCENTAGE']
    # return annual yearly if not is_daily
    days_in_a_year = 1
    if is_daily:
        days_in_a_year = general_configuration['DAYS_IN_YEAR']

    return (
        (actual_interest_rate / 100 / days_in_a_year),
        (risk_premium_rate / 100 / days_in_a_year),
        ((actual_interest_rate + risk_premium_rate) / 100 / days_in_a_year),
    )


def get_channeling_days_in_year(channeling_type, channeling_loan_config=None):
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_loan_config:
            return None

    return channeling_loan_config["general"]['DAYS_IN_YEAR']


def calculate_risk_interest_amount(principal_total, percentage, diff_date):
    daily_interest = float(principal_total) * float(percentage)
    return round(float(daily_interest) * float(diff_date.days))


def recalculate_channeling_payment_interest(loan, channeling_type, channeling_loan_config=None):
    interest_dict = {}
    payments = loan.payment_set.order_by('payment_number')
    channeling_payments = ChannelingLoanPayment.objects.filter(
        payment__in=payments, channeling_type=channeling_type
    )
    if channeling_payments:
        for channeling_payment in channeling_payments:
            interest_dict[channeling_payment.payment.id] = channeling_payment.interest_amount
        return interest_dict

    (
        actual_interest_percentage,
        risk_premium_percentage,
        total_interest_percentage
    ) = get_interest_rate_config(channeling_type, channeling_loan_config, False)
    if not total_interest_percentage:
        return None

    days_in_year = get_channeling_days_in_year(channeling_type, channeling_loan_config)

    if channeling_type not in (ChannelingConst.BSS, ChannelingConst.SMF):
        if channeling_type == ChannelingConst.BNI:
            # BNI the only non PMT for now
            channeling_interest = BNIInterest(
                loan, channeling_type, risk_premium_percentage, days_in_year, list(payments)
            )
            return channeling_interest.channeling_payment_interest()
        elif channeling_type == ChannelingConst.DBS:
            # DBS using roundup instead normal rounding
            channeling_interest = DBSInterest(
                loan, channeling_type, total_interest_percentage, days_in_year, list(payments)
            )
        else:
            channeling_interest = ChannelingInterest(
                loan, channeling_type, total_interest_percentage, days_in_year, list(payments)
            )
        return channeling_interest.pmt_channeling_payment_interest()

    actual_interest_percentage = actual_interest_percentage / days_in_year
    risk_premium_percentage = risk_premium_percentage / days_in_year
    total_interest_percentage = total_interest_percentage / days_in_year

    channeling_loan_payments = []
    start_date = timezone.localtime(loan.fund_transfer_ts).date()
    principal_total = loan.loan_amount
    for payment in payments:
        diff_date = payment.due_date - start_date

        total_interest = calculate_risk_interest_amount(
            principal_total, total_interest_percentage, diff_date
        )
        actual_interest = calculate_risk_interest_amount(
            principal_total, actual_interest_percentage, diff_date
        )
        risk_premium = calculate_risk_interest_amount(
            principal_total, risk_premium_percentage, diff_date
        )

        start_date = payment.due_date
        principal_total -= payment.installment_principal

        interest_dict[payment.id] = total_interest
        channeling_loan_payments.append(
            ChannelingLoanPayment(
                payment=payment,
                due_date=payment.due_date,
                due_amount=payment.due_amount,
                principal_amount=payment.installment_principal,
                interest_amount=total_interest,
                channeling_type=channeling_type,
                actual_interest_amount=actual_interest,
                risk_premium_amount=risk_premium,
            )
        )

    if channeling_loan_payments:
        ChannelingLoanPayment.objects.bulk_create(channeling_loan_payments)

    return interest_dict


def channeling_buyback_process(loan, channeling_type, channeling_loan_config=None):
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_loan_config:
            return False, "Channeling configuration not set"

    general_config = channeling_loan_config['general']
    lender = LenderCurrent.objects.get_or_none(lender_name=general_config['BUYBACK_LENDER_NAME'])
    if not lender:
        return False, "Lender not found"

    transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=LenderTransactionTypeConst.CHANNELING_BUYBACK)
    if not transaction_type:
        return False, "TransactionType not found"

    channeling_proccess_status, message = success_channeling_process(
        loan, lender, transaction_type, loan.get_outstanding_principal(),
        ChannelingStatusConst.SUCCESS, ChannelingStatusConst.BUYBACK
    )
    if channeling_proccess_status == ChannelingStatusConst.FAILED:
        return False, message
    return True, None


def update_loan_lender(loan, lender, channeling_type, change_reason, is_channeling=False):
    today = timezone.now().date()
    channeling_loan_histories = ChannelingLoanHistory.objects.filter(
        loan=loan,
        is_void=False,
        date_valid_from__month=today.month,
        date_valid_from__year=today.year,
    ).order_by('cdate')
    first_channeling_loan_history = channeling_loan_histories.first()
    previous_channeling_loan_history = channeling_loan_histories.last()
    old_lender = loan.lender

    channeling_loan_history = ChannelingLoanHistory.objects.create(
        loan=loan,
        old_lender=old_lender,
        new_lender=lender,
        channeling_type=channeling_type,
        change_reason=change_reason,
        is_void=False,
    )
    channeling_loan_history.update_safely(date_valid_from=channeling_loan_history.cdate)
    if not channeling_loan_histories:
        return old_lender, channeling_loan_history

    if previous_channeling_loan_history:
        previous_channeling_loan_history.update_safely(date_valid_to=channeling_loan_history.cdate)

    if first_channeling_loan_history:
        original_lender = first_channeling_loan_history.old_lender
        original_lender_month = first_channeling_loan_history.date_valid_from.month
        original_lender_year = first_channeling_loan_history.date_valid_from.year
        list_channeling_loan_history = []

        # is_void = True if the loans revert back to original lender in the same month of the year
        if (
            original_lender == lender  # revert back to original lender
            and original_lender_month == channeling_loan_history.date_valid_from.month  # same month
            and original_lender_year == channeling_loan_history.date_valid_from.year  # same year
        ):
            channeling_loan_history.update_safely(is_void=True)
            for last_channeling_loan_history in channeling_loan_histories:
                last_channeling_loan_history.is_void = True
                list_channeling_loan_history.append(last_channeling_loan_history)
        elif (
            original_lender != lender
            and original_lender_month == channeling_loan_history.date_valid_from.month  # same month
            and original_lender_year == channeling_loan_history.date_valid_from.year  # same year
        ):
            # go back to original lender and change again to another lender
            channeling_loan_history.update_safely(is_void=False)
        elif (
            original_lender == lender  # revert back to original lender
            and original_lender_month < channeling_loan_history.date_valid_from.month  # diff month
            and original_lender_year >= channeling_loan_history.date_valid_from.year
        ):
            # changes in different month and go back to original lender after the month changes
            channeling_loan_history.update_safely(is_void=True)
            is_void = False
            for last_channeling_loan_history in channeling_loan_histories:
                last_channeling_loan_history.is_void = is_void
                list_channeling_loan_history.append(last_channeling_loan_history)
                is_void = True

        if list_channeling_loan_history:
            bulk_update(list_channeling_loan_history, update_fields=['is_void'])

    loan.update_safely(lender=lender)

    if is_channeling:
        # some functions which call to update_loan_lender() use transaction.atomic
        # so run this task after transaction is committed to guarantee loan is updated new lender
        execute_after_transaction_safely(
            lambda: send_user_attributes_to_moengage_for_change_lender.delay(loan_id=loan.id)
        )

    return old_lender, channeling_loan_history


def calculate_new_lender_balance(
        loan_id, loan_amount, lender, channeling_loan_history, transaction_type):
    from juloserver.followthemoney.tasks import calculate_available_balance
    lender_balance = LenderBalanceCurrent.objects.select_for_update().filter(lender=lender).last()
    lender_transaction = LenderTransaction.objects.create(
        lender=lender,
        lender_balance_current=lender_balance,
        transaction_type=transaction_type,
        transaction_amount=-loan_amount,
    )
    LenderTransactionMapping.objects.create(
        lender_transaction=lender_transaction,
        channeling_transaction=channeling_loan_history,
    )

    loan_interest_amount = Payment.objects.filter(loan_id=loan_id).aggregate(
        total_amount=Sum('installment_interest')).get('total_amount')
    outstanding_interest = lender_balance.outstanding_interest + loan_interest_amount
    outstanding_principal = lender_balance.outstanding_principal + loan_amount
    updated_dict = {
        'outstanding_principal': outstanding_principal,
        'outstanding_interest': outstanding_interest,
        'loan_amount': loan_amount,
        'is_delay': False,
    }
    calculate_available_balance(lender_balance.id, SnapshotType.TRANSACTION, **updated_dict)


def calculate_old_lender_balance(
        loan_id, loan_amount, lender, channeling_loan_history, transaction_type):
    from juloserver.followthemoney.tasks import calculate_available_balance
    lender_balance = LenderBalanceCurrent.objects.select_for_update().filter(lender=lender).last()
    lender_transaction = LenderTransaction.objects.create(
        lender=lender,
        lender_balance_current=lender_balance,
        transaction_type=transaction_type,
        transaction_amount=loan_amount,
    )
    LenderTransactionMapping.objects.create(
        lender_transaction=lender_transaction,
        channeling_transaction=channeling_loan_history,
    )

    loan_interest_amount = Payment.objects.filter(loan_id=loan_id).aggregate(
        total_amount=Sum('installment_interest')).get('total_amount')
    outstanding_interest = lender_balance.outstanding_interest - loan_interest_amount
    outstanding_principal = lender_balance.outstanding_principal - loan_amount
    updated_dict = {
        'outstanding_principal': outstanding_principal,
        'outstanding_interest': outstanding_interest,
        'repayment_amount': loan_amount,
        'is_delay': False,
    }
    calculate_available_balance(lender_balance.id, SnapshotType.TRANSACTION, **updated_dict)


@transaction.atomic
def success_channeling_process(
    loan, lender, transaction_type, amount, current_status, new_status, reason=None
):
    from juloserver.channeling_loan.services.fama_services import (
        update_fama_eligibility_rejected_by_dpd,
    )

    # follow the money block
    channeling_loan_status = get_channeling_loan_status(loan, current_status)
    if not channeling_loan_status:
        return ChannelingStatusConst.FAILED, "Channeling status data missing"

    if new_status == ChannelingStatusConst.SUCCESS:
        channeling_type = channeling_loan_status.channeling_type
        old_lender, channeling_loan_history = update_loan_lender(
            loan, lender, channeling_type, "{} Channeling".format(channeling_type),
            is_channeling=True
        )

        if not lender.is_pre_fund_channeling_flow:
            # Bring amount back to old lender
            calculate_old_lender_balance(
                loan.id, amount, old_lender, channeling_loan_history, transaction_type)

            # Deduct bss lender balance
            calculate_new_lender_balance(
                loan.id, amount, lender, channeling_loan_history, transaction_type)

            # generate new P3PTI & SKRTP
            generate_new_summary_lender_and_julo_one_loan_agreement(
                loan=loan, lender=lender, channeling_type=channeling_type
            )

    change_reason = "Success from partner"
    if new_status == ChannelingStatusConst.REJECT:
        change_reason = reason if reason else "Reject From Partner"

    update_channeling_loan_status(
        channeling_loan_status.id, new_status, change_reason=change_reason
    )
    # Update the eligibility
    if (
        FAMADPDRejectionStatusEligibility.dpd in change_reason.lower()
        and channeling_loan_status.channeling_type == ChannelingConst.FAMA
    ):
        update_fama_eligibility_rejected_by_dpd(channeling_loan_status.loan)
    return ChannelingStatusConst.SUCCESS, None


def success_prefund_loan_for_channeling(loan):
    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.PROCESS)
    if not channeling_loan_status:
        return ChannelingStatusConst.FAILED, "Channeling loan status data missing"

    update_channeling_loan_status(channeling_loan_status.id, ChannelingStatusConst.SUCCESS)
    return ChannelingStatusConst.SUCCESS, None


def process_loan_for_channeling(loan):
    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.PENDING)
    if not channeling_loan_status:
        return ChannelingStatusConst.FAILED, "Channeling loan status data missing"

    update_channeling_loan_status(channeling_loan_status.id, ChannelingStatusConst.PROCESS)
    return ChannelingStatusConst.SUCCESS, None


def cancel_loan_for_channeling(loan, channeling_loan_status):
    channeling_loan_status = get_channeling_loan_status(loan, channeling_loan_status)
    if not channeling_loan_status:
        return ChannelingStatusConst.FAILED, "Channeling loan status data missing"

    update_channeling_loan_status(channeling_loan_status.id, ChannelingStatusConst.FAILED)
    return ChannelingStatusConst.FAILED, "Channeling loan cannot be proccess"


def approve_loan_for_channeling(
    loan, approval_status, channeling_type, channeling_loan_config=None, reason=None
):
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_loan_config:
            return ChannelingStatusConst.FAILED, "Channeling configuration not set"

    if not loan:
        return ChannelingStatusConst.FAILED, "Loan not found"

    general_config = channeling_loan_config['general']
    lender = LenderCurrent.objects.get_or_none(lender_name=general_config['LENDER_NAME'])
    if not lender:
        return ChannelingStatusConst.FAILED, "Lender not found"

    transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=LenderTransactionTypeConst.CHANNELING)
    if not transaction_type:
        return ChannelingStatusConst.FAILED, "Channeling transaction not found"

    if loan.lender and loan.lender.lender_name in general_config['EXCLUDE_LENDER_NAME']:
        return ChannelingStatusConst.FAILED, "Lender excluded"

    if not lender.is_pre_fund_channeling_flow:
        if not hasattr(lender, 'lenderbalancecurrent'):
            return ChannelingStatusConst.FAILED, "Lender balance not found"

        lender_balance = lender.lenderbalancecurrent
        if lender_balance.available_balance < loan.loan_amount:
            return ChannelingStatusConst.FAILED, "Lender balance is less than loan amount"

    channeling_loan_status = get_channeling_loan_status(loan, ChannelingStatusConst.PROCESS)
    if not channeling_loan_status:
        return ChannelingStatusConst.FAILED, "Channeling loan status data missing"

    if approval_status.lower() not in ('y', 'n'):
        return ChannelingStatusConst.FAILED, "Approval status not match, %s" % approval_status

    new_status = ChannelingStatusConst.SUCCESS
    if approval_status == "n":
        new_status = ChannelingStatusConst.REJECT

    channeling_process_status, message = success_channeling_process(
        loan,
        lender,
        transaction_type,
        loan.loan_amount,
        ChannelingStatusConst.PROCESS,
        new_status,
        reason,
    )

    if channeling_process_status == ChannelingStatusConst.FAILED:
        return channeling_process_status, message

    return ChannelingStatusConst.SUCCESS, ""


def generate_new_summary_lender_and_julo_one_loan_agreement(loan, lender, channeling_type):
    from juloserver.followthemoney.tasks import (
        assign_lenderbucket_xid_to_lendersignature,
        generate_summary_lender_loan_agreement,
        generate_julo_one_loan_agreement,
    )

    if channeling_type and not is_channeling_lender_dashboard_active(channeling_type):
        # Generate new P3PTI
        # Lender bucket will not be generated if its already generated before via lender dashboard
        lender_bucket = LenderBucket.objects.create(
            partner=lender.user.partner,
            total_approved=1,
            total_rejected=0,
            total_disbursement=loan.loan_disbursement_amount,
            total_loan_amount=loan.loan_amount,
            loan_ids={"approved": [loan.id], "rejected": []},
            is_disbursed=True,
            is_active=True,
            action_time=timezone.localtime(timezone.now()),
            action_name='Disbursed',
        )
        assign_lenderbucket_xid_to_lendersignature(
            [loan.id], lender_bucket.lender_bucket_xid, is_loan=True
        )
    else:
        loan_lender_buckets_xids = get_lender_bucket_xids_by_loans([loan])
        lender_bucket_xid = loan_lender_buckets_xids.get(loan.pk, "")
        lender_bucket = LenderBucket.objects.filter(lender_bucket_xid=lender_bucket_xid)

    if lender_bucket:
        execute_after_transaction_safely(
            lambda: generate_summary_lender_loan_agreement.delay(
                lender_bucket.id,
                is_new_generate=True,
            )
        )

    # Generate new SKRTP
    execute_after_transaction_safely(
        lambda: generate_julo_one_loan_agreement.delay(loan.id, is_new_generate=True)
    )


def is_account_had_loan_paid_off(account):
    return Loan.objects.filter(account=account, loan_status_id=LoanStatusCodes.PAID_OFF).exists()


def is_account_status_entered_gt_420(account):
    return AccountStatusHistory.objects.filter(
        account=account,
        status_new__gt=AccountConstant.STATUS_CODE.active
    ).exists()


def is_account_had_installment_paid_off(account):
    """
    If account has a paid installment
    """
    return Payment.objects.filter(
        loan__account_id=account.id,
        payment_status_id__in=PaymentStatusCodes.paid_status_codes(),
    ).exists()


def get_editable_ineligibilities_config() -> Dict[str, bool]:
    """
    Get the general editable ineligibilities feature setting config
    """
    fs = FeatureSetting.objects.filter(
        feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_EDITABLE_INELIGIBILITIES,
        is_active=True
    ).last()
    if fs:
        return fs.parameters
    return None


def is_block_regenerate_document_ars_config_active():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BLOCK_REGENERATE_DOCUMENT_AR_SWITCHING, is_active=True
    ).exists()


def get_bypass_daily_limit_threshold_config():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BYPASS_DAILY_LIMIT_THRESHOLD, is_active=True
    ).last()


def get_general_channeling_ineligible_conditions(
    loan: Loan,
) -> Dict[GeneralIneligible.Condition, Callable[..., bool]]:
    """
    Return ineligible conditions for general channeling
    """
    all_ineligible_conditions = {
        GeneralIneligible.LOAN_NOT_FOUND: lambda: loan is None,
        GeneralIneligible.ZERO_INTEREST_LOAN_NOT_ALLOWED: lambda: is_loan_is_zero_interest(loan),
        GeneralIneligible.HAVENT_PAID_OFF_A_LOAN: (
            lambda: not is_account_had_loan_paid_off(loan.account)
        ),
        GeneralIneligible.HAVENT_PAID_OFF_AN_INSTALLMENT: (
            lambda: not is_account_had_installment_paid_off(loan.account)
        ),
        GeneralIneligible.ACCOUNT_STATUS_MORE_THAN_420_AT_SOME_POINT: (
            lambda: is_account_status_entered_gt_420(loan.account)
        ),
        GeneralIneligible.AUTODEBIT_INTEREST_BENEFIT: (
            lambda: not loan.account.is_account_eligible_to_hit_channeling_api()
        ),
        GeneralIneligible.LOAN_HAS_INTEREST_BENEFIT: (
            lambda: check_if_loan_has_promo_benefit_type(
                loan, PromoCodeBenefitConst.INTEREST_DISCOUNT
            )
        ),
        GeneralIneligible.LOAN_FROM_PARTNER: lambda: loan_from_partner(loan),
    }

    # remove inactive ones based on fs
    to_remove = []
    ineligibilities = get_editable_ineligibilities_config()
    if ineligibilities:
        for condition, _ in all_ineligible_conditions.items():
            # remove if its not set as True
            if not ineligibilities.get(condition.name, True):
                to_remove.append(condition)

    for condition in to_remove:
        all_ineligible_conditions.pop(condition, None)

    return all_ineligible_conditions


def get_channeling_daily_duration(loan, payments):
    last_payment = payments[len(payments) - 1]
    start_date = timezone.localtime(loan.fund_transfer_ts).date()
    end_date = last_payment.due_date

    diff_date = (end_date - start_date).days + 1
    return diff_date


def get_fama_channeling_admin_fee(channeling_loan_status, channeling_loan_config=None):
    """
    admin fee calculated based first payment
    daily - monthly (actual_interest_amount - interest_amount)
    if the value is positive, we need to pay bank that amount
    if the value is negative, bank need to pay us that amount
    """
    if not channeling_loan_config:
        channeling_loan_config = get_channeling_loan_configuration(ChannelingConst.FAMA)

    admin_fee = 0
    if not channeling_loan_status:
        return admin_fee

    loan = channeling_loan_status.loan
    payments = loan.payment_set.order_by('payment_number')
    channeling_loan_payment = ChannelingLoanPayment.objects.filter(
        payment_id=payments[0].id, channeling_type=ChannelingConst.FAMA
    ).first()

    # calculate admin fee o
    admin_fee = (
        channeling_loan_payment.actual_daily_interest - channeling_loan_payment.interest_amount
    )
    return admin_fee


def encrypt_data_and_upload_to_sftp_server(
    gpg_recipient: str,
    gpg_key_data: str,
    sftp_client: SFTPClient,
    content: str,
    filename: str,
) -> None:
    if settings.ENVIRONMENT == "dev":
        return

    action = 'channeling_loan.services.general_services.encrypt_data_and_upload_to_sftp_server'

    is_success, encrypted_data = encrypt_content_with_gpg(
        content=content, gpg_recipient=gpg_recipient, gpg_key_data=gpg_key_data
    )
    if not is_success:
        logger.error(
            {
                'action': action,
                'sftp_client_host': sftp_client.host,
                'filename': filename,
                'message': 'encrypt failed',
            }
        )
        sentry_client.captureMessage(
            {
                'error': 'encrypt content with gpg failed',
                'sftp_client_host': sftp_client.host,
                'filename': filename,
                'stderr': encrypted_data,
            }
        )
        return

    sftp_service = SFTPProcess(sftp_client=sftp_client)
    sftp_service.upload(content=encrypted_data, remote_path=filename)

    logger.info(
        {
            'action': action,
            'sftp_client_host': sftp_client.host,
            'filename': filename,
            'message': 'encrypt & upload successful',
        }
    )


def decrypt_data(
    filename: str,
    content: Union[str, bytes],
    passphrase: str,
    gpg_recipient: str,
    gpg_key_data: str,
    return_raw_bytes: bool = False,
) -> Optional[Union[str, bytes]]:
    action = 'channeling_loan.services.general_services.decrypt_data'

    is_success, decrypted_data = decrypt_content_with_gpg(
        content=content,
        passphrase=passphrase,
        gpg_recipient=gpg_recipient,
        gpg_key_data=gpg_key_data,
    )
    if not is_success:
        logger.error(
            {
                'action': action,
                'filename': filename,
                'message': 'decrypt failed',
            }
        )
        sentry_client.captureMessage(
            {
                'error': 'decrypt content with gpg failed',
                'filename': filename,
                'stderr': decrypted_data,
            }
        )
        return None

    return str(decrypted_data, 'utf-8') if not return_raw_bytes else decrypted_data


def download_latest_fama_approval_file_from_sftp_server(
    file_type,
) -> Tuple[Optional[str], Optional[bytes]]:
    """
    Get the latest file by getting the latest file in the approval folder.
    The number of files can be increased day by day, but we can't rely on a specific day,
    so let's try with this approach first.
    :return: filename and content of the latest FAMA approval file
    """
    sftp_service = SFTPProcess(sftp_client=get_fama_sftp_client())

    # approval directory contains only files, no need to check any child directories
    remote_path = FAMAChannelingConst.FILE_TYPE.get(file_type)
    filenames = sftp_service.list_dir(remote_dir_path=remote_path)
    if not filenames:
        return None, None

    # filename has format JUL_Confirmation_Disbursement_%Y%m%d%H%M%S%f.txt.gpg and
    # list filenames already be sorted in Connection.listdir,
    # so we can get the latest filename by get the last element of the list
    latest_fama_approval_filename = filenames[-1]

    return latest_fama_approval_filename, sftp_service.download(
        remote_path='{}/{}'.format(
            remote_path,
            latest_fama_approval_filename,
        )
    )


def download_latest_file_from_sftp_server(
    sftp_client, remote_path
) -> Tuple[Optional[str], Optional[bytes]]:
    """
    Get the latest file by getting the latest file in the folder.
    The number of files can be increased day by day, but we can't rely on a specific day,
    so let's try with this approach first.

    :return: filename and content of the latest file
    """
    sftp_service = SFTPProcess(sftp_client=sftp_client)

    # directory contains only files, no need to check any child directories
    filenames = sftp_service.list_dir(remote_dir_path=remote_path)
    if not filenames:
        return None, None

    # list filenames already be sorted date in filename in Connection.listdir,
    # so we can get the latest filename by get the last element of the list
    latest_filename = filenames[-1]

    return latest_filename, sftp_service.download(
        remote_path='{}/{}'.format(
            remote_path,
            latest_filename,
        )
    )


def convert_fama_approval_content_from_txt_to_csv(content: str) -> str:
    """
    :param content: here is an example
    JUL|JULO|20240531|2|97120.00
    8314060707||prod only|49870.00|20240531|Reject|Interest does not match,
    8314060708||prod only|50000.00|20240531|Approve|sample,
    :return:
    """
    lines = content.splitlines()
    if not lines:
        return ''

    # remove first line because it's a header
    lines.pop(0)

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    # write header
    writer.writerow(["Application_XID", "disetujui", "reason"])

    for line in lines:
        elements = line.split('|')
        reason = ""
        if elements[6]:
            reason = elements[6].replace(",", ";")
        writer.writerow(
            [
                # elements[0] has format like JTF123456789, need to parse numbers to get correct xid
                parse_numbers_only(elements[0]),
                "n" if elements[5] == FAMAChannelingConst.APPROVAL_STATUS_REJECT else "y",
                reason,
            ]
        )

    return buffer.getvalue()


def convert_dbs_approval_content_from_txt_to_csv(content: str) -> str:
    """
    :param content: encrypted content, DBS use coordinate to separate each values
    for example decrypted content,
    please check test_convert_dbs_approval_content_from_txt_to_csv unittest
    :return:
    """
    invalid_approval_statuses = {}
    data_coordinates = DBSDisbursementApprovalConst.APPLICATION_STATUS_REPORT_DATA_COORDINATE

    lines = content.splitlines()
    if not lines:
        return ''

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    # write header
    writer.writerow(data_coordinates.keys())

    for idx, line in enumerate(lines, start=1):
        line = line.strip()

        row_data = []
        for column in data_coordinates:
            start_coordinate = data_coordinates[column][0] - 1
            end_coordinate = start_coordinate + data_coordinates[column][1]

            data = line[start_coordinate:end_coordinate].strip()

            if column == DBSDisbursementApprovalConst.APPROVAL_STATUS_COLUMN_HEADER:
                if data not in DBSDisbursementApprovalConst.APPLICATION_STATUS_MAPPING:
                    invalid_approval_statuses["row {}".format(idx)] = data
                    continue
                data = DBSDisbursementApprovalConst.APPLICATION_STATUS_MAPPING.get(data)
            elif column == DBSDisbursementApprovalConst.LOAN_XID_COLUMN_HEADER:
                data = parse_numbers_only(data)

            row_data.append(data)
        writer.writerow(row_data)

    if invalid_approval_statuses:
        logger.error(
            {
                'action': 'channeling_loan.services.general_services.'
                'convert_dbs_approval_content_from_txt_to_csv',
                'error': 'invalid approval status',
                'invalid_approval_statuses': invalid_approval_statuses,
            }
        )
        sentry_client.captureMessage(
            {
                'error': 'invalid approval status',
                'invalid_approval_statuses': invalid_approval_statuses,
            }
        )

    return buffer.getvalue()


def create_channeling_loan_send_file_tracking(
    channeling_type: str, action_type: str, user_id: Optional[int] = None
) -> None:
    ChannelingLoanSendFileTracking.objects.create(
        channeling_type=channeling_type,
        action_type=action_type,
        created_by_user_id=user_id,
    )


def get_filename_counter_suffix_length(channeling_type: str) -> Optional[int]:
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    if not channeling_loan_config:
        return None

    filename_counter_suffix_config = channeling_loan_config.get('filename_counter_suffix', {})
    if filename_counter_suffix_config.get('is_active'):
        return filename_counter_suffix_config.get('LENGTH')
    return None


def get_next_filename_counter_suffix(
    channeling_type: str, action_type: str, current_ts: datetime
) -> str:
    length_of_filename_counter_suffix = get_filename_counter_suffix_length(channeling_type)
    if length_of_filename_counter_suffix is None:
        return ''

    current_counter = ChannelingLoanSendFileTracking.objects.filter(
        channeling_type=channeling_type, action_type=action_type, cdate__date=current_ts.date()
    ).count()
    return str(current_counter + 1).zfill(length_of_filename_counter_suffix)


def upload_approval_file_to_oss_and_create_document(
    channeling_type: str,
    file_type: str,
    filename: str,
    approval_file_id: int,
    content: Union[str, bytes],
) -> int:
    remote_filepath = '{}/{}/{}/{}'.format(
        ChannelingLoanApprovalFileConst.DOCUMENT_TYPE, channeling_type, file_type, filename
    )
    upload_file_as_bytes_to_oss(
        bucket_name=settings.OSS_MEDIA_BUCKET,
        file_bytes=content,
        remote_filepath=remote_filepath,
    )

    document = Document.objects.create(
        document_source=approval_file_id,
        document_type=ChannelingLoanApprovalFileConst.DOCUMENT_TYPE,
        filename=filename,
        url=remote_filepath,
    )
    return document.pk


def get_process_approval_response_time_delay_in_minutes(channeling_type: str) -> Optional[int]:
    channeling_loan_config = get_channeling_loan_configuration(channeling_type)
    if not channeling_loan_config:
        return None

    return channeling_loan_config.get('process_approval_response', {}).get(
        'DELAY_MINS', ChannelingLoanApprovalFileConst.PROCESS_APPROVAL_FILE_DELAY_MINS
    )


def mark_approval_file_processed(approval_file_id: int, document_id: Optional[int] = None) -> None:
    approval_file = ChannelingLoanApprovalFile.objects.get_or_none(pk=approval_file_id)
    if not approval_file:
        raise ChannelingLoanApprovalFileNotFound(
            'approval_file_id = {} not found'.format(approval_file_id)
        )

    if document_id:
        approval_file.document_id = document_id

    approval_file.is_processed = True
    approval_file.save()


def get_latest_approval_file_object(
    channeling_type: str, file_type: str, time_delay_in_minutes: int
) -> Optional[ChannelingLoanApprovalFile]:
    current_ts = timezone.localtime(timezone.now())

    return ChannelingLoanApprovalFile.objects.filter(
        channeling_type=channeling_type,
        file_type=file_type,
        cdate__gte=current_ts - timezone.timedelta(minutes=time_delay_in_minutes),
    ).last()


def execute_new_approval_response_process(channeling_type: str, file_type: str) -> None:
    approval_file = ChannelingLoanApprovalFile.objects.create(
        channeling_type=channeling_type, file_type=file_type
    )

    if channeling_type == ChannelingConst.FAMA:
        from juloserver.channeling_loan.tasks import process_fama_approval_response

        process_fama_approval_response.delay(file_type=file_type, approval_file_id=approval_file.id)
    elif channeling_type == ChannelingConst.DBS:
        from juloserver.channeling_loan.tasks import process_dbs_approval_response

        process_dbs_approval_response.delay(file_type=file_type, approval_file_id=approval_file.id)
    elif channeling_type == ChannelingConst.PERMATA:
        from juloserver.channeling_loan.tasks import process_permata_approval_response

        process_permata_approval_response.delay(
            file_type=file_type, approval_file_id=approval_file.id
        )


def get_response_approval_file(approval_file_document_id: int) -> HttpResponse:
    document = Document.objects.get_or_none(pk=approval_file_document_id)
    if not document:
        raise ChannelingLoanApprovalFileDocumentNotFound(
            'document_id={} not found'.format(approval_file_document_id)
        )

    document_stream = get_file_from_oss(
        bucket_name=settings.OSS_MEDIA_BUCKET, remote_filepath=document.url
    )
    return response_file(
        content_type=document_stream.content_type,
        content=document_stream.read(),
        filename=document.filename,
    )


class SFTPProcess:
    def __init__(self, sftp_client: SFTPClient):
        self.sftp_client = sftp_client

    def upload(self, content: Union[str, bytes], remote_path: str) -> None:
        try:
            self.sftp_client.upload(content=content, remote_path=remote_path)
        except Exception as error:
            raise error

    def download(self, remote_path: str) -> bytes:
        try:
            return self.sftp_client.download(remote_path=remote_path)
        except Exception as error:
            raise error

    def list_dir(self, remote_dir_path: str) -> List[str]:
        try:
            return self.sftp_client.list_dir(remote_dir_path=remote_dir_path)
        except Exception as error:
            raise error


def get_channeling_outstanding_amount(loan, channeling_type):
    outstanding_amount = 0
    payments = loan.payment_set.order_by('payment_number')

    for payment in payments:
        channeling_payment = payment.channelingloanpayment_set.filter(
            channeling_type=channeling_type
        ).last()
        if channeling_payment:
            outstanding_amount += py2round(channeling_payment.original_outstanding_amount, 2)

    return outstanding_amount


def filter_field_channeling(application: Application, channeling_type: str) -> str:
    fs = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.FILTER_FIELD_CHANNELING, is_active=True
    )
    if not fs:
        return ""
    error = ""
    param = fs.parameters.get(channeling_type)
    if not param:
        return error
    for value, fields in param.items():
        try:
            if value == 'not_empty':
                for field in fields:
                    filter_field = eval(field)
                    if not filter_field:
                        error += "{} cannot be empty, ".format(field)
            if value == 'restricted_value':
                for field in fields:
                    for key, subfield in field.items():
                        if eval(key) in subfield:
                            error += "{} is restricted, ".format(key)
        except Exception as errors:
            logger.error(
                {
                    'action': 'channeling_loan.services.filter_field_channeling',
                    'channeling_type': channeling_type,
                    'message': errors,
                }
            )
            return errors
    return error


def get_payment_event_wo_channeling_payment_event(payment_ids):
    from juloserver.channeling_loan.tasks import process_channeling_repayment_task

    logger.info(
        {
            'action': 'juloserver.channeling_loan.services.general_services.'
            'get_payment_event_wo_channeling_payment_event',
            'payment_ids': payment_ids,
            'message': 'Create channeling payment event trigger via bulk_create payment event',
        }
    )

    payment_events = PaymentEvent.objects.filter(
        payment__id__in=payment_ids, channelingpaymentevent__isnull=True
    )
    pe_ids = set()

    for pe in payment_events:
        pe_ids.add(pe.id)

    execute_after_transaction_safely(lambda: process_channeling_repayment_task.delay(pe_ids))


def check_loan_and_approve_channeling(loan_xid, approved, channeling_type, reason):
    loan = Loan.objects.get_or_none(loan_xid=loan_xid)
    if not loan:
        return "Error: Loan_xid %s not found\n" % str(loan_xid)
    status, message = approve_loan_for_channeling(loan, approved, channeling_type, reason=reason)
    if status == "failed":
        return "Error: Loan_xid %s %s\n" % (str(loan_xid), message)
    return


def create_channeling_loan_api_log(**kwargs) -> ChannelingLoanAPILog:
    required_fields = [
        'channeling_type',
        'application_id',
        'loan_id',
        'request_type',
        'http_status_code',
        'request',
    ]

    for field in required_fields:
        if field not in kwargs:
            raise ValueError(f"Missing required field: {field}")

    # Optional fields with defaults
    kwargs.setdefault('response', '')
    kwargs.setdefault('error_message', '')

    return ChannelingLoanAPILog.objects.create(**kwargs)


def get_channeling_loan_status_by_loan_xid(
    loan_xid: str, channeling_type: str
) -> Optional[ChannelingLoanStatus]:
    return ChannelingLoanStatus.objects.filter(
        loan__loan_xid=loan_xid, channeling_type=channeling_type
    ).last()


def check_common_failed_channeling(loan: Loan, config: Dict[str, Any]):
    general_channeling_config = config['general']
    lender_name = general_channeling_config['LENDER_NAME']
    lender = LenderCurrent.objects.get_or_none(lender_name=lender_name)
    if not lender:
        return "Lender not found: {}".format(lender_name)

    transaction_type = LenderTransactionType.objects.get_or_none(
        transaction_type=LenderTransactionTypeConst.CHANNELING
    )
    if not transaction_type:
        return "Channeling transaction not found"

    if loan.lender and loan.lender.lender_name in general_channeling_config['EXCLUDE_LENDER_NAME']:
        return "Lender excluded: {}".format(loan.lender.lender_name)

    lender_balance = getattr(lender, 'lenderbalancecurrent', None)
    if not lender_balance:
        return "Lender balance not found"

    if lender_balance.available_balance < loan.loan_amount:
        return "Lender balance is less than loan amount"

    return None


def upload_channeling_file_to_oss_and_slack(
    content: Any,
    document_remote_filepath: str,
    lender_id: int,
    filename: str,
    document_type: str,
    channeling_type: str,
    channeling_action_type: str,
    slack_channel: str,
) -> int:
    upload_file_as_bytes_to_oss(
        bucket_name=settings.OSS_MEDIA_BUCKET,
        file_bytes=content,
        remote_filepath=document_remote_filepath,
    )

    document = Document.objects.create(
        document_source=lender_id,
        document_type=document_type,
        filename=filename,
        url=document_remote_filepath,
    )
    document.refresh_from_db()

    send_notification_to_slack(
        """
        Here's your {} {} link file {}
        this link expiry time only 2 minutes
        if the link is already expired, please ask engineer to manually download it
        with document_id {}
        """.format(
            channeling_type, channeling_action_type, document.document_url, document.id
        ),
        slack_channel,
    )

    return document.id


def get_credit_score_conversion(customer_id: int, channeling_type: str) -> Optional[str]:
    fs = CreditScoreConversionSetting()
    if not fs.is_active:
        return None

    score = get_channeling_bscore(customer_id, channeling_type)
    if not score:
        return None

    for from_score, to_score, grade in fs.get_configuration(channeling_type):
        if from_score < score <= to_score:
            return grade
    return None


def get_channeling_bscore(customer_id: int, channeling_type: str) -> Optional[float]:
    channeling_bscore = ChannelingBScore.objects.filter(
        customer_id=customer_id,
        channeling_type=channeling_type
    ).last()

    return channeling_bscore.pgood if channeling_bscore else None
