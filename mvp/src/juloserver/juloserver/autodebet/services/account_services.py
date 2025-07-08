import logging
import calendar
from datetime import datetime
from datetime import timedelta

import semver
from django.utils import timezone
from django.template import Template, Context
from dateutil.relativedelta import relativedelta
from django.db.models import Q

from babel.numbers import format_number
from babel.dates import format_date

from juloserver.account_payment.models import AccountPayment
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)
from juloserver.autodebet.constants import (
    AutodebetStatuses,
    FeatureNameConst,
    VendorConst,
    AutodebetDeductionSourceConst,
    AutodebetVendorConst,
    AutodebetTncVersionConst,
)
from juloserver.julo.constants import (
    FeatureNameConst as JuloConst,
    LoanStatusCodes,
)
from juloserver.autodebet.models import (
    AutodebetAccount,
    AutodebetMandiriTransaction,
)
from juloserver.autodebet.services.benefit_services import get_autodebet_benefit_control_message
from juloserver.julo.models import (
    Bank,
    FeatureSetting,
    Loan,
    ExperimentSetting,
    Image,
)
from juloserver.account.models import Account
from juloserver.account.constants import AccountConstant
from juloserver.minisquad.constants import DEFAULT_DB
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.autodebet.constants import ExperimentConst
from juloserver.julo.statuses import ApplicationStatusCodes, PaymentStatusCodes


sentry = get_julo_sentry_client()

logger = logging.getLogger(__name__)


def get_existing_autodebet_account(account, vendor=None):
    _filter = {
        "account": account,
        "is_deleted_autodebet": False,
    }
    if vendor:
        _filter["vendor"] = vendor
    return AutodebetAccount.objects.filter(**_filter).last()


def get_latest_deactivated_autodebet_account(account, vendor=None):
    _filter = {
        "account": account,
        "is_use_autodebet": False,
    }
    if vendor:
        _filter["vendor__iexact"] = vendor
    return AutodebetAccount.objects.filter(**_filter).last()


def is_autodebet_feature_active():
    autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BCA
    ).last()
    if autodebet_bca_feature_setting:
        return autodebet_bca_feature_setting.is_active
    return False


def is_autodebet_bri_feature_active():
    autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BRI
    ).last()
    if autodebet_bca_feature_setting:
        return autodebet_bca_feature_setting.is_active
    return False


def is_autodebet_gopay_feature_active():
    autodebet_gopay_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_GOPAY
    ).last()
    if autodebet_gopay_feature_setting:
        return autodebet_gopay_feature_setting.is_active
    return False


def is_autodebet_mandiri_feature_active():
    autodebet_mandiri_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI
    ).last()
    if autodebet_mandiri_feature_setting:
        return autodebet_mandiri_feature_setting.is_active
    return False


def is_autodebet_bni_feature_active():
    autodebet_bni_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BNI
    ).last()
    if autodebet_bni_feature_setting:
        return autodebet_bni_feature_setting.is_active
    return False


def is_autodebet_dana_feature_active():
    autodebet_dana_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_DANA
    ).last()
    if autodebet_dana_feature_setting:
        return autodebet_dana_feature_setting.is_active
    return False


def is_autodebet_ovo_feature_active():
    autodebet_ovo_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_OVO
    ).last()
    if autodebet_ovo_feature_setting:
        return autodebet_ovo_feature_setting.is_active
    return False


def is_autodebet_vendor_feature_active(vendor):
    if vendor == VendorConst.BCA:
        return is_autodebet_feature_active()
    elif vendor == VendorConst.BRI:
        return is_autodebet_bri_feature_active()
    elif vendor == VendorConst.GOPAY:
        return is_autodebet_gopay_feature_active()
    elif vendor == VendorConst.MANDIRI:
        return is_autodebet_mandiri_feature_active()
    elif vendor == VendorConst.BNI:
        return is_autodebet_bni_feature_active()
    elif vendor == VendorConst.DANA:
        return is_autodebet_dana_feature_active()
    elif vendor == VendorConst.OVO:
        return is_autodebet_ovo_feature_active()

    return False


def is_autodebet_bca_whitelist_feature_active(account):
    whitelist_autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WHITELIST_AUTODEBET_BCA, is_active=True
    ).last()
    if not whitelist_autodebet_bca_feature_setting:
        return is_autodebet_feature_active()

    application = account.last_application
    if application.id in whitelist_autodebet_bca_feature_setting.parameters["applications"]:
        return True
    return False


def is_autodebet_bri_whitelist_feature_active(account):
    whitelist_autodebet_bri_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WHITELIST_AUTODEBET_BRI, is_active=True
    ).last()
    if not whitelist_autodebet_bri_feature_setting:
        return is_autodebet_bri_feature_active()

    application = account.last_application
    if application.id in whitelist_autodebet_bri_feature_setting.parameters["applications"]:
        return True
    return False


