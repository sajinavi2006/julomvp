from __future__ import print_function
import json
import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.models import User
from django.http import (
    HttpResponse,
    Http404,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.utils import timezone

from juloserver.apiv2.models import EtlJob
from juloserver.cfs.constants import VerifyAction, CfsActionId
from juloserver.cfs.crm_forms import CFSSearchForm
from django.views.generic import ListView, DetailView
from future import standard_library

from juloserver.cfs.services.core_services import (
    lock_assignment_verification,
    unlock_assignment_verification,
)
from juloserver.cfs.services.crm_services import (
    change_pending_state_assignment,
    update_agent_verification,
    update_after_upload_payslip_bank_statement_verified,
    record_monthly_income_value_change,
)
from juloserver.julo.models import (
    Application, Agent, Image
)
from juloserver.cfs.models import (
    CfsAssignmentVerification, CfsActionAssignment
)
from juloserver.cfs.constants import (
    CfsProgressStatus,
    AssignmentVerificationDataListViewConstants,
)
from juloserver.cfs.serializers import CfsChangePendingStatus
from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.sales_ops.services.julo_services import get_cfs_tier_info
from juloserver.utilities.paginator import TimeLimitedPaginator
from object import julo_login_required
from juloserver.moengage.services.use_cases import \
    send_user_attributes_to_moengage_for_cfs_mission_change

standard_library.install_aliases()

logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')
logger = logging.getLogger(__name__)


@julo_login_required
class AssignmentVerificationDataListView(ListView):
    queryset = CfsAssignmentVerification.objects.crm_queryset()
    model = CfsAssignmentVerification
    paginate_by = 50
    paginator_class = TimeLimitedPaginator
    template_name = '../templates/cfs/list.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_paginator(self, queryset, per_page, orphans=0,
                      allow_empty_first_page=True, **kwargs):
        """
        Override to add extra 'timeout' parameter
        """
        kwargs['timeout'] = AssignmentVerificationDataListViewConstants.TIMEOUT
        return self.paginator_class(
            queryset, per_page, orphans=orphans,
            allow_empty_first_page=allow_empty_first_page, **kwargs
        )

    def get_queryset(self):
        queryset = super(AssignmentVerificationDataListView, self).get_queryset()
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)
        # Filter the missions have application eligible_for_cfs property
        queryset = queryset.filter(
            Q(
                account__application__application_status_id__in=ApplicationStatusCodes.active_account()
            )
            & (
                Q(account__application__product_line__product_line_code=ProductLineCodes.J1)
                | Q(account__application__workflow__name=WorkflowConst.JULO_STARTER)
            )
        )
        return queryset

    def get_ordering(self):
        ordering = self.request.GET.get('sort_q')
        if ordering:
            self.request.session['sort_q'] = ordering

        return self.request.session.get('sort_q', 'cdate')

    def get_request_data(self):
        request_data = self.request.GET.copy()
        request_data['sort_q'] = self.get_ordering()
        return request_data

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        form = CFSSearchForm(self.get_request_data())
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_condition = form.cleaned_data.get('filter_condition', 'contains')
            filter_field = form.cleaned_data.get('filter_field')

            if filter_keyword:
                filter_args = {
                    '{}__{}'.format(filter_field, filter_condition): filter_keyword
                }
                queryset = queryset.filter(**filter_args)
            filter_action = form.cleaned_data.get('filter_action')
            if filter_action:
                queryset = queryset.action(filter_action)
        return queryset

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(AssignmentVerificationDataListView, self).get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        filter_form = CFSSearchForm(self.get_request_data())
        if self.is_reset_filter():
            filter_form.reset_filter()
        context['filter_form'] = filter_form
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context


@julo_login_required
def change_pending_state(request):
    data = request.POST.dict()
    serializer = CfsChangePendingStatus(data=data)
    if not serializer.is_valid():
        return HttpResponse(
            json.dumps({
                'result': "failed",
                'reason': 'Monthly income must be integer.',
            }),
            content_type="application/json"
        )
    if not data.get('monthly_income'):
        return HttpResponse(
            json.dumps({
                'result': "failed",
                'reason': 'Missing monthly income input',
            }),
            content_type="application/json"
        )
    agent = Agent.objects.filter(user=request.user).last()
    assignment_verification = get_object_or_404(
        CfsAssignmentVerification, id=data['verification_id']
    )
    cfs_action_assignment = get_object_or_404(
        CfsActionAssignment, id=assignment_verification.cfs_action_assignment.id
    )

    if assignment_verification.locked_by_id != agent.id:
        return HttpResponse(
            json.dumps({
                'result': "failed",
                'reason': 'Assignment tidak di-lock oleh Anda.',
            }),
            content_type="application/json"
        )
    verification_id = assignment_verification.id
    application = cfs_action_assignment.customer.account.get_active_application()
    if not application:
        raise Http404("Application not found customer_id=%s", cfs_action_assignment.customer.id)

    verify_action = data['verify_action']
    agent_note = data['agent_note']
    if not agent_note and not assignment_verification.message:
        return HttpResponse(
            json.dumps({
                'result': "failed",
                'reason': 'Error! Missing agent note!'
            }),
            content_type="application/json"
        )
    now = timezone.localtime(timezone.now())
    logger.info({
        'cfs_verification_id': assignment_verification.id,
        'action': verify_action,
        'now': now,
    })
    old_monthly_income = application.monthly_income
    if verify_action in (VerifyAction.APPROVE, VerifyAction.REFUSE):
        status = CfsProgressStatus.START
        if verify_action == VerifyAction.APPROVE:
            status = CfsProgressStatus.UNCLAIMED
        with transaction.atomic():
            change_pending_state_assignment(
                application, cfs_action_assignment, assignment_verification,
                status, verify_action, agent
            )
            update_agent_verification(verification_id, agent, agent_note=agent_note)
            unlock_assignment_verification(verification_id)
            execute_after_transaction_safely(
                lambda: send_user_attributes_to_moengage_for_cfs_mission_change.delay(
                    cfs_action_assignment.customer_id, verification_id)
            )
            monthly_income = int(data['monthly_income'])
            if verify_action == VerifyAction.APPROVE and cfs_action_assignment.action.id in [
                CfsActionId.UPLOAD_SALARY_SLIP,
                CfsActionId.UPLOAD_BANK_STATEMENT,
            ]:
                update_after_upload_payslip_bank_statement_verified(
                    application, agent.user, monthly_income
                )
            record_monthly_income_value_change(
                assignment_verification, old_monthly_income, monthly_income
            )

        return HttpResponse(
            json.dumps({
                'result': "success"
            }),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                'result': "failed",
                'reason': 'Action not support',
            }),
            content_type="application/json"
        )


