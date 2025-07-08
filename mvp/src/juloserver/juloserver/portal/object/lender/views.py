from builtins import str
from builtins import range
import json
import operator
import random
import string
import logging
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.core import serializers
from django.core.urlresolvers import reverse
from django.db import transaction
from django.db.models import Q, Case, When, IntegerField
from django.http import (HttpResponse,
                         HttpResponseNotAllowed,
                         HttpResponseBadRequest,
                         JsonResponse,
                         HttpResponseServerError,
                         HttpResponseRedirect)
from django.shortcuts import render
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView, TemplateView, View
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages

from object import julo_login_required, julo_login_required_multigroup, julo_login_required_group
from object.dashboard.constants import JuloUserRoles

from juloserver.julo.models import LenderBalance
from juloserver.julo.models import LenderCustomerCriteria
from juloserver.julo.models import LenderDisburseCounter
from juloserver.julo.models import LenderProductCriteria
from juloserver.julo.models import LenderServiceRate
from juloserver.julo.models import Partner
from juloserver.julo.models import ProductCustomerCriteria
from juloserver.julo.models import ProductProfile
from juloserver.julo.models import ProductLookup, FeatureSetting
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException

from juloserver.julo.banks import BankManager
from juloserver.followthemoney.models import LenderCurrent, LenderBankAccount, LenderInsurance
from juloserver.followthemoney.tasks import (
    send_email_set_password,
    calculate_available_balance)
from juloserver.followthemoney.constants import (
    BusinessType, SourceOfFund,
    DocumentType, BankAccountType, LenderStatus,
    LenderRepaymentTransactionStatus,
    LenderRepaymentTransferType
)
from juloserver.followthemoney.models import (LenderWithdrawal,
                                              LenderTransaction,
                                              LenderTransactionMapping,
                                              LenderBalanceCurrent,
                                              LenderTransactionType,
                                              LenderRepaymentTransaction)
from juloserver.followthemoney.constants import LenderTransactionTypeConst, SnapshotType
from juloserver.followthemoney.withdraw_view.services import get_lender_withdrawal_process_by_id
from juloserver.followthemoney.services import get_transfer_order
from juloserver.followthemoney.services import update_successful_repayment
from juloserver.followthemoney.services import create_repayment_data, new_repayment_transaction
from juloserver.followthemoney.services import retry_repayment_transaction, get_transaction_detail

from juloserver.julocore.python2.utils import py2round
from juloserver.julo.services import reset_lender_disburse_counter
from juloserver.julo.constants import FeatureNameConst

from product_profile.constants import JOB_TYPE_CHOICES
from product_profile.constants import JOB_INDUSTRY_CHOICES
from product_profile.constants import JOB_DESCRIPTION_CHOICES
from product_profile.constants import CREDIT_SCORE_CHOICES
from product_profile.constants import CREDIT_SCORE_CHOICES_EXCLUDE_C
from product_profile.constants import MTL_STL_PRODUCT
from product_profile.forms import ProductProfileSearchForm
from product_profile.services import get_cleaned_data
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from .utils import LoggedResponse, StatementParserFactory
from .utils import LoggedResponse, transform_mintos_upload_key
from .forms import UploadFileForm, LenderReversalPaymentForm
from .serializers import MintosUpdateSerializer

from rest_framework.status import (HTTP_200_OK,
                                   HTTP_404_NOT_FOUND,
                                   HTTP_400_BAD_REQUEST,
                                   HTTP_500_INTERNAL_SERVER_ERROR)
from juloserver.followthemoney.services import (get_repayment_transaction_data,
                                                filter_by_repayment_transaction,
                                                generate_group_id)
from juloserver.followthemoney.utils import split_total_repayment_amount
from .constants import RepaymentParseConst
from juloserver.julo.services2 import get_redis_client

from juloserver.lenderinvestment.tasks import update_mintos_loan_from_report
from juloserver.lenderinvestment.services import upsert_mintos_report
from juloserver.sdk.services import xls_to_dict
from juloserver.followthemoney.services import (get_reversal_trx_data,
                                                deduct_lender_reversal_transaction)
from functools import reduce
from juloserver.julo.partners import PartnerConstant

logger = logging.getLogger(__name__)

