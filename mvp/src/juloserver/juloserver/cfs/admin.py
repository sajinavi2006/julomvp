from django.contrib import admin
from juloserver.cfs.models import CfsTier, CfsActionPoints, CfsAction
from juloserver.julo.admin import JuloModelAdmin


class CfsTierAdmin(JuloModelAdmin):

    list_display = ('id', 'name', 'point', 'message', 'description', 'cashback_multiplier',
                    'referral_bonus', 'qris', 'ppob', 'ecommerce', 'tarik_dana', 'dompet_digital',
                    'transfer_dana', 'pencairan_cashback', 'julo_card', 'pasca_bayar',
                    'listrik_pln', 'bpjs_kesehatan', 'tiket_kereta', 'pdam', 'education', 'balance_consolidation'
                    )
    readonly_fields = ('id', 'name')

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CfsTier, CfsTierAdmin)


class CfsActionAdmin(JuloModelAdmin):
    list_display = (
        'id', 'action_code', 'title', 'is_active', 'default_expiry', 'display_order',
        'icon', 'app_link', 'first_occurrence_cashback_amount', 'repeat_occurrence_cashback_amount',
        'is_need_agent_verify', 'app_version', 'action_type', 'tag_info'
    )
    readonly_fields = (
        'id', 'action_code', 'app_version', 'action_type', 'icon', 'app_link',
        'is_need_agent_verify'
    )

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CfsAction, CfsActionAdmin)


class CfsActionPointsAdmin(JuloModelAdmin):
    list_display = ('id', 'description', 'multiplier', 'floor', 'ceiling', 'default_expiry')
    readonly_fields = ('id',)

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CfsActionPoints, CfsActionPointsAdmin)
