from django.conf.urls import url
from juloserver.employee_financing import views

urlpatterns = [
    url(r'^pilot-application-csv-upload/$', views.pilot_application_csv_upload_view,
        name='pilot_application_csv_upload'),
    url(r'^pre-approval-csv-upload/$', views.pre_approval_view, name='pre_approval_csv_upload'),
    url(r'^ef_upload_history$', views.EFUploadHistory.as_view(), name='ef_upload_history'),
    url(r'^export-web-form/$', views.export_response_web_form_view, name='export_web_form'),
    url(r'^send-form-url-to-email/$', views.send_form_url_to_email, name='send_form_url_to_email'),
]
