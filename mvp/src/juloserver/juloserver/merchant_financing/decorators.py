import json
from functools import wraps

from django.http import HttpRequest, HttpResponse

from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.standardized_api_response.utils import (
    general_error_response, unauthorized_error_response)
from juloserver.julo.models import (
    Application,
    Loan,
    FeatureSetting,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.partnership.constants import (
    ErrorMessageConst
)
from juloserver.partnership.constants import HTTPGeneralErrorMessage
from juloserver.partnership.models import PartnershipConfig, PartnershipUser
from juloserver.merchant_financing.api_response import error_response
from juloserver.merchant_financing.services import is_customer_pass_otp
from juloserver.merchant_financing.constants import (
    ErrorMessageConstant,
    MFStandardRole,
    MFFeatureSetting,
)
from juloserver.merchant_financing.web_app.constants import WebAppErrorMessage

from rest_framework import status
from typing import Callable, Any


def check_mf_loan(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        user = request.user if request.auth else kwargs.get('user')
        if not user:
            return unauthorized_error_response('User tidak ditemukan')

        loan_xid = request.GET.get('loan_xid')
        if not loan_xid:
            return general_error_response('Loan_xid {}'.format(ErrorMessageConst.REQUIRED))
        if not str(loan_xid).isdigit():
            return general_error_response('Loan_xid {}'.format(ErrorMessageConst.INVALID_DATA))
        loan = Loan.objects.filter(loan_xid=loan_xid).last()
        if not loan or not loan.account:
            return general_error_response(ErrorMessageConstant.LOAN_NOT_FOUND)

        application = loan.customer.application_set.last()
        if not application:
            return general_error_response(ErrorMessageConstant.LOAN_NOT_FOUND)

        if application.partner is None:
            return general_error_response(ErrorMessageConstant.LOAN_NOT_FOUND)

        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            application.partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )
        if detokenize_partner.name != request.META.get('HTTP_USERNAME', b''):
            return general_error_response(ErrorMessageConstant.LOAN_NOT_FOUND)

        if application.partner.token != request.META.get('HTTP_SECRET_KEY', b''):
            return general_error_response(ErrorMessageConstant.LOAN_NOT_FOUND)

        return function(view, request, *args, **kwargs)

    return wrapper


def check_valid_merchant_partner(function):
    @wraps(function)
    def wrapper(view, request, *args, **kwargs):
        application_xid = kwargs.get('application_xid') or request.data.get('application_xid')
        if not str(application_xid).isdigit():
            return general_error_response(
                'application_xid {}'.format(ErrorMessageConst.INVALID_DATA)
            )

        application = Application.objects.filter(
            application_xid=application_xid).only('partner_id').last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))
        if application.partner_id != request.user.partner.id:
            return general_error_response(ErrorMessageConst.INVALID_DATA)
        return function(view, request, *args, **kwargs)

    return wrapper


