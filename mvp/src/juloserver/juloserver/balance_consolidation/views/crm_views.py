import logging
import json

from django.db import transaction, DatabaseError
from django.http import (
    HttpResponseNotAllowed,
    JsonResponse,
    HttpResponse,
)
from django.shortcuts import render
from django.http import Http404
from rest_framework.reverse import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.views.generic import UpdateView, ListView
from django.views.decorators.http import require_http_methods
from rest_framework import status as status_code

from juloserver.balance_consolidation.crm_forms import (
    BalanceConsolidationForm,
    BalanceConsolidationVerificationForm
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.julo.serializers import ApplicationSimpleSerializer
from juloserver.julo.models import Application
from juloserver.balance_consolidation.models import (
    BalanceConsolidationVerification,
    BalanceConsolidationVerificationHistory,
    BalanceConsolidation,
)
from juloserver.balance_consolidation.exceptions import (
    BalConVerificationLimitIncentiveException
)
from juloserver.balance_consolidation.forms import (
    BalanceConsolidationVerificationCRMConditionFilterForm,
)
from juloserver.balance_consolidation.constants import (
    BalanceConsolidationStatus,
    HTTPMethod,
    StatusResponse,
    MessageBankNameValidation,
    REQUIRED_GROUPS,
    UploadPDFFileMessage,
    BalanceConsolidationMessageException,
)
from juloserver.balance_consolidation.serializers import (
    BankNameValidationSerializer,
    BankNameValidationDetailSerializer,
)
from juloserver.balance_consolidation.services import (
    populate_info_for_name_bank,
    prepare_data_to_validate,
    validate_name_bank_validation,
    ConsolidationVerificationStatusService,
    populate_fdc_data,
    lock_consolidation_verification,
    unlock_consolidation_verification,
    process_approve_balance_consolidation,
    upload_loan_agreement_document, get_lock_status, get_status_map_change_reason,
    update_balance_consolidation_data,
    get_status_note_histories, get_balance_consolidation_detail_list_history,
    get_lock_edit
)
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)

