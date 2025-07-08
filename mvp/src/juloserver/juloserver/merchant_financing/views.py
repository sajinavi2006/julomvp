from builtins import str
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST
)
from rest_framework.generics import ListAPIView
from django.utils import timezone
from juloserver.core.decorators import partner_protected_logic
from juloserver.merchant_financing.models import Merchant
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    forbidden_error_response,
)

from juloserver.merchant_financing.serializers import (
    PartnerAuthenticationSerializer,
    ApplicationSubmissionSerializer,
    DisbursementRequestSerializer,
    LoanDurationSerializer,
    LoanAgreementStatusSerializer,
    MerchantLoanSerializer,
    RepaymentSerializer,
    AxiataDailyReportSerializer,
    EmailSerializer,
    PgServiceCallbackTransferResultSerializer,
)
from juloserver.pin.utils import transform_error_msg
from juloserver.merchant_financing.services import (
    PartnerAuthenticationService,
    PartnerApplicationService,
    PartnerDisbursementService,
    get_sphp_template_merhant_financing,
    emails_sign_sphp_merchant_financing_expired,
    LoanMerchantFinancing,
    process_create_loan,
    get_account_payments_and_virtual_accounts,
    generate_encrypted_application_xid,
    get_urls_axiata_report,
    get_sphp_loan_merchant_financing,
    list_all_axiata_data,
)
from juloserver.partnership.security import PartnershipAuthentication
from juloserver.partnership.decorators import (check_application,
                                               check_pin_created, check_merchant_ownership)
from juloserver.julo.models import Application
from juloserver.julo.exceptions import JuloException
from juloserver.partnership.constants import ErrorMessageConst
from juloserver.merchant_financing.tasks import (
    upload_sphp_to_oss_merchant_financing,
    process_callback_transfer_result_task,
)
from juloserver.merchant_financing.constants import LoanAgreementStatus

from juloserver.julo.models import (
    Application,
    Loan,
    Payment
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes, LoanStatusCodes,
)
from juloserver.partnership.constants import (
    ErrorMessageConst,
    partnership_status_mapping_statuses,
    HTTPStatusCode,
    MERCHANT_FINANCING_PREFIX
)
from juloserver.partnership.security import PartnershipAuthentication
from juloserver.partnership.decorators import (
    check_loan,
    check_pin_created,
    check_pin_used_status,
)
from juloserver.partnership.views import PartnershipAPIView

from juloserver.julo.services import process_application_status_change

from juloserver.partnership.services.services import (
    get_document_submit_flag, get_credit_limit_info, get_existing_partnership_loans, is_able_to_reapply
)
from juloserver.partnership.paginations import CustomPagination
from juloserver.partnership.serializers import ApplicationStatusSerializer
from juloserver.pin.utils import transform_error_msg

from juloserver.loan.services.sphp import (
    accept_julo_sphp,
    cancel_loan
)

from juloserver.julo.partners import PartnerConstant
import juloserver.pin.services as pin_services
from juloserver.julo.utils import check_email
from juloserver.pin.constants import VerifyPinMsg, ResetMessage
from juloserver.merchant_financing.decorators import (
    check_mf_loan,
    check_valid_merchant_partner,
    check_otp_validation
)
from juloserver.partnership.utils import is_allowed_account_status_for_loan_creation_and_loan_offer
from juloserver.disbursement.constants import DisbursementStatus
from juloserver.payment_gateway.constants import TransferProcessStatus
from juloserver.disbursement.models import (
    Disbursement,
    Disbursement2History,
)
from juloserver.loan.services.lender_related import (
    julo_one_loan_disbursement_failed,
    julo_one_loan_disbursement_success,
)

logger = logging.getLogger(__name__)


class PartnerAuthenticationView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    serializer_class = PartnerAuthenticationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        serializer.is_valid(raise_exception=True)

        try:
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']

            response = PartnerAuthenticationService.authenticate(username, password)

            return success_response(response)
        except Exception as e:
            return general_error_response(str(e))


