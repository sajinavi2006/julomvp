from django.conf import settings
from django.contrib import messages
from django.core.urlresolvers import reverse

from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.generic import ListView

from juloserver.dana.constants import DanaUploadAsyncStateType
from juloserver.dana.repayment.crm.forms import DanaRepaymentSettlementForm
from juloserver.dana.repayment.tasks import process_dana_repayment_settlement_task
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.models import Agent, UploadAsyncState
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from juloserver.utilities.paginator import TimeLimitedPaginator


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def dana_repayment_settlement(request):
    upload_form = DanaRepaymentSettlementForm(request.POST, request.FILES)
    template_name = 'object/dana/dana_repayment_settlement.html'
    url = reverse('bulk_upload:dana_repayment_settlement')
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
            product = upload_form.data['product_field']
            agent = Agent.objects.filter(user=request.user).last()
            file_ = upload_form.cleaned_data['file_field']
            extension = file_.name.split('.')[-1]

            if extension != 'csv':
                msg = 'Please upload the correct file type: CSV'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            in_processed_status = {
                UploadAsyncStateStatus.WAITING,
                UploadAsyncStateStatus.PROCESSING,
            }
            is_upload_in_waiting = UploadAsyncState.objects.filter(
                task_type=DanaUploadAsyncStateType.DANA_REPAYMENT_SETTLEMENT,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=DanaUploadAsyncStateType.DANA_REPAYMENT_SETTLEMENT,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            process_dana_repayment_settlement_task.delay(upload_async_state_id, product)
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        upload_form = DanaRepaymentSettlementForm()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class DanaRepaymentSettlementUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/dana/dana_repayment_settlement_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                DanaUploadAsyncStateType.DANA_REPAYMENT_SETTLEMENT,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context
