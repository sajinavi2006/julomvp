import logging
import pytz
from datetime import datetime
from django.db import transaction, DatabaseError
from django.http import Http404
from cryptography.fernet import InvalidToken
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.generics import get_object_or_404
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView
from rest_framework.response import Response
from rest_framework import status
from juloserver.loan.serializers import CreateManualSignatureSerializer
from juloserver.balance_consolidation.tasks import balance_consolidation_upload_signature_image
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.balance_consolidation.serializers import BalanceConsolidationSubmitSerializer
from juloserver.balance_consolidation.models import (
    BalanceConsolidation,
    Fintech,
    BalanceConsolidationVerification,
    BalanceConsolidationVerificationHistory,
)
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationInfo,
    BalanceConsolidationStatus,
    FileTypeUpload,
)
from juloserver.balance_consolidation.services import (
    get_fintechs,
    upload_loan_agreement_document,
    create_balance_consolidation_verification,
    is_blocked_create_balance_consolidation,
    BalanceConsolidationToken,
    get_skrtp_template_temporary_loan,
    get_loan_balance_consolidation_duration,
)
from juloserver.balance_consolidation.utils import is_valid_file
from juloserver.julo.models import Customer
from juloserver.customer_module.serializers import BankAccountDestinationInfoSerializer
from juloserver.pin.decorators import pin_verify_required
from juloserver.standardized_api_response.utils import (
    success_response,
    general_error_response,
    not_found_response,
)
from juloserver.julo.exceptions import JuloException
from juloserver.loan.decorators import cache_expiry_on_headers
from juloserver.balance_consolidation.decorators import handle_token_decryption


logger = logging.getLogger(__name__)