@julo_login_required
@julo_login_required_group(JuloUserRoles.BUSINESS_DEVELOPMENT)
class LenderProductListView(ListView):
    model = Partner
    paginate_by = 50
    template_name = 'object/lender/list.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = Partner.objects.filter(type='lender')
        self.err_message_here = None
        self.search_q = None
        self.sort_q = None
        self.sort_agent = None

        if self.request.method == 'GET':
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [Q(**{('%s__icontains' % 'id'): self.search_q}),
                     Q(**{('%s__icontains' % 'code'): self.search_q}),
                     Q(**{('%s__icontains' % 'name'): self.search_q}),
                     Q(**{('%s__icontains' % 'partner__name'): self.search_q}),
                    ]))

            if(self.sort_q):
                self.qs = self.qs.order_by(self.sort_q)

            return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(LenderProductListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ProductProfileSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ProductProfileSearchForm()

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context

    def render_to_response(self, context, **response_kwargs):
        rendered = super(LenderProductListView, self).render_to_response(context, **response_kwargs)
        return rendered


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'business_development'])
class LenderRegistrationView(ListView):
    model = LenderCurrent
    paginate_by = 50
    template_name = 'object/lender/registration.html'

    def get_queryset(self):
        self.qs = super(LenderRegistrationView, self).get_queryset()
        self.search_q = None
        self.sort_q = None

        if self.request.method == 'GET':
            self.search_q = self.request.GET.get('q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [Q(**{('%s__icontains' % 'lender_name'): self.search_q}),
                     Q(**{('%s__icontains' % 'lender_display_name'): self.search_q}),
                     Q(**{('%s__icontains' % 'lender_status'): self.search_q}),
                     Q(**{('%s__icontains' % 'business_type'): self.search_q}),
                     Q(**{('%s__icontains' % 'poc_email'): self.search_q}),
                     Q(**{('%s__icontains' % 'poc_name'): self.search_q}),
                    ]))

            if(self.sort_q):
                self.qs = self.qs.order_by(self.sort_q)

            return self.qs

    def get_context_data(self, **kwargs):
        context = super(LenderRegistrationView, self).get_context_data(**kwargs)
        self.q = self.request.GET.get('q', '').strip()
        context['extra_context'] = {'q': self.q}
        context['q_value'] = self.q
        context['results_per_page'] = self.paginate_by
        context['DONE_STATUS'] = LenderStatus.DONE_STATUS
        return context


@julo_login_required
def verification(request, pk):
    lender = LenderCurrent.objects.get(id=pk)
    if lender.lender_status in LenderStatus.PROCESS_STATUS:
        lender.lender_status = LenderStatus.IN_PROGRESS
        lender.save()
        pass
    else:
        url = reverse('lender:registration')
        return redirect(url)

    template_name = 'object/lender/verification.html'
    npwp = lender.npwp()
    akta = lender.akta()
    tdp = lender.tdp()
    siup = lender.siup()
    nib = lender.nib()
    sk_menteri = lender.sk_menteri()
    skdp = lender.skdp()
    insurance = LenderInsurance.objects.first()
    if not insurance:
        insurance = {"id": 0, "name": "PT. Asuransi Simas Insurtech"}

    context_data = {}
    context_data['lender'] = lender
    context_data['PRODUCT_LIST'] = ProductProfile.objects.order_by('name').all()
    context_data['MTL_STL_PRODUCT'] = MTL_STL_PRODUCT
    context_data['BUSINESS_TYPES'] = BusinessType.LIST
    context_data['SOURCE_OF_FUNDS'] = SourceOfFund.LIST
    context_data['BANK_ACCOUNT_TYPES'] = BankAccountType.LIST
    context_data['BANK_ACCOUNT_VA'] = BankAccountType.VA
    context_data['CREDIT_SCORE_CHOICES'] = CREDIT_SCORE_CHOICES_EXCLUDE_C
    context_data['BANK_LIST'] = BankManager.get_bank_names()
    context_data['DOCUMENTS'] = [ npwp, akta, tdp, siup, nib, sk_menteri, skdp ]
    context_data['INSURANCE'] = insurance

    return render(
        request,
        template_name,
        context_data
    )

@julo_login_required
def reject(request, pk):
    lender_registration = LenderCurrent.objects.filter(id=pk)
    lender_registration.update(lender_status=LenderStatus.TERMINATED)

    url = reverse('lender:registration')
    return redirect(url)

@julo_login_required
def add(request):
    template_name = 'object/lender/add.html'
    context_data = {}
    partner_list = Partner.objects.filter(type='lender')
    product_list = ProductProfile.objects.all()

    context_data['LENDER_PRODUCT_TYPE_CHOICES'] = [type[0] \
    for type in LenderProductCriteria.LENDER_PRODUCT_TYPE_CHOICES]
    context_data['JOB_TYPE_CHOICES'] = JOB_TYPE_CHOICES
    context_data['JOB_INDUSTRY_CHOICES'] = JOB_INDUSTRY_CHOICES
    context_data['JOB_DESCRIPTION_CHOICES'] = JOB_DESCRIPTION_CHOICES
    context_data['CREDIT_SCORE_CHOICES'] = CREDIT_SCORE_CHOICES
    context_data['partner_list'] = partner_list
    context_data['product_list'] = product_list
    context_data['isError'] = False

    return render(
        request,
        template_name,
        context_data
    )

