import logging

from django.db.models import Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
)
from bulk_update.helper import bulk_update

from juloserver.channeling_loan.constants import ChannelingStatusConst, ChannelingConst
from juloserver.followthemoney.views.application_views import FollowTheMoneyAPIView
from juloserver.followthemoney.utils import (
    success_response,
    server_error_response,
    spoofing_response,
    general_error_response,
    generate_lenderbucket_xid,
)
from juloserver.followthemoney.serializers import (
    ListApplicationSerializer,
    BucketLenderSerializer,
)
from juloserver.followthemoney.models import (
    LenderBucket,
)
from juloserver.followthemoney.services import (
    get_list_product_line_code_need_to_hide,
    get_application_credit_score,
    assign_lenderbucket_xid_to_lendersignature_service,
    get_max_limit,
)
from juloserver.followthemoney.tasks import (
    generate_summary_lender_loan_agreement,
    reset_julo_one_loan_agreement,
)
from juloserver.loan.tasks.lender_related import (
    julo_one_disbursement_trigger_task,
)
from juloserver.channeling_loan.services.general_services import (
    get_channeling_loan_configuration,
    is_channeling_lender_dashboard_active,
)
from juloserver.channeling_loan.models import ChannelingLoanStatus
from juloserver.julo.constants import (
    FalseRejectMiniConst,
)

from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import (
    Loan,
    FeatureSetting,
)
from juloserver.julo.constants import FeatureNameConst as JuloFeatureNameConst
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.channeling_loan.tasks import (
    send_loan_for_channeling_to_bss_task,
    send_loans_for_channeling_to_dbs_task,
)

logger = logging.getLogger(__name__)


