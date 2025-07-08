from builtins import range
from builtins import object
import logging
import ast
from http import HTTPStatus
from typing import List

from django.utils import timezone
from django.conf import settings

from juloserver.disbursement.services.xendit import XenditService
from juloserver.ecommerce.constants import EcommerceConstant
from juloserver.followthemoney.models import LenderCurrent
from juloserver.julo.banks import BankManager
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, Loan, Application, Bank
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2 import get_redis_client
from juloserver.utilities.models import DisbursementTrafficControl
from juloserver.utilities.constants import CommonVariables
from juloserver.utilities.services import rule_satisfied
from juloserver.utilities.services import gen_probability
from juloserver.disbursement.constants import (
    DisbursementStatus,
    DisbursementVendors,
    DisbursementVendorStatus,
    NameBankValidationStatus,
    NameBankValidationVendors,
    XenditDisbursementStep,
    XfersDisbursementStep,
    MoneyFlow,
    AyoconnectDisbursementStep,
    AyoconnectBeneficiaryStatus,
    PaymentGatewayVendorConst,
    AyoconnectConst,
    AyoconnectErrorCodes,
    AyoconnectErrorReason,
    PaymentgatewayDisbursementStep,
)
from juloserver.disbursement.exceptions import (
    BankNameNotFound,
    DisbursementServiceError,
    XenditExperimentError,
    AyoconnectServiceError,
    AyoconnectServiceForceSwitchToXfersError,
)
from juloserver.disbursement.models import (
    Disbursement,
    NameBankValidation,
    BankNameValidationLog,
    NameBankValidationHistory,
    Disbursement2History,
    PaymentGatewayCustomerDataLoan,
)
from juloserver.disbursement.services.xfers import JTFXfersService, JTPXfersService
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.customer_module.models import BankAccountDestination
from juloserver.disbursement.services.ayoconnect import AyoconnectService
from juloserver.disbursement.services.payment_gateway import PaymentGatewayService
from juloserver.grab.models import (
    PaymentGatewayBankCode
)
from juloserver.disbursement.utils import payment_gateway_matchmaking
from juloserver.julo.statuses import LoanStatusCodes


BALANCE_CACHE_TIMEOUT = 600

logger = logging.getLogger(__name__)


def get_service(service_name, is_grab: bool = False):
    if service_name.upper() == DisbursementVendors.PG:
        if is_grab:
            return PaymentGatewayService(
                client_id=settings.PG_GRAB_CLIENT_ID,
                api_key=settings.PG_GRAB_API_KEY,
            )
        else:
            return PaymentGatewayService(
                client_id=settings.PG_LOAN_CLIENT_ID, api_key=settings.PG_LOAN_API_KEY
            )
    mod = __import__('juloserver.disbursement.services.%s' % (service_name.lower()), fromlist=[''])
    service = getattr(mod, '%sService' % (service_name))
    return service()


def get_xfers_service(disbursement):
    """specical service for xfers"""

    # use jtf xfers service when (step=1 and status=completed) or step=2
    if disbursement.step == XfersDisbursementStep.FIRST_STEP and\
            disbursement.disburse_status == DisbursementStatus.COMPLETED or\
            disbursement.step == XfersDisbursementStep.SECOND_STEP:
        return JTFXfersService()
    # use jtp xfers service on rest cases
    return JTPXfersService(disbursement.lender_id)


def get_validation_method(application):
    if application.is_grab():
        return NameBankValidationVendors.PAYMENT_GATEWAY
    traffic_rules = DisbursementTrafficControl.objects.filter(
        rule_type=CommonVariables.RULE_DISBURSEMENT_TRAFFIC, is_active=True)
    validation = None
    for traffic_rule in traffic_rules:
        is_satisfied = rule_satisfied(
            traffic_rule.condition, traffic_rule.key, application)
        if is_satisfied:
            if traffic_rule.success_value:
                # extract INSTAMONEY or DEFAULT etc..
                validation = getattr(
                    NameBankValidationVendors, traffic_rule.success_value.upper(), None)
            else:
                validation = NameBankValidationVendors.DEFAULT
            break
    return validation if validation else NameBankValidationVendors.DEFAULT


def is_bca_disbursement(application):
    traffic_rules = DisbursementTrafficControl.objects.filter(
        rule_type=CommonVariables.RULE_DISBURSEMENT_TRAFFIC,
        success_value="bca",
        is_active=True)
    for traffic_rule in traffic_rules:
        is_satisfied = rule_satisfied(
            traffic_rule.condition, traffic_rule.key, application)
        if is_satisfied:
            return True
    return False


def get_disbursement_method(name_bank_validation, application=None, loan_xid=None):
    # if its grab it will check bank code for ayoconnect first and do a payment gateway matchmaking
    application = Application.objects.filter(name_bank_validation=name_bank_validation).last()
    if application and application.is_grab():
        bank_account_dest = BankAccountDestination.objects.filter(
            name_bank_validation=name_bank_validation
        ).last()
        if not bank_account_dest:
            logger.info({
                "action": "get_disbursement_method",
                "name_bank_validation_id": name_bank_validation.id,
                "message": "bank account destination doesn't exist"
            })
            return

        ayo_service = AyoconnectService()
        payment_gateway_vendor = ayo_service.get_payment_gateway()
        ayoconnect_bank_exist = PaymentGatewayBankCode.objects.filter(
            bank_id=bank_account_dest.bank_id,
            payment_gateway_vendor=payment_gateway_vendor,
            is_active=True
        ).exists()
        if ayoconnect_bank_exist:
            return payment_gateway_matchmaking()
        else:
            return DisbursementVendors.PG
    else:
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if (
            loan
            and loan.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]
            # and name_bank_validation.method == NameBankValidationVendors.XFERS
        ):
            # force AYC when transaction is E-wallet
            if loan.transaction_method_id == TransactionMethodCode.DOMPET_DIGITAL.code:
                if loan.is_xfers_ewallet_transaction:
                    return DisbursementVendors.XFERS

                return DisbursementVendors.AYOCONNECT

            bank_account_dest = BankAccountDestination.objects.filter(
                name_bank_validation=name_bank_validation
            ).last()
            # if trying to AYC disburse with unsupported bank, use Xfers & ignore the experiment
            if (
                bank_account_dest
                and not AyoconnectService().get_payment_gateway_bank(
                    bank_id=bank_account_dest.bank_id
                )
            ):
                return DisbursementVendors.XFERS

            method = get_experiment_disbursement_method(loan)
            if method:
                return method

        if name_bank_validation.bank_code.lower() == "bca" or \
                application and is_bca_disbursement(application):
            return DisbursementVendors.BCA

    return name_bank_validation.method


def get_experiment_disbursement_method(loan):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DISBURSEMENT_METHOD,
        is_active=True
    ).first()
    if not feature_setting:
        # return method=None to use default method
        return None

    parameters = feature_setting.parameters
    if loan.transaction_method_id not in parameters['list_transaction_method_code_apply_ratio']:
        # return method=None to use default method
        return None

    application_id = loan.get_application.id
    disbursement_vendor_config = parameters['disbursement_vendor']

    # priority whitelist first
    for vendor in disbursement_vendor_config.keys():
        whitelist_config = disbursement_vendor_config[vendor]['whitelist']
        if (
            whitelist_config['is_active']
            and application_id in whitelist_config['list_application_id']
        ):
            return vendor

    active_vendors = [
        vendor for vendor in disbursement_vendor_config.keys()
        if disbursement_vendor_config[vendor]['is_active']
    ]

    # if no active vendor, return None to no disbursement
    if len(active_vendors) == 0:
        raise DisbursementServiceError('No active vendors')

    # if only one active vendor, return it
    if len(active_vendors) == 1:
        return active_vendors[0]

    # check last digit of loan id
    for active_vendor in active_vendors:
        if (
            loan.id % 10
            in disbursement_vendor_config[active_vendor]['list_last_digit_of_loan_id']
        ):
            return active_vendor

    # digit not match, return None to no disbursement
    raise DisbursementServiceError('Last digit of loan id not match with any vendor')


def get_new_disbursement_flow(method):
    """implement traffic management"""
    traffic_obj = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DISBURSEMENT_TRAFFIC_MANAGE,
        is_active=True
    ).first()

    if not traffic_obj:
        return method, False

    traffic_setting = traffic_obj.parameters.get(method.lower())
    result = gen_probability(traffic_setting)
    if result:
        result = result.title()
        if result == MoneyFlow.NEW_XFERS:
            return DisbursementVendors.XFERS, True
        if result in DisbursementVendors.VALID_LIST:
            return result, False
    return method, False


