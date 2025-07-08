import json
import datetime
import functools
import logging
import time
import re
from functools import wraps, partial
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from rest_framework import exceptions, status
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.standardized_api_response.utils import (
    general_error_response, forbidden_error_response, unauthorized_error_response,
    too_many_requests_response)
from juloserver.julo.models import Application, Loan, Image, FeatureSetting, Customer
from juloserver.partnership.constants import (
    ErrorMessageConst,
    MERCHANT_FINANCING_PREFIX,
    WHITELABEL_PAYLATER_REGEX,
    PartnershipRedisPrefixKey,
    PAYLATER_REGEX
)
from juloserver.julo.services2.encryption import Encryption
from juloserver.pin.constants import VerifyPinMsg, ReturnCode
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
import juloserver.pin.services as pin_services
from juloserver.partnership.models import (
    CustomerPinVerify,
    CustomerPinVerifyHistory, CustomerPin, PartnershipConfig,
    PartnerLoanRequest, PaylaterTransaction
)
from juloserver.partnership.security import get_decrypted_data_whitelabel
from juloserver.julo.utils import format_nexmo_voice_phone_number, format_mobile_phone
from rest_framework.response import Response
from juloserver.julo.models import PartnerProperty
from juloserver.merchant_financing.models import Merchant
from juloserver.partnership.services.services import (is_valid_data)
from juloserver.partnership.utils import (
    verify_webview_pin,
    partnership_detokenize_sync_object_model,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.cache import RedisCache
from juloserver.partnership.models import PartnershipCustomerData
from juloserver.partnership.serializers import WebviewLoginSerializer
from juloserver.pin.utils import transform_error_msg
from juloserver.pii_vault.constants import PiiSource


logger = logging.getLogger(__name__)


try:
    from decorator import decorator
except ImportError:
    def decorator(caller):
        """ Turns caller into a decorator.
        Unlike decorator module, function signature is not preserved.
        :param caller: caller(f, *args, **kwargs)
        """
        def decor(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return caller(f, *args, **kwargs)
            return wrapper
        return decor


def __retry_internal(f, exceptions=Exception, tries=-1, delay=0, backoff=1, logger=logger):
    """
    Executes a function and retries it if it failed.
    :param f: the function to execute.
    :param exceptions: an exception or a tuple of exceptions to catch. default: Exception.
    :param tries: the maximum number of attempts. default: -1 (infinite).
    :param delay: initial delay between attempts. default: 0.
    :param backoff: multiplier applied to delay between attempts. default: 1 (no backoff).
    :param logger: logger.warning(fmt, error, delay) will be called on failed attempts.
                   default: retry.logging_logger. if None, logging is disabled.
    :returns: the result of the f function.
    """
    _tries, _delay = tries, delay
    while _tries:
        try:
            return f()
        except exceptions as e:
            _tries -= 1
            if not _tries:
                raise

            if logger is not None:
                logger.warning('{} retrying in {} seconds...'.format(e, _delay))

            time.sleep(_delay)
            _delay *= backoff


def retry(exceptions=Exception, tries=-1, delay=0, backoff=1, logger=logger):
    """Returns a retry decorator.
    :param exceptions: an exception or a tuple of exceptions to catch. default: Exception.
    :param tries: the maximum number of attempts. default: -1 (infinite).
    :param delay: initial delay between attempts. default: 0.
    :param backoff: multiplier applied to delay between attempts. default: 1 (no backoff).
    :param logger: logger.warning(fmt, error, delay) will be called on failed attempts.
                   default: retry.logging_logger. if None, logging is disabled.
    :returns: a retry decorator.
    """

    @decorator
    def retry_decorator(f, *fargs, **fkwargs):
        args = fargs if fargs else list()
        kwargs = fkwargs if fkwargs else dict()
        return __retry_internal(partial(f, *args, **kwargs),
                                exceptions, tries, delay, backoff, logger)

    return retry_decorator


def check_application(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('user not found')

        application_xid = kwargs.get('application_xid') or request.GET.get('application_xid')
        if not str(application_xid).isdigit():
            return general_error_response(
                'application_xid {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        application = Application.objects.filter(application_xid=application_xid).last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))
        skip_application_partner_check = False
        request_paylater_transaction_xid = request.GET.get('paylater_transaction_xid')
        if not request_paylater_transaction_xid:
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PARTNER_ELIGIBLE_USE_J1,
                is_active=True
            ).last()
            if feature_setting and request.user.partner.name in \
                    feature_setting.parameters['partners'].keys():
                feature_status = \
                    feature_setting.parameters['partners'][request.user.partner.name]['is_active']
                if feature_status:
                    skip_application_partner_check = True
                    account = application.account
                    if not account:
                        return general_error_response('Akun {}'.format(
                            ErrorMessageConst.NOT_FOUND))
                    if not PartnerProperty.objects.filter(
                        partner=request.user.partner, account=account, is_active=True
                    ).exists():
                        return general_error_response(ErrorMessageConst.ACCOUNT_NOT_LINKED)
        raw_data = request.body
        if raw_data:
            try:
                data = json.loads(raw_data)
                if data and 'paylater_transaction_xid' in data:
                    paylater_transaction_xid = data['paylater_transaction_xid']
                else:
                    paylater_transaction_xid = request_paylater_transaction_xid
            except (json.JSONDecodeError, UnicodeDecodeError):
                paylater_transaction_xid = request_paylater_transaction_xid
                pass
        else:
            paylater_transaction_xid = request_paylater_transaction_xid

        if not skip_application_partner_check and not paylater_transaction_xid:
            if application.partner != request.user.partner:
                return forbidden_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        return function(view, request, *args, **kwargs)

    return wrapper


def check_loan(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        paylater_transaction_xid = request.GET.get('paylater_transaction_xid', None)
        paylater_transaction = None
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('User tidak ditemukan')

        loan_xid = kwargs.get('loan_xid') or request.data.get('loan_xid')
        if not loan_xid:
            return general_error_response('Loan_xid {}'.format(ErrorMessageConst.REQUIRED))
        if not str(loan_xid).isdigit():
            return general_error_response('Loan_xid {}'.format(ErrorMessageConst.INVALID_DATA))
        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        if not loan or not loan.account:
            return general_error_response('Loan tidak ditemukan')
        skip_application_partner_check = False
        feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PARTNER_ELIGIBLE_USE_J1,
            is_active=True
        ).last()
        if paylater_transaction_xid and str(paylater_transaction_xid).isdigit():
            paylater_transaction = PaylaterTransaction.objects.filter(
                paylater_transaction_xid=paylater_transaction_xid
            ).last()
        if feature_setting and request.user.partner.name in \
                feature_setting.parameters['partners'].keys():
            feature_status = \
                feature_setting.parameters['partners'][request.user.partner.name]['is_active']
            if feature_status:
                skip_application_partner_check = True
                account = loan.account
                if not account:
                    return general_error_response('Akun {}'.format(
                        ErrorMessageConst.NOT_FOUND))
                if not PartnerProperty.objects.filter(
                    partner=request.user.partner, account=account, is_active=True
                ).exists():
                    if not paylater_transaction:
                        return general_error_response(ErrorMessageConst.ACCOUNT_NOT_LINKED)
        application = loan.account.last_application
        if not skip_application_partner_check:
            if not application or application.partner != request.user.partner:
                return forbidden_error_response('Loan tidak ditemukan')
        else:
            if not PartnerLoanRequest.objects.filter(
                    loan=loan,
                    partner=request.user.partner
            ).exists():
                if not paylater_transaction:
                    return forbidden_error_response('Loan tidak ditemukan')

        return function(view, request, *args, **kwargs)

    return wrapper


def check_image(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('User tidak ditemukan')

        encrypt = Encryption()
        decrypted_image_id = encrypt.decode_string(kwargs['encrypted_image_id'])
        if not decrypted_image_id:
            return general_error_response('Image URL tidak valid')
        image = Image.objects.filter(pk=int(decrypted_image_id)).last()
        if not image:
            return general_error_response('Image tidak ditemukan')

        image_source = image.image_source
        application = None
        if 2000000000 < image_source < 2999999999:
            application = Application.objects.filter(pk=image_source).last()
        elif 3000000000 < image_source < 3999999999:
            loan = Loan.objects.filter(pk=image_source).last()
            if loan and loan.account:
                application = loan.account.last_application
        if not application or application.partner != request.user.partner:
            return forbidden_error_response('Image tidak ditemukan')

        return function(view, request, *args, **kwargs)

    return wrapper


def verify_pin(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        view_name = view.__class__.__name__
        encrypt = Encryption()
        xid = request.data.get('xid', None)
        android_id = None
        if not xid or xid is None:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))
        decoded_app_xid = encrypt.decode_string(xid)
        if decoded_app_xid and \
                decoded_app_xid[:len(MERCHANT_FINANCING_PREFIX)] == MERCHANT_FINANCING_PREFIX:
            decoded_app_xid = int(decoded_app_xid[len(MERCHANT_FINANCING_PREFIX):])
        application = Application.objects.filter(application_xid=decoded_app_xid).last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        user = application.customer.user

        if not user:
            return general_error_response(VerifyPinMsg.USER_NOT_FOUND)

        pin = request.data.get('pin')
        if not pin:
            return general_error_response(VerifyPinMsg.REQUIRED_PIN)

        customer_pin = CustomerPin.objects.filter(user=user).last()
        if not customer_pin:
            return general_error_response('pin not created')
        customer_pin_verify_data = CustomerPinVerify.objects.get_or_none(customer_pin=customer_pin)
        if customer_pin_verify_data:
            customer_pin_verify_data.update_safely(is_pin_used=True)

        pin_process = pin_services.VerifyPinProcess()
        code, msg, _ = pin_process.verify_pin_process(
            view_name=view_name, user=user, pin_code=pin, android_id=android_id
        )
        if code != ReturnCode.OK:
            if code == ReturnCode.LOCKED:
                return forbidden_error_response(msg)
            elif code == ReturnCode.FAILED:
                return unauthorized_error_response(msg)
            return general_error_response(msg)
        with transaction.atomic():
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PARTNER_PIN_EXPIRY_TIME,
                is_active=True
            ).last()
            current_time = timezone.localtime(timezone.now())
            if feature_setting:
                partner_pin_expiry_time = feature_setting.parameters['partner_pin_expiry_time']
                expiry_time = current_time + timedelta(seconds=partner_pin_expiry_time)
            else:
                expiry_time = current_time + timedelta(seconds=300)
            if not customer_pin_verify_data:
                customer_pin_verify_data = CustomerPinVerify.objects.create(
                    customer=application.customer,
                    is_pin_used=False,
                    customer_pin=customer_pin,
                    expiry_time=expiry_time
                )
            else:
                customer_pin_verify_data.update_safely(is_pin_used=False, expiry_time=expiry_time)

            customer_pin_verify_history_data = dict(customer_pin_verify=customer_pin_verify_data,
                                                    is_pin_used=False,
                                                    expiry_time=expiry_time)

            CustomerPinVerifyHistory.objects.create(**customer_pin_verify_history_data)

        return function(view, request, *args, **kwargs)

    return wrapper


def check_pin_used_status(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        application_xid = kwargs.get('application_xid') or request.data.get('application_xid')
        if not str(application_xid).isdigit():
            return general_error_response(
                'application_xid {}'.format(ErrorMessageConst.INVALID_DATA)
            )
        application = Application.objects.filter(application_xid=application_xid).last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))
        partnership_config = PartnershipConfig.objects.filter(
            partner=request.user.partner
        ).last()
        if not partnership_config.is_transaction_use_pin:
            return function(view, request, *args, **kwargs)
        customer = application.customer
        customer_pin_verify_data = CustomerPinVerify.objects.\
            get_or_none(customer=customer,
                        is_pin_used=False,
                        expiry_time__gte=timezone.now())
        if not customer_pin_verify_data:
            return general_error_response('Verifikasi PIN terlebih dahulu')

        return function(view, request, *args, **kwargs)

    return wrapper


def check_pin_created(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):

        app_xid = kwargs.get('application_xid') or request.GET.get('application_xid')
        if not str(app_xid).isdigit():
            return general_error_response(
                'application_xid {}'.format(ErrorMessageConst.INVALID_DATA)
            )

        application = Application.objects.filter(application_xid=app_xid).last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        user = application.customer.user
        customers_pin = CustomerPin.objects.filter(user=user)
        if not customers_pin:
            return general_error_response('Aplikasi belum memiliki PIN')

        return function(view, request, *args, **kwargs)

    return wrapper


def check_merchant_ownership(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        merchant_xid = kwargs.get('merchant_xid') or request.GET.get('merchant_xid')

        merchant = Merchant.objects.filter(merchant_xid=merchant_xid).last()
        if not merchant:
            return general_error_response('Merchant {}'.format(ErrorMessageConst.NOT_FOUND))

        if merchant.distributor.partner.user != user:
            return general_error_response('Merchant bukan milik partner')

        return function(view, request, *args, **kwargs)
    return wrapper


def get_verified_data_whitelabel(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        try:
            decrypted_data = get_decrypted_data_whitelabel(request)
            regex = WHITELABEL_PAYLATER_REGEX
            regex1 = PAYLATER_REGEX
            if not (re.fullmatch(regex, decrypted_data)) and \
                    not (re.fullmatch(regex1, decrypted_data)):
                raise exceptions.AuthenticationFailed('Forbidden request, invalid Key')

            email, phone, partner_name, partner_reference_id, \
                public_key, paylater_transaction_xid, \
                token_expiry_time, partner_customer_id, \
                email_phone_diff, partner_origin_name = re.split(r':', decrypted_data)
            kwargs['validated_email'] = email
            kwargs['validated_phone'] = phone
            kwargs['validated_partner_name'] = partner_name
            kwargs['validated_partner_reference_id'] = partner_reference_id
            kwargs['validated_paylater_transaction_xid'] = paylater_transaction_xid
            kwargs['validated_partner_customer_id'] = partner_customer_id
            kwargs['validated_email_phone_diff'] = email_phone_diff
            kwargs['validated_partner_origin_name'] = partner_origin_name
            current_time = int(time.time())
            if paylater_transaction_xid and current_time > int(token_expiry_time):
                raise exceptions.AuthenticationFailed('Coba Muat Ulang\nLink sudah kedaluwarsa, '
                                                      'silakan ulangi proses untuk melanjutkan')
        except exceptions.AuthenticationFailed as e:
            return general_error_response(str(e))

        return function(view, request, *args, **kwargs)
    return wrapper


def verify_pin_whitelabel(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        view_name = view.__class__.__name__
        android_id = None
        try:
            decrypted_data = get_decrypted_data_whitelabel(request)
            regex = WHITELABEL_PAYLATER_REGEX
            regex1 = PAYLATER_REGEX
            if not (re.fullmatch(regex, decrypted_data)) and \
                    not (re.fullmatch(regex1, decrypted_data)):
                raise exceptions.AuthenticationFailed('Forbidden request, invalid Key')

            email, phone, partner_name, partner_reference_id, \
                public_key, paylater_transaction_xid, \
                token_expiry_time, partner_customer_id, \
                email_phone_diff, partner_origin_name = re.split(r':', decrypted_data)
        except exceptions.AuthenticationFailed as e:
            return general_error_response(str(e))

        possible_phone_numbers = {
            format_mobile_phone(phone),
            format_nexmo_voice_phone_number(phone),
        }

        if not email_phone_diff:
            customer = (
                Customer.objects.filter(
                    email=email.lower(), phone__in=possible_phone_numbers
                )
                .select_related("user")
                .last()
            )

            if not customer:
                return general_error_response("Customer Not found for user")

            application = (
                Application.objects.select_related("customer", "customer__user")
                .filter(
                    customer=customer,
                    workflow__name=WorkflowConst.JULO_ONE,
                    mobile_phone_1__in=[
                        format_nexmo_voice_phone_number(phone),
                        format_mobile_phone(phone),
                    ],
                )
                .last()
            )

        else:
            customer = None
            if email_phone_diff == "email":
                customer = Customer.objects.filter(email=email.lower()).last()
            elif email_phone_diff == "phone":
                customer = Customer.objects.filter(
                    phone__in=possible_phone_numbers
                ).last()

            if not customer:
                return general_error_response("Customer Not found for user")

            application = customer.application_set.filter(
                workflow__name=WorkflowConst.JULO_ONE,
                product_line__product_line_code__in=ProductLineCodes.julo_one(),
                application_status_id=ApplicationStatusCodes.LOC_APPROVED,
            ).last()

        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))
        user = customer.user

        if not user:
            return general_error_response(VerifyPinMsg.USER_NOT_FOUND)

        pin = request.data.get('pin')
        if not pin:
            return general_error_response(VerifyPinMsg.REQUIRED_PIN)

        customer_pin = CustomerPin.objects.prefetch_related(
            'customerpinverify_set').filter(user=user).last()
        if not customer_pin:
            return general_error_response('pin not created')
        customer_pin_verify_data = customer_pin.customerpinverify_set.last()
        if customer_pin_verify_data:
            customer_pin_verify_data.update_safely(is_pin_used=True)

        pin_process = pin_services.VerifyPinProcess()
        code, msg, _ = pin_process.verify_pin_process(
            view_name=view_name, user=user, pin_code=pin, android_id=android_id
        )
        if msg == VerifyPinMsg.LOGIN_FAILED:
            msg = ErrorMessageConst.INCORRECT_PIN
        if code != ReturnCode.OK:
            if code == ReturnCode.LOCKED:
                return forbidden_error_response(msg)
            elif code == ReturnCode.FAILED:
                return unauthorized_error_response(msg)
            return general_error_response(msg)
        with transaction.atomic():
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PARTNER_PIN_EXPIRY_TIME,
                is_active=True
            ).last()
            current_time = timezone.localtime(timezone.now())
            if feature_setting:
                partner_pin_expiry_time = feature_setting.parameters['partner_pin_expiry_time']
                expiry_time = current_time + timedelta(seconds=partner_pin_expiry_time)
            else:
                expiry_time = current_time + timedelta(seconds=300)
            if not customer_pin_verify_data:
                customer_pin_verify_data = CustomerPinVerify.objects.create(
                    customer=application.customer,
                    is_pin_used=False,
                    customer_pin=customer_pin,
                    expiry_time=expiry_time
                )
            else:
                customer_pin_verify_data.update_safely(is_pin_used=False, expiry_time=expiry_time)

            customer_pin_verify_history_data = dict(customer_pin_verify=customer_pin_verify_data,
                                                    is_pin_used=False,
                                                    expiry_time=expiry_time)

            CustomerPinVerifyHistory.objects.create(**customer_pin_verify_history_data)

        return function(view, request, *args, **kwargs)
    return wrapper


def update_pin_response_400(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        return_value = function(view, request, *args, **kwargs)
        if type(return_value) == Response:
            if return_value.status_code == status.HTTP_401_UNAUTHORIZED:
                return_value.status_code = status.HTTP_400_BAD_REQUEST
        return return_value
    return wrapper


def verify_partner_pin(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        view_name = view.__class__.__name__
        pin = request.data.get('pin')
        android_id = None
        customer = Customer.objects.filter(user=request.user).last()
        if customer is None:
            return general_error_response('Customer {}'.format(ErrorMessageConst.NOT_FOUND))

        detokenize_customer = partnership_detokenize_sync_object_model(
            PiiSource.CUSTOMER,
            customer,
            customer.customer_xid,
            ['nik'],
        )

        nik = detokenize_customer.nik
        pin_error = verify_webview_pin(pin)
        if pin_error is not None:
            return general_error_response(pin_error)

        customer, customer_pin, error_msg = is_valid_data(nik, pin)
        if error_msg is not None:
            return general_error_response(error_msg)

        user = customer.user
        customer_pin_verify_data = CustomerPinVerify.objects.get_or_none(customer_pin=customer_pin)
        if customer_pin_verify_data:
            customer_pin_verify_data.update_safely(is_pin_used=True)

        pin_process = pin_services.VerifyPinProcess()
        code, msg, _ = pin_process.verify_pin_process(
            view_name=view_name, user=user, pin_code=pin, android_id=android_id
        )
        if code != ReturnCode.OK:
            if code == ReturnCode.LOCKED:
                return forbidden_error_response(msg)
            elif code == ReturnCode.FAILED:
                return unauthorized_error_response(msg)
            return general_error_response(msg)
        with transaction.atomic():
            feature_setting = FeatureSetting.objects.filter(
                feature_name=FeatureNameConst.PARTNER_PIN_EXPIRY_TIME,
                is_active=True
            ).last()
            current_time = timezone.localtime(timezone.now())
            if feature_setting:
                partner_pin_expiry_time = feature_setting.parameters['partner_pin_expiry_time']
                expiry_time = current_time + timedelta(seconds=partner_pin_expiry_time)
            else:
                expiry_time = current_time + timedelta(seconds=300)
            if not customer_pin_verify_data:
                customer_pin_verify_data = CustomerPinVerify.objects.create(
                    customer=customer,
                    is_pin_used=False,
                    customer_pin=customer_pin,
                    expiry_time=expiry_time
                )
            else:
                customer_pin_verify_data.update_safely(is_pin_used=False, expiry_time=expiry_time)

            customer_pin_verify_history_data = dict(customer_pin_verify=customer_pin_verify_data,
                                                    is_pin_used=False,
                                                    expiry_time=expiry_time)

            CustomerPinVerifyHistory.objects.create(**customer_pin_verify_history_data)

        return function(view, request, *args, **kwargs)

    return wrapper


def check_webview_pin_created(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'customer'):
            return general_error_response(VerifyPinMsg.USER_NOT_FOUND)

        application = Application.objects.filter(customer=request.user.customer).last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        if not application.is_julo_one() or \
                application.product_line_id != ProductLineCodes.J1:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        customers_pin = CustomerPin.objects.filter(user=user)
        if not customers_pin:
            return general_error_response('Aplikasi belum memiliki PIN')

        return function(view, request, *args, **kwargs)

    return wrapper


def count_request_on_redis(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        if 'GetPhoneNumberView' in request.resolver_match.view_name:
            session_id = request.data.get('sessionID') or request.GET.get('sessionID')
            if not session_id:
                return general_error_response('sessionID {}'.format(ErrorMessageConst.REQUIRED))
            redis_key = '%s_%s' % (
                PartnershipRedisPrefixKey.WEBVIEW_GET_PHONE_NUMBER, session_id)
        else:
            application_id = request.data.get('application_id')
            if not application_id:
                return general_error_response(
                    'Application_id {}'.format(ErrorMessageConst.REQUIRED)
                )
            redis_key = '%s_%s' % (
                PartnershipRedisPrefixKey.WEBVIEW_CREATE_LOAN, application_id)

        redis_cache = RedisCache(key=redis_key, hours=1)
        # Redis value for this key will be '{count};{date}'
        value = redis_cache.get()
        if not value:
            request_count = 0
        else:
            request_count = int(value.split(';')[0])
        if request_count > 2:
            string_datetime = value.split(';')[1]
            timestamp = datetime.datetime.strptime(string_datetime, '%Y-%m-%d %H:%M:%S')
            next_one_hour = timestamp + timedelta(hours=1)
            return too_many_requests_response('Terlalu banyak percobaan. Coba lagi pada: %s' %
                                              next_one_hour)
        return function(view, request, *args, **kwargs)
    return wrapper


def verify_webview_login_partnership(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        if not token:
            return unauthorized_error_response("Token {}".format(ErrorMessageConst.REQUIRED))
        serializer = WebviewLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        partnership_customer_data = PartnershipCustomerData.objects.filter(
            token=token,
            otp_status=PartnershipCustomerData.VERIFIED
        ).last()
        partnership_nik = partnership_customer_data.nik
        data = request.data
        nik = ''
        if 'nik' in data:
            nik = data['nik']
        if not nik:
            return unauthorized_error_response("Nik {}".format(ErrorMessageConst.REQUIRED))
        if nik and partnership_nik != nik:
            return unauthorized_error_response("Partnership Customer Data {}".format(
                ErrorMessageConst.NOT_FOUND))

        user = pin_services.get_user_from_username(nik)
        if not user or not hasattr(user, 'customer'):
            return general_error_response("NIK Anda tidak terdaftar")

        # PARTNER-1965: Blocked except Linkaja
        customer = user.customer
        if not customer.application_set.filter(partner__name=PartnerNameConstant.LINKAJA,
                                               partner__is_active=True).exists():
            return unauthorized_error_response(
                'Mohon untuk melanjutkan login pada apps JULO sesuai akun yang '
                'terdaftar. Mengalami kesulitan login? hubungi cs@julo.co.id'
            )

        return_value = function(view, request, *args, **kwargs)
        return return_value
    return wrapper


def check_webview_loan(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('User tidak ditemukan')

        loan_xid = kwargs.get('loan_xid') or request.data.get('loan_xid')
        if not loan_xid:
            return general_error_response('Loan_xid {}'.format(ErrorMessageConst.REQUIRED))
        if not str(loan_xid).isdigit():
            return general_error_response('Loan_xid {}'.format(ErrorMessageConst.INVALID_DATA))
        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        if not loan or not loan.customer:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        if user.id != loan.customer.user_id:
            return general_error_response(ErrorMessageConst.LOAN_NOT_FOUND)

        return function(view, request, *args, **kwargs)

    return wrapper


def check_webview_pin_used_status(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        token = request.META.get('HTTP_SECRET_KEY', b'')
        partnership_customer = PartnershipCustomerData.objects.filter(
            token=token,
            otp_status=PartnershipCustomerData.VERIFIED
        ).first()
        if not partnership_customer:
            return general_error_response('Partnership Customer Data {}'.format(
                ErrorMessageConst.NOT_FOUND))
        partnership_config = PartnershipConfig.objects.filter(
            partner=partnership_customer.partner
        ).last()
        if not partnership_config.is_transaction_use_pin:
            return function(view, request, *args, **kwargs)
        customer = partnership_customer.customer
        customer_pin_verify_data = CustomerPinVerify.objects.\
            get_or_none(customer=customer,
                        is_pin_used=False,
                        expiry_time__gte=timezone.now())
        if not customer_pin_verify_data:
            return general_error_response('Verifikasi PIN terlebih dahulu')

        return function(view, request, *args, **kwargs)
    return wrapper
