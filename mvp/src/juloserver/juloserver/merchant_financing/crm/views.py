from django.conf import settings
from django.views.generic import ListView

from juloserver.julo.constants import UploadAsyncStateType
from juloserver.julo.models import UploadAsyncState
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)
from juloserver.utilities.paginator import TimeLimitedPaginator


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class MerchantFinancingRegiserUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/merchant_financing/merchant_financing_upload_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.MERCHANT_FINANCING_REGISTER,
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


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class MerchantFinancingDisbursementUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/merchant_financing/merchant_financing_upload_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.MERCHANT_FINANCING_DISBURSEMENT,
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


@julo_login_required
@julo_login_required_multigroup(['bo_data_verifier'])
class MerchantFinancingAdjustLimitUploadHistory(ListView):
    model = UploadAsyncState
    paginate_by = 10
    paginator_class = TimeLimitedPaginator
    template_name = 'object/merchant_financing/merchant_financing_upload_history.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super().get_queryset()
        self.qs = self.qs.filter(
            task_type__in=[
                UploadAsyncStateType.MERCHANT_FINANCING_ADJUST_LIMIT,
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
