import logging

from django.conf import settings

from rest_framework.parsers import FormParser
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView

from juloserver.disbursement.exceptions import (
    DisbursementException,
    DisbursementServiceError,
)
from juloserver.disbursement.services import (
    get_disbursement_process,
    get_name_bank_validation_process,
    is_grab_disbursement,
)
from juloserver.disbursement.services.xfers import XfersConst
from juloserver.disbursement.tasks import (
    process_callback_from_xfers,
    application_bulk_disbursement_tasks,
    process_callback_from_xfers_partner,
    process_disbursement_payment_gateway,
)
from juloserver.disbursement.serializers import PaymentGatewayCallbackSerializer

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Loan,
    LoanDisburseInvoices,
)
from juloserver.julo.services import (
    record_disbursement_transaction,
    process_application_status_change
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
)
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixinV2
from juloserver.standardized_api_response.utils import success_response, general_error_response

logger = logging.getLogger(__name__)


class LoggedResponse(Response):
    def __init__(self, **kwargs):
        super(LoggedResponse, self).__init__(**kwargs)
        kwargs['http_status_code'] = self.status_code
        logger.info(kwargs)


# Create your views here.
class XenditNameValidateEventCallbackView(APIView):
    """Endpoint for Xendit Name Validate callback"""
    permission_classes = (AllowAny,)

    def post(self, request):

        data = request.data
        logger.info(data)

        validation_id = data['id']

        try:
            validation = get_name_bank_validation_process(validation_id)
        except DisbursementServiceError:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return LoggedResponse(data={
                'bank_code': data['bank_code'],
                'bank_account_number': data['bank_account_number'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated'],
            })

        if validation.is_success():
            return LoggedResponse(data={
                'bank_code': data['bank_code'],
                'bank_account_number': data['bank_account_number'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated'],
            })

        validation.update_status(data)
        name_bank_validation_id = validation.get_id()
        loan = Loan.objects.filter(name_bank_validation_id=name_bank_validation_id).last()

        # check if loan are from partner laku6
        if not loan:
            invoices = LoanDisburseInvoices.objects.filter(
                name_bank_validation_id=name_bank_validation_id
            ).order_by('cdate').last()
            loan = invoices.loan

        application = loan.application
        if validation.is_success():
            new_status_code = ApplicationStatusCodes.LENDER_APPROVAL
            change_reason = 'Lender approval'
            process_application_status_change(application.id, new_status_code, change_reason)
        elif validation.is_failed():
            new_status_code = ApplicationStatusCodes.NAME_VALIDATE_FAILED
            change_reason = 'Name validation failed'
            process_application_status_change(application.id, new_status_code, change_reason)

        return LoggedResponse(data={
            'bank_code': data['bank_code'],
            'bank_account_number': data['bank_account_number'],
            'status': data['status'],
            'id': data['id'],
            'updated': data['updated'],
        })


class XenditDisburseEventCallbackView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.META['HTTP_X_CALLBACK_TOKEN'] != settings.XENDIT_DISBURSEMENT_VALIDATION_TOKEN:
            try:
                raise DisbursementException("Failed xendit validation token")
            except DisbursementException:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
            return LoggedResponse()

        data = request.data
        disburse_id = data['id']
        try:
            disbursement = get_disbursement_process(disburse_id)
        except DisbursementServiceError:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return LoggedResponse(data={
                'bank_code': data['bank_code'],
                'account_holder_name': data['account_holder_name'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated'],
            })

        # check if disbursement already success (multiple callback)
        if disbursement.is_success():
            return LoggedResponse(data={
                'bank_code': data['bank_code'],
                'account_holder_name': data['account_holder_name'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated'],
            })

        disbursement_id = disbursement.get_id()
        loan = Loan.objects.filter(disbursement_id=disbursement_id).order_by('cdate').last()

        if disbursement.get_type() == 'loan_one':
            send_to = 'bukalapak'
        else:
            # check if loan are from partner laku6
            if not loan:
                invoices = LoanDisburseInvoices.objects.filter(disbursement_id=disbursement_id)\
                    .order_by('cdate').last()
                loan = invoices.loan

            application = loan.application
            send_to = application.email

        disbursement.update_status(data)
        disbursement_data = disbursement.get_data()
        if disbursement.is_success():
            if loan:
                if loan.lender and loan.lender.is_active_lender:
                    record_disbursement_transaction(loan)
            # process change status to 180
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s \
                    account number %s atas Nama %s via %s' % (
                send_to,
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])
            if disbursement.get_type() != 'loan_one':
                process_application_status_change(application.id,
                                                  new_status_code,
                                                  change_reason,
                                                  note)
        elif disbursement.is_failed():
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            change_reason = 'Fund disbursal failed'
            note = 'Disbursement failed to %s Bank %s \
                    account number %s atas Nama %s via %s' % (
                send_to,
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])

            if disbursement.get_type() != 'loan_one':
                process_application_status_change(application.id,
                                                  new_status_code,
                                                  change_reason,
                                                  note)

        if (disbursement.is_failed() or disbursement.is_success()) and \
                disbursement.get_type() == 'bulk':
            application_bulk_disbursement_tasks.delay(disbursement_id, new_status_code, note)

        return LoggedResponse(data={
            'bank_code': data['bank_code'],
            'account_holder_name': data['account_holder_name'],
            'status': data['status'],
            'id': data['id'],
            'updated': data['updated'],
        })


class XfersDisburseEventCallbackView(APIView):
    permission_classes = (AllowAny, )
    parser_classes = (FormParser, JSONParser, )
    renderer_classes = (JSONRenderer,)

    def post(self, request):
        data = request.data
        current_step = request.GET.get("step")
        is_reversal_payment = request.GET.get("reversal_payment")
        disburse_id = data['idempotency_id']

        logger.info({
            "action": "callbacks/xfers-disburse",
            "disburse_id": disburse_id,
            "current_step": current_step,
            "is_reversal_payment": is_reversal_payment,
            "callback_data": data,
        })

        if data['status'] != XfersConst.CALLBACK_PROCESSING_STATUS:  # ignore status processing
            params = dict(
                data=data,
                current_step=current_step,
                is_reversal_payment=is_reversal_payment
            )
            if is_grab_disbursement(disburse_id, is_reversal_payment):
                process_callback_from_xfers_partner.delay(**params)
            else:
                process_callback_from_xfers.delay(**params)

        return Response(
            status=HTTP_200_OK,
            data={
                "message": "sucessfully received callback of disbursement {}".format(
                    data['idempotency_id']
                )
            }
        )


class InstamoneyDisburseEventCallbackView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        if request.META['HTTP_X_CALLBACK_TOKEN'] != settings.INSTAMONEY_API_TOKEN:
            try:
                raise DisbursementException("Failed instamoney validation token")
            except DisbursementException:
                sentry_client = get_julo_sentry_client()
                sentry_client.captureException()
            return LoggedResponse()

        data = request.data
        disburse_id = data['id']
        try:
            disbursement = get_disbursement_process(disburse_id)
        except DisbursementServiceError:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            return LoggedResponse(data={
                'bank_code': data['bank_code'],
                'account_holder_name': data['account_holder_name'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated'],
            })

        # check if disbursement already success (multiple callback)
        if disbursement.is_success():
            return LoggedResponse(data={
                'bank_code': data['bank_code'],
                'account_holder_name': data['account_holder_name'],
                'status': data['status'],
                'id': data['id'],
                'updated': data['updated'],
            })

        disbursement_id = disbursement.get_id()
        loan = Loan.objects.filter(
            disbursement_id=disbursement_id).order_by('cdate').last()

        if disbursement.get_type() == 'loan_one':
            send_to = 'bukalapak'
        else:
            # check if loan are from partner laku6
            if not loan:
                invoices = LoanDisburseInvoices.objects.filter(
                    disbursement_id=disbursement_id).order_by('cdate').last()
                loan = invoices.loan

            application = loan.application
            send_to = application.email

        disbursement.update_status(data)
        disbursement_data = disbursement.get_data()
        if disbursement.is_success():
            if loan:
                if loan.lender and loan.lender.is_active_lender:
                    record_disbursement_transaction(loan)
            # process change status to 180
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            change_reason = 'Fund disbursal successful'
            note = 'Disbursement successful to %s Bank %s \
                    account number %s atas Nama %s via %s' % (
                send_to,
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])
            if disbursement.get_type() != 'loan_one':
                process_application_status_change(application.id,
                                                  new_status_code,
                                                  change_reason,
                                                  note)
        elif disbursement.is_failed():
            new_status_code = ApplicationStatusCodes.FUND_DISBURSAL_FAILED
            change_reason = 'Fund disbursal failed'
            note = 'Disbursement failed to %s Bank %s \
                    account number %s atas Nama %s via %s' % (
                send_to,
                disbursement_data['bank_info']['bank_code'],
                disbursement_data['bank_info']['account_number'],
                disbursement_data['bank_info']['validated_name'],
                disbursement_data['method'])
            if disbursement.get_type() != 'loan_one':
                process_application_status_change(application.id,
                                                  new_status_code,
                                                  change_reason,
                                                  note)

        if (disbursement.is_failed() or disbursement.is_success()) and \
                disbursement.get_type() == 'bulk':
            application_bulk_disbursement_tasks.delay(disbursement_id, new_status_code, note)

        return LoggedResponse(data={
            'bank_code': data['bank_code'],
            'account_holder_name': data['account_holder_name'],
            'status': data['status'],
            'id': data['id'],
            'updated': data['updated'],
        })


class PaymentGatewayDisburseEventCallbackView(StandardizedExceptionHandlerMixinV2, APIView):
    logging_data_conf = {
        'log_data': ['request', 'response', 'header'],
        'header_prefix': 'HTTP',
        'log_success_response': True,
    }
    serializer_class = PaymentGatewayCallbackSerializer
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response('invalid parameters')

        validated_data = serializer.validated_data
        process_disbursement_payment_gateway.delay(validated_data)

        return success_response('Success')
