from __future__ import print_function
import logging

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.generic import ListView
from future import standard_library
from rest_framework.reverse import reverse
from django.contrib import messages
from dashboard.constants import JuloUserRoles
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
    UploadAsyncStateType,
)
from juloserver.julo.models import (
    Agent,
    UploadAsyncState,
)
from juloserver.utilities.paginator import TimeLimitedPaginator
from object import julo_login_required, julo_login_required_group
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julovers.tasks import process_julovers_task

standard_library.install_aliases()

logger = logging.getLogger(__name__)
client = get_julo_sentry_client()


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')
VALID_CONTENT_TYPES_UPLOAD = [
    'text/csv',
    'application/vnd.ms-excel',
    'text/x-csv',
    'application/csv',
    'application/x-csv',
    'text/comma-separated-values',
    'text/x-comma-separated-values',
    'text/tab-separated-values'
]


@julo_login_required
@julo_login_required_group(JuloUserRoles.PRODUCT_MANAGER)
def UploadJuloversData(request):
    template_name = 'julovers/julovers_csv_upload.html'
    if request.method == 'POST':
        if not request.FILES.get('csv_file'):
            messages.error(request, 'Error! File is not selected')
        else:
            agent = Agent.objects.filter(user=request.user).last()
            file = request.FILES['csv_file']
            if file.content_type not in VALID_CONTENT_TYPES_UPLOAD:
                messages.error(request, 'Error! File type should be CSV')
            else:
                upload_async_state = UploadAsyncState(
                    task_type=UploadAsyncStateType.JULOVERS,
                    task_status=UploadAsyncStateStatus.WAITING,
                    agent=agent,
                    service='oss',
                )
                upload_async_state.save()
                upload = request.FILES['csv_file']
                upload_async_state.file.save(
                    upload_async_state.full_upload_name(upload.name), upload
                )
                process_julovers_task.delay(upload_async_state.id)
                messages.success(
                    request,
                    'Your file is being processed. Please check Upload History to see the status'
                )
    elif request.method == 'GET':
        return render(request, template_name)
    url = reverse('julovers.crm:upload_julovers_data')
    return HttpResponseRedirect(url)


@julo_login_required
@julo_login_required_group(JuloUserRoles.PRODUCT_MANAGER)
class UploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'julovers/upload_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super(UploadHistory, self).get_queryset()
        self.qs = self.qs.order_by('-id')
        self.err_message_here = None
        return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(UploadHistory, self).get_context_data(**kwargs)

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context