def get_name_bank_validation(name_bank_validation_id):
    name_bank_validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
    name_bank_validation_data = {}
    if not name_bank_validation:
        name_bank_validation_data['id'] = None
        name_bank_validation_data['bank_code'] = None
        name_bank_validation_data['account_number'] = None
        name_bank_validation_data['name_in_bank'] = None
        name_bank_validation_data['method'] = None
        name_bank_validation_data['validation_id'] = None
        name_bank_validation_data['validation_status'] = None
        name_bank_validation_data['validated_name'] = None
        name_bank_validation_data['cdate'] = None
        name_bank_validation_data['reason'] = None
        return name_bank_validation_data

    name_bank_validation_data['id'] = name_bank_validation.id
    name_bank_validation_data['bank_code'] = name_bank_validation.bank_code
    name_bank_validation_data['account_number'] = name_bank_validation.account_number
    name_bank_validation_data['name_in_bank'] = name_bank_validation.name_in_bank
    name_bank_validation_data['method'] = name_bank_validation.method
    name_bank_validation_data['validation_id'] = name_bank_validation.validation_id
    name_bank_validation_data['validation_status'] = name_bank_validation.validation_status
    name_bank_validation_data['validated_name'] = name_bank_validation.validated_name
    name_bank_validation_data['cdate'] = name_bank_validation.cdate.__str__()
    name_bank_validation_data['reason'] = name_bank_validation.reason
    return name_bank_validation_data


def get_disbursement(disbursement_id):
    disbursement = Disbursement.objects.get_or_none(pk=disbursement_id)
    disbursement_data = {}
    if not disbursement:
        disbursement_data['id'] = None
        disbursement_data['name_bank_validation_id'] = None
        disbursement_data['external_id'] = None
        disbursement_data['method'] = None
        disbursement_data['amount'] = None
        disbursement_data['disburse_id'] = None
        disbursement_data['disburse_status'] = None
        disbursement_data['retry_times'] = None
        disbursement_data['reason'] = None
        return disbursement_data

    disbursement_data['id'] = disbursement.id
    disbursement_data['name_bank_validation_id'] = disbursement.name_bank_validation_id
    disbursement_data['external_id'] = disbursement.external_id
    disbursement_data['method'] = disbursement.method
    disbursement_data['amount'] = disbursement.amount
    disbursement_data['disburse_id'] = disbursement.disburse_id
    disbursement_data['disburse_status'] = disbursement.disburse_status
    disbursement_data['retry_times'] = disbursement.retry_times
    disbursement_data['reason'] = disbursement.reason
    return disbursement_data


def get_multi_step_disbursement(disbursement_id, lender_id):
    disbursement = Disbursement.objects.get_or_none(pk=disbursement_id)
    new_xfers = False

    def get_single_disbursement(disbursement_id):
        data = get_disbursement(disbursement_id)
        data['julo_balance'] = get_xfers_balance('jtf', lender_id)
        return [data]

    if not disbursement:
        return new_xfers, get_single_disbursement(disbursement_id)

    if not disbursement.step:
        return new_xfers, get_single_disbursement(disbursement_id)

    new_xfers = True

    disbursement_data_list = []

    first_step_last_history = Disbursement2History.objects.filter(
        disbursement=disbursement, step=XfersDisbursementStep.FIRST_STEP).order_by('cdate').last()

    second_step_last_history = Disbursement2History.objects.filter(
        disbursement=disbursement, step=XfersDisbursementStep.SECOND_STEP
    ).order_by('cdate').last()

    # for handle application before new history released (transition situation)
    if not first_step_last_history:
        disbursement_data = {'method': disbursement.method,
                             'amount': disbursement.original_amount,
                             'disburse_id': disbursement.disburse_id,
                             'disburse_status': disbursement.disburse_status,
                             'reason': disbursement.reason,
                             'julo_balance': get_xfers_balance('jtp', lender_id)}
        disbursement_data_list.append(disbursement_data)
        if disbursement.step == XfersDisbursementStep.SECOND_STEP:
            # if the disbursement step == 2 assumed  the first step is already completed
            disbursement_data_list[0]['disburse_status'] = DisbursementStatus.COMPLETED
            disbursement_data_list[0]['reason'] = 'success'
            disbursement_data = {'method': disbursement.method,
                                 'amount': disbursement.amount,
                                 'disburse_id': disbursement.disburse_id,
                                 'disburse_status': disbursement.disburse_status,
                                 'reason': disbursement.reason,
                                 'julo_balance': get_xfers_balance('jtf', lender_id)}
            disbursement_data_list.append(disbursement_data)
    else:
        if first_step_last_history:
            disbursement_data = {'method': first_step_last_history.method,
                                 'amount': first_step_last_history.amount,
                                 'disburse_id': first_step_last_history.order_id,
                                 'disburse_status': first_step_last_history.disburse_status,
                                 'reason': first_step_last_history.reason,
                                 'julo_balance': get_xfers_balance('jtp', lender_id)}
            disbursement_data_list.append(disbursement_data)

        if second_step_last_history:
            disbursement_data = {'method': second_step_last_history.method,
                                 'amount': second_step_last_history.amount,
                                 'disburse_id': second_step_last_history.idempotency_id,
                                 'disburse_status': second_step_last_history.disburse_status,
                                 'reason': second_step_last_history.reason,
                                 'julo_balance': get_xfers_balance('jtf', lender_id)}
            disbursement_data_list.append(disbursement_data)
    return new_xfers, disbursement_data_list


def get_xfers_balance(type, lender_id):
    service = JTPXfersService(lender_id) if type == 'jtp' else JTFXfersService()
    try:
        balance = service.get_balance()
    except Exception:
        return None
    return balance


def get_julo_balance(method):
    service = get_service(method)
    try:
        balance = service.get_balance()
    except Exception:
        return None
    return balance


def get_xfers_balance_from_cache(lender_type, lender_id):
    key = "%s_%s" % (lender_type, lender_id)

    redis_client = get_redis_client()
    balance = redis_client.get(key)
    if balance is not None:
        return balance

    service = JTPXfersService(lender_id) if lender_type == 'jtp' else JTFXfersService()
    try:
        balance = service.get_balance()
    except Exception:
        return None

    redis_client.set(key, balance, BALANCE_CACHE_TIMEOUT)
    return balance


def get_julo_balance_from_cache(method):
    key = method
    redis_client = get_redis_client()
    balance = redis_client.get(key)
    if balance is not None:
        return balance

    service = get_service(method)
    try:
        balance = service.get_balance()
    except Exception:
        return None

    redis_client.set(key, balance, BALANCE_CACHE_TIMEOUT)
    return balance


def get_bank_id_and_bank_code_by_method(bank: Bank, method: str):
    bank_id = None
    bank_code = None
    if method == NameBankValidationVendors.PAYMENT_GATEWAY:
        bank_id = bank.id
        bank_code = bank.bank_code
    else:
        bank_code = getattr(bank, '{}_bank_code'.format(method.lower()))

    return bank_id, bank_code