logger = logging.getLogger(__name__)


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
class BalanceConsolidationVerificationDetailFormView(UpdateView):
    model = BalanceConsolidationVerification
    form_class = BalanceConsolidationVerificationForm
    template_name = '../templates/details.html'
    default_order = '-id_penyelenggara'

    def get_ordering(self):
        return self.request.GET.get('sort_q', self.default_order)

    def get_request_data(self):
        request_data = self.request.GET.copy()
        request_data['sort_q'] = self.get_ordering()
        return request_data

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        get_params = self.request.GET.copy()
        filter_form = BalanceConsolidationVerificationCRMConditionFilterForm(get_params)
        obj = context['object']
        balance_consolidation = obj.balance_consolidation
        application = Application.objects.filter(customer=balance_consolidation.customer).last()

        if application:
            context['app_info'] = ApplicationSimpleSerializer(application).data
            context['user'] = self.request.user

        context['form'] = self.form_class(self.object)
        context['balance_cons_form'] = BalanceConsolidationForm(instance=balance_consolidation)

        # limit incentive info
        context['limit_incentive'] = {}
        if obj.validation_status == BalanceConsolidationStatus.ON_REVIEW:
            account = obj.balance_consolidation.customer.account
            consolidation_service = ConsolidationVerificationStatusService(
                consolidation_verification=obj, account=account
            )
            eligible, limit_incentive_info_dict = consolidation_service.evaluate_increase_limit_incentive_amount()
            context['limit_incentive']['eligible'] = eligible
            increase_limit = limit_incentive_info_dict.get('increase_amount', 0)
            if eligible and increase_limit > 0:
                context['limit_incentive'].update({
                    'increase_limit': increase_limit,
                    'bonus_limit': consolidation_service.limit_incentive_config.get('bonus_incentive')
                })
        elif obj.validation_status == BalanceConsolidationStatus.APPROVED:
            amount_changed = 0
            if obj.account_limit_histories.get('upgrade'):
                amount_changed = obj.account_limit_histories['upgrade'].get('amount_changed', 0)

            context['limit_incentive'].update({
                'increase_limit': amount_changed,
                'bonus_limit': 0
            })

        is_lock_by_me = obj.locked_by_id == context['user'].agent.id
        context['is_locked_by_me'] = is_lock_by_me
        context['lock_status'] = get_lock_status(obj, is_lock_by_me)
        context['lock_edit'] = get_lock_edit(obj)
        context['status_map_change_reason'] = get_status_map_change_reason()
        context['history_note_list'] = get_status_note_histories(obj)
        context[
            'balance_consolidation_detail_history_list'
        ] = get_balance_consolidation_detail_list_history(balance_consolidation)
        context['filter_form'] = filter_form
        populate_info_for_name_bank(context, balance_consolidation)
        populate_fdc_data(application, context)

        return context


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.GET, HTTPMethod.POST])
def ajax_bank_validation_consolidation(request):
    if request.method == HTTPMethod.GET:
        consolidation_verification_id = int(request.GET.get('consolidation_verification_id', 0))
        consolidation_verification = BalanceConsolidationVerification.objects.get_or_none(
            pk=consolidation_verification_id
        )
        status = StatusResponse.SUCCESS
        message = MessageBankNameValidation.REFRESH_SUCCESS

        if not consolidation_verification:
            status = StatusResponse.FAILED
            message = MessageBankNameValidation.BALANCE_CONSOLIDATION_NOT_FOUND
            return JsonResponse(
                {"status": status, "messages": message}, status=status_code.HTTP_404_NOT_FOUND
            )
        if not consolidation_verification.name_bank_validation:
            status = StatusResponse.FAILED
            message = MessageBankNameValidation.Name_BANK_NOT_FOUND_AND_VERIFY_FIRST
            return JsonResponse(
                {"status": status, "messages": message}, status=status_code.HTTP_404_NOT_FOUND
            )

        name_bank = consolidation_verification.name_bank_validation
        data = BankNameValidationDetailSerializer(instance=name_bank).data
        return JsonResponse({"status": status, "messages": message, "data": data})

    else:
        data = request.POST.dict()
        serializer = BankNameValidationSerializer(data=data)
        if not serializer.is_valid():
            return JsonResponse(
                {"status": StatusResponse.FAILED, "messages": serializer.errors},
                status=status_code.HTTP_400_BAD_REQUEST,
            )

        agent = request.user.agent
        data_to_validate = serializer.validated_data

        prepare_data_to_validate(data_to_validate)

        status = StatusResponse.SUCCESS
        message = MessageBankNameValidation.SUBMIT_SUCCESS
        try:
            name_bank_validation = validate_name_bank_validation(data_to_validate, agent)
            data = BankNameValidationDetailSerializer(instance=name_bank_validation).data
        except Exception as e:
            status = StatusResponse.FAILED
            message = str(e)
            logger.error({'action': 'get_and_update_name_bank_validation', 'error': message})

        return JsonResponse({"status": status, "messages": message, "data": data})


