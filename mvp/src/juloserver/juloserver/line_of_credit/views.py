from builtins import str
import logging

from django.conf import settings
from django.utils import timezone

from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.status import HTTP_201_CREATED
from rest_framework.renderers import TemplateHTMLRenderer

from .constants import LocConst
from .constants import LocErrorTemplate
from .constants import LocResponseMessageTemplate
from .constants import LocTransConst
from .exceptions import LocException
from .models import LineOfCredit
from .services import LineOfCreditService
from .services import LineOfCreditStatementService
from .services import LineOfCreditTransactionService
from .services import LineOfCreditProductService
from .services import LineOfCreditPurchaseService
from .serializers import LineOfCreditPurchaseSerializer
from .serializers import LineOfCreditProductListByTypeViewSerializer
from .serializers import LineOfCreditProductInquryElectricityAccountSerializer
from .serializers import LineOfCreditTransactionSerializer
from .utils import failure_template
from .utils import success_template

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients.sepulsa import SepulsaResponseCodes
from juloserver.julo.services2.sepulsa import SepulsaService


julo_sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class LineOfCreditActivityView(APIView):
    def get(self, request):
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(
                failure_template(LocErrorTemplate.LOC_NOT_FOUND['code'],
                                 LocErrorTemplate.LOC_NOT_FOUND['message']))

        loc = customer.lineofcredit
        data = LineOfCreditService.get_activity(loc)
        return Response(success_template(data))


class LineOfCreditStatementDetailView(APIView):
    def get(self, request, statement_id):
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(failure_template('LOC-01', 'No LOC found'))

        loc = customer.lineofcredit
        data = LineOfCreditStatementService().get_statement_by_id(statement_id)

        if not data:
            return Response(failure_template('LOC-02', 'Invalid Statement Id'))

        return Response(success_template(data))


class LineOfCreditTransactionView(APIView):
    def get(self, request):
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(failure_template('LOC-01', 'No LOC found'))

        loc = customer.lineofcredit
        transactions = LineOfCreditTransactionService().get_pending_list(loc.id)
        data = {'transactions': transactions}
        return Response(success_template(data))


class LineOfCreditPurchaseView(APIView):

    serializer_class = LineOfCreditPurchaseSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        if not serializer.is_valid():
            return Response(status=HTTP_400_BAD_REQUEST, data=failure_template('LOC-04', LocResponseMessageTemplate.GENERAL_ERROR))

        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(
                failure_template(LocErrorTemplate.LOC_NOT_FOUND['code'],
                                 LocErrorTemplate.LOC_NOT_FOUND['message']))

        loc = customer.lineofcredit
        data = serializer.data

        if 'pin' not in data:
            if settings.LOC_PIN_MODE == LocConst.PIN_MODE_ENFORCING:
                return Response(status=HTTP_400_BAD_REQUEST,
                                data=failure_template('LOC-04',
                                                      LocResponseMessageTemplate.GENERAL_ERROR))
        else:
            if loc.pin == '0':
                return Response(
                        failure_template(LocErrorTemplate.LOC_PIN_NOT_SET['code'],
                                         LocErrorTemplate.LOC_PIN_NOT_SET['message']))
            pin_is_valid = LineOfCreditService.check_pin(loc, data['pin'])
            if not pin_is_valid:
                return Response(
                        failure_template(LocErrorTemplate.LOC_PIN_INVALID['code'],
                                         LocErrorTemplate.LOC_PIN_INVALID['message']))

        try:
            if LineOfCreditPurchaseService.add_purchase(
                    loc,
                    data['product_id'],
                    data['phone_number'],
                    data['total_customer_price'],
                    data['account_name'],
                    data['meter_number']):
                return Response(status=HTTP_201_CREATED, data=success_template({'created': True}))
            return Response(status=HTTP_400_BAD_REQUEST,
                            data=failure_template('LOC-04',
                                                  LocResponseMessageTemplate.GENERAL_ERROR))
        except Exception as e:
            julo_sentry_client.captureException()
            return Response(status=HTTP_400_BAD_REQUEST, data=failure_template('LOC-04', str(e)))


class LineOfCreditProductListByIdView(APIView):

    def get(self, request, product_id):
        product = LineOfCreditProductService.get_by_id(product_id)
        if not product:
            return Response(status=HTTP_404_NOT_FOUND,
                            data=failure_template('LOC-04', LocResponseMessageTemplate.GENERAL_ERROR))
        return Response(status=HTTP_200_OK, data=success_template(product))


class LineOfCreditProductListByTypeView(APIView):

    serializer_class = LineOfCreditProductListByTypeViewSerializer

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)

        if not serializer.is_valid():
            return Response(status=HTTP_400_BAD_REQUEST,
                            data=failure_template('LOC-04',
                                                  LocResponseMessageTemplate.GENERAL_ERROR))
        data = serializer.data
        customer = request.user.customer
        if hasattr(customer, 'lineofcredit'):
            loc = customer.lineofcredit
            products = LineOfCreditProductService.get_by_type_and_category(data['type'],
                                                                           data['category'],
                                                                           data['operator_id'],
                                                                           loc.limit)
        else:
            return Response(status=HTTP_404_NOT_FOUND,
                            data=failure_template('LOC-01',
                                                  LocResponseMessageTemplate.LOC_NOT_FOUND))
        return Response(status=HTTP_200_OK, data=success_template(products))


