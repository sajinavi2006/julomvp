import time
import uuid
import logging

from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from juloserver.dana.constants import DanaBasePath

from juloserver.dana.views import DanaAPIView
from juloserver.dana.models import DanaCustomerData

from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework import status

from juloserver.dana.repayment.serializers import DanaRepaymentSerializer
from juloserver.dana.constants import (
    RepaymentResponseCodeMessage,
    RejectCodeMessage,
    RepaymentRejectCode,
)
from juloserver.dana.repayment.services import (
    construct_repayment_redis_key,
    check_invalid_loan_status,
    create_pending_repayment_reference,
    run_repayment_sync_process,
)
from juloserver.dana.repayment.tasks import run_repayment_async_process
from juloserver.dana.utils import (
    get_redis_key,
    construct_massive_logger,
    set_redis_key,
)
from juloserver.dana.models import DanaRepaymentReference

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.statuses import LoanStatusCodes


sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


class BaseDanaRepaymentAPIView(DanaAPIView):
    base_path = DanaBasePath.repayment


class DanaRepaymentView(BaseDanaRepaymentAPIView):
    serializer_class = DanaRepaymentSerializer

    def post(self, request: Request) -> Response:
        log_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DANA_MASSIVE_LOG,
        ).first()

        is_active_log_feature_setting = (
            log_feature_setting
            and log_feature_setting.is_active
            and log_feature_setting.parameters.get(self.base_path)
        )

        feature_setting_repayment_async_process = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.DANA_ENABLE_REPAYMENT_ASYNCHRONOUS,
        ).first()

        log_data = dict()

        # Check Logger Validation Execution Time
        if is_active_log_feature_setting:
            start_validation_execution_time = time.time()
            start_validation_execution_datetime = timezone.localtime(timezone.now())

        # idempotency check
        repayment_redis_key = construct_repayment_redis_key(self.request.data)
        partner_reference_no = self.request.data.get('partnerReferenceNo')
        customer_identifier = self.request.data.get('customerId')
        reference_no_from_redis = None
        data_response_idempotency = {
            "responseCode": RepaymentResponseCodeMessage.SUCCESS.code,
            "responseMessage": RepaymentResponseCodeMessage.SUCCESS.message,
            "referenceNo": None,
            "partnerReferenceNo": partner_reference_no,
            "additionalInfo": {
                "rejectCode": RejectCodeMessage.IDEMPOTENCY.code,
                "rejectMessage": RejectCodeMessage.IDEMPOTENCY.message.format(partner_reference_no),
            },
        }

        try:
            if repayment_redis_key:
                reference_no_from_redis = get_redis_key(repayment_redis_key)
                if reference_no_from_redis:
                    data_response_idempotency['referenceNo'] = reference_no_from_redis

                    # Check Logger Validation Execution Time
                    if is_active_log_feature_setting:
                        validation_logger = construct_massive_logger(
                            start_validation_execution_time,
                            start_validation_execution_datetime,
                        )

                        log_data = {
                            'action': 'dana_logging_execution_time',
                            'partnerReferenceNo': partner_reference_no,
                            'validation_execution_time': validation_logger,
                        }

                        logger.info(log_data)

                    return Response(status=status.HTTP_200_OK, data=data_response_idempotency)
        except Exception as e:
            logger.error(
                {
                    "action": "dana_repayment_check_idempotency",
                    "message": "error redis {}".format(str(e)),
                }
            )

        if not reference_no_from_redis:
            dana_repayment_reference = list(
                DanaRepaymentReference.objects.filter(
                    partner_reference_no=partner_reference_no, customer_id=customer_identifier
                )
                .order_by('bill_id')
                .annotate(billId=F('bill_id'), billStatus=F('bill_status'))
                .values(
                    'partner_reference_no',
                    'customer_id',
                    'billId',
                    'billStatus',
                    'total_repayment_amount',
                    'reference_no',
                )
            )
            if dana_repayment_reference:
                data_for_construct_key = {
                    'partnerReferenceNo': dana_repayment_reference[0]['partner_reference_no'],
                    'customerId': dana_repayment_reference[0]['customer_id'],
                    'repaymentDetailList': dana_repayment_reference,
                }
                repayment_redis_key_data_from_db = construct_repayment_redis_key(
                    data_for_construct_key
                )
                if repayment_redis_key_data_from_db == repayment_redis_key:
                    data_response_idempotency['referenceNo'] = dana_repayment_reference[0][
                        'reference_no'
                    ]

                    # End Check Logger Validation Execution Time
                    if is_active_log_feature_setting:
                        validation_logger = construct_massive_logger(
                            start_validation_execution_time,
                            start_validation_execution_datetime,
                        )

                        log_data = {
                            'action': 'dana_logging_execution_time',
                            'partnerReferenceNo': partner_reference_no,
                            'validation_execution_time': validation_logger,
                        }

                        logger.info(log_data)

                    return Response(status=status.HTTP_200_OK, data=data_response_idempotency)

        serializer = self.serializer_class(data=self.request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        dana_customer_id = validated_data['customerId']
        partner_reference_no = validated_data['partnerReferenceNo']
        lender_product_id = validated_data['lenderProductId']
        float_credit_usage_mutation = float(
            validated_data.get('creditUsageMutation', {}).get('value', 0)
        )
        credit_usage_mutation = int(float_credit_usage_mutation)
        repayment_id = validated_data.get('additionalInfo', {}).get('repaymentId', '')

        dana_customer_data = (
            DanaCustomerData.objects.select_related('account')
            .filter(
                dana_customer_identifier=dana_customer_id,
                lender_product_id=lender_product_id,
            )
            .last()
        )
        if not dana_customer_data:
            not_found_response = {
                'code': RepaymentResponseCodeMessage.BAD_REQUEST.code,
                'message': RepaymentResponseCodeMessage.BAD_REQUEST.message,
            }
            data = {
                'responseCode': not_found_response['code'],
                'responseMessage': not_found_response['message'],
                'partnerReferenceNo': partner_reference_no,
                'referenceNo': None,
                'additionalInfo': {"errors": {"customerId": ["customerId data not found"]}},
            }
            return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

        account = dana_customer_data.account

        total_repayment_amount = 0
        list_bill_not_processed = []
        list_bill_pending = []
        total_repayment_detail = len(validated_data['repaymentDetailList'])

        index = 0

        while index < len(validated_data['repaymentDetailList']):
            bill_id = validated_data['repaymentDetailList'][index]['billId']

            loan_check = check_invalid_loan_status(bill_id, dana_customer_id)
            if not loan_check.is_valid:
                if loan_check.loan_status == LoanStatusCodes.CANCELLED_BY_CUSTOMER:
                    list_bill_not_processed.append(bill_id)
                    validated_data['repaymentDetailList'].pop(index)
                else:
                    list_bill_pending.append(validated_data['repaymentDetailList'][index])
                    validated_data['repaymentDetailList'].pop(index)
            else:
                total_repayment_amount += int(
                    float(
                        validated_data['repaymentDetailList'][index]['totalRepaymentAmount'][
                            'value'
                        ]
                    )
                )
                index += 1

        reference_no = str(uuid.uuid4())

        data = {
            "responseCode": RepaymentResponseCodeMessage.SUCCESS.code,
            "responseMessage": RepaymentResponseCodeMessage.SUCCESS.message,
            "referenceNo": reference_no,
            "partnerReferenceNo": partner_reference_no,
            "additionalInfo": {},
        }

        if total_repayment_detail == len(list_bill_not_processed):
            data['additionalInfo'][
                'rejectCode'
            ] = RepaymentRejectCode.All_BILL_ID_HAS_LOAN_CANCELED.code
            data['additionalInfo'][
                'rejectReason'
            ] = RepaymentRejectCode.All_BILL_ID_HAS_LOAN_CANCELED.reason

            # End Check Logger Validation Execution Time
            if is_active_log_feature_setting:
                validation_logger = construct_massive_logger(
                    start_validation_execution_time,
                    start_validation_execution_datetime,
                )

                log_data = {
                    'action': 'dana_logging_execution_time',
                    'partnerReferenceNo': partner_reference_no,
                    'validation_execution_time': validation_logger,
                }

                logger.info(log_data)

            return Response(status=status.HTTP_200_OK, data=data)

        # End Check Logger Validation Execution Time
        if is_active_log_feature_setting:
            validation_logger = construct_massive_logger(
                start_validation_execution_time,
                start_validation_execution_datetime,
            )

            log_data = {
                'action': 'dana_logging_execution_time',
                'partnerReferenceNo': partner_reference_no,
                'validation_execution_time': validation_logger,
            }

        repaid_time = parse_datetime(validated_data['repaidTime'])

        # If async task process repayment is active, stored data in pending repayment
        if (
            feature_setting_repayment_async_process
            and feature_setting_repayment_async_process.is_active
        ):
            all_list_repayment = validated_data['repaymentDetailList'] + list_bill_pending
            if repayment_redis_key:
                set_redis_key(repayment_redis_key, reference_no, 300)
            repayment_created = create_pending_repayment_reference(
                all_list_repayment,
                partner_reference_no,
                dana_customer_id,
                reference_no,
                repaid_time,
                credit_usage_mutation,
                repayment_id,
                lender_product_id,
            )

            run_repayment_async_process.delay(
                repayment_created.bill_ids,
                repayment_created.list_partner_references_no,
            )
        else:
            # Processed Pending Repayment
            if list_bill_pending:
                create_pending_repayment_reference(
                    list_bill_pending,
                    partner_reference_no,
                    dana_customer_id,
                    reference_no,
                    repaid_time,
                    credit_usage_mutation,
                    repayment_id,
                    lender_product_id,
                )

            # Processed Not Pending Repayment
            if validated_data['repaymentDetailList']:
                is_success_to_process = run_repayment_sync_process(
                    validated_data=validated_data,
                    partner_reference_no=partner_reference_no,
                    reference_no=reference_no,
                    account=account,
                    total_repayment_amount=total_repayment_amount,
                    repaid_time=repaid_time,
                    is_active_log_feature_setting=is_active_log_feature_setting,
                    log_data=log_data,
                    repayment_redis_key=repayment_redis_key,
                )

                if not is_success_to_process:
                    duplicate_response = {
                        'code': RepaymentResponseCodeMessage.INCONSISTENT_REQUEST.code,
                        'message': RepaymentResponseCodeMessage.INCONSISTENT_REQUEST.message,
                    }
                    data = {
                        'responseCode': duplicate_response['code'],
                        'responseMessage': duplicate_response['message'],
                        'partnerReferenceNo': partner_reference_no,
                        'referenceNo': None,
                        'additionalInfo': {
                            "errors": {"partnerReferenceNo": ["duplicate partnerReferenceNo"]}
                        },
                    }
                    return Response(status=status.HTTP_400_BAD_REQUEST, data=data)

        if len(list_bill_not_processed) != 0:
            data['additionalInfo'][
                'rejectCode'
            ] = RepaymentRejectCode.HAS_BILL_ID_WITH_LOAN_CANCELED.code
            data['additionalInfo'][
                'rejectReason'
            ] = RepaymentRejectCode.HAS_BILL_ID_WITH_LOAN_CANCELED.reason
            data['additionalInfo']['billIdNotProcessed'] = list_bill_not_processed

        return Response(status=status.HTTP_200_OK, data=data)