def is_autodebet_whitelist_feature_active(account):
    autodebet_account = get_existing_autodebet_account(account)
    if autodebet_account:
        if autodebet_account.is_use_autodebet:
            return False
        if autodebet_account.vendor == VendorConst.BCA:
            return is_autodebet_bca_whitelist_feature_active(account)
        else:
            return is_autodebet_bri_whitelist_feature_active(account)

    is_bca_feature_active = is_autodebet_bca_whitelist_feature_active(account)
    if not is_bca_feature_active:
        return is_autodebet_bri_whitelist_feature_active(account)
    return is_bca_feature_active


def construct_autodebet_bca_feature_status(account):
    is_feature_active = is_autodebet_feature_active()
    whitelist_autodebet_bca_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.WHITELIST_AUTODEBET_BCA, is_active=True
    ).last()
    if whitelist_autodebet_bca_feature_setting:
        application = account.last_application
        if application.id in whitelist_autodebet_bca_feature_setting.parameters["applications"]:
            is_feature_active = True
        else:
            is_feature_active = False

    if not is_feature_active and not whitelist_autodebet_bca_feature_setting:
        return False, False, False

    is_autodebet_active = False
    is_manual_activation = False
    existing_autodebet_account = get_existing_autodebet_account(account, VendorConst.BCA)
    if existing_autodebet_account:
        is_autodebet_active = existing_autodebet_account.is_use_autodebet
        is_manual_activation = existing_autodebet_account.is_manual_activation

    return is_feature_active, is_autodebet_active, is_manual_activation


def autodebet_feature_flags():
    data = {}
    autodebet_feature_setting = FeatureSetting.objects.filter(
        feature_name__in=(
            FeatureNameConst.AUTODEBET_BCA,
            FeatureNameConst.AUTODEBET_BRI,
            FeatureNameConst.AUTODEBET_GOPAY,
            FeatureNameConst.AUTODEBET_MANDIRI,
            FeatureNameConst.AUTODEBET_BNI,
            FeatureNameConst.AUTODEBET_DANA,
            FeatureNameConst.AUTODEBET_OVO,
        )
    ).values('feature_name', 'is_active')

    for idx, data_vendor in enumerate(VendorConst.AUTODEBET_BY_VENDOR):
        feature = next(
            filter(lambda x: x['feature_name'] == data_vendor['name'], autodebet_feature_setting),
            {'is_active': False},
        )
        data[data_vendor['name']] = feature['is_active']

    return data


def construct_deactivate_warning(autodebet_account, vendor):
    feature_name = vendor.lower() + "_autodebet_deactivate_warning"
    feature_setting = FeatureSetting.objects.filter(
        feature_name=feature_name,
        is_active=True,
    ).last()
    if not feature_setting:
        return None
    if vendor == VendorConst.BCA:
        # validation for bca vendor

        # calculate interval
        interval_days = feature_setting.parameters.get('interval_days')
        if not interval_days:
            return None

        # safely cast to integer in case parameter written in string
        try:
            interval_days_int = int(interval_days)
        except ValueError:
            return None

        min_time_activation = timezone.localtime(timezone.now()) - timedelta(days=interval_days_int)
        if (
            autodebet_account.status == AutodebetStatuses.REGISTERED
            and autodebet_account.activation_ts.date() > min_time_activation.date()
        ):
            available_deactivate_date = autodebet_account.activation_ts.date() + timedelta(
                days=interval_days_int
            )
            content = feature_setting.parameters.get('content').replace(
                "{{date}}", format_date(available_deactivate_date, 'd MMMM yyyy', locale='id_ID')
            )
            content = content.replace("{{interval_days}}", str(interval_days))

            return {
                "title": feature_setting.parameters.get('title'),
                "content": content,
            }

    return None


def check_due_date(account: Account) -> bool:
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    is_due_date = (
        account.accountpayment_set.not_paid_active()
        .filter(due_date__range=(today, tomorrow))
        .exists()
    )

    return is_due_date


