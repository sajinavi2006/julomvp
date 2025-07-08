import json
from django.shortcuts import get_object_or_404
from django.views.generic import ListView, DetailView
from django.db.models import Count
from django.http import JsonResponse, HttpResponse
from juloserver.balance_consolidation.constants import HTTPMethod
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from django.views.decorators.http import require_http_methods
from juloserver.julo_financing.forms import (
    JFinancingVerificationFilterForm,
    JFinancingVerificationForm,
)
from juloserver.julo_financing.constants import (
    REQUIRED_GROUPS,
    JFinancingResponseMessage,
    JFinancingStatus,
)
from juloserver.julo_financing.models import (
    JFinancingVerification,
)
from juloserver.julo_financing.services.verification_related import (
    lock_j_financing_verification,
    unlock_j_financing_verification,
)
from juloserver.julo_financing.services.crm_services import (
    update_julo_financing_verification_status,
    update_verification_note,
    update_courier_info_for_checkout,
    get_couriers,
    is_invalid_validation_status_change,
)


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
class JFinancingVerificationListView(ListView):
    queryset = JFinancingVerification
    template_name = 'verification_list.html'

    def get_queryset(self):
        return (
            JFinancingVerification.objects.exclude(
                validation_status=JFinancingStatus.INITIAL,
            )
            .values('validation_status')
            .annotate(status_count=Count('validation_status'))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_display'] = dict(JFinancingVerification.VALIDATION_STATUS_CHOICES)
        return context


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
class JFinancingVerificationStatusListView(ListView):
    queryset = JFinancingVerification.objects.select_related(
        'j_financing_checkout', 'j_financing_checkout__customer', 'loan'
    ).order_by('-id')
    paginate_by = 50
    template_name = 'verification_status_list.html'

    def get_queryset(self):
        verification_status = self.kwargs['verification_status']
        queryset = (
            super(JFinancingVerificationStatusListView, self)
            .get_queryset()
            .filter(validation_status=verification_status)
        )
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)
        return queryset

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        form = JFinancingVerificationFilterForm(self.request.GET.copy())
        self.error_message = None
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_field = form.cleaned_data.get('filter_field')
            filter_args = {}

            if filter_keyword:
                filter_args['{}'.format(filter_field)] = filter_keyword
            try:
                queryset = queryset.filter(**filter_args)
            except (ValidationError, ValueError):
                self.error_message = JFinancingResponseMessage.INVALID_INPUT
                queryset = list()
        return queryset

    def get_context_data(self, **kwargs):
        context = super(JFinancingVerificationStatusListView, self).get_context_data(**kwargs)

        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        filter_form = JFinancingVerificationFilterForm(get_copy)
        context['results_per_page'] = self.paginate_by
        context['filter_form'] = filter_form
        context['parameters'] = parameters
        context['current_status'] = self.kwargs['verification_status']
        return context


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.GET])
def check_locking_j_financing_verification_status(request: dict, verification_id: int):
    verification = JFinancingVerification.objects.get_or_none(id=verification_id)
    if not verification:
        return JsonResponse(
            status=404,
            data={
                'success': False,
                'data': None,
                'error': JFinancingResponseMessage.VERIFICATION_NOT_FOUND,
            },
        )

    agent = request.user.agent
    data = {
        'is_locked': verification.is_locked,
        'is_locked_by_me': verification.locked_by_id == agent.id,
        'locked_by_info': verification.locked_by_info,
    }

    return JsonResponse(
        data={
            'success': True,
            'data': data,
        }
    )


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.POST])
def lock_j_financing_verification_status(request, verification_id):
    agent = request.user.agent

    try:
        is_success = lock_j_financing_verification(verification_id, agent.id)
        if not is_success:
            return JsonResponse(
                status=423,
                data={
                    'success': False,
                    'data': None,
                    'error': JFinancingResponseMessage.VERIFICATION_LOCKED,
                },
            )
        return HttpResponse(status=201)

    except ObjectDoesNotExist:
        return JsonResponse(
            status=404,
            data={
                'success': False,
                'data': None,
                'error': JFinancingResponseMessage.VERIFICATION_NOT_FOUND,
            },
        )


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.POST])
def unlock_j_financing_verification_status(request, verification_id):
    unlock_j_financing_verification(verification_id, request.user.agent.id)
    return JsonResponse(
        data={
            'success': True,
            'data': True,
        }
    )


class JFinancingVerificationStatusDetailView(DetailView):
    model = JFinancingVerification
    template_name = '../templates/verification_details.html'
    form_class = JFinancingVerificationForm

    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        queryset = self.get_queryset().select_related(
            'loan',
            'j_financing_checkout',
            'j_financing_checkout__customer',
            'j_financing_checkout__j_financing_product',
        )
        return get_object_or_404(queryset, pk=pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.form_class(self.object)
        context['first_due_date'] = (
            self.object.loan.payment_set.all().order_by('payment_number').first().due_date
        )
        is_locked_by_me = self.object.locked_by_id == self.request.user.agent.id
        context['is_locked_by_me'] = is_locked_by_me
        context['lock_status'] = False
        if not is_locked_by_me:
            context['lock_status'] = bool(self.object.locked_by_id)
        context['courier_choices'] = get_couriers()
        return context


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.PUT])
def ajax_update_julo_financing_verification(request, verification_id):
    agent = request.user.agent
    verification = JFinancingVerification.objects.filter(
        pk=verification_id, locked_by_id=agent.pk
    ).first()
    if not verification:
        return JsonResponse(status=404, data={'success': False, 'error': "Verification not found"})

    req_data = json.loads(request.body)
    courier_info = req_data.get('courier_info')
    status_to = req_data.get('status')
    note = req_data.get('note')
    http_status = 200
    success = True
    error = None

    if courier_info:
        update_courier_info_for_checkout(verification, courier_info)

    if note:
        if isinstance(note, str):
            update_verification_note(verification, note)
        else:
            http_status = 400
            error = "Invalid note."

    if status_to:
        if is_invalid_validation_status_change(status_to, verification.validation_status):
            http_status = 400
            error = "Invalid status transition."

        is_success, reason = update_julo_financing_verification_status(
            status_to, verification, request.user.pk
        )
        if not is_success:
            http_status = 400
            error = reason

    return JsonResponse(status=http_status, data={'success': success, 'error': error})
