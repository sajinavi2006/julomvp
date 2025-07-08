from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^form/topup$', views.form_view, name='form'),

    #for ajax
    url(r'^ajax_form_topup', views.ajax_form_topup_view, name='ajax_form_topup'),
]