def trigger_name_in_bank_validation(data_to_validate, method=None, new_log=None):
    logger.info({
        'action': 'name_in_bank_validation_triggered',
        'data_to_validate': data_to_validate,
        'method': method,
        'new_log': new_log,
    })
    # check bank manager
    # assign validation_method
    bank_name = data_to_validate['bank_name']
    account_number = data_to_validate['account_number']
    name_in_bank = data_to_validate['name_in_bank']
    name_bank_validation_id = data_to_validate['name_bank_validation_id']
    mobile_phone = data_to_validate['mobile_phone']
    application = data_to_validate['application']
    is_initiated = False
    bank_entry = BankManager.get_by_name_or_none(bank_name)
    if not bank_entry:
        raise BankNameNotFound

    if name_bank_validation_id is not None:
        name_bank_validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
        if name_bank_validation is None:
            raise DisbursementServiceError('validation %s not found!' % name_bank_validation_id)

        if not method:
            if application.is_grab():
                method = name_bank_validation.method
            else:
                method = get_validation_method(application)

        bank_id, bank_code = get_bank_id_and_bank_code_by_method(bank_entry, method)

        update_fields = []
        if name_bank_validation.bank_code != bank_code:
            name_bank_validation.bank_code = bank_code
            update_fields.append('bank_code')
        if name_bank_validation.account_number != account_number:
            name_bank_validation.account_number = account_number
            update_fields.append('account_number')
        if name_bank_validation.name_in_bank != name_in_bank:
            name_bank_validation.name_in_bank = name_in_bank
            update_fields.append('name_in_bank')
        if name_bank_validation.mobile_phone != mobile_phone:
            update_fields.append('mobile_phone')
        if name_bank_validation.bank_id != bank_id:
            name_bank_validation.bank_id = bank_id
            update_fields.append('bank_id')
        if len(update_fields) > 0:
            name_bank_validation.save(update_fields=update_fields)
            name_bank_validation.create_history('update_field', update_fields)

    else:
        if not method:
            method = get_validation_method(application)

        bank_id, bank_code = get_bank_id_and_bank_code_by_method(bank_entry, method)

        name_bank_validation = NameBankValidation.objects.create(
            bank_code=bank_code,
            account_number=account_number,
            name_in_bank=name_in_bank,
            mobile_phone=mobile_phone,
            method=method,
            bank_id=bank_id,
        )
        update_fields = [
            'bank_code',
            'account_number',
            'name_in_bank',
            'mobile_phone',
            'method',
            'bank_id',
        ]
        name_bank_validation.create_history('create', update_fields)
        name_bank_validation_id = name_bank_validation.id
        is_initiated = True

        logger.info({
            'action': 'name_bank_validation_created',
            'name_bank_validation': name_bank_validation,
        })

    name_bank_validation.refresh_from_db()

    if new_log:
        name_bank_validation_log = BankNameValidationLog()
        name_bank_validation_log.validated_name = name_bank_validation.name_in_bank
        name_bank_validation_log.account_number = name_bank_validation.account_number
        name_bank_validation_log.method = name_bank_validation.method
        name_bank_validation_log.application = application
        bank_validation_log_old = BankNameValidationLog.objects.filter(application=application)\
            .order_by('cdate').last()
        if bank_validation_log_old:
            name_bank_validation_log.validation_status_old = \
                bank_validation_log_old.validation_status
            name_bank_validation_log.validated_name_old = bank_validation_log_old.validated_name
            name_bank_validation_log.account_number_old = bank_validation_log_old.account_number
            name_bank_validation_log.reason_old = bank_validation_log_old.reason
            name_bank_validation_log.method_old = bank_validation_log_old.method
        else:
            if not is_initiated:
                # why i get old value from event = create,
                # because there's no historical data about when account_number
                # change and when it validated
                bank_validation_history = NameBankValidationHistory.objects.get(
                    name_bank_validation_id=name_bank_validation_id, event='create')
                bank_validation_history_parsed = bank_validation_history.field_changes
                name_bank_validation_log.validated_name_old = \
                    bank_validation_history_parsed['name_in_bank']
                name_bank_validation_log.account_number_old = \
                    bank_validation_history_parsed['account_number']
                name_bank_validation_log.method_old = \
                    bank_validation_history_parsed['method']
                name_bank_validation_log.validation_status_old = \
                    name_bank_validation.validation_status
                name_bank_validation_log.reason_old = name_bank_validation.reason
        name_bank_validation_log.save()
        return ValidationProcess(name_bank_validation, name_bank_validation_log)
    else:
        return ValidationProcess(name_bank_validation)


def trigger_disburse(data_to_disburse, method=None, application=None, new_payment_gateway=False):
    from juloserver.disbursement.tasks import send_payment_gateway_vendor_api_alert_slack
    logger.info({
        "action": "trigger_disburse",
        "data": data_to_disburse
    })
    name_bank_validation_id = data_to_disburse['name_bank_validation_id']
    name_bank_validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
    if name_bank_validation is None:
        raise DisbursementServiceError('could not disburse loan before validate bank account')

    if name_bank_validation.validation_status != NameBankValidationStatus.SUCCESS:
        raise DisbursementServiceError('could not disburse loan to invalid bank account')

    disbursement_id = data_to_disburse['disbursement_id']
    if disbursement_id is not None:
        disbursement = Disbursement.objects.filter(id=disbursement_id).last()
        if not disbursement:
            raise DisbursementServiceError(
                'disbursement %s not found' % disbursement_id)

        application = Application.objects.filter(
            name_bank_validation=disbursement.name_bank_validation
        ).last()
        if (
                application
                and application.is_grab()
                and disbursement.method == DisbursementVendors.AYOCONNECT
        ):
            max_retry = AyoconnectConst.MAX_FAILED_RETRIES
            grab_disbursement_retry_feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.GRAB_DISBURSEMENT_RETRY, is_active=True
            ).last()
            if grab_disbursement_retry_feature_setting:
                parameter = grab_disbursement_retry_feature_setting.parameters
                max_retry = parameter.get('max_retry_times', max_retry)
            if (
                    disbursement.retry_times >= max_retry
                    or disbursement.reason == AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE
            ):
                logger.info({
                    "action": "trigger_disburse",
                    "disbursement_id": disbursement_id,
                    "message": "failover triggered"
                })
                # check feature setting flag
                feature_setting = FeatureSetting.objects.filter(
                    feature_name=FeatureNameConst.GRAB_AYOCONNECT_XFERS_FAILOVER,
                    is_active=True
                ).last()
                if (
                        feature_setting
                        and (
                        disbursement.retry_times >= max_retry + 1
                        or disbursement.reason == AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE)
                ):
                    # to handle the failover from ayoconnect payment gateway
                    redirecting_method = DisbursementVendors.PG
                    disbursement.retry_times = 0
                    disbursement.disburse_status = DisbursementStatus.INITIATED
                    disbursement.method = redirecting_method
                    disbursement.step = PaymentgatewayDisbursementStep.SECOND_STEP

                    disbursement.save(update_fields=['retry_times', 'method', 'udate',
                                                     'step', 'disburse_status'])
                    disbursement.create_history('update method', ['method'])

                    msg_str = "Failover from Ayoconnect to Payment Gateway Services triggered for disbursement_id {}"
                    msg = msg_str.format(disbursement_id)
                    send_payment_gateway_vendor_api_alert_slack.delay(
                        err_message=msg,
                        msg_type=2
                    )

        if disbursement.name_bank_validation_id != name_bank_validation.id:
            disbursement.name_bank_validation = name_bank_validation
            disbursement.save()
            disbursement.create_history('update name_bank_validation', ['name_bank_validation_id'])
    else:
        amount = data_to_disburse['amount']
        external_id = data_to_disburse['external_id']
        disbursement_type = data_to_disburse['type']
        original_amount = data_to_disburse.get('original_amount')
        disbursement = Disbursement(disbursement_type=disbursement_type,
                                    name_bank_validation=name_bank_validation,
                                    amount=amount,
                                    original_amount=original_amount,
                                    external_id=external_id)
        if not method:
            method = get_disbursement_method(name_bank_validation, application,
                                             loan_xid=data_to_disburse['external_id'])
        if data_to_disburse['type'] in ('loan', 'bulk'):
            use_new_flow = False
            if method not in (DisbursementVendors.AYOCONNECT, DisbursementVendors.PG):
                method, use_new_flow = get_new_disbursement_flow(method)

                loan = Loan.objects.get_or_none(loan_xid=external_id)
                is_xfers_ewallet_transaction = loan.is_xfers_ewallet_transaction if loan else False
                if is_xfers_ewallet_transaction:
                    method == DisbursementVendors.XFERS

                if use_new_flow:
                    disbursement.step = XfersDisbursementStep.FIRST_STEP
                    if (
                        loan
                        and loan.lender
                        and loan.transaction_method_id
                        not in TransactionMethodCode.single_step_disbursement()
                    ) or is_xfers_ewallet_transaction:
                        if loan.lender.lender_name in LenderCurrent.escrow_lender_list():
                            disbursement.step = XfersDisbursementStep.SECOND_STEP

                # xendit experiment --
                if is_vendor_experiment_possible(loan):
                    if not is_xendit_use_step_one_disbursement():  # no step one
                        experiment_method = get_ecommerce_disbursement_experiment_method(loan)
                        if not experiment_method:
                            raise XenditExperimentError("No method is on")
                        if experiment_method == DisbursementVendors.XENDIT:
                            method = DisbursementVendors.XENDIT
                            disbursement.step = XenditDisbursementStep.SECOND_STEP
                # -- xendit experiment
            else:
                if not new_payment_gateway:
                    disbursement.step = AyoconnectDisbursementStep.SECOND_STEP
                else:
                    disbursement.step = PaymentgatewayDisbursementStep.SECOND_STEP

        disbursement.method = method
        disbursement.save()

        update_fields = ['method', 'name_bank_validation', 'amount',
                         'external_id', 'disbursement_type']
        disbursement.create_history('create', update_fields)

    disbursement.refresh_from_db()
    if name_bank_validation.method == NameBankValidationVendors.XENDIT:
        if disbursement.method == DisbursementVendors.XFERS:
            raise DisbursementServiceError(
                'cannot disburse use xfers method for xendit validation')
    return get_disbursement_by_obj(disbursement)


def get_name_bank_validation_process(validation_id):
    name_bank_validation = NameBankValidation.objects.filter(
        validation_id=validation_id).order_by('cdate').last()
    if not name_bank_validation:
        raise DisbursementServiceError('name bank validation process not found')
    return ValidationProcess(name_bank_validation)


