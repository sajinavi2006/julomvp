from future import standard_library
standard_library.install_aliases()
from builtins import str
import logging
import random
import string
import os
import tempfile
import json
import urllib.request, urllib.parse, urllib.error
from itertools import chain

from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from collections import OrderedDict
from operator import getitem
from django.db.models.fields import CharField

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from rest_framework.views import APIView
from rest_framework import exceptions
from juloserver.api_token.models import ExpiryToken as Token
from rest_framework.decorators import parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User, Group
from django.db import transaction
from django.db.models import F, Sum, Q, Max, Case, When
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.http import HttpResponse, StreamingHttpResponse
from django.core import serializers

from juloserver.channeling_loan.constants import ChannelingConst
from juloserver.channeling_loan.services.general_services import get_channeling_loan_configuration
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_application_status_change
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import (ApplicationStatusCodes,
                                      PaymentStatusCodes)
from juloserver.julo.models import (Application,
                                    Partner,
                                    Loan,
                                    RepaymentTransaction,
                                    Payment,
                                    Document,
                                    StatusLookup,
                                    Image,
                                    LenderDisburseCounter,
                                    MobileFeatureSetting,
                                    EmailHistory)
from juloserver.julo.clients import get_julo_sentry_client, get_julo_digisign_client
from juloserver.julo.clients.constants import DigisignResultCode
from juloserver.julo.tasks import upload_document
from ..utils import (success_response,
                    server_error_response,
                    not_found_response,
                    general_error_response,
                    convert_timestamp,
                    spoof_text,
                    spoofing_response,
                    generate_lenderbucket_xid
                    )

from ..serializers import (LoginSerializer,
                          ChangePasswordSerializer,
                          RegisterSerializer,
                          ListApplicationSerializer,
                          ListBucketLenderSerializer,
                          BucketLenderSerializer,
                          CancelBucketSerializer,
                          DisbursementSerializer,
                          LoanAgreementSerializer,
                          LenderTransactionSerializer,
                          RegisterLenderWebSerializer,
                          ForgotPasswordSerializer,
                          DocumentStatusLenderSerializer,
                          SignedDocumentLenderSerializer,
                          OJKSubmitFormSerializer
                          )

from ..models import (LenderBucket,
                     LenderApproval,
                     LenderCurrent,
                     LenderBalanceCurrent,
                     LenderTransaction,
                     LenderTransactionMapping,
                     LenderBankAccount,
                     LenderTransactionType,
                     LenderSignature)

from ..tasks import (approved_application_process_disbursement,
                    bulk_approved_application_process_disbursement,
                    send_email_set_password,
                    generate_summary_lender_loan_agreement,
                    assign_lenderbucket_xid_to_lendersignature)

from ..services import (
    get_max_limit,
    reassign_lender,
    get_summary_value,
    get_repayment,
    calculate_net_profit,
    get_loan_agreement_template,
    get_loan_details,
    get_total_outstanding_for_lender,
    reassign_lender_julo_one,
)

from ..constants import LenderTransactionTypeConst, DocumentType, LoanAgreementType
from juloserver.julo.constants import ExperimentConst, FalseRejectMiniConst
from juloserver.julo.clients import get_julo_email_client, get_julo_sentry_client
from django.template.loader import render_to_string
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.loan.tasks.lender_related import julo_one_disbursement_trigger_task
from juloserver.loan.tasks.lender_related import grab_lender_manual_approval_task
from juloserver.loan.services.lender_related import get_whitelist_manual_approval_feature
from juloserver.payment_point.constants import TransactionMethodCode

# Create your views here.
logger = logging.getLogger(__name__)


class FollowTheMoneyAuthentication(ExpiryTokenAuthentication):
    def authenticate(self, request):
        if super(FollowTheMoneyAuthentication, self).authenticate(request):
            user, auth = super(FollowTheMoneyAuthentication, self).authenticate(request)
            if not hasattr(user, 'partner'):
                raise exceptions.AuthenticationFailed('Forbidden request, invalid lender')
            else:
                if user.partner.type != 'lender':
                    raise exceptions.AuthenticationFailed('Forbidden request, invalid lender')
            return (user, auth)
        else:
            raise exceptions.AuthenticationFailed('Forbidden request, invalid lender')


class FollowTheMoneyAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (FollowTheMoneyAuthentication,)

    def validate_data(self, serializer_class, data):
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class LoginViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = LoginSerializer
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)

        user = User.objects.filter(username=data['username'].strip()).last()
        if not user:
            return general_error_response("username atau password yang anda masukan salah")

        is_password_correct = user.check_password(request.data['password'])
        if not is_password_correct:
            return general_error_response("username atau password yang anda masukan salah")

        all_channeling_configuration = get_channeling_loan_configuration(is_active=False)
        lender_names = []
        for _, channeling_loan_config in all_channeling_configuration.items():
            lender_name = (channeling_loan_config.get('general', {})).get('LENDER_NAME', None)
            if lender_name:
                lender_names.append(lender_name)

        lender = user.lendercurrent
        is_channeling = False
        if lender.lender_name in lender_names:
            is_channeling = True

        company_name = '-'
        if lender and lender.lender_display_name:
            company_name = lender.lender_display_name
        res_data = {
            'token': user.auth_expiry_token.key,
            'user': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'company_name': company_name,
                'is_channeling': is_channeling,
            }
        }

        return success_response(res_data)


class ForgotPasswordViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = ForgotPasswordSerializer
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)

        email = data['email'].strip()
        user = User.objects.filter(email=data['email']).last()

        if not user:
            return general_error_response("email yang anda masukan salah.", {'email': email})

        lender = LenderCurrent.objects.get_or_none(user=user)

        if not lender:
            return general_error_response("email yang anda masukan salah.", {'email': email})

        send_email_set_password.delay(lender.id, True)

        return success_response()


class ChangePasswordViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        self.serializer_class(data=request.data).is_valid(raise_exception=True)
        new_password = request.data['new_password']

        user = self.request.user
        try:
            user.set_password(new_password)
            user.save()
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - ChangePasswordViews',
                'data': request.data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()

        res_data = {
            'token': user.auth_expiry_token.key
        }

        return success_response(res_data)


class CheckTokenLinkViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = []

    def post(self, request):
        user = self.request.user

        res_data = {
            'is_active': user.is_active
        }

        return success_response(res_data)


class RegisterLenderViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = RegisterSerializer
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)

        try:
            with transaction.atomic():
                lender = LenderCurrent.objects.create(
                    lender_name=data['lender_name'],
                    lender_address=data['company_address'],
                    business_type=data['business_type'],
                    poc_email=data['poc_email'],
                    poc_name=data['poc_name'],
                    poc_phone=data['poc_phone'],
                    poc_position=data['poc_position'],
                    source_of_fund=data['source_of_fund']
                )

                # do the upload document things

                return success_response()

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - RegisterLenderView',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class ListApplicationViews(FollowTheMoneyAPIView):
    http_method_names = ['get']
    serializer_class = ListApplicationSerializer

    def get(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        try:
            limit = request.GET.get('limit', 25)
            limit = get_max_limit(limit=limit)

            order = request.GET.get('order', 'asc')
            application_id = request.GET.get('application_id')
            last_application_id = request.GET.get('last_application_id')
            exclude_ = dict(
                id__in=[]
            )

            filter_ = dict(
                application_status=ApplicationStatusCodes.LENDER_APPROVAL,
                loan__partner=user.partner
            )

            lender_buckets = LenderBucket.objects.filter(
                is_active=True, partner=user.partner
            ).values_list('loan_ids', flat=True)
            if lender_buckets:
                exclude_ids = []
                for lender_bucket in lender_buckets:
                    if lender_bucket:
                        if lender_bucket['approved']:
                            exclude_ids.extend(list(lender_bucket['approved']))
                        if lender_bucket['rejected']:
                            exclude_ids.extend(list(lender_bucket['rejected']))
                exclude_ = dict(
                    id__in=exclude_ids
                )

            if application_id:
                filter_['id'] = application_id

            order_by = '-id'
            if order == "desc":
                if last_application_id:
                    filter_['id__lt'] = last_application_id
            elif order == "asc":
                order_by = 'id'
                if last_application_id:
                    filter_['id__gt'] = last_application_id

            applications = Application.objects.filter(**filter_).exclude(**exclude_).exclude(
                product_line__in=ProductLineCodes.julo_one() + ProductLineCodes.grab()
            ).order_by(order_by)[:limit]
            res_data = applications.values('id', 'application_xid', 'cdate', 'udate', 'fullname',
                                           'gender', 'product_line__product_line_type',
                                           'product_line__max_interest_rate', 'loan__loan_disbursement_amount',
                                           'loan__loan_amount', 'loan__loan_duration', 'creditscore__score', 'loan_purpose'
                                           )

            filter_.pop('application_status')
            filter_.pop('loan__partner')
            filter_['partner'] = user.partner

            loans = Loan.objects.filter(**filter_).filter(
                loan_status=LoanStatusCodes.LENDER_APPROVAL,
                account__application__product_line__in=
                ProductLineCodes.julo_one() + ProductLineCodes.grab()
            ).order_by(order_by)[:limit]
            loans_data = loans.annotate(
                fullname=F('account__application__fullname'),
                gender=F('account__application__gender'),
                product_line__product_line_type=F(
                    'account__application__product_line__product_line_type'
                ),
                product_line__max_interest_rate=F(
                    'account__application__product_line__max_interest_rate'
                ),
                creditscore__score=F(
                    'account__application__creditscore__score'
                ),
                loan__loan_amount=F('loan_amount'),
                loan__loan_disbursement_amount=F('loan_disbursement_amount'),
                loan__loan_duration=F('loan_duration'),
                loan_purpose_base_transaction_method=Case(
                    When(
                        transaction_method_id=TransactionMethodCode.SELF.code,
                        then=F('loan_purpose')
                    ),
                    When(
                        transaction_method_id__in=
                        TransactionMethodCode.loan_purpose_base_transaction_method(),
                        then=F('transaction_method__fe_display_name')
                    ),
                    When(
                        transaction_method_id__isnull=True,
                        then=F('account__application__loan_purpose')
                    ),
                    output_field=CharField()
                )
            ).values(
                'id', 'application_xid', 'cdate', 'udate', 'fullname',
                'gender', 'product_line__product_line_type', 'loan_xid', 'loan_status',
                'product_line__max_interest_rate', 'loan_disbursement_amount',
                'loan__loan_amount', 'loan__loan_duration', 'creditscore__score', 'loan_purpose',
                'account__application__loan_purpose', 'loan_purpose_base_transaction_method',
            )
            res_data = list(chain(res_data, loans_data))

            for app in res_data:
                app_xid = app['application_xid'] if 'application_xid' in app else None
                application = Application.objects.get_or_none(application_xid=app_xid)
                application_experiment = application.applicationexperiment_set.filter(
                    experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION
                    )
                if application_experiment:
                    app['creditscore__score'] = FalseRejectMiniConst.SCORE

                if 'loan_xid' in app and app['loan_xid']:
                    app['application_xid'] = app['loan_xid']
                if not app['creditscore__score']:
                    app['creditscore__score'] = 'B+'

                loan_purpose = app['loan_purpose']
                if 'loan_purpose_base_transaction_method' in app:
                    loan_purpose = app['loan_purpose_base_transaction_method']

                app['loan_purpose'] = loan_purpose

            logger.info({
                'action_view': 'follow_the_money_list_view_data',
                'data': res_data,
            })
            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - ListApplicationViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class ListLenderBucketViews(FollowTheMoneyAPIView):
    http_method_names = ['get']
    serializer_class = ListBucketLenderSerializer

    def get(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        try:
            limit = request.GET.get('limit', 1)
            order = request.GET.get('order', 'desc')
            is_active = data['is_active'] if data['is_active'] else True
            is_disbursed = data['is_disbursed'] if data['is_disbursed'] else False
            bucket_id = request.GET.get('bucket_id')
            last_bucket_id = request.GET.get('last_bucket_id')

            filter_ = dict(
                partner=user.partner,
                is_active=is_active,
                is_disbursed=is_disbursed
            )

            if bucket_id:
                filter_['id'] = bucket_id

            order_by = '-id'
            if order == "desc":
                if last_bucket_id:
                    filter_['id__lt'] = last_bucket_id
            elif order == "asc":
                order_by = 'id'
                if last_bucket_id:
                    filter_['id__gt'] = last_bucket_id

            lender_buckets = LenderBucket.objects.filter(**filter_).order_by(order_by)[:limit]
            bucket_list = lender_buckets.values('id', 'cdate', 'udate', 'total_approved', 'total_rejected',
                                                'is_active', 'is_disbursed', 'application_ids',
                                                'total_disbursement', 'total_loan_amount')
            for bucket in bucket_list:
                rejected = bucket['application_ids']['rejected']
                approved = bucket['application_ids']['approved']

                #mapping rejected
                detail_rejected = []
                for reject in rejected:
                    app = Application.objects.filter(id=reject).values('id', 'cdate', 'udate', 'fullname',
                                                                       'application_status',
                                                                       'creditscore__score', 'application_xid')
                    detail_rejected.append(spoofing_response(app, 'fullname', 2))

                #mapping approved
                detail_approved = []
                for approve in approved:
                    app = Application.objects.filter(id=approve).values('id', 'cdate', 'udate', 'fullname',
                                                                        'application_status',
                                                                        'creditscore__score', 'application_xid')
                    detail_approved.append(spoofing_response(app, 'fullname', 2))

                bucket['application_ids']['detail_rejected'] = detail_rejected
                bucket['application_ids']['detail_approved'] = detail_approved

            return success_response(bucket_list)

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - ListLenderBucketViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class CreateLenderBucketViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = BucketLenderSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        if LenderBucket.objects.filter(partner=user.partner, is_active=True).last():
            return general_error_response("lender bucket sudah terdaftar sebelumnya.")

        # total disbursement amount and total loan amount
        fields = ("loan_disbursement_amount", "loan_amount")
        total = {"loan_disbursement_amount": 0, "loan_amount": 0}

        primary_keys = {
            'application_ids_approved': [],
            'loan_ids_approved': [],
            'application_ids_rejected': [],
            'loan_ids_rejected': [],
        }

        applications = Application.objects.filter(
            id__in=data['application_ids']['approved'] + data['application_ids']['rejected'],
        ).exclude(
            product_line__in=
            ProductLineCodes.julo_one() + ProductLineCodes.grab()
        )
        loans = Loan.objects.filter(
            id__in=data['application_ids']['approved'] + data['application_ids']['rejected'],
            account__application__product_line__in=
            ProductLineCodes.julo_one() + ProductLineCodes.grab()
        )


        primary_keys['application_ids_approved'] = list(applications.exclude(
            id__in=data['application_ids']['rejected'],
        ).values_list('id', flat=True))
        primary_keys['loan_ids_approved'] = list(loans.exclude(
            id__in=data['application_ids']['rejected'],
        ).values_list('id', flat=True))
        primary_keys['application_ids_rejected'] = list(applications.exclude(
            id__in=data['application_ids']['approved'],
        ).values_list('id', flat=True))
        primary_keys['loan_ids_rejected'] = list(loans.exclude(
            id__in=data['application_ids']['approved'],
        ).values_list('id', flat=True))

        for field in fields:
            subtotal_base_application = applications.aggregate(
                total_amount=Sum('loan__{}'.format(field)))['total_amount'] or 0
            subtotal_base_loan = loans.aggregate(
                total_amount=Sum('{}'.format(field)))['total_amount'] or 0
            subtotal = {
                'loan__{}__sum'.format(field): subtotal_base_application + subtotal_base_loan
            }
            if not subtotal['loan__%s__sum' % (field)]:
                subtotal['loan__%s__sum' % (field)] = 0

            total[field] = subtotal['loan__%s__sum' % (field)]

        try:
            lender_bucket_id = None
            total_approved = len(data['application_ids']['approved']) > 0
            if total_approved > 0:
                lender_bucket = LenderBucket.objects.create(
                    partner=user.partner,
                    total_approved=len(data['application_ids']['approved']),
                    total_rejected=len(data['application_ids']['rejected']),
                    total_disbursement=total['loan_disbursement_amount'],
                    total_loan_amount=total['loan_amount'],
                    application_ids={'approved': primary_keys['application_ids_approved'],
                                     'rejected': primary_keys['application_ids_rejected']},
                    is_disbursed=False,
                    is_active=True,
                    action_time=timezone.now(),
                    action_name='Disbursed',
                    lender_bucket_xid=generate_lenderbucket_xid(),
                    loan_ids={'approved': primary_keys['loan_ids_approved'],
                              'rejected': primary_keys['loan_ids_rejected']},
                )

                # generate summary lla
                for index in primary_keys:
                    if index in ['loan_ids_approved', 'application_ids_approved']\
                            and primary_keys[index]:
                        is_loan = True if index == 'loan_ids_approved' else False
                        assign_lenderbucket_xid_to_lendersignature(
                            primary_keys[index],
                            lender_bucket.lender_bucket_xid, is_loan
                        )
                generate_summary_lender_loan_agreement.delay(lender_bucket.id)
                lender_bucket_id = lender_bucket.id

            # change status rejected and round robin again to change partner
            for reject in primary_keys['application_ids_rejected']:
                reassign_lender(reject)

            for loan_id in primary_keys['loan_ids_rejected']:
                reassign_lender_julo_one(loan_id)

            # for application_id in data['application_ids']['approved']:
            #     approved_application_process_disbursement.delay(application_id)

            for loan_id in primary_keys['loan_ids_approved']:
                loan = Loan.objects.get_or_none(pk=loan_id)
                if loan.account:
                    application = loan.get_application
                    if loan.account.account_lookup.workflow.name == WorkflowConst.GRAB:
                        grab_lender_manual_approval_task.delay(loan.id)
                    elif not application.is_axiata_flow():
                        julo_one_disbursement_trigger_task.delay(loan.id, True)

            return success_response({'lender_bucket_id': lender_bucket_id})
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - CreateLenderBucketViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class CancelBucketViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = CancelBucketSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        lender_bucket_id = data['bucket']['id']

        lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)
        if lender_bucket is None:
            return general_error_response("lender bucket tidak terdaftar.")

        try:
            # Set lender bucket to inactive
            lender_bucket.update_safely(is_active=False,
                action_time=timezone.now(),
                action_name="Canceled")

            return success_response({'lender_bucket_id': lender_bucket_id})
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - CancelBucketViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class SummaryViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = self.request.user
        partner = user.partner

        if partner is None:
            return general_error_response("partner tidak ada.")

        loans = Loan.objects.filter(partner=partner, loan_status__gt=StatusLookup.INACTIVE_CODE).values(
            'application_id', 'id', 'loan_disbursement_amount', 'loan_status')

        res_data = {
            'disbursement': 0,
            'outstanding': 0,
            'repayment': 0,
            'principal': 0,
            'interest': 0,
            'fee': 0,
            'net_profit': 0
        }

        for loan in loans :
            principal = get_summary_value(loan['id'], 'paid_principal')
            interest = get_summary_value(loan['id'], 'paid_interest')
            fee = get_summary_value(loan['id'], 'paid_late_fee')

            res_data['disbursement'] += loan['loan_disbursement_amount']
            res_data['outstanding'] += get_summary_value(loan['id'], 'due_amount')
            res_data['repayment'] += get_repayment(loan['id'])
            res_data['principal'] += principal
            res_data['interest'] += interest
            res_data['fee'] += fee
            res_data['net_profit'] += calculate_net_profit(loan['loan_status'], principal, interest, fee)

        return success_response(res_data)


class ReportViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = self.request.user
        data = request.data
        partner = user.partner

        if partner is None:
            return general_error_response("partner tidak ada.")

        try:
            limit = request.GET.get('limit', 50)
            order = request.GET.get('order', 'asc')
            application_xid = request.GET.get('application_xid')
            last_application_xid = request.GET.get('last_application_xid')

            filter_ = dict(
                partner=partner,
                loan_status__gt=StatusLookup.INACTIVE_CODE
            )

            if application_xid:
                filter_['application__application_xid'] = application_xid

            order_by = 'application__application_xid'
            if order == 'asc':
                if last_application_xid:
                    filter_['application__application_xid__gt'] = last_application_xid

            elif order == 'desc':
                order_by = '-application__application_xid'
                if last_application_xid:
                    filter_['application__application_xid__lt'] = last_application_xid

            loans =  Loan.objects.filter(**filter_).values(
                'application_id', 'id', 'loan_disbursement_amount', 'loan_status'
                ).order_by(order_by)[:limit]

            res_data = []
            for loan in loans:
                application = Application.objects.get_or_none(id=loan['application_id'])
                principal = get_summary_value(loan['id'], 'paid_principal')
                interest = get_summary_value(loan['id'], 'paid_interest')
                fee = get_summary_value(loan['id'], 'paid_late_fee')

                item = {
                    "xid": application.application_xid,
                    "disbursement": loan['loan_disbursement_amount'],
                    "outstanding": get_summary_value(loan['id'], 'due_amount'),
                    "principal": principal,
                    "interest": interest,
                    "fee": fee,
                    "repayment": calculate_net_profit(loan['loan_status'], principal, interest, fee),
                    "fullname": application.fullname
                }
                res_data.append(item)

            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - ReportViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class ListApplicationPastViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = self.request.user
        data = request.data
        partner = user.partner

        if partner is None:
            return general_error_response("partner tidak ada.")

        try:
            order = request.GET.get('order', 'desc')
            limit = request.GET.get('limit', 25)
            limit = get_max_limit(limit=limit)

            application_xid = request.GET.get('application_xid')
            last_in_date = request.GET.get('last_in_date')

            filter_ = dict(
                loan__partner=partner.id,
                applicationhistory__status_new__in=[ApplicationStatusCodes.BULK_DISBURSAL_ONGOING,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
                    ApplicationStatusCodes.APPLICATION_DENIED]
            )

            order_by = '-lastest_history_cdate'
            if application_xid:
                filter_['application_xid'] = application_xid

            if order == 'asc':
                order_by = 'lastest_history_cdate'
                if last_in_date:
                    filter_['lastest_history_cdate__gt'] = last_in_date

            elif order == 'desc':
                if last_in_date:
                    filter_['lastest_history_cdate__lt'] = last_in_date

            applications = Application.objects.annotate(
                lastest_history_cdate=Max(
                    Case(
                        When(
                            Q(applicationhistory__status_new=ApplicationStatusCodes.BULK_DISBURSAL_ONGOING) |
                            Q(applicationhistory__status_new=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED) |
                            Q(applicationhistory__status_new=ApplicationStatusCodes.APPLICATION_DENIED),
                            then=F('applicationhistory__cdate')
                        )
                    )
                )
            ).filter(
                **filter_
            ).filter(
                Q(application_status=ApplicationStatusCodes.APPLICATION_DENIED) |
                Q(application_status__gte=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED)
            ).exclude(
                product_line__in=ProductLineCodes.julo_one() + ProductLineCodes.grab()
            ).values(
                'cdate', 'application_xid',
                'email','fullname','creditscore__score',
                'product_line__product_line_type','loan__loan_amount',
                'loan__loan_duration','product_line__max_interest_rate',
                'application_status','loan_purpose',
                'lastest_history_cdate','applicationhistory__status_new'
            ).order_by(order_by)[:limit]

            filter_.pop('applicationhistory__status_new__in')
            filter_.pop('loan__partner')
            filter_['partner'] = user.partner

            if 'application_xid' in filter_:
                filter_.pop('application_xid')
                filter_['loan_xid'] = application_xid

            loans = Loan.objects.annotate(
                lastest_history_cdate=Max(
                    Case(
                        When(
                            Q(loanhistory__status_new=LoanStatusCodes.LENDER_APPROVAL) |
                            Q(loanhistory__status_new=LoanStatusCodes.LENDER_REJECT) |
                            Q(loanhistory__status_new=LoanStatusCodes.CURRENT) |
                            Q(loanhistory__status_new=LoanStatusCodes.FUND_DISBURSAL_ONGOING),
                            then=F('loanhistory__cdate')
                        )
                    )
                ),
            ).filter(
                **filter_
            ).filter(
                loan_status__in=[LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                                 LoanStatusCodes.CURRENT,
                                 LoanStatusCodes.LENDER_REJECT],
                account__application__product_line__in=
                ProductLineCodes.julo_one() + ProductLineCodes.grab()
            ).order_by(order_by)[:limit]
            loans_data = loans.annotate(
                lastest_history_cdate=F('lastest_history_cdate'),
                fullname=F('account__application__fullname'),
                gender=F('account__application__gender'),
                product_line__product_line_type=F(
                    'account__application__product_line__product_line_type'
                ),
                product_line__max_interest_rate=F(
                    'account__application__product_line__max_interest_rate'
                ),
                creditscore__score=F(
                    'account__application__creditscore__score'
                ),
                status=F('loan_status'),
                loan__loan_disbursement_amount=F('loan_disbursement_amount'),
                loan__loan_duration=F('loan_duration'),
                loan__loan_amount=F('loan_amount'),
                email=F('account__application__email'),
                application_status=F('loan_status'),
                loan_purpose_base_transaction_method=Case(
                    When(
                        transaction_method_id=TransactionMethodCode.SELF.code,
                        then=F('loan_purpose')
                    ),
                    When(
                        transaction_method_id__in=
                        TransactionMethodCode.loan_purpose_base_transaction_method(),
                        then=F('transaction_method__fe_display_name')
                    ),
                    When(
                        transaction_method_id__isnull=True,
                        then=F('account__application__loan_purpose')
                    ),
                    output_field=CharField()
                )
            ).values(
                'application_xid', 'lastest_history_cdate', 'fullname',
                'product_line__product_line_type', 'email',
                'product_line__max_interest_rate', 'loan__loan_disbursement_amount',
                'loan__loan_amount', 'creditscore__score', 'loan_purpose',
                'loan__loan_duration', 'application_status', 'loan_xid', 'loan_status',
                'account__application__loan_purpose', 'loan_purpose_base_transaction_method'
            )

            res_data = []

            for application in list(chain(applications, loans_data)):
                app = Application.objects.get_or_none(application_xid=application['application_xid'])
                application_experiment = app.applicationexperiment_set.filter(
                    experiment__code=ExperimentConst.FALSE_REJECT_MINIMIZATION
                    )
                if application_experiment:
                    application['creditscore__score'] = FalseRejectMiniConst.SCORE
                if 'loan_xid' in application and application['loan_xid']:
                    application['application_xid'] = application['loan_xid']
                if not application['creditscore__score']:
                    application['creditscore__score'] = 'B+'

                loan_purpose = application['loan_purpose']
                if 'loan_purpose_base_transaction_method' in application:
                    loan_purpose = application['loan_purpose_base_transaction_method']

                if 'loan_status' in application and application['loan_status'] == 220:
                    application['application_status'] = 180
                elif 'loan_status' in application and application['loan_status'] == 219:
                    application['application_status'] = 135
                elif 'loan_status' in application and application['loan_status'] == 212:
                    application['application_status'] = 177
                elif 'loan_status' in application and application['loan_status'] == 218:
                    application['application_status'] = 181

                item = {
                    "in_date":application['lastest_history_cdate'],
                    "application_xid":application['application_xid'],
                    "fullname": application['fullname'],
                    "creditscore__score": application['creditscore__score'],
                    "product_line__product_line_type": application['product_line__product_line_type'],
                    "loan__loan_amount": application['loan__loan_amount'],
                    "loan__loan_duration": application['loan__loan_duration'],
                    "product_line__max_interest_rate": application['product_line__max_interest_rate'],
                    "status": application['application_status'],
                    "loan_purpose": loan_purpose
                }

                res_data.append(item)

            return success_response(spoofing_response(res_data, 'fullname', 2))

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - ListApplicationPastViews',
                'data': data,
                'errors': str(e)
            })
            print('error ListApplicationPastViews__ ', str(e))
            JuloException(e)
            return server_error_response()


class LoanAgreementViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = LoanAgreementSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user
        partner = user.partner

        if partner is None:
            return general_error_response("partner tidak ada.")

        application_xid = data['application_xid']
        application = Application.objects.filter(application_xid=application_xid,
            partner=partner)
        if not application:
            return general_error_response("Application tidak ditemukan.")

        try:
            document = Document.objects.filter(application_xid=application_xid,
                document_type="lender_sphp").last()

            if not document:
                return general_error_response("Document tidak ditemukan.")

            return success_response({'url': document.document_url})

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - LoanAgreementViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class LenderApprovalViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = self.request.user
        data = request.data
        partner = user.partner

        return_value = {
            "is_auto": False,
            "delay": "00:00:00"
        }

        if partner is None:
            return general_error_response("partner tidak ada.")

        lender_approval = LenderApproval.objects.get_or_none(partner=partner)
        if lender_approval:
            feature_setting = get_whitelist_manual_approval_feature()
            return_value = {
                "is_auto": lender_approval.is_auto if not feature_setting else False,
                "delay": lender_approval.delay.strftime("%H:%M:%S")
            }

        return success_response(return_value)


@csrf_exempt
def disbursement(request):
    lender_bucket_id = request.POST.get('bucket')
    response = {'status': "", 'lender_bucket_id': lender_bucket_id}

    lender_bucket = LenderBucket.objects.filter(is_active=True, id=lender_bucket_id).last()
    if not lender_bucket:
        response['status'] = "Failed"
        response["message"] = "Lender Bucket tidak ditemukan"
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    try:
        for application_id in lender_bucket.application_ids['approved']:
            approved_application_process_disbursement.delay(application_id, lender_bucket.partner.id)

        lender_bucket.update_safely(is_active=False,
            is_disbursed=True,
            action_time=timezone.now(),
            action_name="Disbursed")

        response['status'] = "Success"
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error({
            'action_view': 'FollowTheMoney - AJAX DisbursementViews',
            'data': request,
            'errors': str(e)
        })
        JuloException(e)

        response['status'] = "Failed"
        return HttpResponse(json.dumps(response),
            content_type="application/json")


