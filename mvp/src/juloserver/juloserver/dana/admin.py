from django.contrib import admin

from juloserver.dana.models import (
    DanaCustomerData,
    DanaLoanReference,
)
from juloserver.julo.admin import JuloModelAdmin


class DanaLoanReferenceAdmin(JuloModelAdmin):
    search_fields = ('loan__id', 'reference_no', 'partner_reference_no')
    list_select_related = ('loan',)
    list_display = ('loan', 'reference_no', 'partner_reference_no')
    readonly_fields = ('loan',)


class DanaCustomerDataAdmin(JuloModelAdmin):
    search_fields = ('id', 'full_name', 'nik')
    list_select_related = ('customer', 'partner')
    list_display = ('full_name', 'nik', 'mobile_number')
    readonly_fields = ('customer', 'partner', 'account', 'application')


admin.site.register(DanaLoanReference, DanaLoanReferenceAdmin)
admin.site.register(DanaCustomerData, DanaCustomerDataAdmin)
