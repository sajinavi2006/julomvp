from django.contrib import messages
from typing import Any, Dict, List
from django.conf import settings

from juloserver.dana.constants import DanaUploadAsyncStateType
from juloserver.dana.loan.crm.forms import DanaSettlementFileUpload
from juloserver.julo.models import Agent, UploadAsyncState
from juloserver.portal.object import julo_login_required, julo_login_required_multigroup
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpRequest, HttpResponse
from django.views.generic import ListView
from django.db.models import QuerySet

from juloserver.dana.dana_lender.crm.tasks import process_dana_lender_payment_upload_task

from juloserver.julo.constants import UploadAsyncStateStatus
from django.shortcuts import render
from juloserver.utilities.paginator import TimeLimitedPaginator


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
def dana_lender_upload_payment(request):
    upload_form = DanaSettlementFileUpload(request.POST, request.FILES)
    template_name = 'object/dana/dana_lender_upload_payment.html'
    url = reverse('bulk_upload:dana_lender_upload_payment')
    if request.method == 'POST':
        if not upload_form.is_valid():
            for key in upload_form.errors:
                messages.error(request, upload_form.errors[key][0] + "\n")
        else:
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
                task_type=DanaUploadAsyncStateType.DANA_LENDER_PAYMENT_UPLOAD,
                task_status__in=in_processed_status,
                agent=agent,
                service='oss',
            ).exists()

            if is_upload_in_waiting:
                msg = 'Another process in waiting or process please wait and try again later'
                messages.error(request, msg)
                return HttpResponseRedirect(url)

            upload_async_state = UploadAsyncState(
                task_type=DanaUploadAsyncStateType.DANA_LENDER_PAYMENT_UPLOAD,
                task_status=UploadAsyncStateStatus.WAITING,
                agent=agent,
                service='oss',
            )
            upload_async_state.save()
            upload = file_
            upload_async_state.file.save(upload_async_state.full_upload_name(upload.name), upload)
            upload_async_state_id = upload_async_state.id
            process_dana_lender_payment_upload_task.delay(
                upload_async_state_id,
                DanaUploadAsyncStateType.DANA_LENDER_PAYMENT_UPLOAD,
            )
            messages.success(
                request,
                'Your file is being processed. Please check Upload History to see the status',
            )

    elif request.method == 'GET':
        upload_form = DanaSettlementFileUpload()
        return render(request, template_name, {'form': upload_form})
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class DanaLenderPaymentUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/dana/dana_lender_upload_payment_history.html'

    def http_method_not_allowed(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponse:
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self) -> List:
        return ListView.get_template_names(self)

    def get_queryset(self) -> QuerySet:
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                DanaUploadAsyncStateType.DANA_LENDER_PAYMENT_UPLOAD,
            ],
            agent__user_id=self.request.user.id,
        ).order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list: Any) -> Any:
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs: Any) -> Dict:
        context = super().get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context