class GetFintechs(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        return success_response(get_fintechs())


class BalanceConsolidationSubmitView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = BalanceConsolidationSubmitSerializer

    @handle_token_decryption
    @pin_verify_required
    def post(self, request, **kwargs):
        customer = kwargs['customer']
        application = customer.account.get_active_application()
        if not application:
            return not_found_response('Application not found')

        try:
            fintech = get_object_or_404(Fintech, pk=request.data['fintech_id'])
        except Http404:
            return not_found_response('Fintech not found')

        request_file = request.FILES.get("loan_agreement_document")
        if request_file:
            filename = request_file.name
            if not is_valid_file(filename):
                return general_error_response(
                    'Only accept file type: {}'.format(', '.join(FileTypeUpload.valid_file_types()))
                )
        request.data['fintech'] = fintech.id
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Verify again loan duration from request
        validated_data = serializer.validated_data
        loan_duration = validated_data['loan_duration']
        loan_outstanding_amount = validated_data['loan_outstanding_amount']
        available_durations = get_loan_balance_consolidation_duration(
            application, customer, loan_outstanding_amount
        )
        if loan_duration not in available_durations:
            return general_error_response('Invalid Loan Duration')

        with transaction.atomic():
            if is_blocked_create_balance_consolidation(customer):
                return general_error_response('Your request already exists!')
            if request_file:
                document = upload_loan_agreement_document(application, request_file)
                serializer.validated_data['loan_agreement_document'] = document
            serializer.validated_data['customer'] = customer
            serializer.validated_data['email'] = customer.email
            serializer.validated_data['fullname'] = customer.fullname
            balance_consolidation = serializer.save()
            create_balance_consolidation_verification(balance_consolidation)

        return success_response(
            {
                "balance_consolidation_id": balance_consolidation.id,
            }
        )


class BalanceConsolidationGetLoanDurationView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    @handle_token_decryption
    def get(self, request, *args, **kwargs):
        customer = kwargs['customer']
        application = customer.account.get_active_application()
        if not application:
            return not_found_response('Application not found')

        if 'loan_amount' not in request.GET:
            return general_error_response("Missing loan amount parameter")

        loan_amount = int(request.GET['loan_amount'])
        available_durations = get_loan_balance_consolidation_duration(
            application, customer, loan_amount
        )

        return success_response(
            {
                "loan_duration": available_durations,
            }
        )


class BalanceConsolidationInfoAPIView(APIView):
    serializer_class = BalanceConsolidationSubmitSerializer

    def get_queryset(self):
        return BalanceConsolidation.objects.filter(
            customer=self.request.user.customer,
            balanceconsolidationverification__validation_status=BalanceConsolidationStatus.APPROVED,
            balanceconsolidationverification__loan__isnull=True,
        )

    @cache_expiry_on_headers()
    def get(self, request, *args, **kwargs):
        qs = self.get_queryset()
        consolidation = qs.last()

        if not consolidation:
            return success_response({'balance_consolidation': None})

        consolidation_data = {
            'title': BalanceConsolidationInfo.TITLE,
            'message': BalanceConsolidationInfo.MESSAGE,
            'amount': consolidation.loan_outstanding_amount,
        }
        name_bank_validation = consolidation.balanceconsolidationverification.name_bank_validation
        bank_account_destination = name_bank_validation.bankaccountdestination_set.filter(
            customer=request.user.customer).last() if name_bank_validation else None

        if not bank_account_destination:
            raise JuloException('Bank account destination does not exist')

        bank_account_destination_serializer = \
            BankAccountDestinationInfoSerializer(bank_account_destination).data
        consolidation_data['bank_account'] = bank_account_destination_serializer

        return success_response({"balance_consolidation": consolidation_data})


class TemporaryLoanAgreementContentWebView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    @handle_token_decryption
    def get(self, request, *args, **kwargs):
        balance_consolidation_id = kwargs['balance_consolidation_id']
        customer = kwargs['customer']
        balance_consolidation = BalanceConsolidation.objects.get_or_none(
            id=balance_consolidation_id,
            customer=customer,
            signature_image=None,
        )
        if not balance_consolidation:
            return not_found_response("Balance Consolidation not found")

        # Filter on draft status before digisign
        balance_consolidation_verification = BalanceConsolidationVerification.objects.get_or_none(
            balance_consolidation_id=balance_consolidation_id,
            validation_status=BalanceConsolidationStatus.DRAFT,
        )
        if not balance_consolidation_verification:
            return not_found_response("Balance Consolidation not found")

        text_sphp = get_skrtp_template_temporary_loan(balance_consolidation)
        if not text_sphp:
            return general_error_response("The balance consolidation data mismatch.")
        return success_response(data=text_sphp)


class BalanceConsolidationUploadSignatureView(StandardizedExceptionHandlerMixin, CreateAPIView):
    permission_classes = []
    authentication_classes = []
    serializer_class = CreateManualSignatureSerializer

    @handle_token_decryption
    def create(self, request, **kwargs):
        balance_consolidation_id = kwargs['balance_consolidation_id']
        customer = kwargs['customer']
        balance_consolidation = BalanceConsolidation.objects.get_or_none(
            id=balance_consolidation_id,
            customer=customer,
        )
        if not balance_consolidation:
            return not_found_response("Balance Consolidation not found")

        image_file = self.request.POST['upload']
        if not image_file:
            raise JuloException("No Upload Data")

        data = request.POST.copy()

        data['image_source'] = balance_consolidation_id
        data['image_type'] = 'signature'
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                # Lock balance consolidation verification when updating status
                balance_consolidation_verification = (
                    BalanceConsolidationVerification.objects.select_for_update(nowait=True).get(
                        balance_consolidation_id=balance_consolidation_id,
                        validation_status=BalanceConsolidationStatus.DRAFT,
                    )
                )
                signature = serializer.save()
                signature.image.save(signature.full_image_name(image_file.name), image_file)
                balance_consolidation.update_safely(signature_image=signature)
                # Update balance status to on_review after digisign
                BalanceConsolidationVerificationHistory.objects.create(
                    balance_consolidation_verification=balance_consolidation_verification,
                    field_name='validation_status',
                    value_old=balance_consolidation_verification.validation_status,
                    value_new=BalanceConsolidationStatus.ON_REVIEW,
                )
                balance_consolidation_verification.note = 'customer sign the loan agreement'
                balance_consolidation_verification.validation_status = (
                    BalanceConsolidationStatus.ON_REVIEW
                )
                balance_consolidation_verification.save()
            balance_consolidation_upload_signature_image.delay(signature.pk, customer.id)
        except DatabaseError:
            # Handle error message if duplicate request
            return general_error_response(
                "Terima kasih, permintaan Anda sebelumnya sudah kami terima dan sedang diproses."
                "Jika butuh bantuan, hubungi Customer Service kami."
            )
        except ObjectDoesNotExist:
            # Handle error for customer back to digisign after submitting
            return not_found_response("Balance Consolidation not found")
        except JuloException as je:
            return general_error_response(message=str(je))
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class CustomerInfoView(StandardizedExceptionHandlerMixin, APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        try:
            token_obj = BalanceConsolidationToken()
            customer_id, expiry_timestamp = token_obj.decrypt_token_balance_cons_submit(
                kwargs['token']
            )
        except InvalidToken:
            return not_found_response('Token telah kedaluwarsa. Silakan hubungi CS kami')
        except ValueError:
            return not_found_response('Info pelanggan tidak ditemukan. Silakan hubungi CS kami')

        expiry_datetime = datetime.fromtimestamp(expiry_timestamp, pytz.timezone('Asia/Jakarta'))
        expiry_time_str = expiry_datetime.strftime('%d/%m/%Y %H:%M:%S %Z')
        return success_response(
            {
                "customer_id": customer_id,
                "expiry_time": expiry_time_str,
            }
        )