def construct_autodebet_feature_status(account, version=None, app_version=None, platform=None):
    is_feature_active = autodebet_feature_flags()
    whitelist_autodebet_feature_setting = FeatureSetting.objects.filter(
        feature_name__in=(
            FeatureNameConst.WHITELIST_AUTODEBET_BCA,
            FeatureNameConst.WHITELIST_AUTODEBET_BRI,
            FeatureNameConst.WHITELIST_AUTODEBET_GOPAY,
            FeatureNameConst.WHITELIST_AUTODEBET_MANDIRI,
            FeatureNameConst.WHITELIST_AUTODEBET_BNI,
            FeatureNameConst.WHITELIST_AUTODEBET_DANA,
            FeatureNameConst.WHITELIST_AUTODEBET_OVO,
        )
    ).values('feature_name', 'is_active', 'parameters')

    deduction_cycle_day = None
    autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY,
        is_active=True
    )
    autodebet_deduction_parameters = None
    if autodebet_deduction_feature_setting:
        autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters

    message, success_message = get_autodebet_benefit_control_message(account)
    data = {
        'message': None if not message or 'info' not in message else message['title'],
        'autodebet_bri_otp_alert': get_autodebet_message(account),
        'status': [],
        'tnc_status_id': 1,
        'tnc_status_message': [],
        'autodebet_benefit_message': message,
        'is_idfy_enabled': False,
        'is_activation_enabled': not is_disabled_autodebet_activation(account),
        'idfy_entry_point_image': get_idfy_entry_point(),
        'idfy_call_button_image': get_idfy_call_button(),
    }

    if version != AutodebetTncVersionConst.VERSION_V3:
        # for experiment autodebit bca only
        if autodebet_deduction_parameters:
            if AutodebetDeductionSourceConst.FOLLOW_PAYDAY ==\
                    autodebet_deduction_parameters[AutodebetVendorConst.BCA]['deduction_day_type']:
                deduction_day = get_deduction_day(account)
                if deduction_day:
                    deduction_cycle_day = deduction_day
            else:
                deduction_cycle_day = account.cycle_day
        data['tnc_status_message'] = [
            'Tanggal pendebitan setiap bulannya jatuh pada tanggal <b>{}</b>'
            .format(deduction_cycle_day),
            'Jika tanggal pendebitan tidak tersedia pada bulan tertentu, '
            'maka pendebitan akan dilakukan pada tanggal terakhir dari bulan tersebut',
            'Jika kamu mengaktifkan Auto Debit pada tanggal yang sama saat jatuh tempo, '
            'maka tagihan tidak akan terpotong',
        ]
    else:
        data.pop('tnc_status_message')

    if version in AutodebetTncVersionConst.LIST:
        data['success_message'] = 'Asik, tagihamu akan dibayarkan otomatis tiap bulannya.' \
            if not success_message else success_message
    hide_payment_methods_by_lender_id = set()
    fs = FeatureSetting.objects.filter(
        feature_name=JuloConst.HIDE_PAYMENT_METHODS_BY_LENDER,
        is_active=True,
    ).last()
    if fs:
        lender_ids = list(
            account.loan_set.filter(
                loan_status_id__gte=LoanStatusCodes.CURRENT,
                loan_status_id__lt=LoanStatusCodes.PAID_OFF,
            ).values_list('lender_id', flat=True)
        )
        for hide_payment_method in fs.parameters:
            if int(hide_payment_method.get('lender_id')) in lender_ids:
                hide_payment_methods_by_lender_id.update(
                    hide_payment_method.get('payment_method_codes')
                )
    is_due_date = check_due_date(account)
    for idx, feature_data in enumerate(whitelist_autodebet_feature_setting):
        for data_autodebet in VendorConst.AUTODEBET_BY_VENDOR:
            application = account.last_application
            if data_autodebet['vendor'] == VendorConst.DANA:
                if platform not in ['iOS', 'lite'] and (
                    not app_version or semver.match(app_version, '<=8.26.0')
                ):
                    continue
            if data_autodebet['vendor'] == VendorConst.OVO:
                if platform not in ['iOS', 'lite'] and (
                    not app_version or semver.match(app_version, '<=8.39.0')
                ):
                    continue
            if feature_data['feature_name'] == data_autodebet['whitelist']:
                if feature_data['is_active']:
                    if application.id in \
                            whitelist_autodebet_feature_setting[idx]['parameters']['applications']:
                        is_feature_active[data_autodebet['name']] = True
                    else:
                        is_feature_active[data_autodebet['name']] = False

                    if data_autodebet['vendor'] == VendorConst.GOPAY:
                        gopay_linking_feature = FeatureSetting.objects.filter(
                            feature_name=JuloConst.GOPAY_ACTIVATION_LINKING,
                            is_active=True
                        ).exists()
                        if not gopay_linking_feature:
                            is_feature_active[data_autodebet['name']] = False

                autodebet_account = get_existing_autodebet_account(
                    account, data_autodebet['vendor']
                )
                is_autodebet_active, is_autodebet_on_process = False, False
                is_manual_activation = False
                on_process_type = None
                next_payment_date = None
                extra_keys = {}
                if autodebet_account:
                    is_autodebet_active = autodebet_account.is_use_autodebet
                    is_manual_activation = autodebet_account.is_manual_activation
                    if autodebet_account.status == AutodebetStatuses.PENDING_REGISTRATION:
                        is_autodebet_on_process = True
                        on_process_type = 'activation'
                    if autodebet_account.status == AutodebetStatuses.PENDING_REVOCATION:
                        on_process_type = 'revocation'
                    if data_autodebet['vendor'] in VendorConst.VENDOR_INSUFFICIENT_SUSPEND:
                        extra_keys['insufficient_balance'] = autodebet_account.is_suspended
                    if data_autodebet['vendor'] in VendorConst.VENDOR_DEACTIVATE_WARNING:
                        extra_keys['deactivate_warning'] = construct_deactivate_warning(
                            autodebet_account, data_autodebet['vendor']
                        )
                    if version in AutodebetTncVersionConst.LIST and is_autodebet_active:
                        next_payment_date = get_next_payment_date(
                            account, data_autodebet['vendor'])
                        if next_payment_date:
                            now = timezone.localtime(timezone.now())
                            next_payment_date = next_payment_date.strftime(
                                "%Y-%m-%d") + ' ' + timezone.localtime(
                                    now.replace(hour=10, minute=0)).strftime("%H:%M")

                is_disable_keys = {}
                next_payment_date_keys = {}
                tnc_status_message = {}
                is_disable_autodebet = is_autodebet_feature_disable(data_autodebet['vendor'])
                if version in AutodebetTncVersionConst.LIST:
                    is_disable_keys['is_disable'] = is_disable_autodebet
                    next_payment_date_keys['next_payment_date'] = next_payment_date \
                        if is_autodebet_active and next_payment_date else None
                elif is_disable_autodebet:
                    is_feature_active[data_autodebet['name']] = False

                if version == AutodebetTncVersionConst.VERSION_V3:
                    autodebet_tnc_parameters = get_autodebet_tnc_message(
                        data_autodebet['vendor'], is_due_date
                    )
                    if autodebet_tnc_parameters:
                        if autodebet_deduction_parameters and \
                            AutodebetDeductionSourceConst.FOLLOW_PAYDAY ==\
                                autodebet_deduction_parameters[
                                    data_autodebet['vendor']]['deduction_day_type']:
                            payday_content = autodebet_tnc_parameters.get('payday_content')
                            if payday_content:
                                modified_payday_content = process_tnc_message_with_deduction_day(
                                    account,
                                    payday_content,
                                )
                                if modified_payday_content:
                                    autodebet_tnc_parameters['payday_content'] = \
                                        modified_payday_content
                            tnc_status_message['tnc_status_message'] = autodebet_tnc_parameters
                        else:
                            if autodebet_tnc_parameters.get('payday_content'):
                                autodebet_tnc_parameters.pop('payday_content')
                            tnc_status_message['tnc_status_message'] = autodebet_tnc_parameters
                if data_autodebet.get('payment_method_code') in hide_payment_methods_by_lender_id:
                    is_feature_active[data_autodebet['name']] = False
                data['status'].append(
                    {
                        'bank_name': data_autodebet['vendor'],
                        'bank_image': '',
                        'is_feature_active': is_feature_active[data_autodebet['name']],
                        'is_autodebet_active': is_autodebet_active,
                        'is_autodebet_on_process': is_autodebet_on_process,
                        'is_manual_activation': is_manual_activation,
                        'on_process_type': on_process_type,
                        **(extra_keys or {}),
                        **(is_disable_keys or {}),
                        **(next_payment_date_keys or {}),
                        **(tnc_status_message or {}),
                    }
                )

    return data