def get_disbursement_process(disburse_id):
    disbursement = Disbursement.objects.filter(disburse_id=disburse_id).order_by('cdate').last()
    if not disbursement:
        raise DisbursementServiceError('disbursement process not found')
    return get_disbursement_by_obj(disbursement)


def is_grab_disbursement(disburse_id, is_reversal_payment):
    if is_reversal_payment:
        return False
    disbursement = Disbursement.objects.filter(disburse_id=disburse_id).values('pk').last()
    if not disbursement:
        raise DisbursementServiceError('disbursement process not found')

    loan = Loan.objects.filter(disbursement_id=disbursement['pk']).last()
    if not loan:
        return False

    application = loan.get_application
    return application.is_grab()


def get_disbursement_by_obj(disbursement):
    if disbursement.step:
        # -- xendit experiment
        is_xendit_method = disbursement.method == DisbursementVendors.XENDIT
        is_xendit_step_two = disbursement.step == XenditDisbursementStep.SECOND_STEP

        if is_xendit_method and is_xendit_step_two:
            return XenditDisbursementProcess(disbursement)
        # xendit experiment --

        # -- ayoconnect
        is_ayoconnect_method = disbursement.method == DisbursementVendors.AYOCONNECT
        is_ayoconnect_step_two = disbursement.step == AyoconnectDisbursementStep.SECOND_STEP
        if is_ayoconnect_method and is_ayoconnect_step_two:
            return AyoconnectDisbursementProcess(disbursement)
        # -- ayoconnect

        is_doku_method = disbursement.method == DisbursementVendors.PG
        is_doku_step_two = disbursement.step == PaymentgatewayDisbursementStep.SECOND_STEP

        if is_doku_method and is_doku_step_two:
            return PaymentGatewayDisbursementProcess(disbursement)

        return NewXfersDisbursementProcess(disbursement)
    return DisbursementProcess(disbursement)


def get_name_bank_validation_process_by_id(name_bank_validation_id):
    name_bank_validation = NameBankValidation.objects.get_or_none(id=name_bank_validation_id)
    if not name_bank_validation:
        raise DisbursementServiceError('name bank validation process not found')
    return ValidationProcess(name_bank_validation)


def get_disbursement_process_by_id(disbursement_id):
    disbursement = Disbursement.objects.get_or_none(id=disbursement_id)
    if not disbursement:
        raise DisbursementServiceError('disbursement process not found')
    return DisbursementProcess(disbursement)


def get_list_validation_method():
    return NameBankValidationVendors.VENDOR_LIST


def get_list_validation_method_xfers():
    return NameBankValidationVendors.VENDOR_LIST_2


def get_default_validation_method():
    return NameBankValidationVendors.DEFAULT


def get_list_disbursement_method(bank_name, validation_method=None):
    validation_method = validation_method
    if (
        validation_method == NameBankValidationVendors.XENDIT and
        'BCA' in bank_name or
        validation_method == NameBankValidationVendors.INSTAMONEY and
        'BCA' in bank_name
    ):
        disbursement_methods = [
            DisbursementVendors.INSTAMONEY, DisbursementVendors.BCA]
    elif (
        validation_method == NameBankValidationVendors.XFERS and
        'BCA' in bank_name
    ):
        disbursement_methods = [DisbursementVendors.XFERS,
                                DisbursementVendors.INSTAMONEY,
                                DisbursementVendors.BCA]
    elif (
        validation_method == NameBankValidationVendors.XENDIT and
        'BCA' not in bank_name or
        validation_method == NameBankValidationVendors.INSTAMONEY and
        'BCA' not in bank_name
    ):
        disbursement_methods = DisbursementVendors.VENDOR_LIST_2
    elif (
        validation_method == NameBankValidationVendors.XFERS and
        'BCA' not in bank_name
    ):
        disbursement_methods = DisbursementVendors.VENDOR_LIST
    elif validation_method is None:
        disbursement_methods = []

    return disbursement_methods


def get_name_bank_validation_by_bank_account(bank_name, account_number, name_in_bank):
    bank = BankManager.get_by_name_or_none(bank_name)
    if not bank:
        raise DisbursementServiceError('bank %s not found' % bank_name)
    nbv = NameBankValidation.objects.filter(bank_code=bank.xfers_bank_code,
                                            account_number=account_number,
                                            name_in_bank=name_in_bank,
                                            validation_status=NameBankValidationStatus.SUCCESS
                                            ).last()
    if not nbv:
        return None

    return nbv.id


def create_disbursement_new_flow_history(disbursement, reason=None):
    order_id = None
    idempotency_id = None
    request_ts = disbursement.request_ts if 'request_ts' in disbursement.__dict__ else None
    response_ts = disbursement.response_ts if 'response_ts' in disbursement.__dict__ else None

    if disbursement.step == XfersDisbursementStep.FIRST_STEP:
        order_id = disbursement.disburse_id
        amount = disbursement.original_amount
    else:
        idempotency_id = disbursement.disburse_id
        amount = disbursement.amount

    Disbursement2History.objects.create(
        disbursement=disbursement,
        amount=amount,
        method=disbursement.method,
        order_id=order_id,
        idempotency_id=idempotency_id,
        disburse_status=disbursement.disburse_status,
        reason=reason or disbursement.reason,
        reference_id=disbursement.reference_id,
        attempt=disbursement.retry_times,
        step=disbursement.step,
        transaction_request_ts=request_ts,
        transaction_response_ts=response_ts,
    )


def create_disbursement_history_ayoconnect(disbursement):
    request_ts = disbursement.request_ts if 'request_ts' in disbursement.__dict__ else None
    response_ts = disbursement.response_ts if 'response_ts' in disbursement.__dict__ else None

    idempotency_id = disbursement.disburse_id
    amount = disbursement.amount

    Disbursement2History.objects.create(
        disbursement=disbursement,
        amount=amount,
        method=disbursement.method,
        order_id=None,
        idempotency_id=idempotency_id,
        disburse_status=disbursement.disburse_status,
        reason=disbursement.reason,
        reference_id=disbursement.reference_id,
        attempt=disbursement.retry_times,
        step=disbursement.step,
        transaction_request_ts=request_ts,
        transaction_response_ts=response_ts,
    )


def create_disbursement_history_new_payment_gateway(disbursement):
    request_ts = disbursement.request_ts if 'request_ts' in disbursement.__dict__ else None
    response_ts = disbursement.response_ts if 'response_ts' in disbursement.__dict__ else None

    idempotency_id = disbursement.disburse_id
    amount = disbursement.amount

    Disbursement2History.objects.create(
        disbursement=disbursement,
        amount=amount,
        method=disbursement.method,
        order_id=None,
        idempotency_id=idempotency_id,
        disburse_status=disbursement.disburse_status,
        reason=disbursement.reason,
        reference_id=disbursement.reference_id,
        attempt=disbursement.retry_times,
        step=disbursement.step,
        transaction_request_ts=request_ts,
        transaction_response_ts=response_ts,
    )


def get_xendit_whitelist():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.XENDIT_WHITELIST,
        is_active=True
    ).first()


def check_xendit_whitelist(application, feature_setting=None):
    if not application:
        return False

    if not feature_setting:
        feature_setting = get_xendit_whitelist()

    return feature_setting and 'application_id' in feature_setting.parameters\
        and application.id in feature_setting.parameters['application_id']


def get_ecommerce_disbursement_experiment_method(loan):
    return_method = DisbursementVendors.XFERS
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ECOMMERCE_EXPERIMENT,
        is_active=True).first()
    if (
        feature_setting
        and loan
        and loan.transaction_method_id == TransactionMethodCode.E_COMMERCE.code
        and loan.loan_purpose.lower() != EcommerceConstant.IPRICE.lower()
    ):
        xendit_whitelist_feature = get_xendit_whitelist()
        if xendit_whitelist_feature:
            if (
                loan.account
                and check_xendit_whitelist(loan.get_application, xendit_whitelist_feature)
            ):
                return DisbursementVendors.XENDIT
            else:
                return DisbursementVendors.XFERS

        list_active = {}
        for method, parameter in feature_setting.parameters.items():
            if parameter['status'] != DisbursementVendorStatus.ACTIVE:
                continue
            list_active[method] = parameter['loan_id']

        for method, parameter in list_active.items():
            # comparing digit loand id base on parameter criteria number 1
            # i use this parameter setting to make it easy and can be customized
            if len(list_active) > 1:
                criteria = parameter.split(":")
                if criteria[0] == "#nth":
                    if repr(loan.id)[int(criteria[1])] not in criteria[2].split(","):
                        continue
            return_method = method

    return return_method


def is_xendit_use_step_one_disbursement():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.XENDIT_STEP_ONE_DISBURSEMENT,
        is_active=True
    ).exists()


