from django.contrib import admin
from juloserver.collection_vendor.models import CollectionVendorRatio
from django.contrib.admin import AdminSite
# Register your models here.
from juloserver.collection_vendor.services import get_grouped_collection_vendor_ratio
from juloserver.collection_vendor.views import collection_vendor_ratio_edit
from juloserver.julo.admin import JuloModelAdmin
from django.db.models import Aggregate, CharField
from django.template import loader


class Concat(Aggregate):
    function = 'string_agg'
    template = "%(function)s(%(distinct)s%(expressions)s::text, ',')"

    def __init__(self, expression, distinct=False, **extra):
        super(Concat, self).__init__(
            expression,
            distinct='DISTINCT ' if distinct else '',
            output_field=CharField(),
            **extra)


class CollectionVendorRatioAdmin(admin.ModelAdmin):
    def __init__(self, *args, **kwargs):
        super(CollectionVendorRatioAdmin, self).__init__(*args, **kwargs)
        self.list_display_links = None

    def has_add_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        qs = super(CollectionVendorRatioAdmin, self).get_queryset(request)
        data = get_grouped_collection_vendor_ratio(qs)
        extra_context = extra_context or {}
        extra_context['data'] = data
        return super(CollectionVendorRatioAdmin, self).changelist_view(
            request, extra_context=extra_context
        )

    change_list_template = loader.get_template('custom_admin/collection_vendor_ratio_template.html')


class CollectionVendorRatioAdminSite(AdminSite):
    def __init__(self, *args, **kwargs):
        super(CollectionVendorRatioAdminSite, self).__init__(*args, **kwargs)
        self.name = 'collection_vendor_admin'

    def get_urls(self):
        from django.conf.urls import url
        urls = super(CollectionVendorRatioAdminSite, self).get_urls()
        urls = [
            url(r'^collection_vendor_ratio_update/(?P<vendor_types>.+)$', self.admin_view(
                collection_vendor_ratio_edit), name='collection-vendor-ratio-update')] + urls

        return urls


class CollectionVendorRatioCustomAdmin(JuloModelAdmin):
    pass


collection_vendor_ratio_admin_site = CollectionVendorRatioAdminSite()
collection_vendor_ratio_admin_site.register(CollectionVendorRatio, CollectionVendorRatioCustomAdmin)

admin.site.register(CollectionVendorRatio, CollectionVendorRatioAdmin)
