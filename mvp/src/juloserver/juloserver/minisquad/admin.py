from django import forms
from django.contrib import admin
from django.contrib.admin.options import ModelAdmin
from .models import CollectionCalendarsParameter



class CalendarParameterAdminForm(ModelAdmin):
    list_display = (
        'id',
        'summary',
        'description',
        'is_active',
        'is_single_parameter',
        'is_ptp_parameter',
    )
    search_fields = ('summary','description')

admin.site.register(CollectionCalendarsParameter,CalendarParameterAdminForm)
