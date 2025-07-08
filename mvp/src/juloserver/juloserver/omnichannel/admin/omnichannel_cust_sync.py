import codecs
import csv
import logging
import traceback
from django import forms
from django.core.urlresolvers import reverse
from django.shortcuts import redirect
from django.conf.urls import url
from django.template.response import TemplateResponse

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.omnichannel.tasks import omnichannel_bulk_process
from juloserver.omnichannel.constants import ACTION_CHOICES, BULK_PROCESS_GUIDELINE_URL
from juloserver.omnichannel.services.cust_sync_bulk_process import (
    CustomerSyncBulkProcessRedisRepository,
)
from juloserver.omnichannel.models import (
    OmnichannelCustomerSync,
    OmnichannelCustomerSyncBulkProcessHistory,
)
from juloserver.julo.admin import (
    JuloModelAdmin,
)


logger = logging.getLogger(__name__)


class OmnichannelCustomerSyncBulkProcessForm(forms.Form):
    action = forms.ChoiceField(choices=ACTION_CHOICES)
    csv_file = forms.FileField(label='CSV File')
    sync_rollout_attr = forms.BooleanField(label='Sync Rollout Attribute')
    sync_cust_attribute = forms.BooleanField(label='Sync Customer Attribute')
    is_rollout_pds = forms.BooleanField(label='Is PDS Rollout')
    is_rollout_pn = forms.BooleanField(label='Is PN Rollout')
    is_rollout_sms = forms.BooleanField(label='Is SMS Rollout')
    is_rollout_email = forms.BooleanField(label='Is Email Rollout')
    is_rollout_one_way_robocall = forms.BooleanField(label='Is 1-way Robocall Rollout')
    is_rollout_two_way_robocall = forms.BooleanField(label='Is 2-way Robocall Rollout')
    notes = forms.CharField(required=False, initial='-')


class OmnichannelCustomerSyncAdmin(JuloModelAdmin):
    change_list_template = 'custom_admin/change_list_with_custom_object_tools.html'
    change_form_template = 'custom_admin/disable_save_button.html'
    actions = []
    search_fields = ('customer_id',)
    list_display_links = ('id', 'customer_id')
    list_display = [field.name for field in OmnichannelCustomerSync._meta.get_fields()]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def save_model(self, request, obj, form, change):
        pass

    def delete_model(self, request, obj):
        pass

    def save_related(self, request, form, formsets, change):
        pass

    def get_data_table(self):
        return {'property': ['customer_id'], 'data': ['integer']}

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(
            request,
            extra_context=extra_context,
        )
        response.context_data['cl'].show_admin_actions = False
        response.context_data['custom_object_tools'] = [
            {'link': 'add-file/', 'text': 'Bulk Process', 'class': 'addlink'},
            {
                'link': reverse('admin:omnichannel_omnichannelcustomersync_bulkprocesshist'),
                'text': 'History',
                'class': 'historylink',
            },
        ]
        return response

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            url('add-file/', self.import_csv),
            url(
                'bulk-process-hist/',
                self.bulk_process_hist,
                name='omnichannel_omnichannelcustomersync_bulkprocesshist',
            ),
        ]
        return my_urls + urls

    def bulk_process_hist(self, request):
        response = super().changelist_view(
            request,
            extra_context=None,
        )
        response.context_data['disable_search'] = True
        response.context_data['custom_object_tools'] = [
            {
                'link': reverse('admin:omnichannel_omnichannelcustomersync_changelist'),
                'text': 'Back',
                'class': 'historylink',
            },
            {'link': '.', 'text': 'Refresh', 'class': 'historylink'},
        ]
        response.context_data['title'] = 'Omnichannel Customer Sync Bulk Process Histories'
        response.context_data['custom_headers'] = list(
            OmnichannelCustomerSyncBulkProcessHistory.label_to_key().keys()
        )
        response.context_data['custom_result_lists'] = []
        for row in CustomerSyncBulkProcessRedisRepository.list():
            temp = []
            for _, v in OmnichannelCustomerSyncBulkProcessHistory.label_to_key().items():
                temp.append(getattr(row, v))
            response.context_data['custom_result_lists'].append(temp)
        return TemplateResponse(
            request,
            'custom_admin/result_list_with_custom_header_and_value.html',
            response.context_data,
        )

    def post_bulk_process(self, request):
        task_id = CustomerSyncBulkProcessRedisRepository.generate_task_id()
        try:
            logger.info(
                {
                    'action': 'post_bulk_process',
                    'task_id': task_id,
                    'message': 'Start to read CSV File',
                }
            )
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                self.message_user(request, 'Failed to read CSV file.', level='error')
                return redirect('..')

            payload = request.POST
            csv_data = csv.DictReader(codecs.iterdecode(csv_file, 'utf-8'))
            customer_ids = list(map(lambda row: int(row.get('customer_id')), csv_data))
            parameters = {
                'action_by': request.user.username,
                'action': payload['action'].lower(),
            }
            for k in payload.keys():
                if k.startswith('sync_') or k.startswith('is_'):
                    parameters.update({k: True})
                    continue
                if k == 'notes':
                    parameters.update({k: payload[k]})
            logger.info(
                {
                    'action': 'post_bulk_process',
                    'task_id': task_id,
                    'message': 'CSV File has been read succesfully',
                    'parameters': parameters,
                }
            )
            omnichannel_bulk_process.delay(customer_ids, task_id, parameters)
        except Exception as e:
            get_julo_sentry_client().captureException()
            logger.error(
                {
                    'action': 'post_bulk_process',
                    'task_id': task_id,
                    'message': traceback.format_exc(),
                    'level': 'error',
                }
            )
            msg = 'Task ID: {task_id}. Failed to import due to an error in one or more rows: {err}'.format(  # noqa
                task_id=task_id, err=str(e)
            )
            self.message_user(request, msg, level='error')
            return redirect('..')

        self.message_user(
            request,
            'Your bulk process request has been submitted succesfully with Task ID: {}.'.format(
                str(task_id)
            ),
        )
        return redirect(reverse('admin:omnichannel_omnichannelcustomersync_bulkprocesshist'))

    def import_csv(self, request):
        if request.method == 'POST':
            return self.post_bulk_process(request)

        context = self.admin_site.each_context(request)
        context['opts'] = self.model._meta
        context['form'] = OmnichannelCustomerSyncBulkProcessForm()
        context['title'] = 'Omnichannel Customer Sync Bulk Process'
        context['data_table'] = {'property': ['customer_id'], 'data': ['integer']}
        context['custom_object_tools'] = [
            {
                'link': reverse('admin:omnichannel_omnichannelcustomersync_changelist'),
                'text': 'Back',
                'class': 'viewlink',
                'add_back': True,
            },
            {
                'link': BULK_PROCESS_GUIDELINE_URL,
                'text': 'Guideline',
                'class': 'historylink',
                'add_guideline_icon': True,
            },
            {
                'link': reverse('admin:omnichannel_omnichannelcustomersync_bulkprocesshist'),
                'text': 'History',
                'class': 'historylink',
                'add_hist_icon': True,
            },
        ]
        return TemplateResponse(
            request, 'custom_admin/full_upload_form_with_data_table.html', context
        )