@csrf_exempt
def cancel(request):
    lender_bucket_id = request.POST.get('bucket')
    response = {'status': "", 'lender_bucket_id': lender_bucket_id}

    lender_bucket = LenderBucket.objects.get_or_none(pk=lender_bucket_id)
    if lender_bucket is None:
        response['status'] = "Failed"
        response["message"] = "Lender Bucket tidak ditemukan"
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    try:
        app_ids = lender_bucket.application_ids
        approved = app_ids['approved']

        # Set lender bucket to inactive
        lender_bucket.update_safely(is_active=False,
            action_time=timezone.now(),
            action_name="Canceled")

        response['status'] = "Success"
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error({
            'action_view': 'FollowTheMoney - AJAX CancelBucketViews',
            'data': lender_bucket_id,
            'errors': str(e)
        })
        JuloException(e)

        response['status'] = "Failed"
        return HttpResponse(json.dumps(response),
            content_type="application/json")


@csrf_exempt
def loanAgreement(request):
    application_xid = request.POST.get('application_xid')
    response = {'status': "", 'application_xid': application_xid, "url": ""}

    application = Application.objects.filter(application_xid=application_xid)
    if not application:
        response['status'] = "Failed"
        response["message"] = "Application tidak ditemukan."
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    document = Document.objects.filter(application_xid=application_xid, document_type="lender_sphp").last()
    if not document:
        response['status'] = "Failed"
        response["message"] = "Document tidak ditemukan."
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    try:
        response['status'] = "Success"
        response['url'] = document.document_url
        return HttpResponse(json.dumps(response),
            content_type="application/json")

    except Exception as e:
        get_julo_sentry_client().captureException()
        logger.error({
            'action_view': 'FollowTheMoney - AJAX loanAgreement',
            'data': application_xid,
            'errors': str(e)
        })
        JuloException(e)

        response['status'] = "Failed"
        return HttpResponse(json.dumps(response),
            content_type="application/json")


