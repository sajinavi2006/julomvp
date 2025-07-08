import logging

from django.db import transaction
from django.utils import timezone

from django.db.models import Sum
from past.utils import old_div
from rest_framework.status import HTTP_403_FORBIDDEN

from juloserver.dana.loan.tasks import dana_generate_auto_lender_agreement_document_task
from juloserver.dana.services import dana_update_loan_status_and_loan_history
from juloserver.dana.tasks import dana_disbursement_trigger_task
from juloserver.followthemoney.constants import LenderNameByPartner
from juloserver.followthemoney.serializers import BucketLenderSerializer, ListApplicationSerializer
from juloserver.followthemoney.utils import (
    success_response,
    server_error_response,
    general_error_response,
    spoofing_response,
    mapping_loan_and_application_status_code,
    generate_lenderbucket_xid,
)
from juloserver.grab.constants import GRAB_ACCOUNT_LOOKUP_NAME
from juloserver.julo.constants import (
    FalseRejectMiniConst,
    ExperimentConst,
    FeatureNameConst as JuloFeatureNameConst,
)
from juloserver.followthemoney.models import LenderBucket, LenderCurrent
from juloserver.followthemoney.views.application_views import FollowTheMoneyAPIView
from juloserver.followthemoney.services import (
    get_lender_bucket_xids_by_loans,
    get_loan_level_details,
    get_list_product_line_code_need_to_hide,
    RedisCacheLoanBucketXidPast,
    assign_lenderbucket_xid_to_lendersignature_service,
    reassign_lender_julo_one,
)
from juloserver.followthemoney.tasks import (
    generate_summary_lender_loan_agreement,
    reset_julo_one_loan_agreement,
    generate_julo_one_loan_agreement,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Loan,
    Application,
    FeatureSetting,
    ApplicationExperiment,
    CreditMatrixRepeatLoan,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import LoanStatusCodes

from rest_framework.response import Response

from juloserver.julocore.python2.utils import py2round
from juloserver.loan.models import TenorBasedPricing, LoanAdjustedRate, LoanZeroInterest
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.loan.tasks.lender_related import (
    julo_one_disbursement_trigger_task,
    grab_disbursement_trigger_task,
)
from juloserver.partnership.constants import (
    PartnershipAccountLookup,
    PartnershipLoanStatusChangeReason,
)

logger = logging.getLogger(__name__)


class PartnershipListApplicationViews(FollowTheMoneyAPIView):
    http_method_names = ['get']
    serializer_class = ListApplicationSerializer

    def get(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        try:
            limit = int(request.GET.get('limit', 25))
            order = request.GET.get('order', 'asc')  # FIFO support
            loan_id = request.GET.get('application_id')
            last_loan_id = request.GET.get('last_application_id')
            product_line_code = request.GET.get('product_line_code')

            exclude_ = {}

            if not user.lendercurrent:
                return Response(
                    status=HTTP_403_FORBIDDEN,
                    data={'errors': 'User dont have a lender', 'user_id': user.id},
                )

            filter_ = dict(
                loan_status=LoanStatusCodes.LENDER_APPROVAL,
                lender=user.lendercurrent,
                lendersignature__isnull=True,
            )

            lender_name = user.lendercurrent.lender_name
            if loan_id:
                filter_['id'] = loan_id

            order_by = '-udate'
            if order == "desc":
                if last_loan_id:
                    filter_['id__lt'] = last_loan_id
            elif order == "asc":
                order_by = 'udate'
                if last_loan_id:
                    filter_['id__gt'] = last_loan_id

            if product_line_code:
                filter_['product__product_line'] = product_line_code
                if int(product_line_code) in ProductLineCodes.DANA_PRODUCT:
                    # this condition so that we do not query feature setting
                    # if the product is not Dana
                    fs_dana_auto_approve = FeatureSetting.objects.filter(
                        feature_name=JuloFeatureNameConst.DANA_LENDER_AUTO_APPROVE, is_active=True
                    ).first()
                    if fs_dana_auto_approve:
                        filter_['danaloanreference__is_whitelisted'] = True

            loans = (
                Loan.objects.filter(**filter_)
                .using('replica')
                .exclude(**exclude_)
                .order_by(order_by)[:limit]
            )
            if product_line_code and int(product_line_code) in ProductLineCodes.DANA_PRODUCT:
                res_data = []
                application_ids = list(loans.values_list('application_id2', flat=True))

                applications = (
                    Application.objects.select_related("creditscore")
                    .filter(id__in=application_ids)
                    .values("id", "fullname", "creditscore__score")
                )
                application_dict = {}
                for application in applications.iterator():
                    application_dict[application.get('id')] = {
                        'fullname': application.get('fullname'),
                        'score': application.get('creditscore__score'),
                    }

                loans = loans.select_related("product", "danaloanreference").values(
                    'danaloanreference__credit_usage_mutation',
                    'danaloanreference__amount',
                    'application_id2',
                    'id',
                    'loan_xid',
                    'cdate',
                    'udate',
                    'loan_disbursement_amount',
                    'loan_purpose',
                    'loan_amount',
                    'loan_duration',
                    'product__product_code',
                )
                for loan in loans.iterator():
                    # Loan or DanaLoanReference did not have relation to Application
                    # So we need to query it manually
                    interest_amount = loan.get(
                        'danaloanreference__credit_usage_mutation', 0
                    ) - loan.get('danaloanreference__amount', 0)
                    credit_score = ""
                    fullname = ""
                    application_data = application_dict.get(loan.get('application_id2'), None)
                    if application_data:
                        fullname = application_data.get("fullname", "")
                        credit_score = application_data.get("score", "")
                        if credit_score:
                            credit_score = credit_score.upper()

                    data = {
                        "id": loan.get('id'),
                        "loan_xid": loan.get('loan_xid'),
                        "cdate": loan.get('cdate'),
                        "udate": loan.get('udate'),
                        "loan_disbursement_amount": loan.get('loan_disbursement_amount'),
                        "loan_purpose": loan.get('loan_purpose'),
                        "loan_amount": loan.get('loan_amount'),
                        "loan_duration": loan.get('loan_duration'),
                        "product": loan.get('product__product_code'),
                        "application_xid": str(loan.get('loan_xid')),
                        "loan__loan_amount": loan.get('loan_amount'),
                        "loan__loan_duration": loan.get('loan_duration'),
                        "creditscore__score": credit_score,
                        "fullname": fullname,
                        "interest": interest_amount,
                    }
                    res_data.append(data)
            else:
                res_data = []
                application_ids = list(loans.values_list('application_id2', flat=True))

                application_experiments_mapping = {}
                application_experiments = ApplicationExperiment.objects.filter(
                    experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION,
                    application_id__in=application_ids,
                ).values('application_id')
                for application_experiment in application_experiments.iterator():
                    application_experiments_mapping[application_experiment['application_id']] = True

                applications = Application.objects.filter(id__in=application_ids).values(
                    "id", "fullname", "loan_purpose", "creditscore__score"
                )  # Select only the columns you need from Application

                application_dict = {}
                for application in applications:
                    app_id = application['id']
                    application_dict[app_id] = {
                        'fullname': application['fullname'],
                        'score': application['creditscore__score'],
                        'loan_purpose': application['loan_purpose'],
                        'false_reject_experiments': application_experiments_mapping.get(
                            app_id, False
                        ),
                    }

                loan_ids = list(loans.values_list('id', flat=True))

                loans = loans.select_related("application__customer").values(
                    'id',
                    'loan_xid',
                    'cdate',
                    'udate',
                    'loan_disbursement_amount',
                    'loan_purpose',
                    'loan_amount',
                    'loan_duration',
                    'product__interest_rate',
                    'application_id',
                    'application_id2',
                    'application__product_line_id',
                    'application__customer__fullname',
                    'application__loan_purpose',
                    'partnerloanrequest__partner__name',
                    'account_id',
                    'product',
                )

                # fetch interest_rate_monthly bulkyly
                credit_matrix_repeat_loans_mapping = {}
                credit_matrix_repeat_loans = CreditMatrixRepeatLoan.objects.filter(
                    loan_id__in=loan_ids
                ).values('loan_id', 'credit_matrix_repeat__interest')
                for cmrl in credit_matrix_repeat_loans.iterator():
                    credit_matrix_repeat_loans_mapping[cmrl.get('loan_id', None)] = cmrl.get(
                        'credit_matrix_repeat__interest'
                    )

                tenor_based_pricing_loans_mapping = {}
                tenor_based_pricing_loans = TenorBasedPricing.objects.filter(
                    loan_id__in=loan_ids
                ).values('loan_id', 'new_pricing')
                for tbpl in tenor_based_pricing_loans.iterator():
                    tenor_based_pricing_loans_mapping[tbpl.get('loan_id', None)] = tbpl.get(
                        'new_pricing'
                    )

                loan_adjusted_rate_loans_mapping = {}
                loan_adjusted_rate_loans = LoanAdjustedRate.objects.filter(
                    loan_id__in=loan_ids
                ).values('loan_id', 'adjusted_monthly_interest_rate')
                for larl in loan_adjusted_rate_loans.iterator():
                    loan_adjusted_rate_loans_mapping[larl.get('loan_id', None)] = larl.get(
                        'adjusted_monthly_interest_rate'
                    )

                loan_zero_interest_loans_mapping = {}
                loan_zero_interest_loans = LoanZeroInterest.objects.filter(
                    loan_id__in=loan_ids
                ).values('loan_id')
                for lzil in loan_zero_interest_loans.iterator():
                    loan_zero_interest_loans_mapping[lzil.get('loan_id', None)] = True

                gosel_loans = []
                for loan in loans.iterator():
                    name_partner_loan_request = loan.get('partner_loan_request__partner__name', "")
                    if (
                        name_partner_loan_request
                        and name_partner_loan_request == PartnerConstant.GOSEL
                    ):
                        gosel_loans.append(loan.get('loan_xid'))
                        continue

                    fullname = ""
                    loan_purpose = loan.get('loan_purpose', "")
                    credit_score = FalseRejectMiniConst.SCORE

                    interest = py2round(old_div(loan.get('product__interest_rate'), 12), 3)
                    loan_id = loan.get('id', None)
                    if credit_matrix_repeat_loans_mapping.get(loan_id, None):
                        interest = credit_matrix_repeat_loans_mapping.get(loan_id, None)
                    elif tenor_based_pricing_loans_mapping.get(loan_id, None):
                        interest = tenor_based_pricing_loans_mapping.get(loan_id, None)
                    elif loan_adjusted_rate_loans_mapping.get(loan_id, None):
                        interest = loan_adjusted_rate_loans_mapping.get(loan_id, None)
                    elif loan_zero_interest_loans_mapping.get(loan_id, False):
                        interest = 0

                    product_line_code = loan.get('application__product_line_id', None)
                    if product_line_code and product_line_code in ProductLineCodes.axiata():
                        fullname = loan.get('application__customer__fullname')
                        loan_purpose = loan.get('application__loan_purpose', "")

                    application_id2 = loan.get('application_id2', None)
                    if (
                        application_id2
                        and loan.get('account_id', None)
                        and application_dict.get(application_id2, None)
                    ):
                        application_data = application_dict.get(application_id2, None)
                        fullname = application_data.get('fullname', '')
                        credit_score = application_data.get("score", "")
                        if credit_score:
                            credit_score = credit_score.upper()

                        if application_data.get("loan_experiment", False):
                            credit_score = FalseRejectMiniConst.SCORE

                            # override for grab loan purpose will get from application level
                        if lender_name and lender_name in LenderNameByPartner.GRAB:
                            loan_purpose = application_data.get('loan_purpose')
                            # fetch the grab interest manually(ProductLookup already monthly for
                            # grab)
                            interest = loan.get('product__interest_rate')

                    if interest == 0:
                        interest = None

                    data = {
                        "id": loan_id,
                        "loan_xid": loan.get('loan_xid'),
                        "cdate": loan.get('cdate'),
                        "udate": loan.get('udate'),
                        "loan_disbursement_amount": loan.get('loan_disbursement_amount'),
                        "loan_purpose": loan_purpose,
                        "loan_amount": loan.get('loan_amount'),
                        "loan_duration": loan.get('loan_duration'),
                        "product": loan.get('product'),
                        "application_xid": str(loan.get('loan_xid', "")),
                        "loan__loan_amount": loan.get('loan_amount', None),
                        "loan__loan_duration": loan.get('loan_duration', None),
                        "creditscore__score": credit_score,
                        "fullname": fullname,
                        "interest": interest,
                    }
                    res_data.append(data)

                if len(gosel_loans) > 0:
                    new_res_data = []
                    gosel_loans = tuple(gosel_loans)
                    for app in res_data:
                        if app['loan_xid'] not in gosel_loans:
                            new_res_data.append(app)

                    res_data = new_res_data

            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {'action': 'PartnershipListApplicationViews', 'data': data, 'errors': str(e)}
            )
            JuloException(e)
            return server_error_response()


class PartnershipListApplicationPastViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = self.request.user
        data = request.data
        partner = user.partner

        if partner is None:
            return general_error_response("partner tidak ada.")

        try:
            order = request.GET.get('order', 'desc')
            limit = int(request.GET.get('limit', 25))
            loan_xid = request.GET.get('loan_xid')
            last_in_date = request.GET.get('last_in_date')
            product_line_code = request.GET.get('product_line_code')

            if not user.lendercurrent:
                return Response(
                    status=HTTP_403_FORBIDDEN,
                    data={'errors': 'User dont have a lender', 'user_id': user.id},
                )

            filter_ = dict(
                lender=user.lendercurrent,
                loan_status__gte=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                loan_status__lte=LoanStatusCodes.CURRENT,
            )
            lender_current = user.lendercurrent
            order_by = '-udate'
            if loan_xid:
                filter_['loan_xid'] = loan_xid

            if order == 'asc':
                if lender_current.lender_name in {'ska', 'ska2'}:
                    order_by = 'sphp_accepted_ts'
                else:
                    order_by = 'udate'
                if last_in_date:
                    filter_['udate__gt'] = last_in_date

            elif order == 'desc':
                if lender_current.lender_name in {'ska', 'ska2'}:
                    order_by = '-sphp_accepted_ts'
                if last_in_date:
                    filter_['udate__lt'] = last_in_date

            if product_line_code:
                filter_['product__product_line'] = product_line_code
                if int(product_line_code) in ProductLineCodes.DANA_PRODUCT:
                    order_by = '-sphp_accepted_ts'

            exclude_ = {}
            hidden_product_line_codes = get_list_product_line_code_need_to_hide()
            if hidden_product_line_codes:
                exclude_['product__product_line__in'] = hidden_product_line_codes
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

            res_data = []
            loan_lender_buckets_xids = dict()
            if loans:
                loan_lender_buckets_xids = get_lender_bucket_xids_by_loans(loans)

            for loan in loans:
                loan.creditscore__score = FalseRejectMiniConst.SCORE
                loan.fullname = ''
                if loan.is_axiata_loan():
                    loan.fullname = loan.application.customer.fullname
                    loan.loan_purpose = loan.application.loan_purpose

                if loan.account and loan.get_application:
                    application = loan.get_application
                    loan.fullname = application.fullname
                    if hasattr(application, 'creditscore'):
                        loan_experiment = application.applicationexperiment_set.filter(
                            experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION
                        ).exists()
                        if not loan_experiment:
                            loan.creditscore__score = application.creditscore.score.upper()

                lender_bucket_xid = loan_lender_buckets_xids.get(loan.pk, "")

                if product_line_code and int(product_line_code) in ProductLineCodes.DANA_PRODUCT:
                    in_date = loan.sphp_accepted_ts
                else:
                    in_date = loan.udate

                # override for grab loan purpose will get from application level
                if lender_current.lender_name in LenderNameByPartner.GRAB:
                    loan['loan_purpose'] = application.loan_purpose

                item = {
                    "in_date": in_date,
                    "application_xid": str(loan.loan_xid),
                    "lender_bucket_xid": str(lender_bucket_xid),
                    "fullname": loan.fullname,
                    "creditscore__score": loan.creditscore__score,
                    "loan__loan_amount": loan.loan_amount,
                    "loan__loan_duration": loan.loan_duration,
                    "status": mapping_loan_and_application_status_code(loan.loan_status_id),
                    "loan_purpose": loan.loan_purpose,
                }
                res_data.append(item)

            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {'action': 'PartnershipListApplicationPastViews', 'data': data, 'errors': str(e)}
            )
            JuloException(e)
            return server_error_response()


