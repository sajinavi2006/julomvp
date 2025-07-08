from django.contrib import admin
from django.contrib.admin import ModelAdmin

from juloserver.julo.admin import JuloModelAdmin
from juloserver.payment_point.models import AYCProduct, TransactionMethod, XfersProduct
from juloserver.payment_point.forms import AYCProductForm, XfersProductForm


class TransactionMethodAdmin(ModelAdmin):
    ordering = ('id',)
    readonly_fields = ('method',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class XfersProductAdmin(JuloModelAdmin):
    list_display = (
        'product_name',
        'category',
        'partner_price',
        'customer_price',
        'customer_price_regular',
        'is_active',
        'type',
    )
    readonly_fields = ()
    search_fields = ('product_name',)
    list_filter = ('category', 'type')
    ordering = ('id',)
    form = XfersProductForm


class AYCProductAdmin(JuloModelAdmin):
    list_display = (
        'product_name',
        'category',
        'partner_price',
        'customer_price',
        'customer_price_regular',
        'is_active',
        'type',
    )
    readonly_fields = ()
    search_fields = ('product_name',)
    list_filter = ('category', 'type')
    ordering = ('id',)
    form = AYCProductForm


admin.site.register(TransactionMethod, TransactionMethodAdmin)
admin.site.register(XfersProduct, XfersProductAdmin)
admin.site.register(AYCProduct, AYCProductAdmin)