def get_autodebet_bank_name(account, db_name=DEFAULT_DB):
    autodebet_account = AutodebetAccount.objects.using(db_name).filter(
        account_id=account.id, is_deleted_autodebet=False, is_use_autodebet=True
    ).first()
    if not autodebet_account:
        return None

    autodebet_bank = Bank.objects.using(db_name).filter(
        xfers_bank_code=autodebet_account.vendor).last()
    if not autodebet_bank:
        return autodebet_account.vendor

    return autodebet_bank.bank_name


def collect_autodebet_fund_collection(account):
    from juloserver.autodebet.services.task_services import determine_best_deduction_day

    today_date = timezone.localtime(timezone.now()).date()
    deduction_cycle_day = determine_best_deduction_day(account)
    autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY,
        is_active=True
    )
    account_payment = account.accountpayment_set.not_paid_active().filter(
        due_date=today_date
    ).order_by('due_date').last()
    autodebet_deduction_parameters = None
    if autodebet_deduction_feature_setting:
        autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters

    if autodebet_deduction_parameters:
        if autodebet_deduction_parameters[AutodebetVendorConst.BRI]['deduction_day_type'] \
                == AutodebetDeductionSourceConst.FOLLOW_PAYDAY:
            account_payment = None
            account_payment_this_month = AccountPayment.objects.filter(
                due_date__month=today_date.month,
                due_date__year=today_date.year,
                account=account
            ).last()
            if not deduction_cycle_day:
                logger.info({
                    'action': 'collect_autodebet_account_collections_task',
                    'account_id': account.id,
                    'message': 'deduction_cycle_day is none',
                })
            if account_payment_this_month:
                if today_date.day == deduction_cycle_day:
                    if (datetime.strptime(
                            autodebet_deduction_parameters[AutodebetVendorConst.BRI]['last_update'],
                            '%Y-%m-%d').date() < account_payment_this_month.due_date):
                        account_payment = account.accountpayment_set.not_paid_active() \
                            .order_by('due_date').last()

    if not account_payment:
        logger.info({
            'action': 'collect_autodebet_account_collections_task',
            'account_id': account.id,
            'message': "no account payments due today",
        })
        return False, "No account payments due today"

    filter_ = {"due_date__lte": today_date}
    if autodebet_deduction_parameters:
        if autodebet_deduction_parameters[AutodebetVendorConst.BRI]['deduction_day_type'] \
                == AutodebetDeductionSourceConst.FOLLOW_PAYDAY:
            filter_ = {
                "due_date__month__lte": today_date.month,
                "due_date__year__lte": today_date.year
            }
    account_payment_ids = account.accountpayment_set.not_paid_active() \
        .filter(**filter_).order_by('due_date')

    if not account_payment_ids:
        logger.info({
            'action': 'collect_autodebet_account_collections_task',
            'account_id': account.id,
            'message': "account payment not found",
        })
        return False, "Account payment not found"

    return account_payment_ids, ''