class PartnerApplicationView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = ApplicationSubmissionSerializer

    @partner_protected_logic
    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        serializer.is_valid(raise_exception=True)
        try:
            response_data = PartnerApplicationService.submit(serializer.validated_data)

            return success_response(response_data)
        except Exception as e:
            return general_error_response(str(e))

    @partner_protected_logic
    def get(self, request):
        try:
            partner_application_id = request.GET.get("partner_application_id")
            # loan_xid
            loan_xid = request.GET.get('application_xid', None)

            if partner_application_id:
                response = PartnerApplicationService.get_status(partner_application_id, loan_xid)

                return success_response(response)
            else:
                return general_error_response(
                    "Please provide partner_application_id and application_xid.")
        except Exception as e:
            return general_error_response(str(e))


class PartnerDisbursementView(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = DisbursementRequestSerializer

    @partner_protected_logic
    def post(self, request):
        serializer = self.serializer_class(data=request.data)

        serializer.is_valid(raise_exception=True)

        try:
            response = PartnerDisbursementService.disburse(serializer.validated_data)

            return success_response(response)
        except Exception as e:
            return general_error_response(str(e))


# Merchant Financing Views Section
class MerchantLoan(PartnershipAPIView):
    serializer_class = MerchantLoanSerializer

    @check_valid_merchant_partner
    @check_pin_used_status
    @check_otp_validation
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return general_error_response(
                transform_error_msg(serializer.errors, exclude_key=True)[0])
        try:
            application = serializer.application_obj
            setattr(application, 'product_lookup', serializer.product_lookup_obj)
            setattr(application, 'hcpl_obj', serializer.hcpl_obj)
            return process_create_loan(
                serializer.validated_data, application, application.account)
        except Exception as e:
            return general_error_response(str(e))


class SphpContentMerchantFinancing(StandardizedExceptionHandlerMixin, APIView):
    def get(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(application_xid=kwargs['application_xid'])

        if not application:
            return general_error_response('Application {}'.format(ErrorMessageConst.NOT_FOUND))

        user = request.user
        if user != application.customer.user:
            return forbidden_error_response(ErrorMessageConst.INVALID_TOKEN)

        if application.sphp_general_ts:
            return general_error_response(ErrorMessageConst.SPHP_UPLOADED)

        emails_sphp_expired = emails_sign_sphp_merchant_financing_expired(application.id)

        if emails_sphp_expired:
            able_to_reapply, *not_able_reason = is_able_to_reapply(application)
            return general_error_response({
                'message': '%s; Ajukan pinjaman kembali setelah: %s hari' % (
                    ErrorMessageConst.SPHP_EXPIRED, not_able_reason[1]),
                'number_of_days': not_able_reason[1]
            })

        if application.status != ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        sphp_template = get_sphp_template_merhant_financing(application.id, 'webview')

        return success_response(sphp_template)


class SphpSignMerchantFinancing(StandardizedExceptionHandlerMixin, APIView):
    def post(self, request, *args, **kwargs):
        application = Application.objects.get_or_none(application_xid=kwargs['application_xid'])
        if not application:
            return general_error_response('Application {}'.format(ErrorMessageConst.NOT_FOUND))

        user = request.user
        if user != application.customer.user:
            return forbidden_error_response(ErrorMessageConst.INVALID_TOKEN)

        if application.sphp_general_ts:
            return general_error_response(ErrorMessageConst.SPHP_UPLOADED)

        emails_sphp_expired = emails_sign_sphp_merchant_financing_expired(application.id)
        if emails_sphp_expired:
            able_to_reapply, *not_able_reason = is_able_to_reapply(application)
            return general_error_response({
                'message': '%s; Ajukan pinjaman kembali setelah: %s hari' % (
                    ErrorMessageConst.SPHP_EXPIRED, not_able_reason[1]),
                'number_of_days': not_able_reason[1]
            })

        if application.status != ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL:
            return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

        application.update_safely(sphp_general_ts=timezone.localtime(timezone.now()))
        upload_sphp_to_oss_merchant_financing.apply_async((application.id,), countdown=30)
        process_application_status_change(
            application.id, ApplicationStatusCodes.LOC_APPROVED, 'customer_triggered'
        )
        return success_response()


class RangeLoanAmountView(PartnershipAPIView):
    lookup_field = 'application_xid'

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            application_xid = request.GET.get('application_xid')
            if not application_xid or not application_xid.isdigit():
                return general_error_response('Invalid application_xid')

            only_fields = ['id', 'account__id', 'merchant__id']
            application = Application.objects.select_related('account', 'merchant') \
                .only(*only_fields).filter(application_xid=application_xid).last()
            if not application:
                return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

            account = application.account
            if not account:
                return general_error_response(ErrorMessageConst.ACCOUNT_NOT_FOUND)

            if not is_allowed_account_status_for_loan_creation_and_loan_offer(account):
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            range_loan_amount = LoanMerchantFinancing.get_range_loan_amount(
                application)

        except JuloException as e:
            logger.info({
                "action": "RangeLoanAmountView",
                "error": str(e),
                "application_xid": request.GET.get('application_xid')
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)

        return success_response(range_loan_amount)


class LoanDurationView(PartnershipAPIView):
    lookup_field = 'application_xid'
    serializer_class = LoanDurationSerializer

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            serializer = self.serializer_class(data=request.GET.copy())
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            only_fields = ['id', 'account__id', 'merchant__id']
            application = Application.objects.select_related('account', 'merchant') \
                .only(*only_fields).filter(application_xid=data['application_xid']).last()
            if not application:
                return general_error_response('Aplikasi {}'.format(ErrorMessageConst.NOT_FOUND))

            account = application.account
            if not account:
                return general_error_response(ErrorMessageConst.ACCOUNT_NOT_FOUND)

            if not is_allowed_account_status_for_loan_creation_and_loan_offer(account):
                return general_error_response(ErrorMessageConst.STATUS_NOT_VALID)

            loan_duration = LoanMerchantFinancing.get_loan_duration(application, data['loan_amount_request'])

        except JuloException as e:
            logger.info({
                "action": "LoanDurationView",
                "error": str(e),
                "application_xid": data['application_xid']
            })
            return general_error_response(ErrorMessageConst.GENERAL_ERROR)

        return success_response(loan_duration)


class MerchantApplicationStatusView(StandardizedExceptionHandlerMixin, ListAPIView):
    pagination_class = CustomPagination
    authentication_classes = (PartnershipAuthentication, )
    lookup_field = 'merchant_id'
    serializer_class = ApplicationStatusSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_merchant_ownership
    def get(self, request, *args, **kwargs):
        try:
            responses = []
            merchant_xid = self.kwargs['merchant_xid']
            merchant = Merchant.objects.get(merchant_xid=merchant_xid)
            applications = Application.objects.filter(
                merchant_id=merchant.id).exclude(application_status__in={
                    ApplicationStatusCodes.DOCUMENTS_VERIFIED,
                    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL})
            queryset = self.filter_queryset(applications)
            page = self.paginate_queryset(queryset)

            for application in page:
                response = dict()
                serializer = self.serializer_class(application)
                response['application'] = serializer.data
                response['application']['xid'] = generate_encrypted_application_xid(
                    response['application']['application_xid'],
                    MERCHANT_FINANCING_PREFIX)
                response['credit_info'] = {}
                if application.application_status_id >= \
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER \
                    and application.application_status_id not \
                    in {ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
                        ApplicationStatusCodes.NAME_VALIDATE_FAILED}:
                    response['credit_info'] = get_credit_limit_info(application)
                    del response['credit_info']['set_limit']

                    if application.application_status_id < 190:
                        response['credit_info']['available_limit'] = '-'

                is_document_status, mandatory_docs_submission, is_credit_score_generated, can_continue\
                    = get_document_submit_flag(application)
                response['can_continue'] = can_continue
                response['existing_loans'] = get_existing_partnership_loans(
                    application)
                responses.append(response)

        except JuloException as e:
            return general_error_response(str(e))

        return self.get_paginated_response({
            'applications': responses
        })

class ChangeLoanAgreementStatus(PartnershipAPIView):
    serializer_class = LoanAgreementStatusSerializer

    @check_loan
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        loan = Loan.objects.select_related(
            'customer__user'
        ).filter(loan_xid=data['loan_xid']).last()

        if not loan or loan.status != LoanStatusCodes.INACTIVE:
            return general_error_response("Loan {}".format(ErrorMessageConst.NOT_FOUND))
        if data['status'] == LoanAgreementStatus.APPROVE:
            new_loan_status = accept_julo_sphp(loan, "JULO")
        elif data['status'] == LoanAgreementStatus.CANCEL and \
                loan.status < LoanStatusCodes.FUND_DISBURSAL_ONGOING:
            new_loan_status = cancel_loan(loan)

        partnership_status_code = 'UNKNOWN'
        for partnership_status in partnership_status_mapping_statuses:
            if new_loan_status == partnership_status.list_code:
                partnership_status_code = partnership_status.mapping_status
        return success_response(data={
            "status": partnership_status_code,
            "loan_xid": data['loan_xid']
        })


class RepaymentInformation(StandardizedExceptionHandlerMixin, ListAPIView):
    pagination_class = CustomPagination
    authentication_classes = (PartnershipAuthentication,)
    repayment_serializer_class = RepaymentSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    @check_pin_created
    @check_application
    def get(self, request, *args, **kwargs):
        try:
            repayment_serializer = self.repayment_serializer_class(data=request.GET.copy())
            if not repayment_serializer.is_valid():
                return general_error_response(
                    transform_error_msg(repayment_serializer.errors, exclude_key=True)[0])

            data = repayment_serializer.validated_data
            account_payments, virtual_accounts = get_account_payments_and_virtual_accounts(
                data['application_xid'], data
            )
            queryset = self.filter_queryset(account_payments)
            page = self.paginate_queryset(queryset)
            responses = []
            if page:
                payments = Payment.objects.filter(account_payment__in=page)

            for account_payment_obj in page:
                account_payment_dict = {}
                account_payment_dict['due_date'] = account_payment_obj.due_date
                account_payment_dict['due_amount'] = account_payment_obj.due_amount
                account_payment_dict['principal_amount'] = account_payment_obj.principal_amount
                account_payment_dict['principal_interest'] = account_payment_obj.interest_amount
                account_payment_dict['paid_date'] = account_payment_obj.paid_date
                account_payment_dict['late_fee_amount'] = account_payment_obj.late_fee_amount
                account_payment_dict['paid_amount'] = account_payment_obj.paid_amount
                account_payment_dict['paid_principal'] = account_payment_obj.paid_principal
                account_payment_dict['paid_interest'] = account_payment_obj.paid_interest
                account_payment_dict['paid_late_fee'] = account_payment_obj.paid_late_fee
                account_payment_dict['status'] = account_payment_obj.due_status(False)
                payment_list = []
                for payment in payments:
                    if payment.account_payment_id == account_payment_obj.id:
                        payment_dict = {}
                        payment_dict['due_date'] = payment.due_date
                        payment_dict['due_amount'] = payment.due_amount
                        payment_dict['installment_principal'] = payment.installment_principal
                        payment_dict['installment_interest'] = payment.installment_interest
                        payment_dict['late_fee_amount'] = payment.late_fee_amount
                        payment_dict['paid_date'] = payment.paid_date
                        payment_dict['paid_amount'] = payment.paid_amount
                        payment_dict['paid_principal'] = payment.paid_principal
                        payment_dict['paid_interest'] = payment.paid_interest
                        payment_dict['paid_late_fee'] = payment.paid_late_fee
                        payment_list.append(payment_dict)

                account_payment_dict['payment'] = payment_list
                responses.append(account_payment_dict)

            return self.get_paginated_response({
                'account_payments': responses,
                'virtual_accounts': virtual_accounts
            })
        except JuloException as e:
            error_message = ErrorMessageConst.GENERAL_ERROR
            if str(e) == self.paginator.invalid_page_message:
                error_message = str(e)

            return general_error_response(error_message)


class AxiataDailyReport(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = AxiataDailyReportSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, request):
        if not hasattr(request.user, 'partner') or \
                request.user.partner.name != PartnerConstant.AXIATA_PARTNER:
            return forbidden_error_response(ErrorMessageConst.INVALID_PARTNER)
        serializer = self.serializer_class(data=request.GET.dict())
        serializer.is_valid(raise_exception=True)

        try:
            data = serializer.validated_data
            urls = get_urls_axiata_report(data['report_date'], data['report_type'])
            if not urls:
                return general_error_response(ErrorMessageConst.NOT_FOUND)

            return success_response(urls)
        except Exception as e:
            return general_error_response(str(e))


class ResetPin(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = EmailSerializer

    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = request.data['email'].strip().lower()

        email_valid = check_email(email)
        if not email_valid:
            logger.warn({
                'status': 'email_invalid',
                'email': email
            })
            return success_response(ResetMessage.PIN_RESPONSE)

        customer = pin_services.get_customer_by_email(email)
        if not customer or not pin_services.does_user_have_pin(customer.user):
            logger.warn({
                'status': 'email_not_in_database',
                'email': email
            })
            return success_response(ResetMessage.PIN_RESPONSE)

        application_count = pin_services.included_merchants_in_merchant_reset_pin(customer.user)
        if application_count == 0:
            logger.warn({
                'status': 'email_not_in_mf',
                'email': email
            })
            return success_response(ResetMessage.PIN_RESPONSE)

        pin_services.process_reset_pin_request(customer, email, False, True)

        return success_response(ResetMessage.PIN_RESPONSE)


class LoanAgreementContentView(PartnershipAPIView):

    @check_mf_loan
    def get(self, request):
        loan_xid = request.GET.get('loan_xid', None)
        loan = Loan.objects.filter(loan_xid=loan_xid).last()

        if not loan:
            return general_error_response("Loan {}".format(ErrorMessageConst.NOT_FOUND))

        text_sphp = get_sphp_loan_merchant_financing(loan.id)
        return success_response(data=text_sphp)


class AxiataListData(APIView):
    permission_classes = []
    authentication_classes = []
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def get(self, *args, **kwargs):
        try:
            if kwargs['partner_name'] != PartnerConstant.AXIATA_PARTNER:
                return Response(
                    status=HTTP_400_BAD_REQUEST,
                    data={'message': ErrorMessageConst.INVALID_PARTNER,
                          'meta': {}, 'errors': {}}
                )

            details = list_all_axiata_data()
            data = []
            for detail in details:
                row = {}
                row['loan_date'] = detail[0]
                row['fullname'] = detail[1]
                row['ktp'] = detail[2]
                row['distributor_id'] = detail[3]
                row['distributor_name'] = detail[4]
                row['tujuan_pinjaman'] = detail[5]
                row['loan_amount'] = detail[6]
                row['tenor'] = detail[7]
                row['provisi'] = detail[8]
                row['interest'] = detail[9]
                data.append(row)
            return Response(
                status=HTTP_200_OK, data={'data': data, 'meta': {}}
            )
        except Exception as e:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': str(e), 'meta': {}, 'errors': {}}
            )


class PgServiceCallbackTransferResult(APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = PgServiceCallbackTransferResultSerializer

    def post(self, request, *args, **kwargs):
        logger.error(
            {
                "action": "PgServiceCallbackTransferResult",
                "message": "callback received",
                "body": str(request.data),
            }
        )
        try:
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                logger.error(
                    {
                        "action": "PgServiceCallbackTransferResult",
                        "message": "error validation",
                        "error": str(serializer.errors),
                    }
                )
                return general_error_response(serializer.errors)
            data = serializer.validated_data
            status = data.get('status')
            transaction_id = data.get('transaction_id')

            process_callback_transfer_result_task.delay(transaction_id, status)

            return success_response(message="The transfer result has been successfully processed")
        except Exception as e:
            logger.error(
                {
                    "action": "PgServiceCallbackTransferResult",
                    "message": "error exception",
                    "error": str(e),
                }
            )
            return general_error_response(str(e))