@julo_login_required
def update_verification_check(request, pk):
    template_name = '../templates/cfs/verification_check.html'
    assignment_verification = CfsAssignmentVerification.objects.filter(id=pk).first()

    current_agent = request.user.agent
    auth_user = None
    if assignment_verification.agent:
        auth_user = User.objects.filter(id=assignment_verification.agent.user.id).first()

    bank_report_url = ''
    bank_report_name = ''
    sd_data = None
    if assignment_verification.cfs_action_assignment.action.id == CfsActionId.CONNECT_BANK:
        application = Application.objects.filter(account=assignment_verification.account).last()
        sd_data = application.device_scraped_data.last()
        if sd_data and not sd_data.reports_xls_s3_url:
            sd_data = None

        etl_job = EtlJob.objects.filter(
            application_id=application.id, status='load_success',
            data_type__in=['bca', 'mandiri', 'bni', 'bri']
        ).order_by('-cdate').first()

        if etl_job:
            bank_report_url = etl_job.get_bank_report_url()
            bank_report_name = bank_report_url.split('.xlsx')[0] if bank_report_url else ''

    cfs_action_id_has_image = [
        CfsActionId.UPLOAD_SALARY_SLIP,
        CfsActionId.UPLOAD_BANK_STATEMENT,
        CfsActionId.UPLOAD_UTILITIES_BILL,
        CfsActionId.UPLOAD_CREDIT_CARD,
    ]
    images = None
    if assignment_verification.cfs_action_assignment.action_id in cfs_action_id_has_image:
        if "image_id" in assignment_verification.extra_data:
            images = Image.objects.filter(id=assignment_verification.extra_data["image_id"])
        else:
            images = Image.objects.filter(id__in=assignment_verification.extra_data["image_ids"])

    agent_note = assignment_verification.message
    return render(
        request,
        template_name,
        {
            'is_locked_by_me': assignment_verification.locked_by_id == current_agent.id,
            'agent_note': agent_note,
            'assignment_verification': assignment_verification,
            'auth_user': auth_user,
            'sd_data': sd_data,
            'bank_report_url': bank_report_url,
            'bank_report_name': bank_report_name,
            'images': images
        }
    )


@julo_login_required
def ajax_app_status_tab(request, application_pk):
    if request.method != 'GET':
        return HttpResponseNotAllowed([request.method])

    application = Application.objects.get(pk=application_pk)
    template_name = 'cfs/app_status_tab.html'
    jscore, cfs_tier = get_cfs_tier_info(application.account_id)

    data = {
        'is_eligible_for_cfs': application.eligible_for_cfs,
        'jscore': jscore,
        'cfs_tier': cfs_tier,
    }
    return render(request, template_name, data)


@julo_login_required
def assignment_verification_check_lock_status(request, assignment_verification_id):
    if request.method != 'GET':
        return HttpResponseNotAllowed([request.method])

    assignment_verification = CfsAssignmentVerification.objects.get_or_none(
        id=assignment_verification_id
    )
    if assignment_verification is None:
        return JsonResponse(status=404, data={
            'success': False,
            'data': None,
            'error': 'CFS Assignment verification not found.',
        })

    agent = request.user.agent

    return JsonResponse(data={
        'success': True,
        'data': {
            'is_locked': assignment_verification.is_locked,
            'is_locked_by_me': assignment_verification.locked_by_id == agent.id,
            'locked_by_info': assignment_verification.locked_by_info,
        },
    })


@julo_login_required
def assignment_verification_lock(request, assignment_verification_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed([request.method])

    agent = request.user.agent
    try:
        is_success = lock_assignment_verification(assignment_verification_id, agent.id)
        if not is_success:
            return JsonResponse(status=423, data={
                'success': False,
                'data': None,
                'error': 'CFS Assignment verification is locked.',
            })

        return HttpResponse(status=201)
    except ObjectDoesNotExist:
        return JsonResponse(status=404, data={
            'success': False,
            'data': None,
            'error': 'CFS Assignment verification not found.',
        })


@julo_login_required
def assignment_verification_unlock(request, assignment_verification_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed([request.method])

    unlock_assignment_verification(assignment_verification_id)
    return JsonResponse(data={
        'success': True,
        'data': True,
    })


@julo_login_required
class ImageDetailView(DetailView):
    model = Image
    template_name = '../templates/cfs/image_editor.html'
