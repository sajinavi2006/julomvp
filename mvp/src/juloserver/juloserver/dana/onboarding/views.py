import json
import logging

from django.db import transaction
from django.forms import model_to_dict

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import (
    AccountInfoResponseCode,
    BindingResponseCode,
    DanaBasePath,
    DanaQueryTypeAccountInfo,
    ErrorType,
    BindingRejectCode,
    OnboardingRejectReason,
    AccountUpdateResponseCode,
    UPDATE_KEY_LIMIT,
    DanaProductType,
    DANA_ONBOARDING_FIELD_TO_TRACK,
    AccountInquiryResponseCode,
    MaxCreditorStatus,
    DanaFDCStatusSentRequest,
    DanaFDCResultStatus,
)
from juloserver.dana.exceptions import APIInvalidFieldFormatError
from juloserver.dana.models import (
    DanaCustomerData,
    DanaAccountInfo,
    DanaFDCResult,
    DanaApplicationReference,
)
from juloserver.dana.loan.services import (
    dana_max_creditor_check,
    dana_validate_dbr,
    dana_validate_dbr_in_bulk,
)
from juloserver.dana.onboarding.serializers import (
    DanaAccountInfoSerializer,
    DanaRegisterSerializer,
    DanaAccountUpdateSerializer,
    DanaAccountInquirySerializer,
)
from juloserver.dana.onboarding.services import (
    create_dana_user,
    process_valid_application,
    create_reapply_data,
    is_whitelisted_user,
    update_customer_limit,
    validate_customer_for_dana_cash_loan,
    validate_dana_binary_check,
    process_application_to_105,
)
from juloserver.dana.onboarding.utils import decrypt_personal_information
from juloserver.dana.tasks import (
    create_dana_customer_field_change_history,
    process_sending_dana_fdc_result,
)
from juloserver.dana.utils import get_error_message
from juloserver.dana.views import DanaAPIView
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Partner, Application
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import (
    execute_after_transaction_safely,
)
from juloserver.partnership.constants import HTTPStatusCode, PartnershipFlag
from juloserver.partnership.models import PartnershipFlowFlag

from rest_framework import status
from rest_framework.response import Response
from rest_framework.request import Request

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class BaseDanaOnboardingAPIView(DanaAPIView):
    base_path = DanaBasePath.onboarding