class PerformanceSummary(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = request.user
        lender = LenderCurrent.objects.get_or_none(user=user)

        if lender is None:
            return general_error_response("lender tidak ditemukan")

        lender_balance = LenderBalanceCurrent.objects.get_or_none(lender=lender.id)

        if lender_balance is None:
            return general_error_response('Lender balance tidak ditemukan')

        if lender.lender_name != 'jtp':
            net_annualized_yield = 4.17
        else:
            net_annualized_yield = 5.17

        res_data = {
            'total_outstanding': get_total_outstanding_for_lender(lender_name=lender.lender_name),
            'committed': lender_balance.committed_amount,
            'accrued_interest': lender_balance.outstanding_interest,
            'available_balance': lender_balance.available_balance,
            'outstanding_principal': lender_balance.outstanding_principal,
            'net_annualized_yield': net_annualized_yield
        }

        return success_response(res_data)


class History(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = request.user
        limit = request.GET.get('limit', 25)
        limit = get_max_limit(limit=limit)

        last_transaction_id = request.query_params.get('last_lender_transaction_id')
        lender = LenderCurrent.objects.get_or_none(user=user)

        if lender is None:
            return general_error_response("lender tidak ditemukan")

        lender_transactions = LenderTransaction.objects.filter(lender=lender)

        if last_transaction_id is None:
            lender_transactions = lender_transactions.order_by('-id')[:limit]
        else:
            lender_transactions = lender_transactions.filter(id__lt=last_transaction_id)\
                                                     .order_by('-id')[:limit]

        return success_response(LenderTransactionSerializer(lender_transactions, many=True).data)


class ListLoanDetail(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = request.user
        limit = request.query_params.get('limit')
        limit = get_max_limit(limit=limit)

        last_loan_id = request.query_params.get('last_loan_id')
        lender = LenderCurrent.objects.get_or_none(user=user)

        if lender is None:
            return general_error_response("Lender tidak temukan")

        loans_dict = get_loan_details(lender.id, last_loan_id, limit)
        sorted_loan_dict = sorted(list(loans_dict.items()),
                        key=lambda kv: (kv[1]['fund_transfer_ts'] is not None, kv[1]['fund_transfer_ts']), reverse=True)

        loan_data = []

        # check if lender does not have loan
        if len(list(loans_dict.keys())) != 0:
            last_loan_id = sorted_loan_dict[-1][0]
        else:
            return general_error_response("Lender tidak memiliki pinjaman")

        for key, value in sorted_loan_dict:
            loan_data.append({
                'lla_xid': value['lla_xid'],
                'dibursed_date': value['fund_transfer_ts'],
                'loan_amount': value['loan_amount'],
                'outstanding_principal': value['outstanding_principal_amount'],
                'oustanding_interest': value['outstanding_interest_amount'],
                'received_payment': value['total_paid'],
                'loan_purpose': value['loan_purpose'],
                'loan_duration': value['loan_duration'],
                'loan_status_code': value['loan_status_code']
            })

        return success_response(dict({
            'items': loan_data,
            'last_loan_id': last_loan_id
        }))


class AvailableBalance(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = request.user
        lender = LenderCurrent.objects.get_or_none(user=user)
        lender_balance_current = LenderBalanceCurrent.objects.get(lender_id=lender.id)

        available_balance = lender_balance_current.available_balance
        data = {
            'available_balance': available_balance
        }

        return success_response(data)


class LoanLenderAgreementViews(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request, application_xid):
        app = Application.objects.get_or_none(application_xid=application_xid)
        if not app:
            return not_found_response("aplikasi tidak temukan")

        lender = app.loan.lender
        lla_doc = get_loan_agreement_template(app, lender)
        if lla_doc:
            return success_response({"lla_docs":lla_doc})
        else:
            return general_error_response("gagal generate lla")


class RegisterLenderWebViews(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = RegisterLenderWebSerializer
    authentication_classes = []
    permission_classes = []

    @parser_classes((FormParser, MultiPartParser,))
    def post(self, request, *args, **kwargs):
        data = self.validate_data(self.serializer_class, request.data)
        try:
            lender = LenderCurrent.objects.create(
                lender_name=data['lender_name'],
                lender_address=data['lender_address'],
                business_type=data['business_type'],
                poc_email=data['poc_email'],
                poc_name=data['poc_name'],
                poc_phone=data['poc_phone'],
                poc_position=data['poc_position'],
                source_of_fund=data['source_of_fund'],
                addendum_number='',
                lender_display_name='',
                service_fee=0
            )
            if not lender:
                return server_error_response()

            for document_type in DocumentType.LIST:
                if not data.get(document_type):
                    continue

                post_document = data[document_type]

                filename = "lender_{}-{}.pdf".format(document_type, lender.id)
                file_path = os.path.join(tempfile.gettempdir(), filename)
                with open(file_path, "wb+") as f:
                    for chunk in post_document.chunks():
                        f.write(chunk)

                document = Document.objects.create(document_source=lender.id,
                    document_type=document_type,
                    filename=filename,
                    application_xid=None)

                upload_document.delay(document.id, file_path, True)

            res_data = {
                'msg': 'success',
                'success': True
            }
            return success_response(res_data)

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - RegisterLenderView',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class FTMDigisignDocumentStatusView(FollowTheMoneyAPIView):
    http_method_names = ['get']
    serializer_class = DocumentStatusLenderSerializer

    def get(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user
        digisign_client = get_julo_digisign_client()
        partner = user.partner
        lender = LenderCurrent.objects.get_or_none(user=user)
        response = {
            'is_existed': False,
            'is_signed': False,
            'digisign_mode': False,
        }
        feature_setting = MobileFeatureSetting.objects.filter(
            feature_name='digisign_mode', is_active=True).last()
        if not feature_setting:
            return success_response(response)
        else:
            response['digisign_mode'] = True

        if lender is None:
            return general_error_response("lender tidak ditemukan")

        try:
            bucket_id = request.GET.get('bucket_id')

            if not bucket_id:
                last_bucket = LenderBucket.objects.filter(partner=partner).last()
                bucket_id = last_bucket.id__gt

            document = Document.objects.get_or_none(document_source=bucket_id, document_type="summary_lender_sphp")
            if not document:
                return success_response(response)

            document_status_response = digisign_client.document_status(document.id)

            document_status_response_json = document_status_response['JSONFile']
            if (document_status_response_json['result'] == DigisignResultCode.SUCCESS
                and document_status_response_json['status'] == 'waiting'):
                response['is_existed'] = True
                response['is_signed'] = False
            elif (document_status_response_json['result'] == DigisignResultCode.SUCCESS
                and document_status_response_json['status'] == 'complete'):
                response['is_existed'] = True
                response['is_signed'] = True

            return success_response(response)

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - FTMDigisignDocumentStatusView',
                'data': data,
                'errors': str(e)
            })
            return server_error_response()


class FTMDigisignSignDocumentView(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request, bucket_id):
        digisign_client = get_julo_digisign_client()
        user = self.request.user
        lender = LenderCurrent.objects.get_or_none(user=user)

        if lender is None:
            return general_error_response("lender tidak ditemukan")

        document = Document.objects.get_or_none(document_source=bucket_id, document_type="summary_lender_sphp")
        try:
            html_webview = digisign_client.sign_document(document.id, lender.poc_email, is_web_browser=True)
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - FTMDigisignSignDocumentView',
                'data': bucket_id,
                'errors': str(e)
            })
            JuloException(e)
            return general_error_response("webview digisign tidak dapat dibuka")

        return StreamingHttpResponse(html_webview)


class FTMListDocumentView(FollowTheMoneyAPIView):
    http_method_names = ['get']
    serializer_class = ListBucketLenderSerializer

    def get(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        user = self.request.user

        try:
            limit = request.GET.get('limit', 1)
            order = request.GET.get('order', 'desc')
            is_signed = data['is_signed'] if data['is_signed'] else False
            bucket_id = request.GET.get('bucket_id')
            last_bucket_id = request.GET.get('last_bucket_id')

            filter_ = dict(
                partner=user.partner,
                is_active=True,
                is_signed=is_signed
            )

            if bucket_id:
                filter_['id'] = bucket_id

            order_by = '-id'
            if order == "desc":
                if last_bucket_id:
                    filter_['id__lt'] = last_bucket_id
            elif order == "asc":
                order_by = 'id'
                if last_bucket_id:
                    filter_['id__gt'] = last_bucket_id

            lender_buckets = LenderBucket.objects.filter(**filter_).exclude(
                action_name="Canceled").order_by(order_by)[:limit]
            bucket_list = lender_buckets.values('id', 'cdate', 'is_signed')

            for bucket in bucket_list:
                document = Document.objects.get_or_none(
                    document_source=bucket['id'], document_type="summary_lender_sphp")
                bucket['filename'] = document.filename if document else "-"

            return success_response(bucket_list)

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - ListLenderBucketViews',
                'data': data,
                'errors': str(e)
            })
            JuloException(e)
            return server_error_response()


class FTMSignedDocumentView(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = SignedDocumentLenderSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)

        try:
            lenderbucket = LenderBucket.objects.get_or_none(pk=data['bucket_id'])

            if lenderbucket is None:
                return general_error_response("lender bucket tidak ditemukan")

            # update bucket status
            lenderbucket.update_safely(is_signed=True, is_active=False)

            # update application status to 170/178
            bulk_approved_application_process_disbursement.delay(lenderbucket, data['signature_method'])

            return success_response()
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - FTMSignedDocumentView',
                'data': data,
                'errors': str(e)
            })
            return server_error_response()


