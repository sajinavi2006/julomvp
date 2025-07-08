from django.contrib import admin
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.admin.utils import unquote
from django.contrib.postgres.fields import JSONField
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils.encoding import force_text
from django.utils.html import escape
from django.utils.text import capfirst
from django.utils.translation import ugettext_lazy as _

from juloserver.julo.admin import (
    DynamicFormModelAdmin,
    JuloModelAdmin,
    PrettyJSONWidget,
)
from juloserver.julo.models import Partner
from juloserver.julo.services2 import get_redis_client
from juloserver.partnership.constants import PartnershipTypeConstant
from juloserver.partnership.forms.master_partner_config_product_lookup_form import (
    MasterPartnerConfigProductLookupForm,
)
from juloserver.partnership.models import (
    MasterPartnerConfigProductLookup,
    PartnerLoanSimulations,
    PartnershipApiLog,
    PartnershipConfig,
    PartnershipFeatureSetting,
    PartnershipFlowFlag,
    PartnershipImage,
    PartnershipLogRetryCheckTransactionStatus,
    PartnershipProduct,
    PartnershipUserOTPAction,
    PaylaterTransaction,
    PaylaterTransactionDetails,
    PaylaterTransactionLoan,
    PaylaterTransactionStatus,
)


class PartnerFilter(admin.SimpleListFilter):
    title = "Active Partners"
    parameter_name = "partner"

    def lookups(self, request, model_admin):
        partners = Partner.objects.filter(
            masterpartnerconfigproductlookup__isnull=False, is_active=True
        )
        return [(partner.id, partner.name) for partner in partners]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset.all()
        return queryset.filter(partner_id=self.value())


class MasterPartnerConfigProductLookupAdmin(JuloModelAdmin):
    form = MasterPartnerConfigProductLookupForm

    list_display = (
        "id",
        "partner",
        "product_lookup",
        "minimum_score",
        "maximum_score",
    )
    list_filter = (PartnerFilter,)
    search_fields = ("id", "partner__name")
    ordering = ("id",)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["partner"]
        else:
            return []

    def has_delete_permission(self, request, obj=None):
        return False


