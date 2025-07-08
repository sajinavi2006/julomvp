import logging
from django.db import transaction
from rest_framework.views import APIView

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account
from juloserver.autodebet.services.account_services import (
    construct_autodebet_feature_status,
    get_latest_deactivated_autodebet_account,
    is_disabled_autodebet_activation,
    is_idfy_enable,
    is_bca_primary_bank,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.autodebet.services.benefit_services import construct_tutorial_benefit_autodebet
from juloserver.autodebet.serializers import (
    IdfyCallbackCompletedSerializer,
    IdfyCallbackDropOffSerializer,
    IdfyScheduleNotificationSerializer,
    DeactivationSurveySerializer,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
    not_found_response,
    unauthorized_error_response,
    forbidden_error_response,
    request_timeout_response,
)
from juloserver.autodebet.services.idfy_service import (
    create_idfy_profile,
    get_idfy_instruction,
    proceed_the_status_complete_response,
    proceed_the_status_dropoff_response,
    schedule_unfinished_activation_pn,
)
from juloserver.julo.clients.idfy import (
    IDfyTimeout,
    IDfyProfileCreationError,
    IDfyOutsideOfficeHour,
    IDFyGeneralMessageError,
)
from juloserver.autodebet.models import (
    AutodebetDeactivationSurveyQuestion,
    AutodebetDeactivationSurveyUserAnswer,
    AutodebetPaymentOffer,
)
from juloserver.julo.models import FeatureSetting
from juloserver.autodebet.constants import (
    FeatureNameConst,
    GENERAL_ERROR_MESSAGE,
)


logger = logging.getLogger(__name__)


class AccountStatusView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Invalid user')

        application = user.customer.application_set.last()
        if application.product_line_code == 2 and \
                application.application_status_id >= ApplicationStatusCodes.SCRAPED_DATA_VERIFIED:
            account = Account.objects.filter(
                customer=user.customer,
                account_lookup__workflow__name=WorkflowConst.JULO_STARTER
            ).last()
        else:
            account = Account.objects.filter(
                customer=user.customer,
                status_id__gte=AccountConstant.STATUS_CODE.active,
                account_lookup__workflow__name__in=[
                    WorkflowConst.JULO_ONE, WorkflowConst.JULO_STARTER]
            ).last()

        if not account:
            return general_error_response("Customer tidak memiliki account")

        return success_response(
            construct_autodebet_feature_status(account)
        )


class AccountTutorialView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        vendor = request.GET.get('type')
        user = self.request.user

        if not hasattr(user, 'customer'):
            return general_error_response('Invalid user')

        account = Account.objects.filter(customer=user.customer).last()
        if not account:
            return general_error_response("Customer tidak memiliki account")

        return success_response(construct_tutorial_benefit_autodebet(vendor, account))


class IdfyInstructionPage(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        content = get_idfy_instruction()
        if not content:
            return not_found_response('Not found!')

        return success_response(content)


class CreateProfileRequest(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        return not_found_response(GENERAL_ERROR_MESSAGE)
        user = self.request.user
        if not hasattr(user, 'customer'):
            return unauthorized_error_response('User not allowed')

        try:
            customer = user.customer
            url, profile_id = create_idfy_profile(customer)
        except IDfyProfileCreationError as e:
            return general_error_response(str(e))
        except IDfyTimeout as e:
            return request_timeout_response(str(e))
        except IDfyOutsideOfficeHour as e:
            return forbidden_error_response(str(e))
        except IDFyGeneralMessageError as e:
            return general_error_response(str(e))
        except Exception as e:
            logger.warning(
                "Exception on create_profile for : {} due to : {}".format(customer, str(e))
            )
            return general_error_response(str(e))

        if url is None and profile_id is None:
            return unauthorized_error_response('Video call session expired')

        response_data = {
            "video_call_url": url,
            "profile_id": profile_id,
        }

        return success_response(response_data)


class IdfyCallbackCompleted(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = IdfyCallbackCompletedSerializer

    # capture request and response as logging
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        logger.info(
            {
                'action': 'juloserver.autodebet.views.views_api_v1.' 'IdfyCallbackCompleted',
                'response': str(data),
            }
        )
        try:
            proceed_the_status_complete_response(data)
        except Exception as error:
            logger.error(
                {
                    'action': 'juloserver.autodebet.views.views_api_v1.' 'IdfyCallbackCompleted',
                    'error': str(error),
                    'response': str(data),
                }
            )
            return general_error_response(str(error))

        return success_response(data='successfully')


class IdfyCallbackDropOff(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = IdfyCallbackDropOffSerializer

    # capture request and response as logging
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'exclude_fields': {'header': ('HTTP_AUTHORIZATION',)},
        'log_success_response': True,
    }

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        logger.info(
            {
                'action': 'juloserver.autodebet.views.views_api_v1.' 'IdfyCallbackDropOff',
                'response': str(data),
            }
        )
        try:
            proceed_the_status_dropoff_response(data)
        except Exception as error:
            logger.error(
                {
                    'action': 'juloserver.autodebet.views.views_api_v1.' 'IdfyCallbackDropOff',
                    'error': str(error),
                    'response': str(data),
                }
            )
            return general_error_response(str(error))

        return success_response(data='successfully')


class IdfyScheduleNotification(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = IdfyScheduleNotificationSerializer

    def post(self, request):
        return not_found_response(GENERAL_ERROR_MESSAGE)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = self.request.user
        if not hasattr(user, 'customer'):
            return unauthorized_error_response('User not allowed')

        customer = user.customer

        account = customer.account
        if not account:
            return general_error_response("Customer tidak memiliki account")

        return success_response(schedule_unfinished_activation_pn(customer, data["vendor"]))


class DeactivationSurveyView(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request):
        latest_question = AutodebetDeactivationSurveyQuestion.objects.last()

        if latest_question is None:
            return general_error_response("No survey question found")

        answers = latest_question.answers.order_by('order', 'answer').values_list(
            'answer', flat=True
        )

        response_data = {"question": latest_question.question, "answers": list(answers)}

        return success_response(response_data)


class DeactivationSurveyAnswerView(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request):
        serializer = DeactivationSurveySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = self.request.user
        if not hasattr(user, 'customer'):
            return unauthorized_error_response('User not allowed')

        account = request.user.customer.account

        latest_deactivated_account = get_latest_deactivated_autodebet_account(
            account, data["bank_name"]
        )
        if not latest_deactivated_account:
            return general_error_response("Autodebit account not found")

        AutodebetDeactivationSurveyUserAnswer.objects.create(
            account_id=account.id,
            autodebet_account_id=latest_deactivated_account.id,
            question=data["question"],
            answer=data["answer"],
        )

        return success_response("Autodebit deaktivasi survey sukses")


class AutodebetPaymentOfferView(StandardizedExceptionHandlerMixin, APIView):
    """
    This class is used to maniplate payment offer
    using autodebet (with pop up in mobile site) after payment success.
    """

    def post(self, request):
        try:
            with transaction.atomic(using='repayment_db'):
                account = request.user.customer.account
                payment_offer = (
                    AutodebetPaymentOffer.objects.select_for_update()
                    .filter(account_id=account.id)
                    .first()
                )
                if not payment_offer:
                    raise Exception('Account not found')

                payment_offer.is_should_show = False
                payment_offer.save()

                return success_response("success")
        except Exception as e:
            return general_error_response(str(e))

    def get(self, request):
        response_data = {
            "should_show": False,
        }

        account = request.user.customer.account
        if not account:
            return general_error_response("Customer tidak memiliki account")

        if not is_idfy_enable(account.id) or (
            is_disabled_autodebet_activation(account, True) and not is_bca_primary_bank(account)
        ):
            response_data['should_show'] = False
        else:
            payment_offer = AutodebetPaymentOffer.objects.get_or_none(account_id=account.id)
            if payment_offer:
                response_data['should_show'] = payment_offer.is_should_show

        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.AUTODEBET_PAYMENT_OFFER_CONTENT, is_active=True
        )
        if feature_setting and feature_setting.parameters:
            response_data.update(feature_setting.parameters)

        return success_response(response_data)