@julo_login_required_multigroup(REQUIRED_GROUPS)
class BalanceConsolidationVerificationListView(ListView):
    queryset = BalanceConsolidationVerification.objects.all()
    paginate_by = 50
    template_name = 'balance_consolidation_verification_list.html'
    default_order = 'balance_consolidation__due_date'

    def get_queryset(self):
        queryset = super(BalanceConsolidationVerificationListView, self).get_queryset()
        if not self.is_reset_filter():
            queryset = self.filter_queryset(queryset)
        return queryset

    def get_ordering(self):
        return self.request.GET.get('sort_q', self.default_order)

    def get_request_data(self):
        request_data = self.request.GET.copy()
        request_data['sort_q'] = self.get_ordering()
        return request_data

    def is_reset_filter(self):
        return 'reset' in self.request.GET

    def filter_queryset(self, queryset):
        form = BalanceConsolidationVerificationCRMConditionFilterForm(self.get_request_data())
        self.error_message = None
        if form.is_valid():
            filter_keyword = form.cleaned_data.get('filter_keyword')
            filter_condition = form.cleaned_data.get('filter_condition', 'contains')
            filter_field = form.cleaned_data.get('filter_field')
            filter_args = {}

            if filter_keyword:
                filter_args['{}'.format(filter_field)] = filter_keyword

            if filter_condition != 'all':
                filter_args[
                    'validation_status'
                ] = filter_condition
            try:
                queryset = queryset.filter(**filter_args)
            except (ValidationError, ValueError):
                self.error_message = 'Invalid input, please correct!'
        return queryset

    def get_context_data(self, **kwargs):
        context = super(BalanceConsolidationVerificationListView, self).get_context_data(**kwargs)

        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        filter_form = BalanceConsolidationVerificationCRMConditionFilterForm(get_copy)
        context['results_per_page'] = self.paginate_by
        context['filter_form'] = filter_form
        context['parameters'] = parameters
        context['error_message'] = self.error_message
        return context


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
def consolidation_verification_check_lock_status(request, consolidation_verification_id):
    if request.method != 'GET':
        return HttpResponseNotAllowed([request.method])

    consolidation_verification = BalanceConsolidationVerification.objects.get_or_none(
        id=consolidation_verification_id
    )
    if consolidation_verification is None:
        return JsonResponse(status=404, data={
            'success': False,
            'data': None,
            'error': 'Balance consolidation verification not found.',
        })

    agent = request.user.agent

    return JsonResponse(data={
        'success': True,
        'data': {
            'is_locked': consolidation_verification.is_locked,
            'is_locked_by_me': consolidation_verification.locked_by_id == agent.id,
            'locked_by_info': consolidation_verification.locked_by_info,
        },
    })


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
def consolidation_verification_lock(request, consolidation_verification_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed([request.method])

    agent = request.user.agent
    try:
        is_success = lock_consolidation_verification(consolidation_verification_id, agent.id)
        if not is_success:
            return JsonResponse(status=423, data={
                'success': False,
                'data': None,
                'error': 'Balance consolidation verification is locked.',
            })

        return HttpResponse(status=201)
    except ObjectDoesNotExist:
        return JsonResponse(status=404, data={
            'success': False,
            'data': None,
            'error': 'Balance consolidation verification not found.',
        })


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
def consolidation_verification_unlock(request, consolidation_verification_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed([request.method])

    unlock_consolidation_verification(consolidation_verification_id)
    return JsonResponse(data={
        'success': True,
        'data': True,
    })


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
def update_balance_consolidation_verification(request, verification_id):
    if request.method != 'PUT':
        return HttpResponseNotAllowed([request.method])

    req_data = json.loads(request.body)
    status = req_data.get('status')
    note = req_data.get('note')
    change_reason = req_data.get('change_reason')
    is_update_note_only = req_data.get('is_update_note_only')
    try:
        verification = BalanceConsolidationVerification.objects.select_related(
            'balance_consolidation__customer'
        ).get(pk=verification_id)
    except ObjectDoesNotExist:
        return JsonResponse(
            status=404,
            data={
                'success': False,
                'data': None,
                'error': 'Balance consolidation verification not found.',
            },
        )
    if verification.locked_by_id and request.user.agent.id != verification.locked_by_id:
        return JsonResponse(
            status=401,
            data={
                'success': False,
                'data': None,
                'error': 'Balance consolidation verification cannot update, '
                'because it is locked by another agent.',
            },
        )

    agent = verification.locked_by if verification.locked_by else request.user.agent
    old_note = verification.note
    if bool(is_update_note_only):
        if isinstance(note, str) and note.strip() != verification.note:
            with transaction.atomic():
                verification.update_safely(note=note)
                BalanceConsolidationVerificationHistory.objects.create(
                    balance_consolidation_verification=verification,
                    agent=agent,
                    field_name='note',
                    value_old=old_note,
                    value_new=note,
                )
            return JsonResponse(
                status=200,
                data={
                    'success': True,
                    'data': None,
                },
            )
        else:
            return JsonResponse(
                status=400,
                data={
                    'success': False,
                    'error': 'Note not changes',
                },
            )

    # case update ubah status
    if status not in BalanceConsolidationStatus.get_available_update_statuses():
        return JsonResponse(
            status=400,
            data={
                'success': False,
                'error': 'Status does not exist',
            },
        )

    if status and status == BalanceConsolidationStatus.APPROVED:
        if not verification.name_bank_validation:
            return JsonResponse(
                status=400,
                data={
                    'success': False,
                    'error': 'Name bank validation is not verified',
                },
            )

        if verification.name_bank_validation.validation_status != NameBankValidationStatus.SUCCESS:
            return JsonResponse(
                status=400,
                data={
                    'success': False,
                    'error': 'Name bank verification is not success',
                },
            )

    if not ConsolidationVerificationStatusService.can_status_update(
        old_validation_status=verification.validation_status,
        new_validation_status=status
    ):
        return JsonResponse(
            status=400,
            data={
                'success': False,
                'error': 'Can not update status.',
            },
        )

    # update status need to check status can update next
    old_validation_status = verification.validation_status
    histories = []

    if status and status != verification.validation_status:
        verification.validation_status = status
        histories.append(
            BalanceConsolidationVerificationHistory(
                balance_consolidation_verification=verification,
                agent=agent,
                field_name='validation_status',
                value_old=old_validation_status,
                value_new=status,
                change_reason=change_reason,
            )
        )

    if isinstance(note, str) and note.strip() != verification.note:
        verification.note = note.strip()
        histories.append(
            BalanceConsolidationVerificationHistory(
                balance_consolidation_verification=verification,
                agent=agent,
                field_name='note',
                value_old=old_note,
                value_new=note,
            )
        )

    if not len(histories):
        return JsonResponse(
            status=200,
            data={
                'success': False,
                'msg': 'No update',
            },
        )
    account = verification.balance_consolidation.customer.account
    consolidation_service = ConsolidationVerificationStatusService(
        consolidation_verification=verification, account=account
    )
    try:
        with transaction.atomic():
            # Lock balance consolidation verification when updating status
            verification = BalanceConsolidationVerification.objects.select_for_update(
                nowait=True
            ).get(pk=verification_id)
            verification.update_safely(validation_status=status, note=note)
            if status == BalanceConsolidationStatus.APPROVED:
                eligible, limit_incentive_info_dict = \
                    consolidation_service.evaluate_increase_limit_incentive_amount()
                if not eligible:
                    raise BalConVerificationLimitIncentiveException
                process_approve_balance_consolidation(verification, limit_incentive_info_dict)
            BalanceConsolidationVerificationHistory.objects.bulk_create(histories)

        return JsonResponse(
            status=200,
            data={
                'success': True,
                'data': None,
            },
        )

    except DatabaseError:
        # Handle error message if duplicate request
        return JsonResponse(
            status=400,
            data={
                'success': False,
                'error': 'Duplicate request.',
            },
        )
    except BalConVerificationLimitIncentiveException:
        return JsonResponse(
            status=400,
            data={
                'success': False,
                'error': 'Failed because of checking limit incentive',
            },
        )


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.GET, HTTPMethod.POST])
def upload_document_balance_consolidation_verification(request, verification_id):
    balance_consolidation = BalanceConsolidation.objects.get_or_none(
        balanceconsolidationverification__pk=verification_id,
        balanceconsolidationverification__validation_status=BalanceConsolidationStatus.ON_REVIEW,
    )
    if not balance_consolidation:
        raise Http404(BalanceConsolidationMessageException.NOT_FOUND)

    if request.method == HTTPMethod.GET:
        template_name = '../templates/upload_document.html'
        return render(request, template_name, context={'verification_id': verification_id})
    else:
        url = reverse(
            'balance_consolidation_crm:balance_consolidation_verification_upload_document',
            kwargs={'verification_id': verification_id},
        )
        pdf_document = request.FILES.get('pdf_document')
        if not pdf_document or (pdf_document and pdf_document.content_type != 'application/pdf'):
            messages.error(request, UploadPDFFileMessage.WRONG_PDF_TYPE)
            return HttpResponseRedirect(url)

        customer_id = balance_consolidation.customer_id
        application = Application.objects.filter(customer_id=customer_id).last()
        with transaction.atomic():
            document = upload_loan_agreement_document(application, pdf_document)
            balance_consolidation.update_safely(loan_agreement_document=document)
        messages.success(request, UploadPDFFileMessage.UPLOAD_SUCCESS)
        return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(REQUIRED_GROUPS)