class ListApplicationViews(FollowTheMoneyAPIView):
    http_method_names = ["get"]
    serializer_class = ListApplicationSerializer

    def get(self, request, channeling_type):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user
        channeling_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_config:
            return Response(
                status=HTTP_403_FORBIDDEN,
                data={
                    "errors": "channeling_type not found",
                    "channeling_type": channeling_type,
                },
            )

        try:
            limit = request.GET.get('limit', 25)
            limit = get_max_limit(limit=limit)

            order = request.GET.get("order", "asc")  # FIFO support
            loan_id = request.GET.get("application_id")
            last_loan_id = request.GET.get("last_application_id")

            exclude_ = {}
            hidden_product_line_codes = get_list_product_line_code_need_to_hide()
            if hidden_product_line_codes:
                exclude_["loan__product__product_line__in"] = hidden_product_line_codes

            lender = user.lendercurrent
            if not lender:
                return Response(
                    status=HTTP_403_FORBIDDEN,
                    data={"errors": "User dont have a lender", "user_id": user.id},
                )

            if channeling_config['general']['LENDER_NAME'] != lender.lender_name:
                return Response(
                    status=HTTP_403_FORBIDDEN,
                    data={"errors": "User does not have permission"},
                )

            filter_ = dict(
                loan__loan_status=LoanStatusCodes.CURRENT,
                channeling_type=channeling_type,
                channeling_status=ChannelingStatusConst.PROCESS,
            )

            lender_bucket = LenderBucket.objects.filter(
                is_active=True, partner=user.partner
            ).last()
            if lender_bucket:
                loan_ids = lender_bucket.loan_ids
                exclude_["loan__id__in"] = loan_ids["approved"] + loan_ids["rejected"]

            if loan_id:
                filter_["loan__id"] = loan_id

            order_by = "-udate"
            if order == "desc":
                if last_loan_id:
                    filter_["loan__id__lt"] = last_loan_id
            elif order == "asc":
                order_by = "udate"
                if last_loan_id:
                    filter_["loan__id__gt"] = last_loan_id

            loans = (
                ChannelingLoanStatus.objects.filter(**filter_)
                .exclude(**exclude_)
                .only("loan")
                .order_by(order_by)[:limit]
            )
            res_data = []
            for loan in loans:
                loan = loan.loan
                loan_data = {
                    "id": loan.id,
                    "loan_xid": loan.loan_xid,
                    "cdate": loan.cdate,
                    "udate": loan.udate,
                    "loan_disbursement_amount": loan.loan_disbursement_amount,
                    "loan_purpose": loan.loan_purpose,
                    "loan_amount": loan.loan_amount,
                    "loan_duration": loan.loan_duration,
                    "product": loan.product.product_code,
                    "application_xid": loan.loan_xid,
                    "interest": loan.interest_rate_monthly,
                    "loan__loan_amount": loan.loan_amount,
                    "loan__loan_duration": loan.loan_duration,
                    # "creditscore__score": FalseRejectMiniConst.SCORE,
                    "fullname": "",
                }

                application = loan.get_application
                if loan.account and application:
                    loan_data["fullname"] = application.fullname
                    loan_data["creditscore__score"] = (
                        get_application_credit_score(application)
                        or FalseRejectMiniConst.SCORE
                    )

                if loan_data["interest"] == 0:
                    loan_data["interest"] = None

                res_data.append(loan_data)

            return success_response(spoofing_response(res_data, "fullname", 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {
                    "action_view": "FollowTheMoney::ListApplicationViews",
                    "data": data,
                    "errors": str(e),
                }
            )
            JuloException(e)
            return server_error_response()


class CreateLenderBucketChannelingViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = BucketLenderSerializer

    def post(self, request, channeling_type):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user
        channeling_config = get_channeling_loan_configuration(channeling_type)
        if not channeling_config:
            return Response(
                status=HTTP_403_FORBIDDEN,
                data={
                    "errors": "channeling_type not found",
                    "channeling_type": channeling_type,
                },
            )

        is_lender_dashboard_enabled = is_channeling_lender_dashboard_active(channeling_type)
        if not is_lender_dashboard_enabled:
            return Response(
                status=HTTP_403_FORBIDDEN,
                data={
                    "errors": "Lender dashboard disabled",
                    "channeling_type": channeling_type,
                },
            )

        approved_loan_ids = data['application_ids'].get('approved', [])
        rejected_loan_ids = data['application_ids'].get('rejected', [])

        approved_loan_ids_set = set(approved_loan_ids)
        rejected_loan_ids_set = set(rejected_loan_ids)

        common_ids = approved_loan_ids_set.intersection(rejected_loan_ids_set)
        if common_ids:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "errors": "loan cannot approved and rejected at the same time",
                    "channeling_type": channeling_type,
                },
            )

        approved_loans = (
            ChannelingLoanStatus.objects.filter(
                channeling_status=ChannelingStatusConst.PENDING,
                loan_id__in=approved_loan_ids,
                channeling_type=channeling_type,
        ).select_related("loan"))

        if len(approved_loan_ids) != len(approved_loans):
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "errors": "loan not found or loan already processed",
                    "channeling_type": channeling_type,
                },
            )

        loan_ids = []
        for loan in approved_loans:
            loan_ids.append(loan.loan_id)

        loans = (
            Loan.objects.filter(id__in=loan_ids)
        )

        total = approved_loans.aggregate(
            sum_loan_disbursement_amount=Sum('loan__loan_disbursement_amount'),
            sum_loan_amount=Sum('loan__loan_amount'),
        )

        rejected_loans = (
            ChannelingLoanStatus.objects.filter(
                channeling_status=ChannelingStatusConst.PENDING,
                loan_id__in=rejected_loan_ids,
                channeling_type=channeling_type,
        ).select_related("loan"))

        if len(rejected_loan_ids) != len(rejected_loans):
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={
                    "errors": "loan not found or loan already processed",
                    "channeling_type": channeling_type,
                },
            )

        try:
            lender_bucket_id = None
            total_approved = len(approved_loan_ids) > 0
            channeling_loan_status_list = []
            loans_send_to_bss = []
            if total_approved > 0:
                lender_bucket_xid = generate_lenderbucket_xid()
                lender_bucket = LenderBucket.objects.create(
                    partner=user.partner,
                    total_approved=len(approved_loan_ids),
                    total_rejected=len(rejected_loan_ids),
                    total_disbursement=total.get('sum_loan_disbursement_amount', 0),
                    total_loan_amount=total.get('sum_loan_amount', 0),
                    loan_ids=data['application_ids'],
                    is_disbursed=False,
                    is_active=True,
                    action_time=timezone.now(),
                    action_name='Disbursed',
                    lender_bucket_xid=lender_bucket_xid,
                )

                # generate summary lla
                assign_lenderbucket_xid_to_lendersignature_service(
                    loans, lender_bucket_xid
                )
                lender_bucket_id = lender_bucket.id
                for channeling_loan_status in approved_loans.iterator():
                    loans_send_to_bss.append(channeling_loan_status.loan_id)
                    channeling_loan_status.channeling_status = ChannelingStatusConst.PROCESS
                    channeling_loan_status_list.append(channeling_loan_status)

            for rejected_loan in rejected_loans.iterator():
                channeling_loan_status = rejected_loan
                channeling_loan_status.channeling_status = ChannelingStatusConst.REJECT
                channeling_loan_status.reason = "Reject By Lender"
                channeling_loan_status_list.append(channeling_loan_status)

            if channeling_loan_status_list:
                bulk_update(channeling_loan_status_list, update_fields=['channeling_status', 'reason'])

            # Send data to API if lender dashboard is enabled
            if is_lender_dashboard_enabled:
                if channeling_type == ChannelingConst.BSS:
                    execute_after_transaction_safely(
                        lambda: send_loan_for_channeling_to_bss_task.delay(
                            loans_send_to_bss, channeling_config, channeling_type
                        )
                    )
                elif channeling_type == ChannelingConst.DBS:
                    execute_after_transaction_safely(
                        lambda: send_loans_for_channeling_to_dbs_task.delay(loans_send_to_bss)
                    )

            return success_response({'lender_bucket_id': lender_bucket_id})
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - CreateLenderBucketViews',
                'data': data,
                'errors': str(e)
            })
            return server_error_response()
