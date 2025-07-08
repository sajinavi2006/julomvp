from django.contrib import admin
from django.contrib.admin import ModelAdmin

from .models import RenteeDeviceList

class RenteeDeviceListAdmin(ModelAdmin):
    list_display = (
        'id',
        'price',
        'device_name',
        'store',
        'store',
    )


admin.site.register(RenteeDeviceList, RenteeDeviceListAdmin)
