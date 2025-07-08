from rest_framework.views import APIView

from django.db import transaction

from juloserver.account.constants import AccountConstant
from juloserver.autodebet.constants import VendorConst

from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    forbidden_error_response,
    success_response,
)

from juloserver.julo.models import Application
from juloserver.julo.exceptions import JuloException

from juloserver.account.models import Account

from juloserver.autodebet.serializers import (
    AccountRegistrationSerializer,
    AccountRevocationSerializer,
    AccountResetSerializer,
    AutodebetSuspendReactivationSerializer,
)
from juloserver.autodebet.services.authorization_services import (
    process_account_registration,
    process_account_revocation,
    process_reset_autodebet_account,
    get_revocation_status,
)
from juloserver.autodebet.services.benefit_services import (
    get_autodebet_benefit_message,
    construct_tutorial_benefit_data,
)
from juloserver.autodebet.services.account_services import (
    construct_autodebet_bca_feature_status,
    autodebet_account_reactivation_from_suspended
)


class AccountRegistrationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = AccountRegistrationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Account/Application/Customer tidak valid')

        customer = user.customer
        account = Account.objects.get_or_none(pk=data['account_id'], customer=customer)
        if not account:
            return general_error_response('Account/Application/Customer tidak valid')

        application = Application.objects.get_or_none(
            application_xid=data['application_xid'], customer=customer)
        if not account:
            return general_error_response('Account/Application/Customer tidak valid')

        if application != account.last_application:
            return general_error_response('Account/Application/Customer tidak valid')

        try:
            with transaction.atomic():
                data, error_message, is_forbidden = process_account_registration(account)
        except JuloException as e:
            return general_error_response(str(e))

        if error_message:
            if is_forbidden:
                return forbidden_error_response(error_message)
            return general_error_response(error_message)

        return success_response(data)


class AccountStatusView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Invalid user')
        # only for J1 account and exclude inactive one
        account = Account.objects.filter(customer=user.customer,
                                         status_id__gte=AccountConstant.STATUS_CODE.active,
                                         account_lookup_id=1
                                         ).last()
        if not account:
            return general_error_response("Customer tidak memiliki account")

        is_feature_active, is_autodebet_active,\
            is_manual_activation = construct_autodebet_bca_feature_status(account)
        message = get_autodebet_benefit_message(account)
        return success_response(
            dict(
                is_feature_active=is_feature_active,
                is_autodebet_active=is_autodebet_active,
                message=message,
                is_revocation_onprocess=get_revocation_status(account),
                is_manual_activation=is_manual_activation,
            )
        )


class AccountRevocationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = AccountRevocationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Account/Application/Customer tidak valid')

        customer = user.customer
        account = Account.objects.get_or_none(pk=data['account_id'], customer=customer)
        if not account:
            return general_error_response('Account/Application/Customer tidak valid')

        application = Application.objects.get_or_none(
            application_xid=data['application_xid'], customer=customer)
        if not account:
            return general_error_response('Account/Application/Customer tidak valid')

        if application != account.last_application:
            return general_error_response('Account/Application/Customer tidak valid')

        try:
            with transaction.atomic():
                data, error_message = process_account_revocation(account)
        except JuloException as e:
            return general_error_response(str(e))

        if error_message:
            return general_error_response(error_message)

        return success_response(data)


class AccountResetView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = AccountResetSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Account/Application/Customer tidak valid')

        customer = user.customer
        account = Account.objects.get_or_none(pk=data['account_id'], customer=customer)
        if not account:
            return general_error_response('Account/Application/Customer tidak valid')

        application = Application.objects.get_or_none(
            application_xid=data['application_xid'], customer=customer)
        if not account:
            return general_error_response('Account/Application/Customer tidak valid')

        if application != account.last_application:
            return general_error_response('Account/Application/Customer tidak valid')

        return success_response(process_reset_autodebet_account(account))


class AccountTutorialView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Invalid user')

        account = Account.objects.get_or_none(customer=user.customer)
        if not account:
            return general_error_response("Customer tidak memiliki account")

        return success_response(construct_tutorial_benefit_data(account))


class ReactivateView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        account = request.user.customer.account
        return autodebet_account_reactivation_from_suspended(
            account.id, True, VendorConst.BCA)

    def post(self, request):
        serializer = AutodebetSuspendReactivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return autodebet_account_reactivation_from_suspended(
            data['account_id'], False, VendorConst.BCA)