def get_autodebet_message(account):
    account_payments, _ = collect_autodebet_fund_collection(account)
    autodebet_account = get_existing_autodebet_account(account)
    if not autodebet_account or not account_payments:
        return ''

    due_amount = 0
    for account_payment in account_payments.iterator():
        due_amount += account_payment.due_amount

    if due_amount > 1000000:
        return 'Lakukan OTP untuk menyelesaikan pembayaran angsuran Rp.{:,}'.format(due_amount)


def is_account_eligible_for_fund_collection(account_payment):
    autodebet_account = account_payment.account.autodebetaccount_set.last()
    if autodebet_account and account_payment.due_date and autodebet_account.activation_ts:
        if account_payment.due_date == timezone.localtime(autodebet_account.activation_ts).date():
            return False
    return True


def is_account_eligible_for_fund_collection_experiment(autodebet_account, today):
    from juloserver.autodebet.services.task_services import \
        determine_best_deduction_day

    deduction_cycle_day = determine_best_deduction_day(
        autodebet_account.account)

    date_ts = datetime(today.year, today.month, deduction_cycle_day)

    if autodebet_account and date_ts and autodebet_account.activation_ts:
        if date_ts == timezone.localtime(autodebet_account.activation_ts).date():
            return False
    return True


def update_deduction_fields_to_new_cycle_day(account_payment):
    autodebet_account = account_payment.account.autodebetaccount_set.filter(
        is_use_autodebet=True).last()
    if autodebet_account:
        autodebet_account.update_safely(
            deduction_cycle_day=autodebet_account.account.cycle_day,
            deduction_source=AutodebetDeductionSourceConst.ORIGINAL_CYCLE_DAY,
            is_payday_changed=True)


def autodebet_account_reactivation_from_suspended(account_id, is_content_alone, vendor):
    autodebet_account = AutodebetAccount.objects.filter(
        account_id=account_id,
        vendor=vendor
    ).last()

    if not autodebet_account:
        return general_error_response("autodebet not found")

    if not autodebet_account.is_use_autodebet:
        return general_error_response("gagal diproses")

    if not is_content_alone:
        autodebet_account.update_safely(is_suspended=False)

    today_date = timezone.localtime(timezone.now()).date()
    nearest_account_payment = (
        autodebet_account.account.accountpayment_set.not_paid_active().filter(
            due_date__gt=today_date).order_by('due_date').first()
    )

    response_message = "Pastikan saldo rekeningmu nggak kurang dari jumlah "\
                       "tagihan saat proses autodebet, ya!"
    if nearest_account_payment:
        account_payments = autodebet_account.account.accountpayment_set.not_paid_active().filter(
            due_date__lte=nearest_account_payment.due_date
        ).order_by('due_date')

        due_amount = 0
        for account_payment in account_payments.iterator():
            due_amount += account_payment.due_amount

        response_message = "Pastikan saldo rekeningmu nggak kurang dari Rp{} pada {}, ya!".format(
            format_number(due_amount, locale='id_ID'),
            format_date(nearest_account_payment.due_date, 'd MMMM yyyy', locale='id_ID')
        )

    return success_response({
        "status": "ACTIVE",
        "message": response_message
    })


def is_autodebet_feature_disable(vendor):
    feature_name = 'autodebet_' + vendor.lower()
    autodebet_feature = FeatureSetting.objects.filter(
        feature_name=feature_name,
    ).last()

    if autodebet_feature and autodebet_feature.parameters:
        start_date_time = autodebet_feature.parameters.get('disable').get('disable_start_date_time')
        end_date_time = autodebet_feature.parameters.get('disable').get('disable_end_date_time')

        if start_date_time and end_date_time:
            today = datetime.strptime(datetime.strftime(
                timezone.localtime(timezone.now()), '%d/%m/%y %H:%M'), '%d/%m/%y %H:%M')
            start_date_time = datetime.strptime(start_date_time, '%d-%m-%Y %H:%M')
            end_date_time = datetime.strptime(end_date_time, '%d-%m-%Y %H:%M')
            if start_date_time <= today <= end_date_time:
                return True

    return False


