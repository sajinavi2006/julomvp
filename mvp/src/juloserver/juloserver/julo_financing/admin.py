from django.contrib import admin
from django.forms import BaseInlineFormSet, ValidationError
from django.utils.html import format_html

from juloserver.julo_financing.models import (
    JFinancingProduct,
    JFinancingProductSaleTag,
    JFinancingProductSaleTagDetail,
)
from juloserver.julo_financing.services.view_related import get_j_financing_product_images


class JFinancingSaleTagAdmin(admin.ModelAdmin):
    list_display = (
        'tag_name',
        'is_active',
        'description',
    )
    list_display_links = ('tag_name',)
    fieldsets = (
        (
            'Tag Logo',
            {
                'fields': ('display_image',),
            },
        ),
        (
            'Details',
            {
                'fields': (
                    'is_active',
                    'tag_name',
                    'tag_image_url',
                    'description',
                )
            },
        ),
    )
    readonly_fields = ('display_image',)

    def display_image(self, obj):
        if not obj.id or not obj.tag_image_url:
            return '-'

        img = obj.tag_image_url
        return format_html(
            '<img src="{}" style="width:150px; height:auto; margin-right:10px;" />'.format(img)
        )

    def has_delete_permission(self, request, obj=None):
        # Disable delete permission in the admin for this model
        return False


class JFinancingProductSaleTagDetailInlineFormSet(BaseInlineFormSet):
    def clean(self):
        # make sure there is only one primary
        primary_count = 0
        for form in self.forms:
            if form.cleaned_data.get('primary'):
                primary_count += 1

        if primary_count > 1:
            raise ValidationError("Only one primary tag is allowed per product.")


class JFinancingProductSaleTagDetailInline(admin.TabularInline):
    model = JFinancingProductSaleTagDetail
    extra = 0  # Number of empty forms to display
    fields = ('jfinancing_product_sale_tag', 'primary')
    can_delete = True
    formset = JFinancingProductSaleTagDetailInlineFormSet


class JFinancingProductAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'price',
        'display_installment_price',
        'is_active',
        'quantity',
        'j_financing_category_name',
    )
    list_display_links = (
        'id',
        'name',
        'price',
        'display_installment_price',
        'j_financing_category_name',
    )
    list_editable = ('is_active', 'quantity')
    list_select_related = True
    list_filter = ('j_financing_category__name', 'is_active')
    search_fields = ('id', 'name')

    fieldsets = (
        (
            None,
            {
                'fields': (
                    'name',
                    'price',
                    'display_installment_price',
                    'description',
                    'is_active',
                    'quantity',
                    'j_financing_category',
                )
            },
        ),
        (
            'Images',
            {
                'fields': ('display_images',),
                'description': 'The first image is the primary one, the rest are detailed images',
            },
        ),
    )
    readonly_fields = ('display_images',)
    inlines = [JFinancingProductSaleTagDetailInline]

    def display_images(self, obj):
        if not obj.id:
            return '-'

        images = get_j_financing_product_images(product_id=obj.id)
        return format_html(
            ''.join(
                [
                    '<img src="{}" style="width:150px; height:auto; margin-right:10px;" />'.format(
                        img
                    )
                    for img in images
                ]
            )
        )


admin.site.register(JFinancingProduct, JFinancingProductAdmin)
admin.site.register(JFinancingProductSaleTag, JFinancingSaleTagAdmin)
