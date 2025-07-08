import logging
from collections import defaultdict

from django.utils.dateparse import parse_datetime
from juloserver.followthemoney.utils import (
    success_response,
    server_error_response,
    general_error_response,
    spoofing_response,
    mapping_loan_and_application_status_code,
)

from juloserver.julo.constants import (
    FalseRejectMiniConst,
    ExperimentConst,
)
from juloserver.followthemoney.models import LenderBucket
from juloserver.followthemoney.views.application_views import FollowTheMoneyAPIView
from juloserver.followthemoney.services import (
    get_lender_bucket_xids_by_loans,
    get_loan_level_details,
)
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Partner, Loan, Application, ApplicationExperiment
from juloserver.julo.partners import PartnerConstant
from juloserver.julo.statuses import LoanStatusCodes

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

logger = logging.getLogger(__name__)


class PartnershipListPendingLoanViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request: Request) -> Response:
        user = self.request.user

        if not hasattr(user, 'lendercurrent'):
            data = {
                'success': False,
                'status_code': status.HTTP_403_FORBIDDEN,
                'data': [],
                'msg': 'Maaf anda tidak login sebagai pemberi pinjaman',
            }
            return Response(status=status.HTTP_403_FORBIDDEN, data=data)

        limit = request.GET.get('limit', '25')

        if limit and not limit.isdigit():
            return general_error_response("limit harus berupa angka")

        limit = int(limit)
        order = request.GET.get('order', 'asc')
        partner_name = request.GET.get('partner_name', PartnerConstant.GOSEL)
        loan_xid = request.GET.get('loan_xid')
        last_loan_id = request.GET.get('last_loan_id')

        if loan_xid and not loan_xid.isdigit():
            return general_error_response("loan_xid harus berupa angka")

        if last_loan_id and not last_loan_id.isdigit():
            return general_error_response("last_loan_id harus berupa angka")

        if not partner_name:
            return general_error_response("Partner tidak ditemukan.")

        partner_name = partner_name.replace('-', '_')
        partner_id = (
            Partner.objects.filter(
                name=partner_name,
                is_active=True,
            )
            .values_list('id', flat=True)
            .last()
        )

        if not partner_id:
            return general_error_response("Partner tidak ditemukan.")

        try:
            exclude_ = {}

            filter_ = dict(
                loan_status=LoanStatusCodes.LENDER_APPROVAL,
                lender=user.lendercurrent,
                partnerloanrequest__partner_id=partner_id,
            )

            lender_bucket = LenderBucket.objects.filter(
                is_active=True, partner_id=user.partner.pk
            ).last()
            if lender_bucket:
                loan_ids = lender_bucket.loan_ids
                exclude_['id__in'] = loan_ids['approved'] + loan_ids['rejected']

            if loan_xid:
                filter_['loan_xid'] = loan_xid

            order_by = '-udate'
            if order == "desc":
                if last_loan_id:
                    filter_['id__lt'] = last_loan_id
            elif order == "asc":
                order_by = 'udate'
                if last_loan_id:
                    filter_['id__gt'] = last_loan_id

            res_data = []

            loans = (
                Loan.objects.only(
                    'id',
                    'loan_xid',
                    'cdate',
                    'udate',
                    'loan_disbursement_amount',
                    'loan_purpose',
                    'loan_amount',
                    'loan_duration',
                    'application_id2',
                    'product',
                )
                .filter(**filter_)
                .select_related('product')
                .exclude(**exclude_)
                .order_by(order_by)[:limit]
            )

            if not loans:
                return success_response(spoofing_response(res_data, 'fullname', 2))

            application_ids = loans.values_list('application_id2', flat=True)

            # Mapping application data
            application_data_mapping = defaultdict(lambda: defaultdict(int))
            applications = (
                Application.objects.filter(
                    id__in=application_ids,
                )
                .select_related('creditscore')
                .values('id', 'fullname', 'creditscore__score', 'application_xid')
                .order_by('id')
            )

            for application in applications:
                app_id = application['id']
                credit_score = application['creditscore__score']
                app_fullname = application['fullname']
                application_xid = application['application_xid']

                application_data_mapping[app_id]['fullname'] = app_fullname
                application_data_mapping[app_id]['credit_score'] = credit_score
                application_data_mapping[app_id]['application_xid'] = application_xid

            # Mapping application experiment
            application_experiment_mapping = defaultdict(int)
            application_experiments = (
                ApplicationExperiment.objects.filter(
                    application_id__in=application_ids,
                    experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION,
                )
                .select_related('experiment')
                .order_by('application_id')
            )

            for application_experiment in application_experiments:
                application_experiment_mapping[application_experiment.application_id] = True

            for loan in loans:
                interest_amount = (
                    None if loan.interest_rate_monthly == 0 else loan.interest_rate_monthly
                )
                credit_score = FalseRejectMiniConst.SCORE
                fullname = ''
                application_xid = ''

                loan_app_id = loan.application_id2
                if loan_app_id and application_data_mapping.get(loan_app_id):
                    fullname = application_data_mapping[loan_app_id].get('fullname', '')
                    application_xid = application_data_mapping[loan_app_id].get(
                        'application_xid', ''
                    )

                    if application_data_mapping[loan_app_id].get('credit_score'):
                        credit_score = application_data_mapping[loan_app_id]['credit_score']

                        if application_experiment_mapping.get(loan_app_id):
                            credit_score = FalseRejectMiniConst.SCORE

                data = {
                    'id': loan.id,
                    'loan_xid': str(loan.loan_xid),
                    'application_xid': str(application_xid),
                    'cdate': loan.cdate,
                    'udate': loan.udate,
                    'loan_disbursement_amount': loan.loan_disbursement_amount,
                    'loan_purpose': loan.loan_purpose or '',
                    'loan_amount': loan.loan_amount,
                    'loan_duration': loan.loan_duration,
                    'product': loan.product.product_code,
                    'credit_score': credit_score.upper(),
                    'fullname': fullname,
                    'interest': interest_amount,
                }

                res_data.append(data)

            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({'action_view': 'PartnershipListLoanViews', 'errors': str(e)})
            JuloException(e)
            return server_error_response()


class PartnershipListApprovedLoanViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request: Request) -> Response:
        user = self.request.user

        if not hasattr(user, 'lendercurrent'):
            data = {
                'success': False,
                'status_code': status.HTTP_403_FORBIDDEN,
                'data': [],
                'msg': 'Maaf anda tidak login sebagai pemberi pinjaman',
            }
            return Response(status=status.HTTP_403_FORBIDDEN, data=data)

        limit = request.GET.get('limit', '25')

        if limit and not limit.isdigit():
            return general_error_response("limit harus berupa angka")

        limit = int(limit)
        order = request.GET.get('order', 'asc')
        partner_name = request.GET.get('partner_name', PartnerConstant.GOSEL)
        loan_xid = request.GET.get('loan_xid')
        last_in_date = request.GET.get('last_in_date')

        if loan_xid and not loan_xid.isdigit():
            return general_error_response("loan_xid harus berupa angka")

        if not partner_name:
            return general_error_response("Partner tidak ditemukan.")

        if last_in_date:
            is_valid_datetime = parse_datetime(last_in_date)
            if not is_valid_datetime:
                return general_error_response("last_in_date harus berformat tanggal")

        partner_name = partner_name.replace('-', '_')
        partner_id = (
            Partner.objects.filter(
                name=partner_name,
                is_active=True,
            )
            .values_list('id', flat=True)
            .last()
        )

        if not partner_id:
            return general_error_response("Partner tidak ditemukan.")

        try:
            filter_ = dict(
                lender=user.lendercurrent,
                partnerloanrequest__partner_id=partner_id,
                loan_status__gte=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                loan_status__lte=LoanStatusCodes.CURRENT,
            )

            if loan_xid:
                filter_['loan_xid'] = loan_xid

            order_by = '-udate'
            if order == 'desc':
                if last_in_date:
                    filter_['udate__lt'] = last_in_date
            elif order == 'asc':
                order_by = 'udate'
                if last_in_date:
                    filter_['udate__gt'] = last_in_date

            res_data = []

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
                    'application_id2',
                )
                .filter(**filter_)
                .order_by(order_by)[:limit]
            )
            application_ids = loans.values_list('application_id2', flat=True)

            if not loans:
                return success_response(spoofing_response(res_data, 'fullname', 2))

            # Mapping application data
            application_data_mapping = defaultdict(lambda: defaultdict(int))
            applications = (
                Application.objects.filter(
                    id__in=application_ids,
                )
                .select_related('creditscore')
                .values('id', 'fullname', 'creditscore__score')
                .order_by('id')
            )

            for application in applications:
                app_id = application['id']
                credit_score = application['creditscore__score']
                app_fullname = application['fullname']

                application_data_mapping[app_id]['fullname'] = app_fullname
                application_data_mapping[app_id]['credit_score'] = credit_score

            # Mapping application experiment
            application_experiment_mapping = defaultdict(int)
            application_experiments = (
                ApplicationExperiment.objects.filter(
                    application_id__in=application_ids,
                    experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION,
                )
                .select_related('experiment')
                .order_by('application_id')
            )

            for application_experiment in application_experiments:
                application_experiment_mapping[application_experiment.application_id] = True

            # Mapping lender buckets
            loan_lender_buckets_xids = get_lender_bucket_xids_by_loans(loans)

            for loan in loans:
                credit_score = FalseRejectMiniConst.SCORE
                fullname = ''
                loan_app_id = loan.application_id2
                if loan_app_id and application_data_mapping.get(loan_app_id):
                    fullname = application_data_mapping[loan_app_id]['fullname'] or ''
                    if application_data_mapping[loan_app_id].get('credit_score'):
                        credit_score = application_data_mapping[loan_app_id]['credit_score']

                        if application_experiment_mapping.get(loan_app_id):
                            credit_score = FalseRejectMiniConst.SCORE

                lender_bucket_xid = loan_lender_buckets_xids.get(loan.pk, "")
                in_date = loan.udate

                data = {
                    "in_date": in_date,
                    "loan_xid": str(loan.loan_xid),
                    "lender_bucket_xid": str(lender_bucket_xid),
                    "fullname": fullname,
                    "credit_score": credit_score.upper(),
                    "loan_amount": loan.loan_amount,
                    "loan_duration": loan.loan_duration,
                    "status": mapping_loan_and_application_status_code(loan.loan_status_id),
                    "loan_purpose": loan.loan_purpose or '',
                }

                res_data.append(data)

            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({'action_view': 'PartnershipListLoanPastViews', 'errors': str(e)})
            JuloException(e)
            return server_error_response()