def send_pn_autodebet_activated_payday(account, vendor):
    from juloserver.autodebet.services.task_services import determine_best_deduction_day
    from juloserver.moengage.tasks import send_pn_activated_autodebet

    next_account_payment = account.accountpayment_set.not_paid_active().filter(
        due_date__gte=timezone.localtime(timezone.now()).date()
    ).values_list('id', flat=True).first()

    payday = determine_best_deduction_day(account)
    send_pn_activated_autodebet.delay(
        account.customer_id,
        payday,
        vendor,
        next_account_payment
    )


def get_next_payment_date(account, vendor):
    from juloserver.autodebet.services.task_services import \
        determine_best_deduction_day

    next_payment_date = None
    is_loans_active = Loan.objects.filter(
        account=account,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
        loan_status_id__lte=LoanStatusCodes.LOAN_4DPD,
        is_restructured=False,
    ).exists()
    if is_loans_active:
        account_payments = account.accountpayment_set.not_paid_active()
        if account_payments:
            today_date = timezone.localtime(timezone.now()).date()
            autodebet_deduction_feature_setting = FeatureSetting.objects.get_or_none(
                feature_name=JuloFeatureNameConst.AUTODEBET_DEDUCTION_DAY,
                is_active=True
            )
            autodebet_deduction_parameters = None
            if autodebet_deduction_feature_setting:
                autodebet_deduction_parameters = autodebet_deduction_feature_setting.parameters
            if autodebet_deduction_parameters and AutodebetDeductionSourceConst.FOLLOW_PAYDAY ==\
                    autodebet_deduction_parameters[vendor]['deduction_day_type']:
                deduction_day = determine_best_deduction_day(account)
                nearest_account_payment = account_payments.filter(
                    (Q(due_date__month=today_date.month) & Q(
                        due_date__year=today_date.year))).order_by('due_date').first()
                if nearest_account_payment:
                    months = 0
                    if vendor == AutodebetVendorConst.MANDIRI and today_date.day <= deduction_day:
                        next_payment_date = get_mandiri_deduction_date(
                            nearest_account_payment, deduction_day, True)
                    else:
                        if today_date.day >= deduction_day:
                            months = 1
                        next_payment_date = (
                            nearest_account_payment.due_date + relativedelta(
                                day=deduction_day, months=months)
                        )
                else:
                    nearest_account_payment = account_payments.filter(
                        due_date__gt=today_date).order_by('due_date').first()
                    if nearest_account_payment:
                        next_payment_date = (
                            nearest_account_payment.due_date + relativedelta(day=deduction_day)
                        )
            else:
                nearest_account_payment = account_payments.filter(
                    due_date__gt=today_date).order_by('due_date').first()
                if nearest_account_payment:
                    next_payment_date = nearest_account_payment.due_date
                    # DIFFERENT DATE FOR AUTODEBET WITH 2 TIMES DEDUCTION DUE TO LIMIT
                    if vendor == AutodebetVendorConst.MANDIRI:
                        next_payment_date = get_mandiri_deduction_date(
                            nearest_account_payment, next_payment_date.day, False)
                    elif vendor == AutodebetVendorConst.BNI:
                        next_payment_date = get_bni_deduction_date(nearest_account_payment)

    return next_payment_date


def get_autodebet_tnc_message(vendor: str, is_due_date: bool):
    feature_name = vendor.lower() + '_autodebet_tnc'
    autodebet_tnc_feature = FeatureSetting.objects.filter(
        feature_name=feature_name,
        is_active=True,
    ).last()
    if not autodebet_tnc_feature or not autodebet_tnc_feature.parameters:
        return None

    if not is_due_date:
        autodebet_tnc_feature.parameters['alert_content'] = None

    return autodebet_tnc_feature.parameters


def process_tnc_message_with_deduction_day(account, tnc_content_list):
    deduction_day = None
    available_context = None
    deduction_day_message = None
    index = None
    for tnc_content in tnc_content_list:
        if '{{payday}}' in tnc_content:
            deduction_day = get_deduction_day(account)
            if deduction_day:
                available_context = {
                    "payday": deduction_day
                }
            deduction_day_message = tnc_content
            index = tnc_content_list.index(tnc_content)
            break
        elif '{{due_date}}' in tnc_content:
            deduction_day = account.cycle_day
            if deduction_day:
                available_context = {
                    "due_date": deduction_day
                }
            deduction_day_message = tnc_content
            index = tnc_content_list.index(tnc_content)
            break

    if not available_context or not deduction_day_message:
        return None

    template = Template(deduction_day_message)
    new_deduction_day_message = template.render(Context(available_context))
    if index is not None:
        tnc_content_list[index] = new_deduction_day_message
        return tnc_content_list

    return None


