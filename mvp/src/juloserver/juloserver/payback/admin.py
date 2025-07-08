from django.contrib import admin
from .models import CashbackPromo
from django.core.urlresolvers import reverse
from django.utils.safestring import mark_safe
from django.contrib.admin import AdminSite
from django.template import loader
from .views import (
    cashback_promo_add,
    cashback_promo_edit,
    cashback_promo_review,
    cashback_promo_proceed,)

class CashbackPromoAdmin(admin.ModelAdmin):
    def __init__(self, *args, **kwargs):
        super(CashbackPromoAdmin, self).__init__(*args, **kwargs)
        self.list_display_links = None

    def action(self, obj):
        url_edit = reverse('cashback_promo_admin:cashback_promo_edit', kwargs={'cashback_promo_id': obj.id})
        url_review = reverse('cashback_promo_admin:cashback_promo_review', kwargs={'cashback_promo_id': obj.id})
        action_button = ''
        if not obj.decision:
            action_button += '<a class="default" href="'+url_edit+'"> Edit </a> | '
        action_button += '<a class="default" href="'+url_review+'"> Review </a>'
        return mark_safe(action_button)

    def has_add_permission(self, request, obj=None):
        return False

    # search_fields = ['title']
    list_display = ('promo_name', 'requester', 'decision', 'decided_by', 'decision_ts', 'is_completed', 'action')
    change_list_template = loader.get_template('custom_admin/cashback_promo_template.html')


class CashbackPromoCustomAdmin(admin.ModelAdmin):
    pass


class CashbackPromoAdminSite(AdminSite):
    def __init__(self, *args, **kwargs):
        super(CashbackPromoAdminSite, self).__init__(*args, **kwargs)
        self.name = 'cashback_promo_admin'

    def get_urls(self):
        from django.conf.urls import url
        urls = super(CashbackPromoAdminSite, self).get_urls()
        # Note that custom urls get pushed to the list (not appended)
        # This doesn't work with urls += ...
        urls = [
                   url(r'^cashback_promo_add/$',
                       self.admin_view(cashback_promo_add), name='cashback_promo_add'),
                   url(r'^cashback_promo_edit/(?P<cashback_promo_id>[0-9]+)$'
                       , self.admin_view(cashback_promo_edit), name='cashback_promo_edit'),
                   url(r'^cashback_promo_review/(?P<cashback_promo_id>[0-9]+)$',
                       self.admin_view(cashback_promo_review), name='cashback_promo_review'),

                   url(r'^cashback_promo_proceed/(?P<cashback_promo_id>[0-9]+)$',
                       self.admin_view(cashback_promo_proceed), name='cashback_promo_proceed'),
               ] + urls

        return urls

cashback_promo_admin_site = CashbackPromoAdminSite()
cashback_promo_admin_site.register(CashbackPromo, CashbackPromoCustomAdmin)
admin.site.register(CashbackPromo, CashbackPromoAdmin)