@require_http_methods([HTTPMethod.POST])
def ajax_balance_consolidation(request, consolidation_verification_id):
    verification = BalanceConsolidationVerification.objects.get_or_none(
        id=consolidation_verification_id
    )

    if not verification:
        return JsonResponse(
            status=404,
            data={
                'success': False,
                'data': None,
                'error': 'Balance consolidation verification not found.',
            },
        )
    if verification.locked_by_id and request.user.agent.id != verification.locked_by_id:
        return JsonResponse(
            status=401,
            data={
                'success': False,
                'data': None,
                'error': 'Balance consolidation cannot update, '
                         'because it is locked by another agent.'
            },
        )

    if verification.validation_status != BalanceConsolidationStatus.ON_REVIEW:
        return JsonResponse(
            status=401,
            data={
                'success': False,
                'data': None,
                'error': 'Balance consolidation cannot update, '
                         'because it is not on review.'
            },
        )

    data = request.POST.dict()
    balance_cons = verification.balance_consolidation
    form = BalanceConsolidationForm(data)
    if not form.is_valid():
        return JsonResponse(
            status=400,
            data={
                'success': False,
                'data': None,
                'error': 'Invalid value.'
            }
        )

    agent = request.user.agent
    update_balance_consolidation_data(balance_cons, agent, data)
    return JsonResponse(
        status=200,
        data={
            'success': True,
            'data': None,
        },
    )
