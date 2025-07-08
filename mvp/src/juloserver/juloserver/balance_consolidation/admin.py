from django.contrib import admin

from juloserver.balance_consolidation.models import Fintech
from juloserver.julo.admin import JuloModelAdmin


class FintechAdmin(JuloModelAdmin):
    list_display = ('id', 'name', 'is_active')
    list_filter = ('is_active',)
    list_display_links = (
        'id',
        'name',
    )

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Fintech, FintechAdmin)