# this is for all partnership (copy from j1_views), lender dashboard
class PartnershipListLoanDetailViewsV2(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = request.user
        limit = request.query_params.get('limit')
        limit = 25 if limit is None else int(limit)
        last_loan_id = request.query_params.get('last_loan_id')
        loan_xid = request.query_params.get('application_xid')
        product_line_code = request.query_params.get('product_line_code')
        lender = LenderCurrent.objects.get_or_none(user=user)

        if lender is None:
            return general_error_response("Lender tidak temukan")

        loans_dict = get_loan_level_details(
            lender.id, last_loan_id, limit, loan_xid, product_line_code
        )
        sorted_loan_dict = sorted(
            list(loans_dict.items()),
            key=lambda kv: (kv[1]['fund_transfer_ts'] is not None, kv[1]['fund_transfer_ts']),
            reverse=True,
        )

        loan_data = []

        # check if lender does not have loan
        if len(list(loans_dict.keys())) != 0:
            last_loan_id = sorted_loan_dict[-1][0]
        else:
            return general_error_response("Lender tidak memiliki pinjaman")

        for key, value in sorted_loan_dict:
            loan_data.append(
                {
                    'lla_xid': str(value['lla_xid']),
                    'dibursed_date': value['fund_transfer_ts'],
                    'lender_bucket_xid': str(value['lender_bucket_xid']),
                    'loan_amount': value['loan_amount'],
                    'outstanding_principal': value['outstanding_principal_amount'],
                    'oustanding_interest': value['outstanding_interest_amount'],
                    'received_payment': value['total_paid'],
                    'loan_purpose': value['loan_purpose'],
                    'loan_duration': value['loan_duration'],
                    'loan_status_code': value['loan_status_code'],
                }
            )

        return success_response(dict({'items': loan_data, 'last_loan_id': last_loan_id}))


class PartnershipCreateLenderBucketViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = BucketLenderSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        approved_loan_ids = data['application_ids'].get('approved', [])
        rejected_loan_ids = data['application_ids'].get('rejected', [])

        approved_loans = Loan.objects.filter(id__in=approved_loan_ids).select_related(
            "account", "application", "account__account_lookup", "danaloanreference"
        )
        total = approved_loans.aggregate(
            sum_loan_disbursement_amount=Sum('loan_disbursement_amount'),
            sum_loan_amount=Sum('loan_amount'),
        )
        rejected_loans = Loan.objects.filter(id__in=rejected_loan_ids).select_related(
            "account", "account__account_lookup"
        )

        try:
            lender_bucket_id = None
            total_approved = len(approved_loan_ids) > 0
            if total_approved > 0:
                lender_bucket_xid = generate_lenderbucket_xid()
                lender_bucket = LenderBucket.objects.create(
                    partner_id=user.partner.pk,
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

                # cache lender bucket xid for getting application past in lender dashboard
                redis_cache = RedisCacheLoanBucketXidPast()
                redis_cache.set_keys(approved_loan_ids, lender_bucket_xid)

                # generate summary lla
                assign_lenderbucket_xid_to_lendersignature_service(
                    approved_loans, lender_bucket_xid
                )
                generate_summary_lender_loan_agreement.delay(lender_bucket.id)
                lender_bucket_id = lender_bucket.id

                dana_lender_auto_approve = FeatureSetting.objects.filter(
                    feature_name=JuloFeatureNameConst.DANA_LENDER_AUTO_APPROVE, is_active=True
                ).first()
                for loan in approved_loans:
                    application = loan.account.get_active_application()
                    if loan.is_axiata_loan() or loan.is_axiata_web_loan():
                        new_status_code = LoanStatusCodes.FUND_DISBURSAL_ONGOING
                        update_loan_status_and_loan_history(
                            loan.id,
                            new_status_code=new_status_code,
                            change_by_id=loan.application.customer.user_id,
                            change_reason="Axiata process to 212",
                        )
                        generate_julo_one_loan_agreement.delay(loan.id)
                        continue
                    elif loan.account.account_lookup.name == GRAB_ACCOUNT_LOOKUP_NAME:
                        grab_disbursement_trigger_task.delay(loan.id)
                        continue
                    elif loan.account.account_lookup.name == PartnershipAccountLookup.DANA:
                        # For DANA case should not use Async task to update 212
                        # will update status if loan status is 210 / 211
                        """
                        To handle race condition, we have several solution, we can do:
                        1. loan.refresh_from_db()  -> Always get newest loan from db,
                        but possible to increase Latency
                        2. loan = Loan.objects.select_for_update(loan) -> re select all if any
                        updated data from db,
                            but still possible to increase Latency
                        3. first checking the loan history with new_status = 212 -> possible
                        solution
                        """
                        if loan.status < LoanStatusCodes.FUND_DISBURSAL_ONGOING:
                            # current solution to handle race condition
                            # first checking the loan history with new_status 212
                            if loan.loanhistory_set.filter(
                                status_new=LoanStatusCodes.FUND_DISBURSAL_ONGOING
                            ).exists():
                                continue
                            old_status = loan.status
                            with transaction.atomic():
                                dana_update_loan_status_and_loan_history(
                                    loan,
                                    new_status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                                    change_reason=str(
                                        PartnershipLoanStatusChangeReason.LOAN_APPROVED_BY_LENDER,
                                    ),
                                )
                            logger.info(
                                {
                                    'action': 'PartnershipCreateLenderBucketViews',
                                    'loan_id': loan.id,
                                    'old_status': old_status,
                                    'new_status': loan.status,
                                    'message': 'change loan status from lender dashboard',
                                }
                            )

                        if (
                            hasattr(loan, 'danaloanreference')
                            and not loan.danaloanreference.is_whitelisted
                        ):
                            if not dana_lender_auto_approve:
                                dana_generate_auto_lender_agreement_document_task.delay(loan.id)
                                logger.info(
                                    {
                                        'action': 'PartnershipCreateLenderBucketViews',
                                        'loan_id': loan.id,
                                        'message': 'call dana_disbursement_trigger_task',
                                    }
                                )
                                dana_disbursement_trigger_task.delay(loan.id, False)

                    elif (
                        loan.account.account_lookup.name
                        == PartnershipAccountLookup.MERCHANT_FINANCING
                    ):
                        new_status_code = LoanStatusCodes.FUND_DISBURSAL_ONGOING
                        update_loan_status_and_loan_history(
                            loan.id,
                            new_status_code=new_status_code,
                            change_reason="Axiata process to 212",
                        )
                        continue
                    elif application.partner:
                        if application.partner.name == PartnerConstant.GOSEL:
                            new_status_code = LoanStatusCodes.FUND_DISBURSAL_ONGOING
                            update_loan_status_and_loan_history(
                                loan.id,
                                new_status_code=new_status_code,
                                change_reason="gojektsel process to 212",
                            )
                            continue
                    else:
                        reset_julo_one_loan_agreement.delay(loan.id)
                        julo_one_disbursement_trigger_task.delay(loan.id)

            for rejected_loan in rejected_loans.iterator():
                application = rejected_loan.account.get_active_application()
                if rejected_loan.account.account_lookup.name == GRAB_ACCOUNT_LOOKUP_NAME:
                    update_loan_status_and_loan_history(
                        loan_id=rejected_loan.id,
                        new_status_code=LoanStatusCodes.LENDER_REJECT,
                        change_reason="Lender Rejected",
                    )
                    continue
                elif rejected_loan.account.account_lookup.name == PartnershipAccountLookup.DANA:
                    with transaction.atomic():
                        dana_update_loan_status_and_loan_history(
                            rejected_loan,
                            new_status_code=LoanStatusCodes.LENDER_REJECT,
                            change_reason=PartnershipLoanStatusChangeReason.LOAN_REJECTED_BY_LENDER,
                        )
                        continue
                elif (
                    rejected_loan.account.account_lookup.name
                    == PartnershipAccountLookup.MERCHANT_FINANCING
                ):
                    new_status_code = LoanStatusCodes.CANCELLED_BY_CUSTOMER
                    update_loan_status_and_loan_history(
                        loan_id=rejected_loan.id,
                        new_status_code=new_status_code,
                        change_reason="Axiata process to 216",
                    )
                    continue
                elif application.partner:
                    if application.partner.name == PartnerConstant.GOSEL:
                        new_status_code = LoanStatusCodes.LENDER_REJECT
                        update_loan_status_and_loan_history(
                            loan_id=rejected_loan.id,
                            new_status_code=new_status_code,
                            change_reason="gosel process to 219",
                        )
                        continue
                reassign_lender_julo_one(rejected_loan.id)

            return success_response({'lender_bucket_id': lender_bucket_id})
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {'action': 'PartnershipCreateLenderBucketViews', 'data': data, 'errors': str(e)}
            )
            return server_error_response()