def is_vendor_experiment_possible(loan):
    if not loan:
        return False

    return all([
        loan.transaction_method_id == TransactionMethodCode.E_COMMERCE.code,
        loan.loan_purpose != PartnerConstant.IPRICE,
    ])


def update_reason_for_multiple_disbursement(loan_ids: List[int], reason: str) -> None:
    disbursement_ids = Loan.objects.filter(id__in=loan_ids).values_list(
        'disbursement_id', flat=True
    )
    Disbursement.objects.filter(id__in=disbursement_ids).update(reason=reason)


class ValidationProcess(object):
    def __init__(self, name_bank_validation, log_name_bank_validation=None):
        self.name_bank_validation = name_bank_validation
        self.log_name_bank_validation = log_name_bank_validation

    def validate(self, bypass_name_in_bank=False):
        logger.info(
            {
                'action': 'trigger_validation_process',
                'name_bank_validation': self.name_bank_validation,
                'method': self.name_bank_validation.method,
                'status': self.name_bank_validation.validation_status,
            }
        )
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        if name_bank_validation.validation_status in NameBankValidationStatus.SKIPPED_STATUSES:
            return True

        if name_bank_validation.method == '':
            raise DisbursementServiceError('method name bank validation could not be Empty!!')

        service = get_service(name_bank_validation.method)
        response_validate = service.validate(name_bank_validation)
        logger.info({
            'action': 'validation_service_response',
            'name_bank_validation': name_bank_validation.id,
            'response': response_validate,
        })
        validation_status = response_validate['status']
        if (
            response_validate['status'] == NameBankValidationStatus.SUCCESS
            and not bypass_name_in_bank
        ):
            name_in_bank = name_bank_validation.name_in_bank.lower()
            validated_name = response_validate['validated_name'].lower()
            if name_in_bank != validated_name:
                validation_status = NameBankValidationStatus.NAME_INVALID
                response_validate['reason'] = NameBankValidationStatus.NAME_INVALID

        update_fields_for_log_name_bank_validation = ['validation_status',
                                                      'validation_id',
                                                      'validated_name',
                                                      'reason']
        update_fields = update_fields_for_log_name_bank_validation

        if name_bank_validation.method == 'Xfers':
            name_bank_validation.error_message = response_validate['error_message']
            update_fields_for_name_bank_validation = ['error_message']
            update_fields_for_name_bank_validation.extend(
                update_fields_for_log_name_bank_validation
            )

            update_fields = update_fields_for_name_bank_validation

        name_bank_validation.validation_status = validation_status
        name_bank_validation.validation_id = response_validate['id']
        name_bank_validation.validated_name = response_validate['validated_name']
        name_bank_validation.reason = response_validate['reason']

        name_bank_validation.save(update_fields=update_fields)
        name_bank_validation.create_history('update_status',
                                            update_fields)

        if self.log_name_bank_validation:
            log_name_bank_validation = self.log_name_bank_validation
            log_name_bank_validation.validation_id = response_validate['id']
            log_name_bank_validation.validation_status = validation_status
            log_name_bank_validation.reason = response_validate['reason']
            log_name_bank_validation.validated_name = response_validate['validated_name']
            if not log_name_bank_validation.validation_status_old:
                log_name_bank_validation.validated_name_old = name_bank_validation.validated_name
                log_name_bank_validation.account_number_old = name_bank_validation.account_number
                log_name_bank_validation.validation_status_old = \
                    name_bank_validation.validation_status
                log_name_bank_validation.reason_old = name_bank_validation.reason
            log_name_bank_validation.save(update_fields=update_fields_for_log_name_bank_validation)

        return True

    def is_success(self):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        if name_bank_validation.validation_status == NameBankValidationStatus.SUCCESS:
            return True
        return False

    def is_failed(self):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        validation_status = name_bank_validation.validation_status
        if validation_status in NameBankValidationStatus.FAILED_STATUSES:
            return True
        return False

    def change_method(self, method):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        # update bank code
        bank_code = None
        if name_bank_validation.bank_id:
            bank_entry = BankManager.get_by_id_or_none(name_bank_validation.bank_id)
            if bank_entry:
                _, bank_code = get_bank_id_and_bank_code_by_method(bank_entry, method)
        else:
            bank_entry = BankManager.get_by_method_bank_code(name_bank_validation.bank_code)
            _, bank_code = get_bank_id_and_bank_code_by_method(bank_entry, method)

        name_bank_validation.method = method
        name_bank_validation.bank_code = bank_code
        name_bank_validation.save(update_fields=['method', 'bank_code'])
        name_bank_validation.create_history('update_method', ['method', 'bank_code'])

    def update_status(self, data):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        service = get_service(name_bank_validation.method)
        response_validate = service.process_callback_validation(data, name_bank_validation)
        update_fields = ['validation_status', 'validated_name', 'reason']
        name_bank_validation.validation_status = response_validate['status']
        name_bank_validation.validated_name = response_validate['validated_name']
        name_bank_validation.reason = response_validate['reason']
        name_bank_validation.save(update_fields=update_fields)
        name_bank_validation.create_history('update_status', update_fields)

    def get_id(self):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        return self.name_bank_validation.id

    def get_data(self):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        name_bank_validation_data = {}
        name_bank_validation_data['id'] = name_bank_validation.id
        name_bank_validation_data['bank_code'] = name_bank_validation.bank_code
        name_bank_validation_data['account_number'] = name_bank_validation.account_number
        name_bank_validation_data['name_in_bank'] = name_bank_validation.name_in_bank
        name_bank_validation_data['method'] = name_bank_validation.method
        name_bank_validation_data['validation_id'] = name_bank_validation.validation_id
        name_bank_validation_data['validation_status'] = name_bank_validation.validation_status
        name_bank_validation_data['validated_name'] = name_bank_validation.validated_name
        name_bank_validation_data['reason'] = name_bank_validation.reason
        name_bank_validation_data['cdate'] = name_bank_validation.cdate.__str__()
        name_bank_validation_data['attempt'] = name_bank_validation.attempt
        return name_bank_validation_data

    def is_valid_method(self, method):
        if method == self.name_bank_validation.method:
            return True
        return False

    def update_fields(self, fields, values):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        for idx in range(len(fields)):
            setattr(name_bank_validation, fields[idx], values[idx])
        name_bank_validation.save(update_fields=fields)
        name_bank_validation.create_history('update_fields', fields)
        return True

    def get_method(self):
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        return name_bank_validation.method

    def validate_grab(self, bypass_name_in_bank=False):
        logger.info(
            {
                'action': 'trigger_validation_process - grab',
                'name_bank_validation': self.name_bank_validation,
                'method': self.name_bank_validation.method,
                'status': self.name_bank_validation.validation_status,
            }
        )
        name_bank_validation = self.name_bank_validation
        name_bank_validation.refresh_from_db()
        if name_bank_validation.validation_status in NameBankValidationStatus.SKIPPED_STATUSES:
            return True

        if name_bank_validation.method == '':
            raise DisbursementServiceError('method name bank validation could not be Empty!!')

        disbursement_service = get_service(name_bank_validation.method, True)

        response_validate = disbursement_service.validate_grab(name_bank_validation)
        logger.info(
            {
                'action': 'validation_service_response - grab',
                'name_bank_validation': name_bank_validation.id,
                'response': response_validate,
            }
        )
        validation_status = response_validate['status']
        if (
            response_validate['status'] == NameBankValidationStatus.SUCCESS
            and not bypass_name_in_bank
        ):
            name_in_bank = name_bank_validation.name_in_bank.lower()
            validated_name = response_validate['validated_name'].lower()
            if name_in_bank != validated_name:
                validation_status = NameBankValidationStatus.NAME_INVALID
                response_validate['reason'] = NameBankValidationStatus.NAME_INVALID

        fields_to_be_updated = [
            'validation_status',
            'validation_id',
            'validated_name',
            'reason',
        ]

        self.update_name_bank_validation(response_validate, validation_status, fields_to_be_updated)
        if self.log_name_bank_validation:
            self.update_log_name_bank_validation(
                response_validate, validation_status, fields_to_be_updated
            )

        return True

    def update_name_bank_validation(
        self, response_validate, validation_status, fields_to_be_updated
    ):
        self.name_bank_validation.validation_status = validation_status
        self.name_bank_validation.validation_id = response_validate['id']
        self.name_bank_validation.validated_name = response_validate['validated_name']
        self.name_bank_validation.reason = response_validate['reason']

        self.name_bank_validation.save(update_fields=fields_to_be_updated)
        self.name_bank_validation.create_history('update_status', fields_to_be_updated)

    def update_log_name_bank_validation(
        self, response_validate, validation_status, fields_to_be_updated
    ):
        log_name_bank_validation = self.log_name_bank_validation
        log_name_bank_validation.validation_id = response_validate['id']
        log_name_bank_validation.validation_status = validation_status
        log_name_bank_validation.reason = response_validate['reason']
        log_name_bank_validation.validated_name = response_validate['validated_name']
        if not log_name_bank_validation.validation_status_old:
            log_name_bank_validation.validated_name_old = self.name_bank_validation.validated_name
            log_name_bank_validation.account_number_old = self.name_bank_validation.account_number
            log_name_bank_validation.validation_status_old = (
                self.name_bank_validation.validation_status
            )
            log_name_bank_validation.reason_old = self.name_bank_validation.reason
        log_name_bank_validation.save(update_fields=fields_to_be_updated)


