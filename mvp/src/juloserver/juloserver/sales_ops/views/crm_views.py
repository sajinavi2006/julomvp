import csv
from datetime import timedelta
import logging

from django.contrib import messages
from django.core.exceptions import ValidationError, FieldError
from django.core.urlresolvers import reverse
from django.db.models import F
from django.forms import model_to_dict
from django.http import (
    HttpResponseNotAllowed,
    JsonResponse,
    HttpResponseRedirect,
    HttpResponseNotFound,
    HttpResponseBadRequest,
)
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.datastructures import MultiValueDictKeyError
from django.views.generic import (
    ListView,
    DetailView,
    CreateView
)

from dashboard.constants import JuloUserRoles
from dashboard.functions import create_or_update_role
from juloserver.account.models import AccountLimitHistory
from juloserver.graduation.models import GraduationCustomerHistory2
from juloserver.julo.constants import UploadAsyncStateType
from juloserver.julo.models import Agent, Application, Skiptrace, UploadAsyncState, SkiptraceResultChoice
from juloserver.julo.services import update_skiptrace_score
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_group,
)
from juloserver.sales_ops import utils
from app_status.models import CannedResponse
from app_status.utils import canned_filter
from juloserver.portal.object.payment_status.forms import SendEmailForm
from juloserver.sales_ops.constants import (
    SalesOpsRoles,
    AutodialerConst,
    PROMOTION_AGENT_OFFER_AVAILABLE_AT_LEAST_DAYS,
    SalesOpsVendorName,
    VendorRPCConst, BucketCode, SEARCH_FILTER_MAPPINGS, EXTRA_FILTER_MAPPINGS
)
from juloserver.sales_ops import exceptions as sale_ops_exc
from juloserver.sales_ops.exceptions import SalesOpsException
from juloserver.sales_ops.forms import (
    SalesOpsCRMLineupListFilterForm,
    SalesOpsCRMLineupDetailForm,
    SalesOpsCRMLineupCallbackHistoryForm,
)
from juloserver.sales_ops.models import SalesOpsLineup, SalesOpsAgentAssignment
from juloserver.sales_ops.serializers import (
    AutodialerSessionRequestSerializer,
    AutodialerActivityHistoryRequestSerializer,
    AutodialerGetApplicationRequestSerializer,
)
from juloserver.sales_ops.services import (
    julo_services,
    sales_ops_services,
    autodialer_services,
)
from juloserver.sales_ops.services.sales_ops_services import (
    create_sales_ops_lineup_callback_history,
    using_sales_ops_bucket_logic, get_bucket_code_map_with_bucket_name,
)
from juloserver.sales_ops.services.vendor_rpc_services import (
    check_vendor_rpc_csv_format,
    save_vendor_rpc_csv,
    check_promo_code_for_sales_ops_pds,
)
from payment_status.serializers import (
    SkiptraceSerializer,
    SkiptraceHistorySerializer
)
from django.db import transaction

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_group(SalesOpsRoles.SALES_OPS)
class SalesOpsBucketList(ListView):
    queryset = SalesOpsLineup.objects.crm_queryset()
    paginate_by = 50
    template_name = 'sales_ops/list.html'

    def get_queryset(self):
        role_name = JuloUserRoles.SALES_OPS
        create_or_update_role(self.request.user, role_name)
        self.ordering = self.request.GET.get('sort_q')
        queryset = super(SalesOpsBucketList, self).get_queryset()
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)

        if using_sales_ops_bucket_logic():
            queryset = queryset.filter(vendor_name=SalesOpsVendorName.IN_HOUSE)

        return queryset

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        bucket_code = self.request.GET.get('bucket_code')
        form = SalesOpsCRMLineupListFilterForm(bucket_code, self.request.GET.copy())
        self.error_message = None
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_condition = form.cleaned_data.get('filter_condition', 'contains')
            filter_field = form.cleaned_data.get('filter_field')
            if filter_keyword:
                filter_args = {
                    '{}__{}'.format(SEARCH_FILTER_MAPPINGS[filter_field], filter_condition): filter_keyword
                }
                extra_filter = EXTRA_FILTER_MAPPINGS.get(filter_field)
                if extra_filter:
                    filter_args.update(extra_filter)
                try:
                    queryset = queryset.filter(**filter_args)
                except (ValidationError, ValueError, FieldError):
                    self.error_message = 'Invalid input, please correct!'
            if bucket_code:
                queryset = queryset.bucket(bucket_code)
            else:
                queryset = queryset.exclude(bucket_code=BucketCode.GRADUATION)

            filter_agent = form.cleaned_data.get('filter_agent')
            if filter_agent:
                queryset = queryset.agent(filter_agent.id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(SalesOpsBucketList, self).get_context_data(**kwargs)
        context['results_per_page'] = self.paginate_by
        get_copy = self.request.GET.copy()
        bucket_code = self.request.GET.get('bucket_code')
        if bucket_code == BucketCode.GRADUATION:
            self.fetch_bucket_code_graduation(context)

        filter_form = SalesOpsCRMLineupListFilterForm(bucket_code, get_copy)
        if self.is_reset_filter():
            filter_form.reset_filter()
        context['filter_form'] = filter_form
        context['activation_call_change_status'] = \
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
        bucket_code_map = get_bucket_code_map_with_bucket_name(
            exclude_buckets=[BucketCode.GRADUATION]
        )
        context['bucket_code_map'] = bucket_code_map
        context['bucket_title'] = sales_ops_services.get_bucket_title(bucket_code, bucket_code_map)
        context['bucket_code'] = bucket_code
        context['parameters'] = get_copy.pop('page', True) and get_copy.urlencode()
        context['error_message'] = self.error_message

        return context

    def fetch_bucket_code_graduation(self, context):
        fetched_data = []
        for obj in context['salesopslineup_list']:
            if obj.bucket_code == BucketCode.GRADUATION:
                graduation_cust_history = GraduationCustomerHistory2.objects.filter(
                    account_id=obj.account_id, latest_flag=True
                ).last()
                if graduation_cust_history:
                    obj.last_graduated_date = graduation_cust_history.cdate
                    set_limit = AccountLimitHistory.objects.filter(
                        id=graduation_cust_history.set_limit_history_id
                    ).last()
                    obj.previous_given_limit = getattr(set_limit, 'value_old', None)
                    fetched_data.append(obj)

        context['salesopslineup_list'] = fetched_data
        context['object_list'] = fetched_data


@julo_login_required
@julo_login_required_group(SalesOpsRoles.SALES_OPS)
class SalesOpsBucketDetail(DetailView):
    queryset = SalesOpsLineup.objects.crm_detail_queryset()
    template_name = 'sales_ops/detail.html'
    form_class = SalesOpsCRMLineupDetailForm
    form_callback = SalesOpsCRMLineupCallbackHistoryForm

    def get_object(self, queryset=None):
        lineup_id = self.kwargs.get(self.pk_url_kwarg)
        sales_ops_services.update_latest_lineup_info(lineup_id)
        return super().get_object(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account_id = self.get_account_id()

        context['form'] = self.form_class()
        context['form'].fill_form(self.object)

        context['form_callback'] = self.form_callback()

        self._update_last_call_context(context)
        context['product_locked_list'] = self.get_product_locked_list()
        context['cfs_j_score'], context['cfs_tier'] = julo_services.get_cfs_tier_info(account_id)
        context['loan_history'] = julo_services.get_loan_history(account_id)
        context['skiptrace_histories'] = julo_services.get_skiptrace_histories(account_id)
        context['callback_histories'] = sales_ops_services.get_callback_histories(self.object.id)
        context['application_id'] = self.object.latest_application_id
        context['skiptrace_list'] = julo_services.get_skiptrace_list(
            self.object.account.customer_id
        )
        context['can_submit_skiptrace_history'] = \
            sales_ops_services.can_submit_lineup_skiptrace_history(self.object)

        context['form_send_email'] = SendEmailForm()
        canned_responses = CannedResponse.objects.all()
        context['canned_responses'] = canned_filter(canned_responses)
        return context

    def _update_last_call_context(self, context):
        account_id = self.get_account_id()

        context['last_call_sales_ops'] = \
            sales_ops_services.get_last_sales_ops_calls(self.object)
        context['last_call_collection_nexmo'] = \
            julo_services.get_last_collection_nexmo_calls(account_id)
        context['last_call_collection_cootek'] = \
            julo_services.get_last_collection_cootek_calls(account_id)
        context['last_call_collection_intelix'] = \
            julo_services.get_last_collection_skiptrace_calls(account_id, True)
        context['last_call_collection_crm'] = \
            julo_services.get_last_collection_skiptrace_calls(account_id, False)

    def get_account_id(self):
        if self.object:
            return self.object.account_id
        return None

    def get_product_locked_list(self):
        account_id = self.get_account_id()
        product_locked_dict = julo_services.get_product_locked_info_dict(account_id)
        offer_choices = julo_services.get_transaction_method_choices()

        product_locked_list = []
        for offer_code, offer_label in offer_choices:
            offer_value = product_locked_dict.get(offer_code, False)
            product_locked_list.append((offer_code, offer_label, offer_value))

        return product_locked_list

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.form_class(request.POST)
        next_url = request.POST.get(
            'next', reverse('sales_ops.crm:detail', kwargs={'pk': self.object.id})
        )

        if form.is_valid():
            form.save(self.object)
            messages.success(request, 'Successfully updated the Sales Ops Lineup.')
        else:
            messages.error(request, 'Invalid form. Please enter valid data.')

        return HttpResponseRedirect(next_url)


def _get_autodialer_agent(request):
    user = request.user
    if user.is_anonymous():
        raise SalesOpsException({'message': 'User is None. No authenticate user?'})
    agent = julo_services.get_agent(user.id)
    if agent is None:
        raise SalesOpsException({'message': 'Agent is None. User is not a staff?', 'user': user})
    return agent


def _parse_agent_assignment_autodialer_data(agent_assignment, subject):
    lineup_id = agent_assignment.lineup_id
    lineup = SalesOpsLineup.objects.get(pk=lineup_id)
    skiptrace_phone_list = julo_services.get_application_skiptrace_phone(lineup.latest_application)
    promotion = julo_services.get_promo_code_agent_offer(agent_assignment)
    today = timezone.localtime(timezone.now())

    if len(skiptrace_phone_list) == 0:
        logger.warning({'message': 'No phone list found', 'lineup': lineup, 'agent_assignment': agent_assignment})

    response_data = {
        'status': 'success',
        'message': 'Success get Sales Ops Lineup',
        'app_id': lineup.latest_application_id,
        'object_id': agent_assignment.lineup_id,
        'object_name': lineup.latest_application.fullname_with_title,
        'object_type': 'sales_ops',
        'email': lineup.latest_application.email,
        'subject': subject,
        'telphone': skiptrace_phone_list,
        'session_delay': 0,
        'account_id': lineup.account_id,
        'promo_code': {}
    }
    if promotion:
        expiry_date = promotion.end_date - today
        total_seconds = expiry_date.total_seconds()
        if total_seconds <= 0:
            return response_data

        is_warning = promotion.end_date < today + timedelta(
            days=PROMOTION_AGENT_OFFER_AVAILABLE_AT_LEAST_DAYS
        )
        if is_warning:
            expiry_time = utils.display_time(total_seconds)
        else:
            expiry_time = promotion.end_date.strftime("%Y-%m-%d %H:%M:%S")
        response_data['promo_code'] = {
            'code': promotion.promo_code.upper(),
            'expiry_time': expiry_time,
            'is_warning': is_warning
        }
    return response_data


def ajax_get_application_autodialer(request):
    """
        Success JSON Format: (200)
            {
                "status": "success",
                "message": "success get Sales Ops Lineup",
                "object_id": '1',
                "object_name": 'Bpk. James Bond',
                "object_type": "sales_ops",
                "email": 'email@email.com',
                "subject": 'SALES OPS',
                "promo_code": {
                    "code": 'JULOCASHBACK',
                    "expiry_time: "1 week, 4 days",
                    "is_warning": True,
                },
                "telphone": [
                    {
                        'skiptrace_id': '2',
                        'contact_name': 'Contact Name',
                        'contact_source': 'mobile_phone_1',
                        'phone_number': '08123456789'
                    }
                ],
                "session_delay": 0,
            }
        Failed JSON Format: (200) Because of backward compatibility with the JS Logic
            {
                "status": "failed",
                "message": "Tidak ada sales ops lineup yang tersedia",
            }
        """

    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    serializer = AutodialerGetApplicationRequestSerializer(data=request.GET)
    if not serializer.is_valid():
        return JsonResponse({
            "status": "failed",
            "message": "Invalid request format",
            "error": serializer.errors
        })

    option_value = serializer.data.get('options')
    bucket_code = autodialer_services.get_sales_ops_autodialer_option(option_value)
    agent = _get_autodialer_agent(request)
    subject = sales_ops_services.get_bucket_name(bucket_code)
    max_retry = 100
    agent_assignment = autodialer_services.get_active_assignment(agent)
    if agent_assignment and autodialer_services.check_autodialer_due_calling_time(
        agent_assignment.lineup_id
    ):
        response_data = _parse_agent_assignment_autodialer_data(agent_assignment, subject)
        return JsonResponse(response_data)

    delay_setting = sales_ops_services.SalesOpsSetting.get_autodialer_delay_setting()
    qs = SalesOpsLineup.objects.autodialer_default_queue_queryset(
        agent.id, bucket_code, **vars(delay_setting), exclude_buckets=[BucketCode.GRADUATION]
    ).all()
    lineups = qs[:max_retry]
    for retry_idx, lineup in enumerate(lineups):
        if autodialer_services.check_autodialer_due_calling_time(lineup):
            agent_assignment = autodialer_services.assign_agent_to_lineup(agent, lineup)
            if agent_assignment:
                response_data = _parse_agent_assignment_autodialer_data(agent_assignment, subject)
                return JsonResponse(response_data)

        logger.info({
            'message': 'Retry agent assignment for SalesOps Lineup',
            'lineup': lineup,
            'agent': agent,
            'current_retry': retry_idx + 1,
            'max_retry': max_retry,
        })

    return JsonResponse({
        'status': 'failed',
        'message': 'Tidak ada Sales Ops Lineup yang tersedia',
    })


def ajax_autodialer_session_status(request):
    """
    - Get the current AgentAssignment.
    - Get SalesOpsAutodialerSession. Create if not exist.
    - Generate the SalesOpsAutodialerActivity for each call_result
    - Execute stop_autodialer_session logic during `session_stop`

    @param request:  post_data:
                        object_id ---> sales_ops_lineup_id
                        session_start ---> 1 for true, and don't sent parameter for False
                        session_stop ---> 1 for true, and don't sent parameter for False
                        is_failed   ---> 1 for True, and don't sent parameter for False
                        hashtag     ---> 1 for True, and don't sent parameter for False
                        call_result ---> SkiptraceResultChoice id
                        phone_number ---> Phone number
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    serializer = AutodialerSessionRequestSerializer(data=request.POST)
    if not serializer.is_valid():
        return JsonResponse({
            "status": "failed",
            "message": "Invalid request format",
            "error": serializer.errors
        })

    post_data = serializer.data
    lineup_id = post_data.get('object_id')
    agent = _get_autodialer_agent(request)
    agent_assignment = autodialer_services.get_agent_assignment(agent, lineup_id)

    if not agent_assignment:
        logger.info({'message': 'Agent don\'t have access to the lineup', 'agent': agent, 'lineup_id': lineup_id})
        return JsonResponse({'status': 'failed', 'message': f'Anda belum di-assign ke Lineup ini. {lineup_id}'})

    autodialer_session = autodialer_services.get_or_create_autodialer_session(lineup_id)

    phone_number = post_data.get('phone_number')
    call_result = post_data.get('call_result')

    skiptrace_result_choice = None
    if call_result:
        skiptrace_result_choice = julo_services.get_skiptrace_result_choice(call_result)
        if not skiptrace_result_choice:
            logger.info({
                'message': 'Invalid call action.',
                'agent_assignment': agent_assignment,
                'autodialer_session': autodialer_session,
                'post_data': post_data,
            })
            return JsonResponse({'status': 'failed', 'message': f'Call action "{call_result}" tidak valid.'})

    if post_data.get('session_stop'):
        action = AutodialerConst.SESSION_STOP
    elif post_data.get('session_start'):
        action = AutodialerConst.SESSION_START
    else:
        action = AutodialerConst.SESSION_ACTION
        if skiptrace_result_choice:
            if skiptrace_result_choice.weight > 0:
                action = AutodialerConst.SESSION_ACTION_SUCCESS
            else:
                action = AutodialerConst.SESSION_ACTION_FAIL

    skiptrace_result_choice_id = getattr(skiptrace_result_choice, "id", None)
    activity = autodialer_services.create_autodialer_activity(
            autodialer_session, agent_assignment, action,
            phone_number=phone_number,
            skiptrace_result_choice_id=skiptrace_result_choice_id
    )

    if action == AutodialerConst.SESSION_STOP:
        autodialer_services.stop_autodialer_session(autodialer_session, agent_assignment)

    return JsonResponse({
        'status': 'success',
        'message': 'Berhasil rekam Sales Ops Autodialer Session',
        'activity': model_to_dict(activity),
    })


def ajax_autodialer_history_record(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    if request.user.is_anonymous():
        return JsonResponse({
            "status": "failed",
            "message": "non authorized user",
        })

    serializer = AutodialerActivityHistoryRequestSerializer(data=request.POST)
    if not serializer.is_valid():
        return JsonResponse({
            "status": "failed",
            "message": "Invalid request format",
            "error": serializer.errors
        })

    post_data = serializer.data
    lineup_id = post_data.get('object_id')
    autodialer_session = autodialer_services.get_autodialer_session(lineup_id)

    if not autodialer_session:
        return JsonResponse({
            "status": "failed",
            "message": f'Sales Ops session is not found for lineup "{lineup_id}"'
        })

    agent = _get_autodialer_agent(request)
    agent_assignment = autodialer_services.get_agent_assignment(agent, lineup_id)
    if not agent_assignment:
        return JsonResponse({'status': 'failed', 'message': f'Anda belum di-assign ke Lineup ini. {lineup_id}'})

    action = post_data.get('action', AutodialerConst.ACTION_UNKNOWN)
    activity = autodialer_services.create_autodialer_activity(autodialer_session, agent_assignment, action)

    return JsonResponse({
        'status': 'success',
        'message': 'Berhasil rekam Sales Ops Autodialer Activity',
        'activity': model_to_dict(activity)
    })


@julo_login_required
@julo_login_required_group(SalesOpsRoles.SALES_OPS)
def create_callback_history(request, *args, **kwargs):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    callback_at = request.POST['callback_at']
    callback_note = request.POST['callback_note']
    lineup_id = request.POST['lineup_id']
    url = "%s?tab=callback" % (
        reverse('sales_ops.crm:detail', kwargs={'pk': lineup_id})
    )
    form = SalesOpsCRMLineupCallbackHistoryForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors)
        return redirect(url)

    create_sales_ops_lineup_callback_history(
        callback_at, callback_note, lineup_id, request.user)
    return redirect(url)


@julo_login_required_group(SalesOpsRoles.SALES_OPS)
def add_skiptrace(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application = Application.objects.get_or_none(pk=data['application'])
    if not application:
        return HttpResponseNotFound("application id %s not found" % data['application'])

    data['customer'] = application.customer.id
    data['phone_number'] = format_e164_indo_phone_number(data['phone_number'])

    skiptrace_serializer = SkiptraceSerializer(data=data)
    if not skiptrace_serializer.is_valid():
        return HttpResponseBadRequest("invalid data!! or phone number already exist!!")

    skiptrace = skiptrace_serializer.save()
    skiptrace_obj = skiptrace_serializer.data
    return JsonResponse({
        "messages": "save success",
        "data": skiptrace_obj
    })


@julo_login_required_group(SalesOpsRoles.SALES_OPS)
def update_skiptrace(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application = Application.objects.get_or_none(pk=int(data['application']))
    if not application:
        return HttpResponseNotFound("application id %s not found" % data['application'])

    new_phone_number = format_e164_indo_phone_number(
        data['phone_number']) if data['phone_number'] else ''
    data['customer'] = application.customer.id
    data['phone_number'] = new_phone_number

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace_id'])
    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace_id'])
    if new_phone_number == '0':
        skiptrace.update_safely(
            phone_number='',
            contact_source=data['contact_source'],
            contact_name=data['contact_name'],
        )
        skiptrace_serializer = SkiptraceSerializer(skiptrace, data=data, partial=True)
        skiptrace_serializer.is_valid()
        skiptrace_obj = skiptrace_serializer.data
    else:
        skiptrace_serializer = SkiptraceSerializer(skiptrace, data=data, partial=True)
        if not skiptrace_serializer.is_valid():
            return HttpResponseBadRequest("invalid data!! or phone number already exist!!")

        skiptrace_obj = skiptrace_serializer.save()
        skiptrace_obj = skiptrace_serializer.data

    return JsonResponse({
        "messages": "save success",
        "data": skiptrace_obj
    })


@julo_login_required_group(SalesOpsRoles.SALES_OPS)
def skiptrace_history(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace_id'])
    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace_id'])

    with transaction.atomic():
        lineup = SalesOpsLineup.objects.select_for_update().get(pk=data['lineup_id'])
        if not lineup:
            return HttpResponseNotFound("lineup %s not found" % data['lineup_id'])

        if not sales_ops_services.can_submit_lineup_skiptrace_history(lineup):
            latest_agent_assignment = SalesOpsAgentAssignment.objects.get(
                pk=lineup.latest_agent_assignment_id
            )
            return HttpResponseBadRequest(
                "Lineup sudah RPC atau sedang di-call [{}]".format(
                    timezone.localtime(latest_agent_assignment.udate)
                )
            )

        now = timezone.localtime(timezone.now())
        agent = request.user.agent
        data = {
            **data,
            'skiptrace': data['skiptrace_id'],
            'call_result': data['skiptrace_result_id'],
            'agent': agent.id,
            'agent_name': request.user.username,
            'application': lineup.latest_application_id,
            'account': lineup.account_id,
            'start_ts': now,
            'end_ts': now,
            'source': 'Sales Ops - CRM',
        }

        skiptrace_history_serializer = SkiptraceHistorySerializer(data=data)
        if not skiptrace_history_serializer.is_valid():
            logger.warning({
                'skiptrace_id': data['skiptrace_id'],
                'agent_name': data['agent_name'],
                'error_msg': skiptrace_history_serializer.errors
            })
            return HttpResponseBadRequest("data invalid")

        skiptrace_history_serializer.save()
        skiptrace = update_skiptrace_score(skiptrace, data['start_ts'])

        skiptrace_result_id = data['skiptrace_result_id']
        skiptrace_choice = SkiptraceResultChoice.objects.get(id=skiptrace_result_id)
        is_rpc = skiptrace_choice.weight > 0
        autodialer_services.create_agent_assignment_by_skiptrace_result(
            lineup, agent, is_rpc
        )
        if is_rpc:
            lineup.update_safely(
                rpc_count=lineup.rpc_count+1,
            )

    return JsonResponse({
        "messages": "save success",
        "data": SkiptraceSerializer(skiptrace).data
    })


@julo_login_required_group(SalesOpsRoles.SALES_OPS)
def ajax_block(request, lineup_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    try:
        days = data.get('days', None)
        if not days:
            raise SalesOpsException('No param "days"')
        days = int(days)
        if days < 1:
            raise SalesOpsException('Days cant be less than 1')
    except SalesOpsException as e:
        return JsonResponse(
            status=400,
            data={
                'error': str(e),
            },
        )

    now = timezone.localtime(timezone.now())
    expiration_time = now + timedelta(days=days)

    lineup = SalesOpsLineup.objects.get(pk=lineup_id)
    lineup.is_active = False
    lineup.inactive_until = expiration_time
    lineup.save()

    return JsonResponse({
        'status': 'success',
    })


@julo_login_required
@julo_login_required_group(SalesOpsRoles.SALES_OPS)
class VendorRPCCreateView(CreateView):
    template_name = 'sales_ops/vendor_rpc_upload.html'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name)

    def post(self, request, *args, **kwargs):
        url = reverse('sales_ops.crm:vendor_rpc')
        if not request.FILES.get('csv_file'):
            messages.error(request, 'No CSV file found')
            return HttpResponseRedirect(url)

        csv_file = request.FILES['csv_file']
        if csv_file.content_type not in VendorRPCConst.VALID_CONTENT_TYPES_UPLOAD:
            messages.error(request, 'Invalid file upload')
            return HttpResponseRedirect(url)

        try:
            csv_dict_reader = csv.DictReader(csv_file.read().decode('utf-8').splitlines())
        except (UnicodeDecodeError, TypeError):
            messages.error(request, 'Can not read csv file')
            return HttpResponseRedirect(url)

        csv_list = [dict(line) for line in csv_dict_reader]
        if not len(csv_list):
            messages.error(request, 'CSV file is empty')
            return HttpResponseRedirect(url)

        err_msg = True
        try:
            check_vendor_rpc_csv_format(csv_list)
            check_promo_code_for_sales_ops_pds()
            err_msg = False
        except sale_ops_exc.MissingFeatureSettingVendorRPCException:
            messages.error(request, 'Missing setting vendor RPC')
        except sale_ops_exc.MissingCSVHeaderException:
            messages.error(request, 'Headers in file does not match with setting')
        except sale_ops_exc.InvalidBooleanValueException:
            messages.error(request, 'Invalid boolean values')
        except sale_ops_exc.InvalidDatetimeValueException:
            messages.error(request, 'Invalid date time values')
        except sale_ops_exc.InvalidDigitValueException:
            messages.error(request, 'Invalid digit values')
        except sale_ops_exc.InvalidSalesOpsPDSPromoCode:
            messages.error(request, 'Invalid promo code for Sales Ops PDS')

        if not err_msg:
            agent = Agent.objects.filter(user=request.user).last()
            if agent:
                save_vendor_rpc_csv(csv_file, agent)
                messages.success(request, 'Upload csv successfully')
            else:
                messages.error(request, 'Agent not found')

        return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_group(SalesOpsRoles.SALES_OPS)
class VendorRPCListView(ListView):
    model = UploadAsyncState
    paginate_by = 10
    template_name = 'sales_ops/upload_history.html'

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return UploadAsyncState.objects.filter(
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        ).order_by('-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        return context