class LineOfCreditProductInquryElectricityAccountView(APIView):

    serializer_class = LineOfCreditProductInquryElectricityAccountSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(status=HTTP_400_BAD_REQUEST, data=failure_template('LOC-04', LocResponseMessageTemplate.GENERAL_ERROR))
        data = serializer.data
        try:
            sepulsa_service = SepulsaService()
            response = sepulsa_service.get_account_electricity_info(data['meter_number'], data['product_id'])
            if response['response_code'] in SepulsaResponseCodes.SUCCESS:
                return Response(status=HTTP_200_OK, data=success_template(response))
            elif response['response_code'] in SepulsaResponseCodes.FAILED_VALIDATION_ELECTRICITY_ACCOUNT:
                return Response(status=HTTP_200_OK, data=failure_template('LOC-04', LocResponseMessageTemplate.ACCOUNT_ELECTRICITY_INVALID))
            else:
                return Response(status=HTTP_400_BAD_REQUEST, data=failure_template('LOC-04',  LocResponseMessageTemplate.GENERAL_ERROR))
        except Exception as e:
            julo_sentry_client.captureException()
            return Response(status=HTTP_400_BAD_REQUEST, data=failure_template('LOC-04',  LocResponseMessageTemplate.GENERAL_ERROR))


class LineOfCreditPaymentMethodView(APIView):
    def get(self, request):
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(failure_template('LOC-01', 'No LOC found'))

        loc = customer.lineofcredit
        data = LineOfCreditService().get_virtual_accounts(loc.id)

        if not data:
            return Response(failure_template('LOC-05', 'LOC has no payment methods or Inactive'))

        return Response(success_template(data))


class LineOfCreditSetUpdatePinView(APIView):
    def post(self, request):
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(failure_template(LocErrorTemplate.LOC_NOT_FOUND['code'],
                                             LocErrorTemplate.LOC_NOT_FOUND['message']))

        loc = customer.lineofcredit
        data = request.data

        try:
            LineOfCreditService.update_pin(loc, data)
        except LocException as e:
            return Response(failure_template(e.code, str(e)))

        logger.info({
            'status': 'updated pin loc',
            'customer_id': customer.id,
            'loc_id': loc.id
        })

        return Response(success_template(None))


class LineOfCreditResetPin(APIView):
    def get(self, request):
        """
        Handle user's request to send an email for resetting their pin.
        """
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(failure_template(LocErrorTemplate.LOC_NOT_FOUND['code'],
                                             LocErrorTemplate.LOC_NOT_FOUND['message']))
        loc = customer.lineofcredit
        email = customer.email

        LineOfCreditService.reset_pin_request(loc, email)
        remaining_time = (loc.reset_pin_exp_date - timezone.now()).total_seconds() * 1000

        return Response(success_template({'remaining_time': int(remaining_time)}))


class LineOfCreditResetPinConfirm(ObtainAuthToken):
    """
    end point for reset pin page
    """
    renderer_classes = [TemplateHTMLRenderer]

    def get(self, request, *args, **kwargs):
        """
        Called when user clicks link in the reset password email.
        """
        reset_pin_key = self.kwargs['reset_pin_key']

        if reset_pin_key is None:
            return Response(
                {'message': LocErrorTemplate.RESET_KEY_INVALID['message']},
                template_name='reset_pin_failed.html')

        loc = LineOfCredit.objects.get_or_none(reset_pin_key=reset_pin_key)
        if loc is None:
            return Response(
                {'message': LocErrorTemplate.RESET_KEY_INVALID['message']},
                template_name='reset_pin_failed.html')

        if loc.has_resetpin_expired():
            loc.reset_pin_key = None
            loc.reset_pin_exp_date = None
            loc.save()
            return Response(
                {'message': LocErrorTemplate.RESET_KEY_EXPIRED['message']},
                template_name='reset_pin_failed.html')

        action = settings.RESET_PIN_FORM_ACTION + reset_pin_key + '/'
        return Response(
            {'email': loc.customer.email, 'action': action},
            template_name='reset_pin.html')

    def post(self, request, *args, **kwargs):
        """
        Called when user submits the reset pin html form
        """
        pin1 = request.data['pin1']
        pin2 = request.data['pin2']

        reset_pin_key = self.kwargs['reset_pin_key']

        if reset_pin_key is None:
            return Response(
                {'message': LocErrorTemplate.RESET_KEY_INVALID['message']},
                template_name='reset_pin_failed.html')

        loc = LineOfCredit.objects.get_or_none(reset_pin_key=reset_pin_key)
        if loc is None:
            return Response(
                {'message': LocErrorTemplate.RESET_KEY_INVALID['message']},
                template_name='reset_pin_failed.html')

        try:
            LineOfCreditService.reset_pin_confirm(reset_pin_key, pin1, pin2)
        except LocException as e:
            return Response(
                {'message': str(e)},
                template_name='reset_pin_failed.html')

        return Response(template_name='reset_pin_success.html')


class LineOfCreditPinStatus(APIView):
    def get(self, request):
        customer = request.user.customer
        if not hasattr(customer, 'lineofcredit'):
            return Response(failure_template(LocErrorTemplate.LOC_NOT_FOUND['code'],
                                             LocErrorTemplate.LOC_NOT_FOUND['message']))
        loc = customer.lineofcredit
        pin_status = LineOfCreditService.get_pin_status(loc)

        return Response(success_template(pin_status))


