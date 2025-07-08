from __future__ import unicode_literals

from django.conf.urls import url

from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^change_phone_in_x137/', views.change_phone_in_x137, name='change_phone_in_x137'),
    url(r'^send_link_reset_pin/', views.send_link_reset_pin, name='send_link_reset_pin'),
    url(
        r'^change_application_data/', views.change_application_data, name='change_application_data'
    ),
    url(
        r'^force_change_application_status/',
        views.force_change_application_status,
        name='force_change_application_status',
    ),
    url(
        r'^delete_mtl_ctl_stl_null_product_customer/',
        views.delete_mtl_ctl_stl_null_product_customer,
        name='delete_mtl_ctl_stl_null_product_customer',
    ),
    url(
        r'^fix_105_no_credit_score/',
        views.fix_105_no_credit_score,
        name='fix_105_no_credit_score',
    ),
    url(
        r'^show_customer_information/',
        views.show_customer_information,
        name='show_customer_information',
    ),
]
