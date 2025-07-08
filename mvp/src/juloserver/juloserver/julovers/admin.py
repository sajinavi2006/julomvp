from django import forms
from django.contrib import admin

from juloserver.julo.admin import JuloModelAdmin
from juloserver.julovers.constants import JuloverPageConst
from juloserver.julovers.models import JuloverPage, Julovers


class JuloverAdmin(JuloModelAdmin):

    list_display = (
        'fullname', 'email', 'address', 'birth_place', 'dob', 'mobile_phone_number', 'gender',
        'marital_status', 'job_industry', 'job_description', 'job_type', 'job_start',
        'bank_name', 'bank_account_number', 'name_in_bank', 'resign_date', 'set_limit'
    )
    readonly_fields = ('id',)

    def has_delete_permission(self, request, obj=None):
        return False


class JuloverPageAdminForm(forms.ModelForm):
    title = forms.ChoiceField(
        required=True,
        choices=JuloverPageConst.CHOICES,
    )


class JuloverPageAdmin(JuloModelAdmin):
    form = JuloverPageAdminForm
    readonly_fields = ['title']
    list_display = [
        'id', 'title', 'is_active',
    ]
    list_display_links = [
        'id', 'title',
    ]
    list_filter = [
        'is_active',
    ]
    search_fields = [
        'title',
    ]
    fieldsets = (
        (None, {'fields': ('title',)}),
        ('Page Content', {'fields': ('content', 'extra_data')})
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # exists => an edit
            return ['title', ]
        else:
            return []


admin.site.register(Julovers, JuloverAdmin)
admin.site.register(JuloverPage, JuloverPageAdmin)