class PartnershipConfigAdmin(JuloModelAdmin):
    list_display = (
        "id",
        "partner",
        "partnership_type",
        "callback_url",
        "callback_token",
        "is_transaction_use_pin",
        "is_use_signature",
        "loan_duration",
        "loan_cancel_duration",
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["partner"]
        else:
            return []


class PartnerLogRetryCheckTransactionStatusAdmin(JuloModelAdmin):
    list_select_related = ("loan", "partnership_api_log")
    list_display = ("id", "loan", "status")


class PartnershipApiLogAdmin(JuloModelAdmin):
    list_select_related = ("partner", "customer", "application", "distributor")
    list_display = ('id', 'api_type', 'api_url', 'response')


class PartnershipUserOTPActionAdmin(JuloModelAdmin):
    search_fields = ("id", "otp_request")
    list_select_related = ("otp_request",)
    list_display = ("id", "otp_request", "is_used")


class PartnerLoanSimulationAdmin(JuloModelAdmin):
    search_fields = (
        "partnership_config__partner__id",
        "partnership_config__partner__name",
    )
    list_select_related = (
        "partnership_config",
        "partnership_config__partner",
        "partnership_config__partnership_type",
    )
    list_display = (
        "id",
        "partnership_config",
        "interest_rate",
        "tenure",
        "origination_rate",
        "is_active",
    )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "partnership_config":
            kwargs["queryset"] = PartnershipConfig.objects.filter(
                partnership_type__partner_type_name=PartnershipTypeConstant.WHITELABEL_PAYLATER
            ).select_related("partnership_type")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def delete_model(self, request, obj):
        redis_client = get_redis_client()
        partner_key = "%s_%s" % ("partner_simulation_key:", obj.partnership_config.id)
        redis_client.delete_key(partner_key)
        obj.delete()


class PartnershipImageAdmin(JuloModelAdmin):
    search_fields = ("image_source",)
    list_display = (
        "id",
        "ef_image_source",
        "application_image_source",
        "product_type",
        "image_type",
        "image_url",
    )

    def image_url(self, obj):
        if obj.image_url == "":
            return None
        return '<a href="%s">%s</a>' % (obj.image_url, "link to image")

    image_url.allow_tags = True
    image_url.short_description = "image_url"


class PaylaterTransactionAdmin(JuloModelAdmin):
    search_fields = ('id', 'partner_reference_id')


class PaylaterTransactionDetailAdmin(JuloModelAdmin):
    search_fields = ('id', 'paylater_transaction__partner_reference_id',
                     'paylater_transaction__id')
    list_select_related = ('paylater_transaction',)


class PaylaterTransactionStatusAdmin(JuloModelAdmin):
    search_fields = ('id', 'paylater_transaction__partner_reference_id',
                     'paylater_transaction__id')
    list_select_related = ('paylater_transaction',)


class PaylaterTransactionLoanAdmin(JuloModelAdmin):
    search_fields = ('id', 'paylater_transaction__partner_reference_id',
                     'paylater_transaction__id')
    list_select_related = ('paylater_transaction', 'loan')


class PartnershipFlowFlagAdmin(JuloModelAdmin):
    list_display = ("id", "partner", "name")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["partner"]
        else:
            return []


class PartnershipProductAdmin(JuloModelAdmin):
    search_fields = ('id', 'partner__name', 'partner__id', 'product_name')
    list_display = (
        'id',
        'partner',
        'product_line',
        'product_name',
        'product_price',
    )


class PartnershipFeatureSettingAdmin(DynamicFormModelAdmin):
    list_display = (
        "feature_name",
        "is_active",
        "category",
    )
    readonly_fields = ("feature_name",)
    list_filter = ("is_active",)
    search_fields = ("feature_name",)
    ordering = ("feature_name",)
    formfield_overrides = {JSONField: {"widget": PrettyJSONWidget}}
    dynamic_form_key_field = "feature_name"

    class Media(object):
        js = ("default/js/slider_script.js",)  # project static folder
        css = {"all": ("default/css/slider-style.css",)}

    def history_view(self, request, object_id, extra_context=None):
        "The 'history' admin view for this model."
        from django.contrib.admin.models import LogEntry

        # First check if the user can see this history.
        model = self.model
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404(
                _("%(name)s object with primary key %(key)r does not exist.")
                % {
                    "name": force_text(model._meta.verbose_name),
                    "key": escape(object_id),
                }
            )

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        # Then get the history for this object.
        opts = model._meta
        app_label = opts.app_label
        action_list = (
            LogEntry.objects.filter(
                object_id=unquote(object_id),
                content_type=get_content_type_for_model(model),
            )
            .select_related()
            .order_by("-action_time")
        )

        context = dict(
            self.admin_site.each_context(request),
            title=_("Change history: %s") % force_text(obj),
            action_list=action_list,
            module_name=capfirst(force_text(opts.verbose_name_plural)),
            object=obj,
            opts=opts,
            preserved_filters=self.get_preserved_filters(request),
        )
        context.update(extra_context or {})

        request.current_app = self.admin_site.name

        return TemplateResponse(
            request,
            self.object_history_template
            or [
                "admin/%s/%s/object_history.html" % (app_label, opts.model_name),
                "admin/%s/object_history.html" % app_label,
                "admin/object_history.html",
            ],
            context,
        )

    def get_actions(self, request):
        # Disable delete
        actions = super(PartnershipFeatureSettingAdmin, self).get_actions(request)
        del actions["delete_selected"]
        return actions


admin.site.register(MasterPartnerConfigProductLookup, MasterPartnerConfigProductLookupAdmin)
admin.site.register(PartnershipConfig, PartnershipConfigAdmin)

admin.site.register(
    PartnershipLogRetryCheckTransactionStatus,
    PartnerLogRetryCheckTransactionStatusAdmin,
)

admin.site.register(PartnershipApiLog, PartnershipApiLogAdmin)
admin.site.register(PartnershipUserOTPAction, PartnershipUserOTPActionAdmin)
admin.site.register(PartnerLoanSimulations, PartnerLoanSimulationAdmin)
admin.site.register(PartnershipImage, PartnershipImageAdmin)
admin.site.register(PaylaterTransaction, PaylaterTransactionAdmin)
admin.site.register(PaylaterTransactionDetails, PaylaterTransactionDetailAdmin)
admin.site.register(PaylaterTransactionStatus, PaylaterTransactionStatusAdmin)
admin.site.register(PaylaterTransactionLoan, PaylaterTransactionLoanAdmin)
admin.site.register(PartnershipProduct, PartnershipProductAdmin)
admin.site.register(PartnershipFlowFlag, PartnershipFlowFlagAdmin)
admin.site.register(PartnershipFeatureSetting, PartnershipFeatureSettingAdmin)