class DanaAccountBindView(BaseDanaOnboardingAPIView):
    serializer_class = DanaRegisterSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request) -> Response:
        partner = Partner.objects.filter(
            name=PartnerNameConstant.DANA,
            is_active=True,
        ).last()

        # Re-construnct PII Data from DANA
        try:
            error_type = ErrorType.INVALID_MANDATORY_FIELD
            response_code, response_message = get_error_message(self.base_path, error_type)

            additional_info = request.data.get('additionalInfo', None)
            data = {
                'responseCode': response_code,
                'responseMessage': response_message,
                'partnerReferenceNo': request.data.get('partnerReferenceNo', ''),
            }

            # Validated not handled error response in serializer
            if not additional_info:
                data['additionalInfo'] = {
                    'rejectCode': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.code,
                    'rejectReason': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.reason,
                    'errors': {'additionalInfo': 'additionalInfo cannot be empty'},
                }
                return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

            identification_info = additional_info.get('identificationInfo', None)
            if not identification_info:
                data['additionalInfo'] = {
                    'rejectCode': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.code,
                    'rejectReason': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.reason,
                    'errors': {'identificationInfo': 'identificationInfo cannot be empty'},
                }
                return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

            decrypt_identification_info = decrypt_personal_information(identification_info)
            proposed_credit_limit = additional_info.get('proposedCreditLimit', None)

            if not proposed_credit_limit:
                data['additionalInfo'] = {
                    'rejectCode': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.code,
                    'rejectReason': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.reason,
                    'errors': {'proposedCreditLimit': 'proposedCreditLimit cannot be empty'},
                }
                return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

            if not isinstance(proposed_credit_limit, dict):
                response_code, response_message = get_error_message(
                    self.base_path, ErrorType.INVALID_FIELD_FORMAT
                )
                data['responseCode'] = response_code
                data['responseMessage'] = response_message
                data['additionalInfo'] = {
                    'rejectCode': BindingRejectCode.HAS_INVALID_FIELD_FORMAT.code,
                    'rejectReason': BindingRejectCode.HAS_INVALID_FIELD_FORMAT.reason,
                    'errors': {'proposedCreditLimit': 'Invalid format for proposedCreditLimit'},
                }
                return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

            if 'value' not in proposed_credit_limit:
                data['additionalInfo'] = {
                    'rejectCode': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.code,
                    'rejectReason': BindingRejectCode.HAS_INVALID_MANDATORY_FIELD.reason,
                    'errors': {
                        'proposedCreditLimit': 'value in proposedCreditLimit cannot be empty'
                    },
                }
                return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

            # Combine dictionary to request.data
            additional_info['proposedCreditLimit'] = proposed_credit_limit['value']
            additional_info.update(decrypt_identification_info)

            request.data.update(additional_info)
        except Exception as e:
            logger.exception(
                {
                    'action_view': 'dana_failed_to_decrypt_personal_information',
                    'message': 'Dana failed to decrypt encryption data {}'.format(
                        identification_info
                    ),
                    'errors': str(e),
                }
            )

            raise APIInvalidFieldFormatError(
                detail={'additionalInfo': 'Invalid identificationInfo / other additionalInfo'},
            )

        serializer = self.serializer_class(data=request.data, partner=partner)
        serializer.is_valid(raise_exception=True)

        dana_customer_identifier = serializer.validated_data['customerId']
        partner_reference_no = serializer.validated_data['partnerReferenceNo']
        dana_phone = serializer.validated_data['phoneNo']
        dana_nik = serializer.validated_data['cardId']
        lender_product_id = serializer.validated_data['lenderProductId']

        has_dana_customer = DanaCustomerData.objects.filter(
            dana_customer_identifier=dana_customer_identifier,
            lender_product_id=lender_product_id,
        ).last()

        user_whitelisted = is_whitelisted_user(str(dana_customer_identifier))

        if lender_product_id == DanaProductType.CASH_LOAN:
            # checking customer id for dana cash loan
            evaluate_response = validate_customer_for_dana_cash_loan(
                dana_customer_identifier,
                partner_reference_no,
            )
            if evaluate_response:
                return Response(status=status.HTTP_400_BAD_REQUEST, data=evaluate_response)

        is_reapply = False
        old_application = None

        with transaction.atomic():
            if has_dana_customer:
                """
                Re - Apply process
                Create New Application
                No need check fraud, fraud user is handling in serializer check
                """
                dana_customer_data = serializer.save()
                dana_proposed_credit_limit = dana_customer_data.proposed_credit_limit
                old_application = dana_customer_data.application

                if user_whitelisted:
                    is_reapply = True

                dana_data_created = create_reapply_data(dana_customer_data, partner_reference_no)

                # Create customer field change record for dana customer
                old_dana_customer_data = model_to_dict(
                    has_dana_customer, fields=DANA_ONBOARDING_FIELD_TO_TRACK
                )
                new_dana_customer_data = model_to_dict(
                    dana_customer_data, fields=DANA_ONBOARDING_FIELD_TO_TRACK
                )
                execute_after_transaction_safely(
                    lambda: create_dana_customer_field_change_history.delay(
                        old_data=old_dana_customer_data,
                        new_data=new_dana_customer_data,
                        customer_id=has_dana_customer.customer_id,
                    )
                )
            else:
                """
                New user Process
                Process Create a Dana Customer Data
                """

                dana_customer_data = serializer.save()
                dana_proposed_credit_limit = dana_customer_data.proposed_credit_limit
                dana_data_created = create_dana_user(dana_customer_data, partner_reference_no)

        # Dana reference number and application
        application_id = dana_data_created.application_id
        dana_application_reference = dana_data_created.dana_application_reference

        # Set application to 105 (FORM_PARTIAL)
        process_application_to_105(application_id)
        status_code, data = validate_dana_binary_check(
            dana_customer_data,
            user_whitelisted,
            dana_application_reference,
            application_id,
            dana_phone,
            dana_nik,
        )
        if status_code or data:
            return Response(status=status_code, data=data)
        # Valid user
        process_valid_application(application_id)

        data = {
            'responseCode': BindingResponseCode.SUCCESS.code,
            'responseMessage': BindingResponseCode.SUCCESS.message,
            'accountId': str(dana_customer_data.customer.customer_xid),
            'partnerReferenceNo': dana_application_reference.partner_reference_no,
            'referenceNo': str(dana_application_reference.reference_no),
            'additionalInfo': {
                'approvedCreditLimit': {
                    'value': '{:.2f}'.format(dana_proposed_credit_limit),
                    'currency': 'IDR',
                }
            },
        }

        # Set to in progress if max creditor check is active
        config_data = (
            PartnershipFlowFlag.objects.filter(
                partner_id=partner.id, name=PartnershipFlag.MAX_CREDITOR_CHECK
            )
            .values_list('configs', flat=True)
            .last()
        )
        if config_data and config_data.get('is_active'):
            data['responseCode'] = BindingResponseCode.ACCEPTED.code
            data['responseMessage'] = BindingResponseCode.ACCEPTED.message

        if user_whitelisted and is_reapply and old_application:
            """
            This handling only for existing customer, already register and do re-applying
            This flag for experiment whitelisted user and add to rejectReason in response
            """

            if old_application.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD:
                reject_code = BindingRejectCode.WHITELISTED_FRAUD_USER.code
                reject_reason = BindingRejectCode.WHITELISTED_FRAUD_USER.reason
                data['additionalInfo']['rejectCode'] = reject_code
                data['additionalInfo']['rejectReason'] = reject_reason
            elif old_application.status == ApplicationStatusCodes.APPLICATION_DENIED:
                last_history_application = old_application.applicationhistory_set.last()
                is_existing_user_phone_reject = OnboardingRejectReason.EXISTING_PHONE_DIFFERENT_NIK
                if (
                    last_history_application
                    and last_history_application.change_reason == OnboardingRejectReason.BLACKLISTED
                ):
                    reject_code = BindingRejectCode.WHITELISTED_BLACKLIST_USER.code
                    reject_reason = BindingRejectCode.WHITELISTED_BLACKLIST_USER.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason
                elif (
                    last_history_application
                    and last_history_application.change_reason == is_existing_user_phone_reject
                ):
                    reject_code = BindingRejectCode.WHITELISTED_EXISTING_USER_INVALID_NIK.code
                    reject_reason = BindingRejectCode.WHITELISTED_EXISTING_USER_INVALID_NIK.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason
                elif (
                    last_history_application
                    and last_history_application.change_reason == OnboardingRejectReason.UNDERAGE
                ):
                    reject_code = BindingRejectCode.UNDERAGED_CUSTOMER.code
                    reject_reason = BindingRejectCode.UNDERAGED_CUSTOMER.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason
                else:
                    reject_code = BindingRejectCode.WHITELISTED_DELINQUENT_USER.code
                    reject_reason = BindingRejectCode.WHITELISTED_DELINQUENT_USER.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason

        return Response(status=status.HTTP_200_OK, data=data)


