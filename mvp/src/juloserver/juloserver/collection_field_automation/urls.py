from django.conf.urls import url
from . import views

field_supervisor_urls = [
    url(r'^field_supervisor_dashboard',
        views.field_supervisor_dashboard, name='field_supervisor_dashboard'),
    url(r'^download_eligible_account_for_assign',
        views.download_eligible_account_for_assign, name='download_eligible_account_for_assign'),
    url(r'^upload_agent_field_assignment',
        views.upload_agent_field_assignment, name='upload_agent_field_assignment'),
    url(r'^field_agent_attendance_report',
        views.field_agent_attendance_report, name='field_agent_attendance_report'),
    url(r'^download_report_attendance',
        views.download_report_attendance, name='download_report_attendance'),
]
field_agent_urls = [
    url(r'^agent_field_dashboard',
        views.agent_field_dashboard, name='agent_field_dashboard'),
    url(r'^store_location_agent_attendance',
        views.store_location_agent_attendance, name='store_location_agent_attendance'),
    url(r'^agent_field_report_form/(?P<field_assignment_id>\d+)$',
        views.agent_field_report_form, name='agent_field_report_form'),
    url(r'^get_assignment_field_list',
        views.assignment_field_list_for_agent, name='get_assignment_field_list'),
    url(r'^customer_identity/(?P<account_id>\d+)$',
        views.customer_identity, name='customer_identity'),
    url(r'^get_field_assignment_detail',
        views.get_field_assignment_detail, name='get_field_assignment_detail'),
     url(r'^process_bulk_download_excel_trigger',
        views.process_bulk_download_excel_trigger, name='process_bulk_download_excel_trigger'),
     url(r'^(?P<task_id>[\w-]+)/$',
        views.get_bulk_download_excel_progress, name='get_bulk_download_excel_progress'),
     url(r'^do_download_excel_progress/(?P<excel_file_name>[\w-]+)$',
        views.do_download_excel_progress, name='do_download_excel_progress'),
     url(r'^process_bulk_upload_excel_trigger',
        views.process_bulk_upload_excel_trigger, name='process_bulk_upload_excel_trigger')

]
urlpatterns = field_supervisor_urls + field_agent_urls