@julo_login_required
def details(request, pk):
    lender = Partner.objects.get(id=pk)
    lender_product = LenderProductCriteria.objects.filter(partner=lender).first()
    template_name = 'object/lender/detail.html'
    context_data = {}
    context_data['partner'] = lender
    if lender_product:
        context_data['lender_product_criteria_id'] = lender_product.id
        context_data['status'] = 'Edit'
    else:
        context_data['lender_product_criteria_id'] = None
        product_list = ProductProfile.objects.all()

        context_data['LENDER_PRODUCT_TYPE_CHOICES'] = [type[0] \
        for type in LenderProductCriteria.LENDER_PRODUCT_TYPE_CHOICES]
        context_data['JOB_TYPE_CHOICES'] = JOB_TYPE_CHOICES
        context_data['JOB_INDUSTRY_CHOICES'] = JOB_INDUSTRY_CHOICES
        context_data['JOB_DESCRIPTION_CHOICES'] = JOB_DESCRIPTION_CHOICES
        context_data['CREDIT_SCORE_CHOICES'] = CREDIT_SCORE_CHOICES
        context_data['product_list'] = product_list
        context_data['isError'] = False
        context_data['status'] = 'Add'

    return render(
        request,
        template_name,
        context_data
    )

@julo_login_required
def lender_details(request, pk):
    lender = LenderCurrent.objects.get(id=pk)
    template_name = 'object/lender/lender_details.html'
    npwp = lender.npwp()
    akta = lender.akta()
    tdp = lender.tdp()
    siup = lender.siup()
    nib = lender.nib()
    sk_menteri = lender.sk_menteri()
    skdp = lender.skdp()

    lender_product_criteria = LenderProductCriteria.objects.get_or_none(lender=lender)
    products = []
    if lender_product_criteria:
        products = ProductProfile.objects.filter(
            pk__in=lender_product_criteria.product_profile_list
            ).values_list('name', flat=True)

    lender_customer_criteria = LenderCustomerCriteria.objects.get_or_none(lender=lender)
    credit_scores = []
    if lender_customer_criteria:
        if lender_customer_criteria.credit_score:
            credit_scores = lender_customer_criteria.credit_score

    insurance = lender.insurance
    has_insurance = True
    if not insurance:
        insurance = {"id": 0, "name": "PT. Asuransi Simas Insurtech"}
        has_insurance = False

    context_data = {}
    context_data['lender'] = lender
    context_data['banks'] = LenderBankAccount.objects.filter(lender=lender)
    context_data['va'] = BankAccountType.VA
    context_data['products'] = products
    context_data['credit_scores'] = credit_scores
    context_data['account'] = lender.user
    context_data['documents'] = [ npwp, akta, tdp, siup, nib, sk_menteri, skdp ]
    context_data['insurance'] = insurance
    context_data['has_insurance'] = has_insurance

    return render(
        request,
        template_name,
        context_data
    )

def ajax_get_detail(request):
    response_data = {}
    if request.method != 'GET':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    partner_id = int(request.GET.get('partner_id'))
    partner = get_object_or_404(Partner, id=partner_id)
    lender_product_criteria = LenderProductCriteria.objects.get_or_none(partner=partner)
    lender_customer_criteria = LenderCustomerCriteria.objects.filter(
                                partner=partner).first()
    product_profile_list = ProductProfile.objects.all()

    response_data['lender_product_criteria'] = {}
    response_data['lender_customer_criteria'] = {}

    if lender_product_criteria:
        response_data['lender_product_criteria'] = json.loads(
            serializers.serialize('json', [lender_product_criteria]))[0]
    if lender_customer_criteria:
        response_data['lender_customer_criteria'] = json.loads(
            serializers.serialize('json', [lender_customer_criteria]))[0]

    response_data['product_profile_list'] = json.loads(
        serializers.serialize('json', product_profile_list))
    response_data['partner'] = json.loads(serializers.serialize('json', [partner]))[0]
    response_data['LENDER_PRODUCT_TYPE_CHOICES'] = [type[0] for type in \
        LenderProductCriteria.LENDER_PRODUCT_TYPE_CHOICES]
    response_data['JOB_TYPE_CHOICES'] = JOB_TYPE_CHOICES
    response_data['JOB_INDUSTRY_CHOICES'] = JOB_INDUSTRY_CHOICES
    response_data['JOB_DESCRIPTION_CHOICES'] = JOB_DESCRIPTION_CHOICES
    response_data['CREDIT_SCORE_CHOICES'] = CREDIT_SCORE_CHOICES

    return HttpResponse(
        json.dumps(response_data, indent=2),
        content_type="application/json"
    )

