from builtins import object
import os
import re
from croniter import croniter

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import ModelAdmin
from django.contrib.auth.models import User, Group
from django.contrib.auth.hashers import make_password
from django.conf import settings
from juloserver.julo.models import (
    Partner,
    ProductLine,
    ProductProfile,
    ProductLookup,
    Workflow,
    WorkflowStatusPath,
    PartnerProperty,
    XidLookup,
    PaymentMethodLookup
)
from juloserver.julo.constants import WorkflowConst
from juloserver.partnership.models import (PartnershipConfig,
                                           PartnershipType,
                                           Distributor,
                                           PartnershipUser
)
from juloserver.merchant_financing.models import (MerchantPartner,
                                                  MerchantPaymentMethodLookup
)
from juloserver.partnership.constants import  PartnershipTypeConstant
from juloserver.julo.admin import JuloModelAdmin
from juloserver.api_token.authentication import make_never_expiry_token
from juloserver.julo.services2 import encrypt
from juloserver.julo.payment_methods import (PaymentMethodManager,
                                             mf_excluded_payment_method_codes)
from juloserver.julo.services2.payment_method import update_mf_payment_method_is_shown_mf_flag
from .forms.master_partner_affordability_threshold import MasterPartnerAffordabilityThresholdForm
from .forms.merchant_partner import MerchantPartnerAdminForm
from juloserver.merchant_financing.forms.partnership_user import PartnershipUserAdminForm
from .forms.merchant_payment_method_lookup import MerchantPaymentMethodLookupAdminForm
from juloserver.merchant_financing.forms.distributor import DistributorForm
from .models import (
    BulkDisbursementSchedule,
    MasterPartnerAffordabilityThreshold,
    MerchantBinaryCheck,
    MerchantApplicationReapplyInterval
)
from juloserver.partnership.models import Distributor


class BulkDisbursementScheduleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['partner'].queryset = Partner.objects.filter(is_active=True)

    class Meta(object):
        model = BulkDisbursementSchedule
        fields = '__all__'

    def clean_crontab(self):
        crontab = self.cleaned_data['crontab']
        if not croniter.is_valid(crontab):
            raise forms.ValidationError('Incorrect crontab value')
        return crontab


class BulkDisbursementScheduleAdmin(ModelAdmin):
    form = BulkDisbursementScheduleForm
    list_display = (
        'id', 'product_line_code', 'partner', 'distributor', 'is_active', 'is_manual_disbursement')


class PartnerFilter(admin.SimpleListFilter):
    title = 'Active Partners'
    parameter_name = 'partner'

    def lookups(self, request, model_admin):
        partners = Partner.objects.filter(
            masterpartneraffordabilitythreshold__isnull=False, is_active=True
        )
        return [(partner.id, partner.name) for partner in partners]

    def queryset(self, request, queryset):
        if not self.value():
            return queryset.all()
        return queryset.filter(partner_id=self.value())


class MasterPartnerAffordabilityThresholdAdmin(JuloModelAdmin):

    form = MasterPartnerAffordabilityThresholdForm

    list_display = (
        'id', 'partner', 'minimum_threshold', 'maximum_threshold',
    )
    list_filter = (PartnerFilter,)
    search_fields = ('id', 'partner__name')
    ordering = ('id',)

    def get_readonly_fields(self, request, obj=None):
        # when data is being edit, field partner will read_only
        if obj:
            return ["partner"]
        else:
            return []

    def has_delete_permission(self, request, obj=None):
        return False


class PartnerInLine(admin.TabularInline):
    model = Partner


