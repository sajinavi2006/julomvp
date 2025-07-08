from django.contrib import admin
from juloserver.employee_financing.forms.company import CompanyForm
from juloserver.employee_financing.models import (
    Company,
    CompanyConfig,
    EmFinancingWFApplication,
    EmFinancingWFDisbursement,
    EmFinancingWFAccessToken,
    EmployeeFinancingFormURLEmailContent
)
from juloserver.julo.admin import JuloModelAdmin


class CompanyAdmin(JuloModelAdmin):
    form = CompanyForm

    list_display = (
        'id', 'name', 'partner', 'email', 'address', 'phone_number',
        'company_term', 'company_size', 'industry', 'company_profitable',
        'centralised_deduction', 'payday', 'limit_type'
    )
    list_select_related = (
        'partner',
    )
    search_fields = ['id', 'name']

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = CompanyForm
        form = super(CompanyAdmin, self).get_form(request, *args, **kwargs)
        form_partner = form.base_fields['partner']
        form_partner.widget.can_add_related = False
        form_partner.widget.can_change_related = False
        form_partner.widget.can_delete_related = False
        return form

    def get_actions(self, request):
        # Disable delete
        actions = super(CompanyAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions


class CompanyConfigAdmin(JuloModelAdmin):
    list_display = (
        'company', 'allow_disburse',
    )

    def has_delete_permission(self, request, obj=None):
        return False


class EmFinancingWFApplicationAdmin(JuloModelAdmin):
    list_display = ('email', 'nik', 'request_loan_amount', 'tenor')
    list_select_relatd = ('company',)


class EmFinancingWFDisbursementAdmin(JuloModelAdmin):
    list_display = ('nik', 'request_loan_amount', 'tenor')
    list_select_relatd = ('company',)

class EmFinancingWFAccessTokenAdmin(JuloModelAdmin):
    list_display = ('email', 'form_type', 'is_used', 'limit_token_creation', 'expired_at')
    list_select_relatd = ('company',)


admin.site.register(Company, CompanyAdmin)
admin.site.register(CompanyConfig, CompanyConfigAdmin)
admin.site.register(EmFinancingWFApplication, EmFinancingWFApplicationAdmin)
admin.site.register(EmFinancingWFDisbursement, EmFinancingWFDisbursementAdmin)
admin.site.register(EmFinancingWFAccessToken, EmFinancingWFAccessTokenAdmin)
admin.site.register(EmployeeFinancingFormURLEmailContent)