def check_otp_validation(function: Callable):
    @wraps(function)
    def wrapper(view, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        application_xid = kwargs.get('application_xid') or request.data.get('application_xid')
        if not str(application_xid).isdigit():
            return general_error_response(
                'application_xid {}'.format(ErrorMessageConst.INVALID_DATA)
            )

        application = Application.objects.filter(
            application_xid=application_xid).only('customer').last()
        if not application:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        partnership_config = PartnershipConfig.objects.filter(
            partner=request.user.partner
        ).last()
        if partnership_config.is_validation_otp_checking:
            logs = {
                'url': request.path,
                'user': request.user.username,
                'data': dict(request.data)
            }
            is_valid_otp = is_customer_pass_otp(application.customer, json.dumps(logs))
            if not is_valid_otp:
                return general_error_response(ErrorMessageConst.OTP_NOT_VERIFIED)
        return function(view, request, *args, **kwargs)

    return wrapper


def require_partner_agent_role(function: Callable):
    @wraps(function)
    def wrapper(view, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = request.user_obj

        if not user.is_active:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        partnership_user = (
            PartnershipUser.objects.filter(
                user_id=user.id,
            )
            .values('role', 'partner_id')
            .first()
        )

        if not partnership_user:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        if partnership_user['role'] != MFStandardRole.PARTNER_AGENT:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        # Handling IDOR partner can access on other partner application
        if kwargs.get('application_xid'):
            partner_id = (
                Application.objects.filter(
                    product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
                    application_xid=int(kwargs['application_xid']),
                )
                .values_list('partner_id', flat=True)
                .last()
            )

            if partner_id and (partnership_user['partner_id'] != partner_id):
                return error_response(
                    status=status.HTTP_404_NOT_FOUND,
                    message=WebAppErrorMessage.PAGE_NOT_FOUND,
                )

        return function(view, request, *args, **kwargs)

    return wrapper


def require_agent_role(function: Callable):
    @wraps(function)
    def wrapper(view, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user = request.user_obj

        if not user.is_active:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        partnership_user_role = (
            PartnershipUser.objects.filter(
                user_id=user.id,
            )
            .values_list('role', flat=True)
            .first()
        )

        if not partnership_user_role:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        if partnership_user_role != MFStandardRole.AGENT:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        return function(view, request, *args, **kwargs)

    return wrapper


def require_mf_api_v1(function: Callable):
    @wraps(function)
    def wrapper(view, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """
        This decorator will preventing from greater than api_v1 user can login
        This rules for api_v1
        1. partnership_user.role should be null its implementation on v2
        2. partner_id on partner_user / julo_user should be filled (only axiata)
        on v2 if julo user not need to fill the partner_id
        """
        user = request.user_obj

        partnership_user = PartnershipUser.objects.filter(
            user_id=user.id,
        ).first()

        if not partnership_user:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        if not partnership_user.partner:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        if partnership_user.role:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        detokenize_partner = partnership_detokenize_sync_object_model(
            PiiSource.PARTNER,
            partnership_user.partner,
            customer_xid=None,
            fields_param=['name'],
            pii_type=PiiVaultDataType.KEY_VALUE,
        )
        partner_name = detokenize_partner.name
        feature_setting = FeatureSetting.objects.filter(
            feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
            is_active=True,
        ).last()

        if not feature_setting:
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        parameters = feature_setting.parameters
        if not parameters.get('api_v1'):
            return error_response(
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
            )

        api_v1_list_partner = parameters.get('api_v1')
        if partner_name.lower() not in api_v1_list_partner:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        return function(view, request, *args, **kwargs)

    return wrapper


def require_mf_api_v2(function: Callable):
    @wraps(function)
    def wrapper(view, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """
        This decorator will preventing from lower than api_v2 can login
        This rules for api_v2
        1. partnership_user.role should be mandatory
        2. partnership_user.partner will be mandatory if role = partner_agent,
        if partnership_user.role = agent partnership_user.partner not mandatory
        will set as null
        """
        user = request.user_obj

        partnership_user = PartnershipUser.objects.filter(
            user_id=user.id,
        ).first()

        if not partnership_user:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        partner_user_role = partnership_user.role
        if not partner_user_role:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        if partner_user_role not in {
            MFStandardRole.PARTNER_AGENT,
            MFStandardRole.AGENT,
        }:
            return error_response(
                status=status.HTTP_403_FORBIDDEN,
                message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
            )

        if partner_user_role == MFStandardRole.PARTNER_AGENT:
            detokenize_partner = partnership_detokenize_sync_object_model(
                PiiSource.PARTNER,
                partnership_user.partner,
                customer_xid=None,
                fields_param=['name'],
                pii_type=PiiVaultDataType.KEY_VALUE,
            )
            partner_name = detokenize_partner.name
            feature_setting = FeatureSetting.objects.filter(
                feature_name=MFFeatureSetting.STANDARD_PRODUCT_API_CONTROL,
                is_active=True,
            ).last()

            if not feature_setting:
                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                )

            parameters = feature_setting.parameters
            if not parameters.get('api_v2'):
                return error_response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message=HTTPGeneralErrorMessage.INTERNAL_SERVER_ERROR,
                )

            api_v2_list_partner = parameters.get('api_v2')
            if partner_name.lower() not in api_v2_list_partner:
                return error_response(
                    status=status.HTTP_403_FORBIDDEN,
                    message=WebAppErrorMessage.ACCESS_NOT_ALLOWED,
                )

        return function(view, request, *args, **kwargs)

    return wrapper