# this is for gosel
class PartnershipListLoanDetailViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request: Request) -> Response:
        user = self.request.user

        if not hasattr(user, 'lendercurrent'):
            data = {
                'success': False,
                'status_code': status.HTTP_403_FORBIDDEN,
                'data': [],
                'msg': 'Maaf anda tidak login sebagai pemberi pinjaman',
            }
            return Response(status=status.HTTP_403_FORBIDDEN, data=data)

        limit = request.GET.get('limit', '25')

        if limit and not limit.isdigit():
            return general_error_response("limit harus berupa angka")

        limit = int(limit)
        partner_name = request.GET.get('partner_name', PartnerConstant.GOSEL)
        loan_xid = request.GET.get('loan_xid')
        last_loan_id = request.GET.get('last_loan_id')

        if loan_xid and not loan_xid.isdigit():
            return general_error_response("loan_xid harus berupa angka")

        if last_loan_id and not last_loan_id.isdigit():
            return general_error_response("last_loan_id harus berupa angka")

        if not partner_name:
            return general_error_response("Partner tidak ditemukan.")

        partner_name = partner_name.replace('-', '_')
        partner_id = (
            Partner.objects.filter(
                name=partner_name,
                is_active=True,
            )
            .values_list('id', flat=True)
            .last()
        )

        if not partner_id:
            return general_error_response("Partner tidak ditemukan.")

        lender = user.lendercurrent
        loans_dict = get_loan_level_details(
            lender.id, last_loan_id, limit, loan_xid, partner_id=partner_id
        )

        sorted_loan_dict = sorted(
            list(loans_dict.items()),
            key=lambda kv: (kv[1]['fund_transfer_ts'] is not None, kv[1]['fund_transfer_ts']),
            reverse=True,
        )

        loan_data = []
        if len(list(loans_dict.keys())) != 0:
            last_loan_id = sorted_loan_dict[-1][0]
        else:
            return general_error_response("Lender tidak memiliki pinjaman")

        for _, value in sorted_loan_dict:
            loan_data.append(
                {
                    'loan_xid': str(value['lla_xid']),
                    'dibursed_date': value['fund_transfer_ts'],
                    'lender_bucket_xid': str(value['lender_bucket_xid']),
                    'loan_amount': value['loan_amount'],
                    'outstanding_principal': value['outstanding_principal_amount'],
                    'oustanding_interest': value['outstanding_interest_amount'],
                    'received_payment': value['total_paid'],
                    'loan_purpose': value['loan_purpose'] or '',
                    'loan_duration': value['loan_duration'],
                    'loan_status_code': value['loan_status_code'],
                }
            )

        data = {'items': loan_data, 'last_loan_id': last_loan_id}
        return success_response(data)