class DisbursementProcess(object):
    def __init__(self, disbursement):
        self.disbursement = disbursement

    def disburse(self):
        disbursement = self.disbursement
        disbursement.refresh_from_db()

        if disbursement.disburse_status in DisbursementStatus.SKIPPED_STATUSES:
            logger.warn({
                'function': 'DisbursementProcess -> disburse()',
                'status': 'disbursement skiped',
                'disbursement_id': disbursement.id,
                'disbursement_status': disbursement.disburse_status
            })
            return True
        service = get_service(disbursement.method)
        reason, is_balance_sufficient = service.check_balance(disbursement.amount)

        if not is_balance_sufficient:
            update_fields = ['disburse_status', 'reason']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = reason
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)
            return True

        response_disburse = service.disburse(disbursement)
        update_fields = ['disburse_status', 'disburse_id', 'reason', 'reference_id']
        disbursement.disburse_status = response_disburse['status']
        disbursement.disburse_id = response_disburse['id']
        disbursement.reason = response_disburse['reason']
        disbursement.reference_id = response_disburse.get('reference_id')
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        create_disbursement_new_flow_history(disbursement)

        return True

    def is_pending(self):
        if self.disbursement.disburse_status == DisbursementStatus.PENDING:
            return True
        return False

    def is_success(self):
        if self.disbursement.disburse_status == DisbursementStatus.COMPLETED:
            return True
        return False

    def is_failed(self):
        if self.disbursement.disburse_status == DisbursementStatus.FAILED:
            return True
        return False

    def change_method(self, method):
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        if disbursement.disburse_status in DisbursementStatus.SKIPPED_STATUSES:
            raise DisbursementServiceError(
                'Cannot change method PENDING/COMPLETED disbursement')
        disbursement.method = method
        disbursement.save(update_fields=['method'])
        disbursement.create_history('update_method', ['method'])

    def update_status(self, data):
        disbursement = self.disbursement
        service = get_service(disbursement.method)
        response_update_disbursement = service.process_callback_disbursement(data)
        disbursement.disburse_status = response_update_disbursement['status']
        disbursement.reason = response_update_disbursement['reason']
        disbursement.save(update_fields=['disburse_status', 'reason'])
        disbursement.create_history('update_status', ['disburse_status'])
        if not isinstance(service, AyoconnectService):
            create_disbursement_new_flow_history(disbursement)
        else:
            create_disbursement_history_ayoconnect(disbursement)

    def update_fields(self, fields, values):
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        for idx in range(len(fields)):
            setattr(disbursement, fields[idx], values[idx])
        disbursement.save(update_fields=fields)
        disbursement.create_history('update_fields', fields)
        return True

    def get_id(self):
        return self.disbursement.id

    def get_data(self):
        disbursement = self.disbursement
        bank_code = disbursement.name_bank_validation.bank_code
        if disbursement.method not in {
            DisbursementVendors.BCA,
            DisbursementVendors.AYOCONNECT,
            DisbursementVendors.PG,
        }:
            if (
                disbursement.name_bank_validation.method
                == NameBankValidationVendors.PAYMENT_GATEWAY
            ):
                bank_entry = BankManager.get_by_all_bank_code_or_none(
                    disbursement.name_bank_validation.bank_code
                )
            else:
                bank_entry = BankManager.get_by_method_bank_code(
                    disbursement.name_bank_validation.bank_code
                )
            bank_code = getattr(bank_entry, '{}_bank_code'.format(disbursement.method.lower()))
        elif disbursement.method == DisbursementVendors.AYOCONNECT:
            bank_account_dest = BankAccountDestination.objects.filter(
                name_bank_validation=disbursement.name_bank_validation
            ).last()
            if bank_account_dest and bank_account_dest.bank:
                payment_gateway_bank_code = PaymentGatewayBankCode.objects.filter(
                    bank_id=bank_account_dest.bank.id,
                    is_active=True,
                    payment_gateway_vendor__name=PaymentGatewayVendorConst.AYOCONNECT,
                ).last()
                if payment_gateway_bank_code:
                    bank_code = payment_gateway_bank_code.swift_bank_code
        elif disbursement.method == DisbursementVendors.PG:
            if hasattr(self, 'loan'):
                if self.loan.product.product_line_id in [
                    ProductLineCodes.J1,
                    ProductLineCodes.JTURBO,
                ]:
                    bank_account_dest = BankAccountDestination.objects.filter(
                        name_bank_validation=disbursement.name_bank_validation
                    ).last()
                    if bank_account_dest and bank_account_dest.bank:
                        bank_code = bank_account_dest.bank.bank_code
                if self.loan.product.product_line_id in [
                    ProductLineCodes.GRAB,
                ]:
                    bank_entry = BankManager.get_by_id_or_none(
                        disbursement.name_bank_validation.bank_id
                    )
                    if bank_entry:
                        bank_code = bank_entry.bank_code

        disbursement_data = dict()
        disbursement_data['id'] = disbursement.id
        disbursement_data['name_bank_validation_id'] = disbursement.name_bank_validation_id
        disbursement_data['external_id'] = disbursement.external_id
        disbursement_data['method'] = disbursement.method
        disbursement_data['amount'] = disbursement.amount
        disbursement_data['disburse_id'] = disbursement.disburse_id
        disbursement_data['disburse_status'] = disbursement.disburse_status
        disbursement_data['retry_times'] = disbursement.retry_times
        disbursement_data['reason'] = disbursement.reason
        disbursement_data['bank_info'] = {
            'bank_code': bank_code,
            'account_number': disbursement.name_bank_validation.account_number,
            'validated_name': disbursement.name_bank_validation.validated_name
        }
        return disbursement_data

    def is_valid_method(self, method):
        if method == self.disbursement.method:
            return True
        return False

    def get_method(self):
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        return disbursement.method

    def get_type(self):
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        return disbursement.disbursement_type

    def change_method_for_xendit_step_two(self):
        disbursement = self.disbursement
        disbursement.method = DisbursementVendors.XENDIT
        disbursement.step = XenditDisbursementStep.SECOND_STEP
        disbursement.retry_times = 0
        update_fields = ['method', 'step', 'retry_times']
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_method_xendit_experiment', update_fields)


class NewXfersDisbursementProcess(DisbursementProcess):
    """new class to handle new xfers disbursement flow"""

    def disburse(self):
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        service = get_xfers_service(disbursement)
        reason, is_balance_sufficient = service.check_balance(disbursement)
        request_time = timezone.localtime(timezone.now())

        if not is_balance_sufficient:
            update_fields = ['disburse_status', 'reason', 'step']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = reason
            disbursement.step = service.get_step()
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)
            return True

        response_disburse = service.disburse(disbursement)
        update_fields = ['disburse_status', 'disburse_id', 'reason', 'reference_id', 'step']
        disbursement.disburse_status = response_disburse['status']
        disbursement.disburse_id = response_disburse['id']
        disbursement.reason = response_disburse['reason']
        disbursement.reference_id = response_disburse.get('reference_id')
        disbursement.step = service.get_step()
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        disbursement.request_ts = request_time
        disbursement.response_ts = response_disburse['response_time']
        create_disbursement_new_flow_history(disbursement)

        return True


class XenditDisbursementProcess(DisbursementProcess):
    def disburse(self):
        # always step 2 for now
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        xendit_service = XenditService()

        reason, is_balance_sufficient = xendit_service.check_balance(disbursement.amount)

        if not is_balance_sufficient:
            update_fields = ['disburse_status', 'reason']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = reason
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)
            return True

        request_time = timezone.localtime(timezone.now())
        response_disburse = xendit_service.disburse(disbursement)
        update_fields = ['disburse_status', 'reference_id', 'reason', 'reference_id', 'disburse_id']
        disbursement.reference_id = response_disburse.get('id')
        disbursement.disburse_id = response_disburse['external_id']
        disbursement.disburse_status = response_disburse['status']
        disbursement.reason = response_disburse['reason']
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        disbursement.request_ts = request_time
        disbursement.response_ts = response_disburse['response_time']
        create_disbursement_new_flow_history(disbursement)


