from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^agent_properties', views.agent_properties, name='agent_properties'),

    #ajax request
    url(r'^ajax_get_bucket_and_agent_data',
        views.ajax_get_bucket_and_agent_data,
        name='ajax_get_bucket_and_agent_data'),
    url(r'^ajax_assign_agent_to_squad',
        views.ajax_assign_agent_to_squad,
        name='ajax_assign_agent_to_squad')
]