def get_deduction_day(account, raise_error=True):
    original_cycle_day = account.cycle_day
    application = account.last_application
    day = original_cycle_day
    application = application if application.application_status_id ==\
        ApplicationStatusCodes.LOC_APPROVED else None

    if application and not application.payday:
        if raise_error:
            sentry.captureMessage(
                'application payday with account_id: {} is None'.format(account.id)
            )
    elif application and application.payday < original_cycle_day:
        day = application.payday

    return day


def get_mandiri_deduction_date(nearest_account_payment, day, is_payday=False):
    today_date = timezone.localtime(timezone.now()).date()
    account = nearest_account_payment.account
    next_payment_day = day
    month = 0
    mandiri_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = mandiri_max_limit_setting.parameters.get('maximum_amount')
    account_payments = account.accountpayment_set.not_paid_active().filter(
        due_date__lte=nearest_account_payment.due_date
    ).order_by('due_date')
    due_amount = 0
    for account_payment in account_payments.iterator():
        due_amount += account_payment.due_amount

    def check_and_decide_next_payment_day_and_month():
        if is_payday:
            if today_date.day == day:
                last_day_of_the_month = calendar.monthrange(
                    today_date.year, today_date.month)[1]
                if day == last_day_of_the_month:
                    return 1, 1
                return day + 1, month
            else:
                return next_payment_day, month
        else:
            if day == 1:
                return 31, -1
            return day - 1, month

    if ((is_payday and today_date.day == day) or (not is_payday and day - today_date.day == 1)):
        autodebet_account = get_existing_autodebet_account(account, 'MANDIRI')
        autodebet_mandiri_transactions = AutodebetMandiriTransaction.objects.filter(
            autodebet_mandiri_account=autodebet_account.autodebetmandiriaccount_set.last(),
            cdate__date=today_date,
            status__isnull=False,
        )
        if autodebet_mandiri_transactions:
            if len(autodebet_mandiri_transactions) == 1:
                if autodebet_mandiri_transactions.last().status == 'success':
                    if is_payday:
                        next_payment_day, month = check_and_decide_next_payment_day_and_month()
                elif autodebet_mandiri_transactions.last().status == 'failed':
                    if not is_payday:
                        next_payment_day, month = check_and_decide_next_payment_day_and_month()
            elif (len(autodebet_mandiri_transactions)) == 2:
                if is_payday:
                    if (autodebet_mandiri_transactions.last().status == 'failed'
                            and autodebet_mandiri_transactions.last().amount == due_amount):
                        month = 1
                    else:
                        next_payment_day, month = check_and_decide_next_payment_day_and_month()
        elif (not is_payday and not autodebet_mandiri_transactions
                and due_amount > maximum_amount):
            next_payment_day, month = check_and_decide_next_payment_day_and_month()
    elif due_amount > maximum_amount:
        next_payment_day, month = check_and_decide_next_payment_day_and_month()

    next_payment_date = (
        nearest_account_payment.due_date + relativedelta(
            day=next_payment_day, months=month)
    )

    return next_payment_date


def get_bni_deduction_date(nearest_account_payment):
    '''
    This function is to get execution deduction for
    BNI that has 2 times deduction for due_amount above
    limit
    '''
    account = nearest_account_payment.account
    today_date = timezone.localtime(timezone.now())
    next_payment_date = nearest_account_payment.due_date

    bni_max_limit_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_BNI_MAX_LIMIT_DEDUCTION_DAY
    ).last()
    maximum_amount = bni_max_limit_setting.parameters.get('maximum_amount')
    account_payments = (
        account.accountpayment_set.not_paid_active()
        .filter(due_date__lte=nearest_account_payment.due_date)
        .order_by('due_date')
    )
    due_amount = 0
    for account_payment in account_payments.iterator():
        due_amount += account_payment.due_amount

    if due_amount > maximum_amount:
        # deduction start on dpd - 1
        dpd_minus_one_date = next_payment_date - timedelta(days=1)
        if dpd_minus_one_date > today_date.date():
            next_payment_date = dpd_minus_one_date

    return next_payment_date


def is_idfy_enable(account_id: int) -> bool:
    whitelist_idfy_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AUTODEBET_IDFY_WHITELIST, is_active=True
    ).last()
    if not whitelist_idfy_feature_setting:
        return True

    if account_id not in whitelist_idfy_feature_setting.parameters.get("account_id", []):
        return False
    return True


def is_bca_primary_bank(account: Account):
    application = account.application_set.last()

    if "BCA" in application.bank_name:
        return True

    return False