class UnsignApplicationsView(FollowTheMoneyAPIView):
    http_method_names = ['get']

    def get(self, request):
        user = self.request.user
        lender = LenderCurrent.objects.get_or_none(user=user)

        try:
            response = {
                'unsign_count': 0,
                'unsign_applications': [],
                'digisign_mode': False,
            }
            unsign_applications = LenderSignature.objects.filter(
                loan__lender=lender,
                signed_ts=False
            ).values_list('loan__application_id', flat=True)
            if unsign_applications:
                response['unsign_count'] = unsign_applications.count()
                response['unsign_applications'] = unsign_applications

            feature_setting = MobileFeatureSetting.objects.filter(
                feature_name='digisign_mode', is_active=True).last()
            if feature_setting:
                response['digisign_mode'] = True

            return success_response(response)

        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error({
                'action_view': 'FollowTheMoney - UnsignApplicationsView',
                'data': request,
                'errors': str(e)
            })
            return server_error_response()


class OJKSubmitFormView(FollowTheMoneyAPIView):
    http_method_names = ['post']
    serializer_class = OJKSubmitFormSerializer
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)

        fullname = data['fullname']
        phone_number = data['phone_number']
        email = data['email']

        email_client = get_julo_email_client()

        subject = 'Request Laporan Keuangan Tahunan JULO'
        email_to = 'statistik@julo.co.id'
        email_from = 'info@julo.co.id'
        context = {
            'fullname': fullname,
            'email': email,
            'phone_number': phone_number
        }
        message = render_to_string(
            'request_laporan_keuangan_template.html',
            context)

        status, body, headers = email_client.send_email(
            subject=subject,
            content=message,
            email_to=email_to,
            email_from=email_from,
            email_cc=None,
            name_from='JULO',
            reply_to=email_from,
        )

        email_history = EmailHistory.objects.create(
            sg_message_id=headers['X-Message-Id'],
            status=str(status),
            to_email=email_to,
            subject=subject,
            message_content=message
        )

        if email_history:
            return success_response()
