import logging

from django.db.models import Sum
from django.utils import timezone

from rest_framework.response import Response
from rest_framework.status import HTTP_403_FORBIDDEN

from juloserver.followthemoney.models import LenderBucket
from juloserver.followthemoney.serializers import BucketLenderSerializer, ListApplicationSerializer
from juloserver.followthemoney.services import (
    RedisCacheLoanBucketXidPast,
    assign_lenderbucket_xid_to_lendersignature_service,
    reassign_lender_julo_one,
    get_max_limit,
    get_lender_bucket_xids_by_loans,
)
from juloserver.followthemoney.tasks import generate_summary_lender_loan_agreement
from juloserver.followthemoney.utils import (
    general_error_response,
    generate_lenderbucket_xid,
    server_error_response,
    success_response,
    spoofing_response,
    mapping_loan_and_application_status_code,
)
from juloserver.followthemoney.views.application_views import FollowTheMoneyAPIView
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Loan
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.merchant_financing.tasks import (
    merchant_financing_disbursement_process_task,
    generate_mf_std_skrtp,
)
from juloserver.partnership.constants import PartnershipLoanStatusChangeReason
from juloserver.partnership.models import PartnerLoanRequest
from juloserver.merchant_financing.lender_dashboard.services import (
    get_applications_dictionary,
)

logger = logging.getLogger(__name__)


class LenderApprovalView(FollowTheMoneyAPIView):
    http_method_names = ["post"]
    serializer_class = BucketLenderSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        approved_loan_ids = data["application_ids"].get("approved", [])
        rejected_loan_ids = data["application_ids"].get("rejected", [])
        loans = Loan.objects.filter(id__in=approved_loan_ids + rejected_loan_ids).select_related(
            "product"
        )
        for loan in loans:
            product = loan.product
            if product.product_line_id != ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT:
                return general_error_response(
                    "product tidak sesuai untuk loan_id: {}".format(loan.id)
                )

        approved_loans = Loan.objects.filter(id__in=approved_loan_ids).select_related(
            "account", "application", "account__account_lookup"
        )
        total = approved_loans.aggregate(
            sum_loan_disbursement_amount=Sum("loan_disbursement_amount"),
            sum_loan_amount=Sum("loan_amount"),
        )
        rejected_loans = Loan.objects.filter(id__in=rejected_loan_ids).select_related(
            "account", "account__account_lookup"
        )

        try:
            lender_bucket_id = None
            total_approved = len(approved_loans) > 0
            if total_approved > 0:
                lender_bucket_xid = generate_lenderbucket_xid()
                lender_bucket = LenderBucket.objects.create(
                    partner_id=user.partner.id,
                    total_approved=len(approved_loan_ids),
                    total_rejected=len(rejected_loan_ids),
                    total_disbursement=total.get("sum_loan_disbursement_amount", 0),
                    total_loan_amount=total.get("sum_loan_amount", 0),
                    loan_ids=data["application_ids"],
                    is_disbursed=False,
                    is_active=True,
                    action_time=timezone.now(),
                    action_name="Disbursed",
                    lender_bucket_xid=lender_bucket_xid,
                )

                # cache lender bucket xid for getting application past in lender dashboard
                redis_cache = RedisCacheLoanBucketXidPast()
                redis_cache.set_keys(approved_loan_ids, lender_bucket_xid)

                # generate summary lla
                assign_lenderbucket_xid_to_lendersignature_service(
                    approved_loans, lender_bucket_xid
                )
                generate_summary_lender_loan_agreement.delay(lender_bucket.id)
                lender_bucket_id = lender_bucket.id

                for loan in approved_loans:
                    if loan.loan_status.status_code != LoanStatusCodes.LENDER_APPROVAL:
                        continue

                    update_loan_status_and_loan_history(
                        loan.id,
                        new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        change_reason=PartnershipLoanStatusChangeReason.LOAN_APPROVED_BY_LENDER,
                    )

                    generate_mf_std_skrtp.delay(loan.id)
                    merchant_financing_disbursement_process_task.delay(loan.id)

            for rejected_loan in rejected_loans.iterator():
                if rejected_loan.loan_status.status_code != LoanStatusCodes.LENDER_APPROVAL:
                    continue

                update_loan_status_and_loan_history(
                    loan_id=rejected_loan.id,
                    new_status_code=LoanStatusCodes.LENDER_REJECT,
                    change_reason=PartnershipLoanStatusChangeReason.LOAN_REJECTED_BY_LENDER,
                )
                reassign_lender_julo_one(rejected_loan.id)

            return success_response({"lender_bucket_id": lender_bucket_id})
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {
                    "action_view": "merchant_financing.lender_dashboard - LenderApprovalView",
                    "data": data,
                    "errors": str(e),
                }
            )
            return server_error_response()