class AyoconnectDisbursementProcess(DisbursementProcess):
    def __init__(self, disbursement):
        self.disbursement = disbursement
        self.disbursement.refresh_from_db()
        self.loan = Loan.objects.get_or_none(loan_xid=disbursement.external_id)

    def disburse(self):
        loan = self.loan
        if not loan:
            raise DisbursementServiceError('loan not found')

        if loan.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]:
            return self.disburse_j1()

        return self.disburse_grab()

    def parse_reason_disburse_failed(self, response_disburse):
        try:
            reason_string = response_disburse['reason'].split("Failed create disbursement, ")[1]
            reason_dict = ast.literal_eval(reason_string)
            return reason_dict
        except (ValueError, IndexError, AttributeError, KeyError, SyntaxError):
            return None

    def is_can_be_ignored(self, reason_disburse):
        if not reason_disburse:
            return False

        for field in {"error", "status_code"}:
            if field not in reason_disburse:
                return False

        if "errors" not in reason_disburse["error"]:
            return False

        for error in reason_disburse["error"]["errors"]:
            if error["code"] == "0325" and \
               reason_disburse["status_code"] == HTTPStatus.PRECONDITION_FAILED:
                return True
        return False

    def disburse_grab(self):
        from juloserver.grab.segmented_tasks.disbursement_tasks import (
            trigger_create_or_update_ayoconnect_beneficiary,
        )
        from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
        from juloserver.loan.tasks import ayoconnect_loan_disbursement_retry

        # always step 2 for now
        disbursement = self.disbursement
        disbursement.refresh_from_db()
        ayo_service = AyoconnectService()

        loan = self.loan
        loan.refresh_from_db()
        is_beneficiary_exist, beneficiary_status = ayo_service.check_beneficiary(
            loan.customer_id, loan
        )

        if not is_beneficiary_exist or beneficiary_status == AyoconnectBeneficiaryStatus.DISABLED:
            update_fields = ['reason']
            disbursement.reason = AyoconnectErrorReason.ERROR_BENEFICIARY_MISSING_OR_DISABLED
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_history_ayoconnect(disbursement)
            trigger_create_or_update_ayoconnect_beneficiary.delay(loan.customer_id)
            return False

        if beneficiary_status == AyoconnectBeneficiaryStatus.INACTIVE:
            update_fields = ['reason']
            disbursement.reason = AyoconnectErrorReason.ERROR_BENEFICIARY_INACTIVE
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_history_ayoconnect(disbursement)
            trigger_create_or_update_ayoconnect_beneficiary.delay(loan.customer_id)
            return False

        if beneficiary_status == AyoconnectBeneficiaryStatus.BLOCKED:
            update_fields = ['disburse_status', 'reason', 'retry_times']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = AyoconnectErrorReason.ERROR_BENEFICIARY_BLOCKED
            disbursement.retry_times += 3
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_history_ayoconnect(disbursement)

            loan.refresh_from_db()
            update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
                change_reason=AyoconnectErrorReason.ERROR_BENEFICIARY_BLOCKED
            )
            ayoconnect_loan_disbursement_retry(loan_id=loan.id, max_retries=3)
            return False

        request_time = timezone.localtime(timezone.now())
        # the retry is for retry get token
        if disbursement.disburse_status == DisbursementStatus.INITIATED:
            create_disbursement_history_ayoconnect(disbursement)

        response_disburse = ayo_service.disburse(disbursement, n_retry=3)

        # if status code 412 and error code is 0325, we will ignore it.
        reason_disburse = self.parse_reason_disburse_failed(response_disburse)
        if self.is_can_be_ignored(reason_disburse):
            disbursement.reason = response_disburse.get('reason')
            disbursement.save()
            return True

        if response_disburse.get('reason') == AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE:
            self.system_undermaintenance_flow(disbursement, loan, response_disburse.get('reason'))
            return False

        update_fields = ['disburse_status', 'reference_id', 'reason', 'reference_id', 'disburse_id']
        disbursement.reference_id = response_disburse.get('refference_id')
        disbursement.disburse_id = response_disburse.get('id')
        disbursement.disburse_status = response_disburse.get('status')
        disbursement.reason = response_disburse.get('reason')
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        disbursement.request_ts = request_time
        disbursement.response_ts = response_disburse.get('response_time')
        create_disbursement_history_ayoconnect(disbursement)
        return True

    def get_beneficiary_j1(self):
        disbursement = self.disbursement
        loan = self.loan
        customer = loan.customer
        ayo_service = AyoconnectService()

        name_bank_validation = disbursement.name_bank_validation
        bank_account_dest = BankAccountDestination.objects.filter(
            name_bank_validation=name_bank_validation
        ).last()

        ayo_bank = None
        if bank_account_dest:
            ayo_bank = ayo_service.get_payment_gateway_bank(bank_id=bank_account_dest.bank_id)

        if not ayo_bank:
            logger.info({
                "action": "get_beneficiary_j1",
                "name_bank_validation_id": name_bank_validation.id,
                "bank_account_dest": bank_account_dest,
                "message": "ayoconnect payment_gateway_bank not found"
            })
            return None, None

        beneficiary_id, beneficiary_status = ayo_service.get_beneficiary_id_and_status(
            customer_id=loan.customer_id,
            phone_number=customer.phone,
            account_number=name_bank_validation.account_number,
            swift_bank_code=ayo_bank.swift_bank_code,
        )

        # if beneficiary doesn't exist, create new beneficiary
        # (not created yet, or user update phone number, or disburse to different account number)
        # if disburse failed because got unsuccessful callback or API error, recreate beneficiary
        if not beneficiary_id or (
            beneficiary_id
            and beneficiary_status in AyoconnectBeneficiaryStatus.J1_RETRY_ADD_BENEFICIARY_STATUS
            and disbursement.reason in AyoconnectErrorCodes.J1_RECREATE_BEN_IDS
        ):
            try:
                ayo_service.create_or_update_beneficiary(
                    customer_id=customer.id,
                    application_id=(
                        loan.application_id if loan.application_id else loan.application_id2
                    ),
                    account_number=name_bank_validation.account_number,
                    swift_bank_code=ayo_bank.swift_bank_code,
                    new_phone_number=customer.phone,
                    old_phone_number=customer.phone,
                    is_without_retry=True,
                    is_j1=True
                )
                beneficiary_id, beneficiary_status = ayo_service.get_beneficiary_id_and_status(
                    customer_id=loan.customer_id,
                    phone_number=customer.phone,
                    account_number=name_bank_validation.account_number,
                    swift_bank_code=ayo_bank.swift_bank_code,
                )
                pg_customer_data_loan, _ = PaymentGatewayCustomerDataLoan.objects.get_or_create(
                    beneficiary_id=beneficiary_id,
                    loan_id=loan.id,
                    disbursement_id=disbursement.id,
                )

                # pg_customer_data_loan maybe exists before in case unsuccessful ben callback
                # during retry, we regenerate beneficiary id by calling API again
                # so, we need to update processed=False to trigger disburse task via callback
                if pg_customer_data_loan.processed:
                    pg_customer_data_loan.processed = False
                    pg_customer_data_loan.save()

                return None, None
            except AyoconnectServiceForceSwitchToXfersError as error:
                raise error
            except AyoconnectServiceError as error:
                raise error

        if beneficiary_id:
            pg_customer_data_loan, status = PaymentGatewayCustomerDataLoan.objects.get_or_create(
                beneficiary_id=beneficiary_id,
                loan_id=loan.id,
                disbursement_id=disbursement.id,
            )
            if beneficiary_status == AyoconnectBeneficiaryStatus.ACTIVE:
                pg_customer_data_loan.processed = True
                pg_customer_data_loan.save()

        return beneficiary_id, beneficiary_status

    def disburse_j1(self):
        # For J1 Process, moved to task in case needed for retry
        disbursement = self.disbursement
        ayo_service = AyoconnectService()

        try:
            beneficiary_id, beneficiary_status = self.get_beneficiary_j1()
        except AyoconnectServiceForceSwitchToXfersError as err:
            update_fields = ['disburse_status', 'reason']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = err.error_code
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)

            logger.info(
                {
                    "action": "AyoconnectDisbursementProcess.disburse_j1",
                    "disbursement_id": disbursement.id,
                    "customer_id": self.loan.customer_id,
                    "errors": "Request to add beneficiary failed because {}".format(
                        disbursement.reason
                    ),
                }
            )
            return False
        except AyoconnectServiceError as err:
            # request to add beneficiary failed -> will retry
            update_fields = ['disburse_status', 'reason']
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = AyoconnectErrorCodes.GENERAL_FAILED_ADD_BENEFICIARY
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)

            logger.info({
                "action": "AyoconnectDisbursementProcess.disburse_j1",
                "disbursement_id": disbursement.id,
                "customer_id": self.loan.customer_id,
                "errors": "Request to add beneficiary failed because {}".format(err)
            })
            return False

        if not beneficiary_id or beneficiary_status == AyoconnectBeneficiaryStatus.INACTIVE:
            # beneficiary_id is none -> it means the id has just been created
            # or beneficiary_id is not none, but status still inactive.
            # => break the function to waiting for call back to activate the id
            update_fields = ['disburse_status', 'reason']
            disbursement.disburse_status = DisbursementStatus.INITIATED
            disbursement.reason = 'Create new beneficiary id'
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)
            logger.info({
                "action": "AyoconnectDisbursementProcess.disburse_j1",
                "disbursement_id": disbursement.id,
                "customer_id": self.loan.customer_id,
                "beneficiary_id": beneficiary_id,
                "errors": "Beneficiary id has just been created, waiting for the callback"
            })
            return False

        if beneficiary_status in AyoconnectBeneficiaryStatus.J1_RETRY_ADD_BENEFICIARY_STATUS:
            # avoid use not active ben_id to disburse -> will retry
            update_fields = ['disburse_status', 'reason']
            disbursement.disburse_status = DisbursementStatus.FAILED
            # reason was updated when unsuccessful ben id callback, so don't re-update in case
            # J1_FORCE_SWITCH_TO_XFERS to use Xfers in next retry instead of re-creating ben id
            if disbursement.reason not in AyoconnectErrorCodes.force_switch_to_xfers_error_codes():
                disbursement.reason = AyoconnectErrorCodes.GENERAL_FAILED_ADD_BENEFICIARY
            disbursement.save(update_fields=update_fields)
            disbursement.create_history('update_status', update_fields)
            create_disbursement_new_flow_history(disbursement)

            logger.info({
                "action": "AyoconnectDisbursementProcess.disburse_j1",
                "disbursement_id": disbursement.id,
                "customer_id": self.loan.customer_id,
                "beneficiary_id": beneficiary_id,
                "beneficiary_status": beneficiary_status,
                "errors": "Beneficiary id status is {}".format(beneficiary_status)
            })
            return False

        request_time = timezone.localtime(timezone.now())
        response_disburse = ayo_service.disburse(disbursement, beneficiary_id)
        update_fields = [
            'disburse_status', 'reason', 'reference_id', 'disburse_id'
        ]
        disbursement.reference_id = response_disburse.get('refference_id')
        disbursement.disburse_id = response_disburse.get('id')
        disbursement.disburse_status = response_disburse.get('status')
        disbursement.reason = response_disburse.get('reason')

        # For J1 & Turbo flow, if there is any error that needs to retry during disbursement API,
        # change disbursement.status to FAILED, and will check retry by disbursement.reason
        error_code = response_disburse.get('error_code')
        if error_code and error_code in AyoconnectErrorCodes.all_existing_error_codes():
            disbursement.disburse_status = DisbursementStatus.FAILED
            disbursement.reason = error_code

        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        disbursement.request_ts = request_time
        disbursement.response_ts = response_disburse.get('response_time')
        create_disbursement_new_flow_history(disbursement)

        logger.info({
            "action": "AyoconnectDisbursementProcess.disburse_j1",
            "disbursement_id": disbursement.id,
            "disbursement_status": disbursement.disburse_status,
            "message": "Disbursement success with status {}".format(disbursement.disburse_status)
        })
        return True

    def system_undermaintenance_flow(self, disbursement, loan, reason):
        from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
        from juloserver.loan.tasks import ayoconnect_loan_disbursement_retry

        update_fields = ['disburse_status', 'reason']
        disbursement.disburse_status = DisbursementStatus.FAILED
        disbursement.reason = reason
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        create_disbursement_history_ayoconnect(disbursement)

        loan.refresh_from_db()
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
            change_reason=AyoconnectErrorReason.SYSTEM_UNDER_MAINTENANCE
        )
        # for GRAB, we use dynamic feature setting
        max_retries = AyoconnectConst.MAX_FAILED_RETRIES
        grab_disbursement_retry_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.GRAB_DISBURSEMENT_RETRY, is_active=True
        ).last()
        if grab_disbursement_retry_feature_setting:
            parameter = grab_disbursement_retry_feature_setting.parameters
            max_retries = parameter.get('max_retry_times', max_retries)
        ayoconnect_loan_disbursement_retry(loan_id=loan.id, max_retries=max_retries)