def is_disabled_autodebet_activation(
    account: Account, is_extended_account_status: bool = False
) -> bool:
    account_status_disabled = False
    account_payment_status_disabled = False

    status_account_disabled_criteria = (
        AccountConstant.STATUS_CODE.deactivated,
        AccountConstant.STATUS_CODE.terminated,
        AccountConstant.STATUS_CODE.sold_off,
        AccountConstant.STATUS_CODE.fraud_reported,
        AccountConstant.STATUS_CODE.application_or_friendly_fraud,
        AccountConstant.STATUS_CODE.scam_victim,
        AccountConstant.STATUS_CODE.fraud_soft_reject,
        AccountConstant.STATUS_CODE.fraud_suspicious,
        AccountConstant.STATUS_CODE.account_deletion_on_review,
        AccountConstant.STATUS_CODE.consent_withdrawal_requested,
        AccountConstant.STATUS_CODE.consent_withdrawed,
    )
    if is_extended_account_status:
        status_account_disabled_criteria += (
            AccountConstant.STATUS_CODE.inactive,
        )

    if account.status.status_code in status_account_disabled_criteria:
        account_status_disabled = True

    status_account_payment_disabled_criteria = (
        PaymentStatusCodes.PAYMENT_90DPD,
        PaymentStatusCodes.PAYMENT_120DPD,
        PaymentStatusCodes.PAYMENT_150DPD,
        PaymentStatusCodes.PAYMENT_180DPD,
    )
    account_payment = account.get_oldest_unpaid_account_payment()
    if account_payment and account_payment.status_id in status_account_payment_disabled_criteria:
        account_payment_status_disabled = True

    if account_status_disabled is True or account_payment_status_disabled is True:
        return True

    return False


def get_idfy_entry_point() -> str:
    autdoebet_idfy_entry_point = FeatureSetting.objects.filter(
        feature_name=JuloConst.AUTODEBET_IDFY_ENTRY_POINT, is_active=True
    ).last()
    if not autdoebet_idfy_entry_point:
        return ""

    image = Image.objects.get_or_none(
        id=autdoebet_idfy_entry_point.parameters.get('image_id', None)
    )
    if not image:
        return ""

    return image.image_url


def get_idfy_call_button() -> str:
    autodebet_idfy_call_button = FeatureSetting.objects.filter(
        feature_name=JuloConst.AUTODEBET_IDFY_CALL_BUTTON, is_active=True
    ).last()
    if not autodebet_idfy_call_button:
        return ""

    image = Image.objects.get_or_none(
        id=autodebet_idfy_call_button.parameters.get('image_id', None)
    )
    if not image:
        return ""

    return image.image_url


def is_idfy_autodebet_valid(account: Account) -> bool:
    if (
        not is_autodebet_vendor_feature_active(AutodebetVendorConst.BCA)
        or is_autodebet_feature_disable(AutodebetVendorConst.BCA)
        or (is_disabled_autodebet_activation(account, True) and not is_bca_primary_bank(account))
    ):
        return False

    autodebet_account = get_existing_autodebet_account(account)
    if autodebet_account and autodebet_account.status in (
        AutodebetStatuses.PENDING_REGISTRATION,
        AutodebetStatuses.REGISTERED,
    ):
        return False

    return True


def get_autodebet_experiment_setting():
    today = timezone.localtime(timezone.now()).date()
    autodebet_experiment = (
        ExperimentSetting.objects.filter(
            code=ExperimentConst.SMS_REMINDER_AUTODEBET_EXPERIMENT_CODE, is_active=True
        )
        .filter(
            (Q(start_date__date__lte=today) & Q(end_date__date__gte=today)) | Q(is_permanent=True)
        )
        .last()
    )

    return autodebet_experiment


def is_experiment_group_autodebet(account: Account) -> bool:
    autodebet_experiment = get_autodebet_experiment_setting()

    if autodebet_experiment:
        criteria = autodebet_experiment.criteria
        experiment_tail = criteria.get("account_id_tail", {}).get("experiment", None)
        if experiment_tail and (account.id % 10) in experiment_tail:
            return True
    return False


def get_active_autodebet_account(account_id, vendor=None):
    _filter = {
        "account_id": account_id,
        "is_deleted_autodebet": False,
        "is_use_autodebet": True,
    }
    if vendor:
        _filter["vendor"] = vendor
    return AutodebetAccount.objects.filter(**_filter).last()


def get_autodebet_dpd_deduction(vendor: str):
    feature_name = 'autodebet_' + vendor.lower()
    autodebet_feature = FeatureSetting.objects.filter(
        feature_name=feature_name,
    ).last()

    if (
        autodebet_feature
        and autodebet_feature.parameters
        and autodebet_feature.parameters.get("deduction_dpd")
    ):
        dpd_start = autodebet_feature.parameters.get("deduction_dpd").get("dpd_start") or 0
        dpd_end = autodebet_feature.parameters.get("deduction_dpd").get("dpd_end") or 0
        return dpd_start, dpd_end

    return 0, 0