class BaseDanaAccountAPIView(DanaAPIView):
    base_path = DanaBasePath.account


class DanaAccountUpdateView(BaseDanaAccountAPIView):
    serializer_class = DanaAccountUpdateSerializer

    def post(self, request: Request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        dana_customer_id = serializer.validated_data['customerId']
        update_info_list = serializer.validated_data['updateInfoList']
        lender_product_id = serializer.validated_data['lenderProductId']

        additional_info = request.data.get('additionalInfo', {})
        with transaction.atomic():
            # Process Save Info List and additional info
            dana_fdc_result = DanaFDCResult.objects.filter(
                dana_customer_identifier=dana_customer_id, lender_product_id=lender_product_id
            ).last()

            if dana_fdc_result:
                DanaAccountInfo.objects.create(
                    dana_customer_identifier=dana_customer_id,
                    dana_fdc_result_id=dana_fdc_result.id,
                    lender_product_id=lender_product_id,
                    update_info_list=update_info_list,
                    additional_info=additional_info,
                )

            # Process account update
            for info in update_info_list:

                if info['updateKey'] == UPDATE_KEY_LIMIT:
                    update_value = json.loads(info['updateValue'])
                    new_limit = float(update_value['value'])
                    update_customer_limit(dana_customer_id, new_limit, lender_product_id)

        data = {
            'responseCode': AccountUpdateResponseCode.SUCCESS.code,
            'responseMessage': AccountUpdateResponseCode.SUCCESS.message,
        }
        return Response(status=status.HTTP_200_OK, data=data)


class DanaAccountInquiryView(DanaAPIView):
    base_path = DanaBasePath.account_inquiry
    serializer_class = DanaAccountInquirySerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        partner_reference_no = serializer.validated_data['partnerReferenceNo']

        dana_application_reference = DanaApplicationReference.objects.filter(
            partner_reference_no=partner_reference_no
        ).last()
        if not dana_application_reference:
            err_response = {
                'partnerReferenceNo': 'Invalid partnerReferenceNo, partnerReferenceNo not a found'
            }

            response_data = {
                'responseCode': AccountInquiryResponseCode.BAD_REQUEST.code,
                'responseMessage': AccountInquiryResponseCode.BAD_REQUEST.message,
                'additionalInfo': {'errors': err_response},
            }

            return Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        application_id = dana_application_reference.application_id
        application = Application.objects.filter(id=application_id).last()

        approved_credit_limit = (
            DanaCustomerData.objects.filter(customer_id=application.customer_id)
            .values_list('proposed_credit_limit', flat=True)
            .last()
        )

        data = {
            'responseCode': AccountInquiryResponseCode.SUCCESS.code,
            'responseMessage': AccountInquiryResponseCode.SUCCESS.message,
            'referenceNo': str(dana_application_reference.reference_no),
            'partnerReferenceNo': dana_application_reference.partner_reference_no,
            'accountId': str(application.customer.customer_xid),
            'additionalInfo': {},
        }

        if application.status in {
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            ApplicationStatusCodes.APPLICATION_DENIED,
        }:
            data['responseCode'] = AccountInquiryResponseCode.BAD_REQUEST.code
            data['responseMessage'] = AccountInquiryResponseCode.BAD_REQUEST.message

            if application.status == ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD:
                reject_code = BindingRejectCode.FRAUD_CUSTOMER.code
                reject_reason = BindingRejectCode.FRAUD_CUSTOMER.reason
                data['additionalInfo']['rejectCode'] = reject_code
                data['additionalInfo']['rejectReason'] = reject_reason

            else:
                change_reason = (
                    application.applicationhistory_set.filter(
                        status_new=ApplicationStatusCodes.APPLICATION_DENIED
                    )
                    .values_list('change_reason', flat=True)
                    .last()
                )
                if change_reason == OnboardingRejectReason.BLACKLISTED:
                    reject_code = BindingRejectCode.BLACKLISTED_CUSTOMER.code
                    reject_reason = BindingRejectCode.BLACKLISTED_CUSTOMER.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason
                elif change_reason == OnboardingRejectReason.EXISTING_PHONE_DIFFERENT_NIK:
                    reject_code = BindingRejectCode.EXISTING_USER_INVALID_NIK.code
                    reject_reason = BindingRejectCode.EXISTING_USER_INVALID_NIK.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason
                elif change_reason == OnboardingRejectReason.UNDERAGE:
                    reject_code = BindingRejectCode.UNDERAGED_CUSTOMER.code
                    reject_reason = BindingRejectCode.UNDERAGED_CUSTOMER.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason
                else:
                    reject_code = BindingRejectCode.DELINQUENT_CUSTOMER.code
                    reject_reason = BindingRejectCode.DELINQUENT_CUSTOMER.reason
                    data['additionalInfo']['rejectCode'] = reject_code
                    data['additionalInfo']['rejectReason'] = reject_reason

            return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

        elif application.status < ApplicationStatusCodes.LOC_APPROVED:
            data['responseCode'] = AccountInquiryResponseCode.ACCEPTED.code
            data['responseMessage'] = AccountInquiryResponseCode.ACCEPTED.message

            return Response(status=status.HTTP_202_ACCEPTED, data=data)

        if approved_credit_limit:
            data['additionalInfo']['approvedCreditLimit'] = {
                'value': '{:.2f}'.format(approved_credit_limit),
                'currency': 'IDR',
            }

        # Success Process
        credit_score = None
        if hasattr(application, 'creditscore'):
            credit_score = application.creditscore

        creditor_check_status = dana_application_reference.creditor_check_status
        is_pending_status = (
            creditor_check_status and creditor_check_status == MaxCreditorStatus.PENDING
        )

        if not credit_score or not creditor_check_status or is_pending_status:
            data['responseCode'] = AccountInquiryResponseCode.ACCEPTED.code
            data['responseMessage'] = AccountInquiryResponseCode.ACCEPTED.message

            return Response(status=status.HTTP_202_ACCEPTED, data=data)

        if creditor_check_status == MaxCreditorStatus.PASS:
            creditor_status = True
        else:
            creditor_status = False

        data['additionalInfo']['creditorCheck'] = {
            'status': creditor_status,
            'lenderScore': credit_score.score,
        }

        # Notify to dana
        application_id = application.id
        dana_fdc_result = (
            DanaFDCResult.objects.filter(application_id=application_id)
            .values('status', 'fdc_status')
            .last()
        )

        valid_fdc_statuses = {
            DanaFDCResultStatus.APPROVE1,
            DanaFDCResultStatus.APPROVE2,
            DanaFDCResultStatus.APPROVE3,
            DanaFDCResultStatus.APPROVE4,
            DanaFDCResultStatus.APPROVE5,
            DanaFDCResultStatus.APPROVE6,
        }

        logger.info(
            {
                "action": "DanaAccountInquiryView",
                "application_id": application_id,
                "partner_reference_no": partner_reference_no,
                "dana_fdc_result": {
                    'status': dana_fdc_result.get('status', None),
                    'fdc_status': dana_fdc_result.get('fdc_status', None),
                },
                "message": "validating process_sending_dana_fdc_result",
            }
        )

        if (
            dana_fdc_result
            and dana_fdc_result['status'] == DanaFDCStatusSentRequest.PENDING
            and dana_fdc_result['fdc_status'] in valid_fdc_statuses
        ):
            logger.info(
                {
                    "action": "DanaAccountInquiryView",
                    "application_id": application_id,
                    "partner_reference_no": partner_reference_no,
                    "message": "calling process_sending_dana_fdc_result",
                }
            )
            process_sending_dana_fdc_result.apply_async(
                (application_id,),
            )

        return Response(status=status.HTTP_200_OK, data=data)


class DanaAccountInfoView(DanaAPIView):
    base_path = DanaBasePath.account_info
    serializer_class = DanaAccountInfoSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        dana_customer_id = serializer.validated_data["customerId"]
        lender_product_id = serializer.validated_data["lenderProductId"]
        query_info_list = serializer.validated_data["queryInfoParamList"]

        dana_customer_data = (
            DanaCustomerData.objects.filter(
                dana_customer_identifier=dana_customer_id,
                lender_product_id=lender_product_id,
            )
            .select_related(
                "application",
                "application__customer",
                "application__creditscore",
                "application__product_line",
                "application__account",
            )
            .first()
        )
        if not dana_customer_data:
            response_data = {
                "responseCode": AccountInfoResponseCode.BAD_REQUEST.code,
                "responseMessage": AccountInfoResponseCode.BAD_REQUEST.message,
                "queryInfoResultList": [],
                "additionalInfo": {"errorMessage": "customerId doesn't exists"},
            }
            return Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        application = dana_customer_data.application
        query_info_result_list = []
        query_info = query_info_list[0]  # For now only allow 1 query type per hit
        if query_info["queryType"] == DanaQueryTypeAccountInfo.CREDITOR_CHECK:
            is_eligible = dana_max_creditor_check(dana_customer_data, application)
            query_result = {
                "queryType": query_info["queryType"],
                "queryValue": {
                    "status": is_eligible,
                    "lenderScore": application.creditscore.score.upper(),
                },
            }
            query_info_result_list.append(query_result)

        elif query_info["queryType"] == DanaQueryTypeAccountInfo.DBR_ALLOWED:
            is_eligible, max_loan_amount = dana_validate_dbr(
                application, query_info["queryTypeParam"]["repaymentPlanList"]
            )
            query_result = {
                "queryType": query_info["queryType"],
                "queryValue": {
                    "available": is_eligible,
                    "maxLimitAllowed": {
                        "value": "{:.2f}".format(max_loan_amount),
                        "currency": "IDR",
                    },
                },
            }
            query_info_result_list.append(query_result)

        elif query_info["queryType"] == DanaQueryTypeAccountInfo.DBR_INSTALLMENT_CHECK:
            is_eligible_list, max_loan_amount_list = dana_validate_dbr_in_bulk(
                application, query_info["queryTypeParam"]["installmentPlanList"]
            )

            dbr_results = []
            for eligible, max_limit in zip(is_eligible_list, max_loan_amount_list):
                dbr_results.append(
                    {
                        "installmentPlanId": eligible["installmentPlanId"],
                        "available": eligible["isEligible"],
                        "maxLimitAllowed": max_limit["maxLimitAllowed"],
                    }
                )

            query_result = {
                "queryType": query_info["queryType"],
                "queryValue": {
                    "dbrResults": dbr_results,
                },
            }
            query_info_result_list.append(query_result)

        logger.info(
            {
                "action": "dana_query_account_info",
                "query_type": query_info["queryType"],
                "request_data": request.data,
                "result": query_info_result_list,
            }
        )
        response_data = {
            "responseCode": AccountInfoResponseCode.SUCCESS.code,
            "responseMessage": AccountInfoResponseCode.SUCCESS.message,
            "queryInfoResultList": query_info_result_list,
        }

        # Notify to dana
        application_id = application.id
        dana_fdc_result = (
            DanaFDCResult.objects.filter(application_id=application_id)
            .values('status', 'fdc_status')
            .last()
        )

        valid_fdc_statuses = {
            DanaFDCResultStatus.APPROVE1,
            DanaFDCResultStatus.APPROVE2,
            DanaFDCResultStatus.APPROVE3,
            DanaFDCResultStatus.APPROVE4,
            DanaFDCResultStatus.APPROVE5,
            DanaFDCResultStatus.APPROVE6,
        }

        if dana_fdc_result:
            logger.info(
                {
                    "action": "DanaAccountInfoView",
                    "application_id": application_id,
                    "dana_customer_identifier": dana_customer_id,
                    "dana_fdc_result": {
                        'status': dana_fdc_result.get('status', None),
                        'fdc_status': dana_fdc_result.get('fdc_status', None),
                    },
                    "message": "validating process_sending_dana_fdc_result",
                }
            )

        if (
            dana_fdc_result
            and dana_fdc_result['status'] == DanaFDCStatusSentRequest.PENDING
            and dana_fdc_result['fdc_status'] in valid_fdc_statuses
        ):
            logger.info(
                {
                    "action": "DanaAccountInfoView",
                    "application_id": application_id,
                    "dana_customer_identifier": dana_customer_id,
                    "message": "calling process_sending_dana_fdc_result",
                }
            )
            process_sending_dana_fdc_result.apply_async(
                (application_id,),
            )

        return Response(status=status.HTTP_200_OK, data=response_data)


class DanaAccountInfoTempView(DanaAPIView):
    authentication_classes = []
    permission_classes = []
    base_path = DanaBasePath.account_info
    serializer_class = DanaAccountInfoSerializer
    exclude_raise_error_sentry_in_status_code = HTTPStatusCode.EXCLUDE_FROM_SENTRY

    def post(self, request: Request) -> Response:
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        dana_customer_id = serializer.validated_data["customerId"]
        lender_product_id = serializer.validated_data["lenderProductId"]
        query_info_list = serializer.validated_data["queryInfoParamList"]

        dana_customer_data = (
            DanaCustomerData.objects.filter(
                dana_customer_identifier=dana_customer_id,
                lender_product_id=lender_product_id,
            )
            .select_related(
                "application",
                "application__customer",
                "application__creditscore",
                "application__product_line",
                "application__account",
            )
            .first()
        )
        if not dana_customer_data:
            response_data = {
                "responseCode": AccountInfoResponseCode.BAD_REQUEST.code,
                "responseMessage": AccountInfoResponseCode.BAD_REQUEST.message,
                "queryInfoResultList": [],
                "additionalInfo": {"errorMessage": "customerId doesn't exists"},
            }
            return Response(status=status.HTTP_400_BAD_REQUEST, data=response_data)

        application = dana_customer_data.application
        query_info_result_list = []
        query_info = query_info_list[0]  # For now only allow 1 query type per hit
        if query_info["queryType"] == DanaQueryTypeAccountInfo.CREDITOR_CHECK:
            is_eligible = dana_max_creditor_check(dana_customer_data, application)
            query_result = {
                "queryType": query_info["queryType"],
                "queryValue": {
                    "status": is_eligible,
                    "lenderScore": application.creditscore.score.upper(),
                },
            }
            query_info_result_list.append(query_result)

        elif query_info["queryType"] == DanaQueryTypeAccountInfo.DBR_ALLOWED:
            is_eligible, max_loan_amount = dana_validate_dbr(
                application, query_info["queryTypeParam"]["repaymentPlanList"]
            )
            query_result = {
                "queryType": query_info["queryType"],
                "queryValue": {
                    "available": is_eligible,
                    "maxLimitAllowed": {
                        "value": "{:.2f}".format(max_loan_amount),
                        "currency": "IDR",
                    },
                },
            }
            query_info_result_list.append(query_result)

        logger.info(
            {
                "action": "dana_query_account_info",
                "query_type": query_info["queryType"],
                "request_data": request.data,
                "result": query_info_result_list,
            }
        )
        response_data = {
            "responseCode": AccountInfoResponseCode.SUCCESS.code,
            "responseMessage": AccountInfoResponseCode.SUCCESS.message,
            "queryInfoResultList": query_info_result_list,
        }
        return Response(status=status.HTTP_200_OK, data=response_data)