class ListApplicationViews(FollowTheMoneyAPIView):
    http_method_names = ["get"]
    serializer_class = ListApplicationSerializer

    def get(self, request, *args, **kwargs):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user
        if not user.lendercurrent:
            return Response(
                status=HTTP_403_FORBIDDEN,
                data={"errors": "User does not have a lender", "user_id": user.id},
            )

        try:
            limit = request.GET.get("limit", 25)
            limit = get_max_limit(limit=limit)
            order = request.GET.get("order", "asc")  # FIFO support
            loan_id = request.GET.get("application_id")
            last_loan_id = request.GET.get("last_application_id")
            # partner_id = request.GET.get("partner_id")

            exclude_ = {}
            filter_ = dict(
                lender=user.lendercurrent,
                loan_status=LoanStatusCodes.LENDER_APPROVAL,
                product__product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
            )
            if loan_id:
                filter_["id"] = loan_id

            order_by = "-udate"
            if order == "desc":
                if last_loan_id:
                    filter_["id__lt"] = last_loan_id
            elif order == "asc":
                order_by = "udate"
                if last_loan_id:
                    filter_["id__gt"] = last_loan_id

            lender_bucket = LenderBucket.objects.filter(
                is_active=True, partner_id=user.partner.pk
            ).last()
            if lender_bucket:
                loan_ids = lender_bucket.loan_ids
                exclude_["id__in"] = loan_ids["approved"] + loan_ids["rejected"]

            loans = Loan.objects.filter(**filter_).exclude(**exclude_).order_by(order_by)[:limit]
            application_dict = get_applications_dictionary(loans)
            idx = 0
            res_data = []
            for loan in loans:
                application = application_dict[loan.application_id2]["application"]
                creditscore = application_dict[loan.application_id2]["creditscore"]
                product_lookup = loan.product
                product_code = getattr(product_lookup, "id", None)
                product_line_id = getattr(product_lookup, "product_line_id", None)
                interest_rate = getattr(product_lookup, "interest_rate", 0)

                credit_score = ""
                if creditscore.score:
                    credit_score = creditscore.score.upper()

                if product_line_id == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT:
                    idx += 1

                    res_data.append(
                        {
                            "id": loan.id,
                            "loan_xid": loan.loan_xid,
                            "cdate": loan.cdate,
                            "udate": loan.udate,
                            "loan_disbursement_amount": loan.loan_disbursement_amount,
                            "loan_purpose": loan.loan_purpose,
                            "loan_amount": loan.loan_amount,
                            "loan_duration": loan.loan_duration,
                            "product": product_code,
                            "application_xid": str(loan.loan_xid),
                            "loan__loan_amount": loan.loan_amount,
                            "loan__loan_duration": loan.loan_duration,
                            "creditscore__score": credit_score,
                            "fullname": application.fullname,
                            "interest": interest_rate,
                        }
                    )

            return success_response(spoofing_response(res_data, "fullname", 2))

        except Exception as e:
            get_julo_sentry_client().captureException()

            logger.error(
                {
                    "action_view": "merchant_financing.lender_dashboard - ListApplicationViews",
                    "data": data,
                    "errors": str(e),
                }
            )

            return server_error_response()


class ListApplicationPastViews(FollowTheMoneyAPIView):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        data = request.data
        user = self.request.user
        if not user.lendercurrent:
            return Response(
                status=HTTP_403_FORBIDDEN,
                data={"errors": "User does not have a lender", "user_id": user.id},
            )

        try:
            limit = request.GET.get("limit", 25)
            limit = get_max_limit(limit=limit)
            order = request.GET.get("order", "asc")  # FIFO support
            loan_xid = request.GET.get("loan_xid")
            last_in_date = request.GET.get("last_in_date")
            # partner_id = request.GET.get("partner_id")

            exclude_ = {}
            res_data = []
            lender_current = user.lendercurrent
            filter_ = dict(
                lender=lender_current,
                loan_status__gte=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                loan_status__lte=LoanStatusCodes.CURRENT,
                product__product_line=ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT,
            )
            order_by = "-udate"
            if loan_xid:
                filter_["loan_xid"] = loan_xid

            if order == "asc":
                if lender_current.lender_name in {"ska", "ska2"}:
                    order_by = "sphp_accepted_ts"
                else:
                    order_by = "udate"
                if last_in_date:
                    filter_["udate__gt"] = last_in_date

            elif order == "desc":
                if lender_current.lender_name in {"ska", "ska2"}:
                    order_by = "-sphp_accepted_ts"
                if last_in_date:
                    filter_["udate__lt"] = last_in_date

            loan_lender_buckets_xids = dict()
            loans = (
                Loan.objects.only(
                    'pk',
                    'loan_xid',
                    'cdate',
                    'udate',
                    'loan_disbursement_amount',
                    'loan_status',
                    'loan_purpose',
                    'loan_amount',
                    'loan_duration',
                    'account',
                    'application',
                    'application_id2',
                    'sphp_accepted_ts',
                )
                .filter(**filter_)
                .exclude(**exclude_)
                .order_by(order_by)[:limit]
            )
            if loans:
                loan_lender_buckets_xids = get_lender_bucket_xids_by_loans(loans)

            application_dict = get_applications_dictionary(loans)
            for loan in loans:
                application = application_dict[loan.application_id2]["application"]
                creditscore = application_dict[loan.application_id2]["creditscore"]
                lender_bucket_xid = loan_lender_buckets_xids.get(loan.id, "")
                res_data.append(
                    {
                        "in_date": loan.udate,
                        "application_xid": str(loan.loan_xid),
                        "lender_bucket_xid": str(lender_bucket_xid),
                        "fullname": application.fullname,
                        "creditscore__score": creditscore.score.upper(),
                        "loan__loan_amount": loan.loan_amount,
                        "loan__loan_duration": loan.loan_duration,
                        "status": mapping_loan_and_application_status_code(loan.loan_status_id),
                        "loan_purpose": loan.loan_purpose,
                    }
                )

            return success_response(spoofing_response(res_data, "fullname", 2))

        except Exception as e:
            get_julo_sentry_client().captureException()

            logger.error(
                {
                    "action_view": "merchant_financing.lender_dashboard - ListApplicationViews",
                    "data": data,
                    "errors": str(e),
                }
            )

            return server_error_response()