def ajax_update_detail(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    data = request.POST.dict()
    lender_product_data = get_cleaned_data(json.loads(data['lender_product']))
    lender_customer_data = get_cleaned_data(json.loads(data['lender_customer']))
    partner = Partner.objects.get_or_none(pk=lender_product_data['partner'])
    lender_product_data['partner'] = partner
    lender_customer_data['partner'] = partner

    try:
        with transaction.atomic():
            lender_product_criteria = LenderProductCriteria(**lender_product_data)
            lender_product_criteria.clean()
            lender_product_criteria.save()
            # assign product profile object to Product Customer Criteria
            lender_customer_criteria = LenderCustomerCriteria(**lender_customer_data)
            lender_customer_criteria.clean()
            lender_customer_criteria.save()

        url = reverse('lender:details', kwargs={'pk': partner.id})
        return HttpResponse(
            json.dumps({'url': url}),
            content_type="application/json")

    except Exception as e:
        return HttpResponseBadRequest(content=e)

def ajax_add_lender_account(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    data = request.POST.dict()
    lender = json.loads(data['lender'])
    lender_service_rate = json.loads(data['lender_service_rate'])

    response_data = {}

    user_exist = User.objects.filter(username=lender['username']).first()

    if user_exist:
        return HttpResponseBadRequest(content='username already exists')

    try:
        with transaction.atomic():
            user = User.objects.create_user(lender['username'],
                                            lender['email'],
                                            lender['password'])
            partner = Partner.objects.create(user=user,
                                             name=lender['name'],
                                             type=lender['type'],
                                             email=user.email,
                                             is_active=lender['is_active'],
                                             npwp=lender['npwp'],
                                             poc_name=lender['poc_name'],
                                             poc_email=lender['poc_email'],
                                             poc_phone=lender['poc_phone'],
                                             source_of_fund=lender['source_of_fund'],
                                             company_name=lender['company_name'],
                                             company_address=lender['company_address'],
                                             business_type=lender['business_type'])
            disburse_counter = LenderDisburseCounter.objects.create(
                partner=partner, actual_count=0, rounded_count=0)
            lender_balance = LenderBalance.objects.create(partner=partner)
            lender_service_rate = LenderServiceRate.objects.create(
                partner=partner,
                provision_rate=float(lender_service_rate['provision_rate']),
                principal_rate=float(lender_service_rate['principal_rate']),
                interest_rate=float(lender_service_rate['interest_rate']),
                late_fee_rate=float(lender_service_rate['late_fee_rate']))

            is_reset = reset_lender_disburse_counter()

            response_data['status'] = 'success'
            response_data['message'] = 'success add partner'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )

    except Exception as e:
        return HttpResponseBadRequest(content=str(e))

def ajax_add_lender_product(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    data = request.POST.dict()
    lender_product_data = get_cleaned_data(json.loads(data['lender_product']))
    lender_customer_data = get_cleaned_data(json.loads(data['lender_customer']))

    partner_id = lender_product_data['partner']
    partner = Partner.objects.get_or_none(pk=partner_id)

    if partner is None:
        return HttpResponseBadRequest(content='partner with id %s does not exist!!' % partner_id)

    lender_product_data['partner'] = partner
    lender_customer_data['partner'] = partner

    try:
        with transaction.atomic():
            lender_product = LenderProductCriteria(**lender_product_data)
            lender_product.clean()
            lender_product.save()
            lender_customer = LenderCustomerCriteria(**lender_customer_data)
            lender_customer.clean()
            lender_customer.save()

        url = reverse('lender:list')
        return HttpResponse(
            json.dumps({'url': url}),
            content_type="application/json"
        )

    except Exception as e:
        return HttpResponseBadRequest(content=e)

def ajax_get_lender(request):
    response_data = {}
    if request.method != 'GET':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    lender_id = int(request.GET.get('lender_id'))
    lender = get_object_or_404(LenderCurrent, id=lender_id)
    response_data['lender'] = json.loads(serializers.serialize('json', [lender]))[0]

    return HttpResponse(
        json.dumps(response_data, indent=2),
        content_type="application/json"
    )

def ajax_submit_verification(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    data = request.POST.dict()
    lender_data = json.loads(data['lender'])
    account_data = json.loads(data['account'])
    product_data = json.loads(data['product'])
    customer_data = json.loads(data['customer'])
    bank_data = json.loads(data['bank'])

    lender = LenderCurrent.objects.filter(pk=lender_data['id'])
    lender_data['lender_status'] = LenderStatus.INACTIVE

    user_exist = User.objects.filter(username=account_data['username']).first()

    if user_exist:
        return HttpResponseBadRequest(content='username already exists')

    try:
        with transaction.atomic():
            if lender_data['insurance'] == "0":
                lender_insurance = LenderInsurance.objects.update_or_create(name="PT. Asuransi Simas Insurtech")
                lender_data['insurance'] = lender_insurance

            alphabet = string.ascii_letters + string.digits
            password = ''.join(random.choice(alphabet) for i in range(8))

            lender.update(**lender_data)
            lender = lender.first()
            lender.refresh_from_db()

            user = User.objects.create_user(account_data['username'],
                lender_data['poc_email'], password)
            lender.user = user
            lender.save()
            lender.refresh_from_db()

            product_data['lender'] = lender
            lender_product_criteria = LenderProductCriteria(**product_data)
            lender_product_criteria.save()

            customer_data['lender'] = lender
            lender_customer_criteria = LenderCustomerCriteria(**customer_data)
            lender_customer_criteria.save()

            banks = []
            for bank in bank_data:
                bank = bank_data[bank]
                bank['lender'] = lender
                banks.append(LenderBankAccount(**bank))

            LenderBankAccount.objects.bulk_create(banks)

            ldc = LenderDisburseCounter.objects.get_or_none(lender=lender)
            if not ldc:
                LenderDisburseCounter.objects.create(lender=lender)

            lbc = LenderBalanceCurrent.objects.get_or_none(lender=lender)
            if not lbc:
                LenderBalanceCurrent.objects.create(lender=lender)

        send_email_set_password.apply_async((lender.id,), countdown=45)
        url = reverse('lender:lender_details', kwargs={'pk': lender.id})
        return HttpResponse(
            json.dumps({'url': url}),
            content_type="application/json")

    except Exception as e:
        return HttpResponseBadRequest(content=e)


def ajax_submit_update_transaction(request):
    if request.method == 'POST':
        data = request.POST
        transaction_id = data.get('transaction_id')
        withdrawal_id = data.get('withdrawal_id')
        if not (transaction_id and withdrawal_id):
            return res_error()
        withdrawal_process = get_lender_withdrawal_process_by_id(withdrawal_id)
        if not withdrawal_process:
            return res_error()
        withdrawal_process.agent_trigger(transaction_id)
        return res_success()


def ajax_confirm_transaction(request):
    if request.method == 'POST':
        data = request.POST
        withdrawal_id = data.get('withdrawal_id')
        withdrawal_process = get_lender_withdrawal_process_by_id(withdrawal_id)
        if not withdrawal_process:
            return res_error()
        withdrawal_process.do_withdraw()
        return res_success()


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderWithdrawalListView(ListView):
    model = LenderWithdrawal
    paginate_by = 50
    template_name = 'object/lender/transaction.html'

    def get_queryset(self):
        self.qs = super(LenderWithdrawalListView, self).get_queryset()
        self.qs = self.qs.annotate(sort=Case(When(status='pending', then=0), default=1, output_field=IntegerField())) \
            .order_by('sort', '-cdate')
        return self.qs

    def get_context_data(self, **kwargs):
        context = super(LenderWithdrawalListView, self).get_context_data(**kwargs)
        xfers_withdrawal_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst.XFERS_WITHDRAWAL,
            is_active=True,
        )

        xfers_withdrawal_active = xfers_withdrawal_setting is not None

        context['results_per_page'] = self.paginate_by
        context['STATUS'] = "Seluruh Data"
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        context['xfers_withdrawal_active'] = xfers_withdrawal_active
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderReversalPaymentListView(View):
    model = LenderWithdrawal
    paginate_by = 50
    template_name = 'object/lender/reversal_payment.html'

    def get_reversal_trx_list(self, page):
        reversal_trx_list = get_reversal_trx_data()
        paginator = Paginator(reversal_trx_list, self.paginate_by)
        try:
            result_data = paginator.page(page)
        except PageNotAnInteger:
            result_data = paginator.page(1)
        except EmptyPage:
            result_data = paginator.page(paginator.num_pages)

        return {'object_list': result_data,
                'paginator':paginator,
                'is_paginated': True,
                'results_per_page': self.paginate_by,
                'page': page
        }

    def get(self, request):
        page = request.GET.get('page', 1)
        context = self.get_reversal_trx_list(page)
        return render(request, self.template_name, context)

    def post(self, request):
        form = LenderReversalPaymentForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            status, message = deduct_lender_reversal_transaction(data)
            if status:
                messages.success(request, 'reversal payment processed please wait a minute and refresh this page to check the status.')
                return redirect(reverse('lender:reversal_payment_list'))
            else:
                page = request.GET.get('page', 1)
                context = self.get_reversal_trx_list(page)
                context['form'] = form
                context['error'] = 'reversal payment tidak ditemukan'
                return render(request, self.template_name, context)
        else:
            page = request.GET.get('page', 1)
            context = self.get_reversal_trx_list(page)
            context['form'] = form
            context['error'] = 'Loan description wajib diisi'
            return render(request, self.template_name, context)


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
def repayment_list(request, redis_key):
    template_name = 'object/lender/repayment.html'
    context = {}
    context['STATUS'] = "Seluruh Data"
    context['PROJECT_URL'] = settings.PROJECT_URL
    context['repayment_dict'] = get_transfer_order(redis_key)
    context['repayment_dict'] = filter_by_repayment_transaction(context['repayment_dict'])
    return render(
        request,
        template_name,
        context
    )


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_finance'])
class LenderRepaymentUploadView(TemplateView):
    template_name = 'object/lender/repayment-upload-statement.html'

    def get_context_data(self, **kwargs):
        context = super(LenderRepaymentUploadView, self).get_context_data(**kwargs)
        context['list_repayment_channels'] = [
            'BCA 18888',
            'BCA 10994',
            'Faspay 31932',
            'Faspay 32401',
            'Midtrans',
            'Permata',
            'BRI',
            'Icare',
            'Axiata'
        ]

        return context


@csrf_protect
def ajax_repayment_upload(request):
    post_data = request.POST.dict()

    if ',' in post_data['repayment_types']:
        list_repayment_types = post_data['repayment_types'].split(',')
    else:
        list_repayment_types = [post_data['repayment_types']]

    if request.FILES is None:
        return JsonResponse({
            'status': 'failed',
            'message': 'no files uploaded'
        })

    files = request.FILES.getlist('file')
    repayment_type_dict = {
        'BCA 18888': RepaymentParseConst.BCA_18888,
        'BCA 10994': RepaymentParseConst.BCA_10994,
        'Faspay 31932': RepaymentParseConst.FASPAY_31932,
        'Faspay 32401': RepaymentParseConst.FASPAY_32401,
        'Midtrans': RepaymentParseConst.MIDTRANS,
        'Permata': RepaymentParseConst.PERMATA,
        'BRI': RepaymentParseConst.BRI,
        'Icare': RepaymentParseConst.ICARE,
        'Axiata': RepaymentParseConst.AXIATA,
    }

    parsed_result_arr = {}
    parser_factory = StatementParserFactory()
    for index, file in enumerate(files):
        repayment_file_type = repayment_type_dict[list_repayment_types[index]]
        data = file.read()
        parser = parser_factory.get_parser(repayment_file_type)
        try:
            parsed_result_arr[repayment_file_type] = parser.parse(data)
        except Exception as e:
            return JsonResponse({
                'status': 'failed',
                'reason': 'please check the file again',
                'msg': str(e)
            })

        file.close()

    today = timezone.localtime(timezone.now())
    redis_client = get_redis_client()
    repayment_redis_key = RepaymentParseConst.REPAYMENT_REDIS_KEY + today.strftime("%s")
    redis_client.set(
        repayment_redis_key,
        parsed_result_arr,
        timedelta(hours=2))

    return JsonResponse({
        'message': 'success',
        'redis_key': repayment_redis_key
    })


def res_error():
    res = HttpResponse(status=400)
    res['status'] = 'ERROR'
    return res


def res_success():
    res = HttpResponse()
    res['status'] = 'OK'
    return res


@csrf_protect
def ajax_update_repayment(request):
    data = request.POST
    bank_reference_code = data['bank_reference_code']
    transaction_id = data['transaction_id']

    successful_trans = LenderRepaymentTransaction.objects.get_or_none(
        id=transaction_id,
        status__in=[LenderRepaymentTransactionStatus.COMPLETED,
                    LenderRepaymentTransactionStatus.PENDING],
        transfer_type=LenderRepaymentTransferType.MANUAL
    )

    if not successful_trans:
        logger.error({
            'action_view': 'XfersRdlTopUpView',
            'data': data,
            'errors': 'Repayment transaction not found'
        })

        return JsonResponse({
            'status': 'failed',
            'message': 'No transactions!'
        })
    updated_data = {'reference_id': bank_reference_code}
    if successful_trans.additional_info.get('callback_payload'):
        updated_data['status'] = LenderRepaymentTransactionStatus.COMPLETED
    successful_trans.update_safely(**updated_data)

    unprocessed_trans_in_group = LenderRepaymentTransaction.objects.filter(
        lender=successful_trans.lender_id,
        group_id=successful_trans.group_id
    ).exclude(status=LenderRepaymentTransactionStatus.COMPLETED)

    # create lender transaction and linked it relation
    # if only this is the last LenderRepaymentTransaction callback from the group
    if not unprocessed_trans_in_group:
        try:
            lender_transaction_id = update_successful_repayment(
                successful_trans.group_id,
                successful_trans.additional_info['transaction_mapping_ids'],
                successful_trans.lender_id,
                successful_trans.additional_info['paid_principal'],
                successful_trans.additional_info['paid_interest'],
                successful_trans.additional_info['total_service_fee'],
                successful_trans.additional_info['original_amount'],
            )
        except JuloException as error:
            return JsonResponse({
                'status': 'Failed',
                'message': error
            })
        else:
            LenderRepaymentTransaction.objects.filter(
                lender=successful_trans.lender_id,
                group_id=successful_trans.group_id
            ).update(
                lender_transaction_id=lender_transaction_id
            )

    return JsonResponse({
        'status': 'success',
        'message': 'Repayment success!'
    })


@csrf_protect
def reserve_for_manual_transfer(request):
    if request.method == 'POST':
        request_data = request.POST.dict()
        redis_repayment_key = request_data['redis_key']
        lender_id = request.POST.get('lender_id')
        lender_target = LenderCurrent.objects.get(pk=lender_id)

        with transaction.atomic():
            group_data, can_process = get_transaction_detail(lender_id)

            if group_data and can_process:
                retry_repayment_transaction(lender_id)

            elif not group_data and can_process:
                data = get_repayment_transaction_data(lender_target, redis_key=redis_repayment_key)
                split_amount_list = []

                repayment_type_list = data['repayment_detail']
                cust_account_number = data['cust_account_number']
                bank_name = data['bank_name']
                cust_name_in_bank = data['cust_name_in_bank']

                for repayment_type, repayment_detail in list(repayment_type_list.items()):
                    additional_info = repayment_detail['additional_info']
                    amount = repayment_detail['amount']
                    split_amount_list = split_total_repayment_amount(amount)
                    max_group_id = generate_group_id(lender_target.id)
                    for split_amount in split_amount_list:
                        transaction_data = create_repayment_data(split_amount,
                                                                 cust_account_number,
                                                                 bank_name,
                                                                 cust_name_in_bank,
                                                                 additional_info,
                                                                 LenderRepaymentTransferType.MANUAL,
                                                                 max_group_id,
                                                                 repayment_type)

                        transaction_record = new_repayment_transaction(transaction_data,
                                                                       lender=lender_target)

                        transaction_record.status = LenderRepaymentTransactionStatus.PENDING
                        transaction_record.save()

        return JsonResponse({
            'status': 'success',
            'message': 'update successfuly!'
        })


# callback for top-up and repayment to RDL from Xfers
class XfersRdlTopUpView(APIView):
    permission_classes = (AllowAny,)

    def error_500_response(self, error, data):
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()

        logger.error({
            'action_view': 'XfersRdlTopUpView',
            'data': data,
            'errors': str(error)
        })

        return LoggedResponse(
            status=HTTP_500_INTERNAL_SERVER_ERROR,
            data={"error": 'Something went wrong, please try again later or contact our customer service'}
        )

    def post(self, request):
        data = request.data
        va_number = data.get('virtual_account_number')
        amount = data.get('amount')
        status = data.get('status')
        logger.info({
            'action_view': 'XfersRdlTopUpViewInfo',
            'data': data,
        })
        if not amount:
            return LoggedResponse(
                status=HTTP_404_NOT_FOUND,
                data={
                    "error": "amount is mandatory"
                }
            )
        else:
            amount = int(py2round(float(amount)))

        lender_bank_account = LenderBankAccount.objects.filter(
            lender__lender_name=PartnerConstant.JTP_PARTNER, account_number=va_number,
            bank_account_status='active').last()
        if not lender_bank_account:
            return LoggedResponse(
                status=HTTP_404_NOT_FOUND,
                data={
                    "error": "bank account with virtual_account_number %s not found" % va_number
                }
            )
        lender = lender_bank_account.lender
        if lender_bank_account.bank_account_type == BankAccountType.DEPOSIT_VA:
            callback_type = "Deposit"
            if status != "completed":
                return LoggedResponse(
                    status=HTTP_200_OK,
                    data={"message": "%s callback will be ingnored" % status}
                )
            try:
                with transaction.atomic():
                    lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                        .filter(lender_id=lender.id).last()
                    if lender_balance is None:
                        return LoggedResponse(
                            status=HTTP_404_NOT_FOUND,
                            data={"error": 'Lender balance not exist'}
                        )

                    lender_transaction_type = LenderTransactionType.objects \
                        .get_or_none(transaction_type=LenderTransactionTypeConst.DEPOSIT)

                    LenderTransaction.objects.create(
                        lender=lender,
                        lender_balance_current=lender_balance,
                        transaction_type=lender_transaction_type,
                        transaction_amount=amount
                    )

                    calculate_available_balance.delay(
                        lender_balance.id, SnapshotType.TRANSACTION)
            except JuloException as error:
                return self.error_500_response(error, data)

        elif lender_bank_account.bank_account_type == BankAccountType.REPAYMENT_VA:
            callback_type = "Repayment"
            #process splited transfer order one by one
            #one transfer order could have several LenderRepaymentTransaction
            pending_trans = LenderRepaymentTransaction.objects.filter(
                status=LenderRepaymentTransactionStatus.PENDING,
                lender=lender.id,
                amount=amount
            ).first()

            if not pending_trans:
                logger.error({
                    'action_view': 'XfersRdlTopUpView',
                    'data': data,
                    'errors': 'Repayment transaction not found'
                })

                return LoggedResponse(
                    status=HTTP_404_NOT_FOUND,
                    data={"error": 'Transaction not found'}
                )

            if pending_trans.additional_info.get('callback_payload'):
                return LoggedResponse(
                    status=HTTP_400_BAD_REQUEST,
                    data={"error": 'Transaction already processed'}
                )

            pending_trans.additional_info['callback_payload'] = data
            pending_trans.save()

            # in the real situation Xfers will never sent callback with failed status
            # this part only for handle fake callback by agent to make stuck pending into failed
            if status == "failed":
                pending_trans.update_safely(status=LenderRepaymentTransactionStatus.FAILED)
                return LoggedResponse(
                    status=HTTP_200_OK,
                    data={"message": "%s callback processed with failed status" % callback_type}
                )

            if pending_trans.transfer_type == LenderRepaymentTransferType.AUTO \
                    or pending_trans.reference_id:
                pending_trans.update_safely(status=LenderRepaymentTransactionStatus.COMPLETED)

            unprocessed_trans_in_group = LenderRepaymentTransaction.objects.filter(
                lender=lender.id,
                group_id=pending_trans.group_id
            ).exclude(status=LenderRepaymentTransactionStatus.COMPLETED)

            # create lender transaction and linked it relation
            # if only this is the last LenderRepaymentTransaction callback from the group
            if not unprocessed_trans_in_group:
                try:
                    lender_transaction_id = update_successful_repayment(
                        pending_trans.group_id,
                        pending_trans.additional_info['transaction_mapping_ids'],
                        lender.id,
                        pending_trans.additional_info['paid_principal'],
                        pending_trans.additional_info['paid_interest'],
                        pending_trans.additional_info['total_service_fee'],
                        pending_trans.additional_info['original_amount'],
                    )
                except JuloException as error:
                    return self.error_500_response(error, data)
                else:
                    LenderRepaymentTransaction.objects.filter(
                        lender=lender.id,
                        group_id=pending_trans.group_id
                    ).update(
                        lender_transaction_id=lender_transaction_id
                    )
        else:
            return LoggedResponse(
                status=HTTP_400_BAD_REQUEST,
                data={"error": 'virtual account number not registered'}
            )
        return LoggedResponse(
            status=HTTP_200_OK,
            data={"message": "%s callback processed" % callback_type }
        )


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'business_development'])
def lender_investment_upload_view(request):
    """handle get request"""
    template_name = 'object/lender/investment.html'
    logs = ""
    upload_form = None
    ok_couter = 0
    nok_couter = 0

    def _render():
        """lamda func to reduce code"""
        return render(request, template_name, {'form':upload_form,
                                               'logs':logs,
                                               'ok':ok_couter,
                                               'nok':nok_couter})

    if request.method == 'POST':
        upload_form = UploadFileForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            logs = "Invalid form"
            return _render()

        file_ = upload_form.cleaned_data['file_field']
        email_date = upload_form.cleaned_data['email_date']
        extension = file_.name.split('.')[-1]

        if extension not in ['xls', 'xlsx', 'csv']:
            logs = 'Please upload correct file excel'
            return _render()

        try:
            excel_datas = xls_to_dict(file_, ",")
        except Exception as error:
            logs = str(error)
            return _render()

        mintos_report = upsert_mintos_report(file_.name, email_date, excel_datas)
        if mintos_report['exists']:
            logs = 'This file already uploaded'
            return _render()

        for idx_sheet, sheet in enumerate(excel_datas):
            for idx_rpw, row in enumerate(excel_datas[sheet]):
                row = transform_mintos_upload_key(row)
                row['mintos_id'] = row['id']
                serializer = MintosUpdateSerializer(data=row)
                logs += "Sheet: %d   |   Row: %d   |   " % (idx_sheet+1, idx_rpw+2)
                if serializer.is_valid():
                    data = serializer.data
                    # call async func to handle
                    ok_couter += 1
                    update_mintos_loan_from_report.delay(data, mintos_report['id'])
                    logs += "Success in queue.\n"
                else:
                    nok_couter += 1
                    logs += "Error: %s \n" % str(serializer.errors)

                logs += "---"*20 + "\n"

    else:
        upload_form = UploadFileForm()
    return _render()