class PaymentGatewayDisbursementProcess(DisbursementProcess):
    def __init__(self, disbursement):
        self.disbursement = disbursement
        self.disbursement.refresh_from_db()
        self.loan = Loan.objects.get_or_none(loan_xid=disbursement.external_id)

    def initiate_payment_gateway_service(self, client_id, api_key):
        return PaymentGatewayService(client_id, api_key)

    def disburse(self):
        loan = self.loan
        if not loan:
            raise DisbursementServiceError('loan not found')

        if loan.product.product_line_id in [ProductLineCodes.J1, ProductLineCodes.JTURBO]:
            return self.disburse_j1()
        elif loan.product.product_line_id in [ProductLineCodes.GRAB]:
            return self.disburse_grab()

    def disburse_j1(self):
        # For J1 Process, moved to task in case needed for retry
        disbursement = self.disbursement

        payment_gateway_service = self.initiate_payment_gateway_service(
            client_id=settings.PG_LOAN_CLIENT_ID,
            api_key=settings.PG_LOAN_API_KEY,
        )

        request_time = timezone.localtime(timezone.now())
        response_disburse = payment_gateway_service.disburse(disbursement)
        update_fields = ['disburse_status', 'reason', 'disburse_id']
        disbursement.disburse_id = response_disburse.get('id')
        disbursement.disburse_status = response_disburse.get('status')
        disbursement.reason = response_disburse.get('reason')

        # For J1 & Turbo flow, if there is any error that needs to retry during disbursement API,
        # change disbursement.status to FAILED, and will check retry by disbursement.reason

        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        disbursement.request_ts = request_time
        disbursement.response_ts = response_disburse.get('response_time')
        create_disbursement_new_flow_history(disbursement)

        logger.info(
            {
                "action": "PaymentGatewayDisbursementProcess.disburse_j1",
                "disbursement_id": disbursement.id,
                "disbursement_status": disbursement.disburse_status,
                "message": "Disbursement trigger success with status {}".format(
                    disbursement.disburse_status
                ),
            }
        )
        return True

    def is_grab_loan(self, disbursement_external_id):
        try:
            loan = Loan.objects.get(loan_xid=disbursement_external_id)
            return loan.product.product_line_id == ProductLineCodes.GRAB
        except Loan.DoesNotExist:
            return False

    def update_status(self, data):
        disbursement = self.disbursement
        is_grab_loan = self.is_grab_loan(disbursement.external_id)
        service = get_service(disbursement.method, is_grab=is_grab_loan)
        response_update_disbursement = service.process_callback_disbursement(data)
        disbursement.disburse_status = response_update_disbursement['status']
        disbursement.reason = response_update_disbursement['reason']
        disbursement.save(update_fields=['disburse_status', 'reason'])
        disbursement.create_history('update_status', ['disburse_status'])
        create_disbursement_history_new_payment_gateway(disbursement)

    def disburse_grab(self):
        disbursement = self.disbursement
        disbursement.refresh_from_db()

        payment_gateway_service = self.initiate_payment_gateway_service(
            client_id=settings.PG_GRAB_CLIENT_ID,
            api_key=settings.PG_GRAB_API_KEY,
        )

        loan = self.loan
        loan.refresh_from_db()

        request_time = timezone.localtime(timezone.now())

        if disbursement.disburse_status == DisbursementStatus.INITIATED:
            create_disbursement_new_flow_history(disbursement=disbursement)

        response_disburse = payment_gateway_service.disburse(disbursement)

        update_fields = ['disburse_status', 'reason', 'disburse_id']
        disbursement.disburse_id = response_disburse.get('id')
        disbursement.disburse_status = response_disburse.get('status')
        disbursement.reason = response_disburse.get('reason')
        disbursement.save(update_fields=update_fields)
        disbursement.create_history('update_status', update_fields)
        disbursement.request_ts = request_time
        disbursement.response_ts = response_disburse.get('response_time')
        create_disbursement_new_flow_history(disbursement)

        logger.info(
            {
                "action": "PaymentGatewayDisbursementProcess.disburse_grab",
                "disbursement_id": disbursement.id,
                "disbursement_status": disbursement.disburse_status,
                "message": "Disbursement trigger success with status {}".format(
                    disbursement.disburse_status
                ),
            }
        )
        return True


def get_disbursement_process_by_transaction_id(transaction_id):
    disbursement = Disbursement.objects.filter(disburse_id=transaction_id).order_by('cdate').last()
    if not disbursement:
        raise DisbursementServiceError('disbursement process not found')
    return get_disbursement_by_obj(disbursement)