class MerchantBinaryCheckForm(forms.ModelForm):
    class Meta:
        model = MerchantBinaryCheck
        fields = "__all__"
        help_texts = {
                'raw_sql_query': '<b>Rules to Follow for Entering Raw SQL queries:</b><br>'
                                 '1. Use "{{merchant}}" to replace with merchant_id in the query.<br>'
                                 '2. Use "{{merchant_historical_transaction}}" to replace with '
                                 '"ops.merchant_historical_transaction" in the query<br>'
                                 '3. Don\'t using schema names in the query.<br>'
                                 '4. Don\'t use keywords create, update, insert and delete '
                                 'anywhere in the query<br>'
                                 '5. Add is_deleted = false in every query<br><br>'
                                 '<b>Example Query:</b><br>'
                                 'If you want to run a query like <br>'
                                 '<i>select count(*) from ops.merchant_historical_transaction mht '
                                 'where merchant_id = 10 and is_deleted = false</i><br>'
                                 'the raw query we use should be like <br>'
                                 '<i>select count(*) from {{merchant_historical_transaction}} mht '
                                 'where merchant_id = {{merchant}} and is_deleted = false</i>',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        self.fields['raw_sql_query'].error_messages.update({'required': 'This field is required.'})
        self.fields['cut_off_limit'].error_messages.update({'required': 'This field is required.'})
        self.fields['binary_check_weight'].error_messages.update({'required': 'This field is required.'})

    def clean_raw_sql_query(self):
        pattern = re.findall(r'insert\b|delete\b|update\b|create\b|ops\b|ana\b|msg\b|public\b|sb',
                             self.cleaned_data["raw_sql_query"], re.IGNORECASE)
        if pattern:
            problem_keywords = ""
            for idx, string in enumerate(pattern):
                problem_keywords += string + (" and " if len(pattern) != (idx+1) else " ")
            raise forms.ValidationError("{}Cannot Be used".format(problem_keywords))

        result = re.sub('{{\s*merchant\s*}}', '{{merchant}}', self.cleaned_data["raw_sql_query"])
        final_result = re.sub('{{\s*merchant_historical_transaction\s*}}', '{{merchant_historical_transaction}}', result)
        return final_result

    def clean_binary_check_weight(self):
        binary_check_weight = float(self.cleaned_data["binary_check_weight"])
        if binary_check_weight or binary_check_weight == 0:
            if binary_check_weight <= 0:
                raise forms.ValidationError("Ensure this value is greater than or equal to 0.01")
            elif binary_check_weight > 1:
                raise forms.ValidationError("Ensure this value is less than or equal to 1")

        return str(binary_check_weight)


class MerchantBinaryCheckAdmin(ModelAdmin):
    form = MerchantBinaryCheckForm
    change_form_template = "custom_admin/merchant_binary_check_form.html"

    list_display = ('partner', 'category', 'raw_sql_query', 'operator',
                    'cut_off_limit', 'binary_check_weight', 'is_active')
    search_fields = ['partner', 'category']
    list_filter = ('partner',)

    def get_form(self, request, obj=None, **kwargs):
        from juloserver.api_token.models import ExpiryToken
        user = request.user
        expiry_token = ExpiryToken.objects.get(user=user)
        extra_context = {"token": expiry_token, 'base_url': settings.BASE_URL}
        form = super().get_form(request, obj, **kwargs)
        return form

    def change_view(self, request, object_id, form_url='', extra_context=None):
        from juloserver.api_token.models import ExpiryToken
        if extra_context is None:
            user = request.user
            expiry_token = ExpiryToken.objects.get(user=user)
            extra_context = {"token": expiry_token, 'base_url': settings.BASE_URL}
        return super(MerchantBinaryCheckAdmin, self).change_view(
            request, object_id=object_id, form_url=form_url, extra_context=extra_context)

    def add_view(self, request, form_url='', extra_context=None):
        from juloserver.api_token.models import ExpiryToken
        if extra_context is None:
            user = request.user
            expiry_token = ExpiryToken.objects.get(user=user)
            extra_context = {"token": expiry_token, 'base_url': settings.BASE_URL}
        return super().add_view(request, extra_context=extra_context)


class MerchantPartnerAdmin(ModelAdmin):
    form = MerchantPartnerAdminForm
    list_display = ('id', 'name', 'email', 'is_active')
    search_fields = ['id', 'name', 'email']

    actions = ['delete_selected_merchant_partners']

    def get_queryset(self, request):
        partnership_type = PartnershipType.objects.filter(
            partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING).last()
        partner_ids = PartnershipConfig.objects.filter(partnership_type=partnership_type.id).values_list('partner', flat=True)
        query_filter = dict(pk__in=partner_ids)
        partners = MerchantPartner.objects.filter(**query_filter)
        return partners

    def delete_selected_merchant_partners(self, request, queryset):
        success_records_count = 0
        failure_record_count = 0
        failure_msg = success_msg = ''
        for obj in queryset:
            distributor = Distributor.objects.filter(
                partner=obj.id
            ).first()
            if not distributor:
                PartnerProperty.objects.filter(partner=obj.id).delete()
                PartnershipConfig.objects.filter(partner=obj.id).delete()
                User.objects.filter(id=obj.user.id).delete()
                obj.delete()
                success_records_count+=1
            else:
                failure_record_count+=1

        if success_records_count > 0:
            success_msg =  "Successfully deleted %d merchant partners." % success_records_count

        if failure_record_count > 0:
            failure_msg =  "Sorry! not able to delete %d merchant partners. Distributor created for this partner" % failure_record_count

        if success_records_count > 0 and failure_record_count > 0:
            messages.success(request, success_msg)
            messages.error(request, failure_msg)
        elif failure_record_count > 0:
            messages.error(request, failure_msg)
        else:
            messages.success(request, success_msg)

    def get_actions(self, request):
        actions = super().get_actions(request)
        del actions['delete_selected']
        return actions

    def has_add_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

    def delete_model(self, request, obj):
        distributor = Distributor.objects.filter(
            partner=obj.id
        ).first()
        if not distributor:
            User.objects.filter(id=obj.user.id).delete()
            PartnerProperty.objects.filter(partner=obj.id).delete()
            PartnershipConfig.objects.filter(partner=obj.id).delete()
            obj.delete()
        else:
            messages.set_level(request, messages.ERROR)
            messages.error(request, "Sorry! not able to delete. Distributor created for this partner.")
            pass

    def save_model(self, request, obj, form, change):
        if obj.id is not None:
            partner = Partner.objects.get(id=obj.id)
            if partner:
                User.objects.filter(id=partner.user.id).update(username=obj.name,
                                                            email=obj.email)
                super(MerchantPartnerAdmin, self).save_model(request, obj, form, change)

        else:
            group = Group.objects.get(name="julo_partners")
            password = make_password('partner_{}'.format(obj.name))

            user = User.objects.create(username=obj.name,
                                       email=obj.email,
                                       password=password)
            user.groups.add(group)
            make_never_expiry_token(user)
            encrypter = encrypt()
            secret_key = encrypter.encode_string(str(user.auth_expiry_token))
            obj.user = user
            obj.token = secret_key
            super(MerchantPartnerAdmin, self).save_model(request, obj, form, change)
            loan_duration = [3, 7, 14, 30]  # in days
            partnership_type = PartnershipType.objects.filter(
                partner_type_name=PartnershipTypeConstant.MERCHANT_FINANCING).last()
            if partnership_type:
                PartnershipConfig.objects.create(
                    partner=obj,
                    partnership_type=partnership_type,
                    loan_duration=loan_duration
                )

            product_line_code = 300
            product_line_type = 'MF'
            product_line = ProductLine.objects.filter(product_line_type=product_line_type,
                                                      product_line_code=product_line_code).last()
            product_profile = ProductProfile.objects.filter(name=product_line_type,
                                                            code=product_line_code).last()
            if not product_line and not product_profile:

                product_line_code = product_line_code
                product_profile = ProductProfile.objects.create(
                    name=product_line_type,
                    min_amount=2000000,
                    max_amount=40000000,
                    min_duration=3,
                    max_duration=60,
                    min_interest_rate=0.027,
                    max_interest_rate=0.04,
                    interest_rate_increment=0,
                    payment_frequency="Daily",
                    is_active=True,
                    is_product_exclusive=True,
                    is_initial=True,
                    min_origination_fee=0,
                    max_origination_fee=0,
                    code=product_line_code
                )
                ProductLine.objects.create(
                    product_line_code=product_line_code,
                    product_line_type=product_line_type,
                    min_amount=2000000,
                    max_amount=40000000,
                    min_duration=3,
                    max_duration=60,
                    min_interest_rate=0.027,
                    max_interest_rate=0.04,
                    payment_frequency='Daily',
                    product_profile=product_profile
                )
                raw_data = [
                    ['I.000-O.020-L.050-C1.000-C2.000-M', 0.00, 0.020, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.0225-L.050-C1.000-C2.000-M', 0.00, 0.0225, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.025-L.050-C1.000-C2.000-M', 0.00, 0.025, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.0275-L.050-C1.000-C2.000-M', 0.00, 0.0275, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.030-L.050-C1.000-C2.000-M', 0.00, 0.030, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.0325-L.050-C1.000-C2.000-M', 0.00, 0.0325, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.035-L.050-C1.000-C2.000-M', 0.00, 0.035, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.0375-L.050-C1.000-C2.000-M', 0.00, 0.0375, 0.05, 0, 0,
                     True, product_line_code, product_profile.id],
                    ['I.000-O.040-L.050-C1.000-C2.000-M', 0.00, 0.040, 0.05, 0, 0,
                     True, product_line_code, product_profile.id]
                ]
                keys = [
                    'product_name',
                    'interest_rate',
                    'origination_fee_pct',
                    'late_fee_pct',
                    'cashback_initial_pct',
                    'cashback_payment_pct',
                    'is_active',
                    'product_line_id',
                    'product_profile_id'
                ]

                for data in raw_data:
                    ProductLookup.objects.create(**dict(list(zip(keys, data))))
                workflow = Workflow.objects.get_or_none(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
                WorkflowStatusPath.objects.get_or_create(
                    status_previous=0,
                    status_next=100,
                    type="happy",
                    workflow=workflow
                )


class DistributorAdmin(JuloModelAdmin):
    form = DistributorForm

    list_display = (
        'id', 'name', 'partner', 'distributor_category', 'bank_account_name', 'bank_account_number',
        'bank_name',
    )
    list_select_related = (
        'partner', 'distributor_category'
    )
    search_fields = ['id', 'name']

    class Media(object):
        js = (
            'default/js/distributor_admin.js',
        )

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = DistributorForm
        form = super(DistributorAdmin, self).get_form(request, *args, **kwargs)
        form.base_fields['name_bank_validation'].widget = forms.HiddenInput(
            attrs={'readonly': 'readonly'})
        form.base_fields['user'].widget = forms.HiddenInput(
            attrs={'readonly': 'readonly'})
        form.base_fields['user'].required = False
        form_partner = form.base_fields['partner']
        form_partner.widget.can_add_related = False
        form_partner.widget.can_change_related = False
        form_partner.widget.can_delete_related = False
        return form

    def get_readonly_fields(self, request, obj=None):
        return ['distributor_xid']

    def get_actions(self, request):
        # Disable delete
        actions = super(DistributorAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_delete_permission(self, request, obj=None):
        if obj and obj.merchant_set.exists():
            return False
        return True

    def save_model(self, request, obj, form, change):
        if not obj.distributor_xid:
            obj.distributor_xid = XidLookup.get_new_xid()
        if not obj.user_id:
            obj.user_id = obj.partner.user.id
        super(DistributorAdmin, self).save_model(request, obj, form, change)


class MerchantApplicationReapplyIntervalAdmin(ModelAdmin):
    list_display = (
        'id', 'application_status', 'partner', 'interval_day'
    )
    search_fields = ['id', 'application_status__status_code', 'partner__name']

    def get_form(self, request, obj=None, **kwargs):
        form = super(MerchantApplicationReapplyIntervalAdmin, self).get_form(request, obj, **kwargs)
        for field_name in ('application_status', 'partner'):
            field = form.base_fields[field_name]
            field.widget.can_add_related = False
            field.widget.can_change_related = False
            field.widget.can_delete_related = False
        return form


class MerchantPaymentMethodLookupAdmin(ModelAdmin):
    form = MerchantPaymentMethodLookupAdminForm
    list_display = ('code', 'name', 'is_shown_mf')
    search_fields = ['code', 'name']
    ordering = ('code',)

    def get_queryset(self, request):
        payment_methods = PaymentMethodLookup.objects.\
            exclude(code__in=mf_excluded_payment_method_codes).order_by('name')
        payment_methods = payment_methods.exclude(name='PERMATA Bank')
        return payment_methods

    def get_actions(self, request):
        # Disable delete
        actions = super(MerchantPaymentMethodLookupAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if obj:
            payment_method_lookup = PaymentMethodLookup.objects.filter(code=obj.code)
            if payment_method_lookup:
                if PaymentMethodManager.get_payment_code_for_payment_method(obj.code):
                    payment_method_lookup.update(is_shown_mf=obj.is_shown_mf)
                    update_mf_payment_method_is_shown_mf_flag(obj.code, obj.is_shown_mf)
                else:
                    if not obj.is_shown_mf:
                        payment_method_lookup.update(is_shown_mf=obj.is_shown_mf)
                        update_mf_payment_method_is_shown_mf_flag(obj.code, obj.is_shown_mf)
                    else:
                        messages.set_level(request, messages.ERROR)
                        failure_msg = 'Sorry! not able to update the is_shown_mf flag. "%s %s" has ' \
                                      'no payment code exists.' % (obj.code, obj.name)
                        messages.error(request, failure_msg)

    def get_readonly_fields(self, request, obj=None):
        # when data is being edit, certain fields will be read_only
        if obj is None:
            return []
        else:
            return ["code", "name", "image_logo_url", "image_background_url", "bank_virtual_name"]


class PartnershipUserAdmin(admin.ModelAdmin):
    form = PartnershipUserAdminForm
    list_display = ('user', 'partner')
    search_fields = ['partner__name', 'user__username']
    ordering = ('id',)

    def save_model(self, request, obj, form, change):
        obj.user_id = obj.user.id
        obj.partner=obj.partner
        super().save_model(request, obj, form, change)


admin.site.register(BulkDisbursementSchedule, BulkDisbursementScheduleAdmin)
admin.site.register(MerchantBinaryCheck, MerchantBinaryCheckAdmin)
admin.site.register(
    MasterPartnerAffordabilityThreshold,
    MasterPartnerAffordabilityThresholdAdmin
)
admin.site.register(MerchantPartner, MerchantPartnerAdmin)
admin.site.register(Distributor, DistributorAdmin)
admin.site.register(MerchantApplicationReapplyInterval, MerchantApplicationReapplyIntervalAdmin)
admin.site.register(MerchantPaymentMethodLookup, MerchantPaymentMethodLookupAdmin)
admin.site.register(PartnershipUser, PartnershipUserAdmin)
