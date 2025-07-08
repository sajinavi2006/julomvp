from builtins import object
import os
import datetime
import logging
from builtins import str
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils.safestring import mark_safe
from juloserver.portal.core import functions
from juloserver.julo.utils import upload_file_to_oss
from juloserver.julo.models import (Image,
                                    LenderCustomerCriteria,
                                    LenderProductCriteria,
                                    Loan,
                                    LoanPurpose,
                                    Partner,
                                    FeatureSetting,
                                    LenderDisburseCounter)
from juloserver.portal.object.product_profile.constants import get_choices_list

from django.conf.urls import url
from django.core.urlresolvers import reverse
from django.utils.html import format_html
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from django.contrib import messages
from django.contrib import admin
from django.contrib.admin import ModelAdmin
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.services import reset_lender_disburse_counter
from juloserver.julo.statuses import LoanStatusCodes
from django import forms
from django.db import models
from django.db import transaction
from django.utils import timezone
from .models import (FeatureSettingProxy,
                     LoanAgreementTemplate,
                     LenderApproval,
                     LenderCurrent,
                     LenderDisbursementMethod,
                     LenderBalanceCurrent,
                     LenderTransaction,
                     LenderTransactionType,
                     LenderApprovalTransactionMethod,
                     LenderManualRepaymentTracking,
                     LenderTransactionMapping)
from .tasks import (
    insert_data_into_lender_balance_history,
    reset_all_lender_bucket,
    send_warning_message_low_balance_amount,
    calculate_available_balance)
from .constants import (BusinessType,
                        SourceOfFund,
                        SnapshotType,
                        LenderStatus,
                        BankAccountType,
                        LenderTransactionTypeConst,
                        LoanAgreementType,
                        LenderWithdrawalStatus)
from .services import deposit_internal_lender_balance
from .withdraw_view.services import new_lender_withdrawal
from .utils import add_thousand_separator
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


# Register your models here.
class FTMConfigurationForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSettingProxy
        fields = ('is_active', 'description', 'parameters')


class FTMConfigurationAdmin(ModelAdmin):
    form = FTMConfigurationForm
    list_display = (
        'id',
        'feature_name',
        'description',
        'is_active'
    )
    actions_on_bottom = True
    save_on_top = True

    def get_queryset(self, request):
        return self.model.objects.filter(category="followthemoney")

    def has_add_permission(self, request):
        # Nobody is allowed to add
        return False

    def has_delete_permission(self, request, obj=None):
        # Nobody is allowed to delete
        return False


class LenderLoanAgreementForm(forms.ModelForm):
    agreement_type = forms.ChoiceField(required=False, widget=forms.Select())

    class Meta(object):
        model = LoanAgreementTemplate
        fields = ('lender', 'agreement_type', 'body', 'is_active')

    def __init__(self, *args, **kwargs):
        super(LenderLoanAgreementForm, self).__init__(*args, **kwargs)

    def clean(self):
        existing_template = LoanAgreementTemplate.objects.filter(
            lender=self.cleaned_data['lender'], agreement_type=self.cleaned_data['agreement_type']
        ).exclude(pk=self.instance.pk).last()
        if existing_template:
            lender = existing_template.lender
            lender_name = lender.lender_name if lender else "Default"
            raise forms.ValidationError(
                "{} Lender already have template for {} with ID {}".format(
                    lender_name,
                    existing_template.agreement_type,
                    existing_template.id
                )
            )


class LenderLoanAgreementAdmin(ModelAdmin):
    list_display = (
        'id',
        'lender',
        'agreement_type',
        'is_active'
    )
    actions_on_bottom = True
    save_on_top = True

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = LenderLoanAgreementForm
        form = super(LenderLoanAgreementAdmin, self).get_form(request, *args, **kwargs)

        form.base_fields['agreement_type'].choices = LoanAgreementType.LIST_TYPES_UPDATE

        return form


class LenderApprovalTransactionMethodForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(LenderApprovalTransactionMethodForm, self).__init__(*args, **kwargs)
        self.fields['transaction_method'].widget.can_change_related = False
        self.fields['delay'].widget.attrs = []


class LenderApprovalTransactionMethodInline(admin.TabularInline):
    model = LenderApprovalTransactionMethod
    form = LenderApprovalTransactionMethodForm


class LenderApprovalForm(forms.ModelForm):
    delay = forms.TimeField(
        help_text="delay for each application before automatically approved<br/>format (hh:mm:ss)")
    expired_in = forms.TimeField(
        help_text="expiration time before application is automatically reassigned to other lender "
                  "(should be higher than Delay)<br/>format (hh:mm:ss)")

    def __init__(self, *args, **kwargs):
        super(LenderApprovalForm, self).__init__(*args, **kwargs)
        self.fields['start_date'].required = True
        self.fields['expired_in'].required = True
        self.fields['expired_start_time'].required = True
        self.fields['expired_end_time'].required = True

    class Meta(object):
        model = LenderApproval
        fields = (
            'partner',
            'is_auto',
            'delay',
            'start_date',
            'end_date',
            'is_endless',
            'expired_in',
            'expired_start_time',
            'expired_end_time',
        )

    def clean_delay(self):
        global_setting = FeatureSetting.objects.filter(
            is_active=True, feature_name=FeatureNameConst.AUTO_APPROVAL_GLOBAL_SETTING).last()

        if global_setting:
            time_format = {'hour': 0, 'minute': 0, 'second': 0}
            for key in list(time_format.keys()):
                if key in list(global_setting.parameters.keys()):
                    time_format[key] = global_setting.parameters[key]
                else:
                    time_format[key] = 0

            default_delay = datetime.time(**time_format)

            if self.cleaned_data['delay'] > default_delay:
                raise forms.ValidationError(
                    "The value is exceeded the maximum settings allowed {}".format(
                        default_delay.strftime("%H:%M:%S")
                    )
                )

        return self.cleaned_data['delay']

    def clean_expired_in(self):
        if 'delay' in list(self.cleaned_data.keys()):
            if self.cleaned_data['delay'] >= self.cleaned_data['expired_in']:
                raise forms.ValidationError("The value should be higher than Delay")

        return self.cleaned_data['expired_in']


class LenderApprovalAdmin(ModelAdmin):
    inlines = [
        LenderApprovalTransactionMethodInline,
    ]

    form = LenderApprovalForm
    list_display = (
        'partner',
        'is_auto',
        'get_delay',
        'get_delay_date',
        'is_endless',
        'get_expired',
        'get_expired_time',
    )
    actions_on_bottom = True
    save_on_top = True

    def save_model(self, request, obj, form, change):
        super(LenderApprovalAdmin, self).save_model(request, obj, form, change)
        today = timezone.now()

        if not obj.is_endless:
            if not obj.end_date or obj.end_date < today:
                obj.update_safely(is_auto=False)

        obj.refresh_from_db()
        if obj.is_auto:
            if today >= obj.start_date:
                reset_all_lender_bucket.apply_async((obj.partner_id,), eta=obj.start_date)

            else:
                reset_all_lender_bucket.delay(obj.partner_id)

    def get_delay(self, obj):
        return obj.delay.strftime("%H:%M:%S") if obj.delay else "-"

    get_delay.short_description = 'delay'

    def get_expired(self, obj):
        return obj.expired_in.strftime("%H:%M:%S") if obj.expired_in else "-"

    get_expired.short_description = 'expired'

    def get_delay_date(self, obj):
        return obj.formated_start_date + ' - ' + obj.formated_end_date

    get_delay_date.short_description = 'delay date'

    def get_expired_time(self, obj):
        return obj.formated_expired_start_time + ' - ' + obj.formated_expired_end_time

    get_expired_time.short_description = 'expired time'


class LenderDisbursementMethodForm(forms.ModelForm):
    product_lines = forms.ChoiceField(required=False, widget=forms.Select())

    def __init__(self, *args, **kwargs):
        super(LenderDisbursementMethodForm, self).__init__(*args, **kwargs)

    class Meta(object):
        model = LenderDisbursementMethod
        fields = ('partner', 'product_lines', 'is_bulk')


class LenderDisbursementMethodAdmin(ModelAdmin):
    list_display = (
        'id',
        'partner',
        'product_lines',
        'get_disbursement_method'
    )
    actions_on_bottom = True
    save_on_top = True

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = LenderDisbursementMethodForm
        form = super(LenderDisbursementMethodAdmin, self).get_form(request, *args, **kwargs)

        form.base_fields['product_lines'].choices = [
            ('bri', 'BRI'), ('loc', 'LOC'), ('grab', 'GRAB'), ('grabfood', 'GRABFOOD'),
            ('laku6', 'LAKU6'), ('icare', 'ICARE'), ('axiata', 'AXIATA'),
            ('pedemtl', 'PEDEMTL'), ('pedestl', 'PEDESTL'), ('ctl', 'CTL')]

        return form

    def get_disbursement_method(self, obj):
        return "Bulk" if obj.is_bulk else "Normal"
    get_disbursement_method.short_description = 'Disbursement Method'


class LenderCurrentForm(forms.ModelForm):
    lender_name = forms.CharField()
    lender_display_name = forms.CharField()
    company_name = forms.CharField()
    license_number = forms.CharField()
    lender_address = forms.CharField()
    lender_address_city = forms.CharField()
    lender_address_province = forms.CharField()
    poc_name = forms.CharField()
    poc_email = forms.EmailField()
    poc_position = forms.CharField()
    poc_phone = forms.CharField()
    pks_number = forms.CharField()
    addendum_number = forms.CharField()
    business_type = forms.CharField(widget=forms.Select(choices=BusinessType.CHOICE))
    source_of_fund = forms.CharField(widget=forms.Select(choices=SourceOfFund.CHOICE))
    lender_status = forms.CharField(widget=forms.Select(choices=LenderStatus.CHOICE))
    logo = forms.ImageField()

    # old value
    lender_status_old = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super(LenderCurrentForm, self).__init__(*args, **kwargs)
        fields = ['logo', 'lender_status_old']
        for field in fields:
            self.fields[field].required = False

    class Meta(object):
        model = LenderCurrent
        fields = (
            'id', 'user',
            'lender_name', 'lender_display_name', 'lender_status', 'lender_address',
            'poc_name', 'poc_email', 'poc_position', 'poc_phone',
            'pks_number', 'addendum_number', 'business_type', 'source_of_fund', 'service_fee',
            'insurance', 'company_name', 'license_number', 'lender_address', 'lender_address_city',
            'lender_address_province',
        )


class LenderCurrentAdmin(ModelAdmin):
    form = LenderCurrentForm
    list_display = (
        'lender_name',
        'lender_display_name',
        'lender_status_link',
        'pks_number',
        'addendum_number',
        'lender_balance_link',
        'matchmaking_criteria',
    )
    actions_on_bottom = True
    save_on_top = True
    readonly_fields = ("preview_image", )
    change_list_template = "custom_admin/lender_current_list.html"

    def get_urls(self):
        urls = super(LenderCurrentAdmin, self).get_urls()
        balance_urls = [
            url(r'^balance/configuration/$',
                self.admin_site.admin_view(self.lender_balance_configuration_page),
                name='followthemoney_lender_balance_configuration'),
            url(r'^balance/configuration/submit',
                self.admin_site.admin_view(self.submit_balance_configuration)),
            url(r'^(?P<lender_id>.+)/balance/$', self.admin_site.admin_view(self.process_balance),
                name='followthemoney_lender_balance'),
            url(r'^(?P<lender_id>.+)/balance/deposit/',
                self.admin_site.admin_view(self.deposit_balance)),
            url(r'^(?P<lender_id>.+)/balance/withdraw/',
                self.admin_site.admin_view(self.withdraw_balance)),
            url(r'^(?P<lender_id>.+)/status/$', self.admin_site.admin_view(self.lender_status_page),
                name='followthemoney_lender_status'),
            url(r'^(?P<lender_id>.+)/balance/reset/',
                self.admin_site.admin_view(self.reset_balance), name='followthemoney_lender_balance_reset'),
            url(r'^(?P<lender_id>.+)/status/change/',
                self.admin_site.admin_view(self.change_status)),
        ]
        return balance_urls + urls

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = LenderCurrentForm
        form = super(LenderCurrentAdmin, self).get_form(request, *args, **kwargs)
        if obj:
            form.base_fields['lender_status_old'].initial = obj.lender_status
        return form

    def save_model(self, request, obj, form, change):
        super(LenderCurrentAdmin, self).save_model(request, obj, form, change)

        old_status = request.POST['lender_status_old']
        if obj.lender_status == LenderStatus.ACTIVE and old_status != LenderStatus.ACTIVE:
            reset_lender_disburse_counter()

        if not change:
            lcc = LenderCustomerCriteria.objects.get_or_none(lender=obj)
            if not lcc:
                LenderCustomerCriteria.objects.create(lender=obj)

            lpc = LenderProductCriteria.objects.get_or_none(lender=obj)
            if not lpc:
                LenderProductCriteria.objects.create(lender=obj, type="Product List")

            ldc = LenderDisburseCounter.objects.get_or_none(lender=obj)
            if not ldc:
                LenderDisburseCounter.objects.create(lender=obj)

            lbc = LenderBalanceCurrent.objects.get_or_none(lender=obj)
            if not lbc:
                LenderBalanceCurrent.objects.create(lender=obj)

            partner = Partner.objects.get_or_none(user=obj.user)
            if not partner:
                partner = Partner.objects.create(
                    name=obj.lender_name,
                    email=obj.poc_email,
                    phone=obj.poc_phone,
                    type='lender',
                    is_active=False,
                    poc_name=obj.poc_name,
                    poc_email=obj.poc_email,
                    poc_phone=obj.poc_phone,
                    source_of_fund=obj.source_of_fund,
                    company_name=obj.lender_name,
                    company_address=obj.lender_address,
                    business_type=obj.business_type,
                    user=obj.user,
                    agreement_letter_number=obj.pks_number,
                )

        if request.FILES and request.FILES['logo']:
            logo = request.FILES['logo']
            _, file_extension = os.path.splitext(logo.name)

            remote_path = 'lender_{}/logo{}'.format(obj.pk, file_extension)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'lender_logo'
            image.url = remote_path
            image.save()

            file = functions.upload_handle_media(logo, "lender/logo")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )

    def preview_image(self, obj):
        return mark_safe('<img src="{}" width="300" />'.format(obj.logo))

    def lender_status_link(self, obj):
        return format_html(
            '<a href="{}"><strong>{}</strong></a>',
            reverse('admin:followthemoney_lender_status', args=[obj.pk]), obj.lender_status
        )
    lender_status_link.short_description = 'Lender Status'
    lender_status_link.allow_tags = True

    def lender_balance_link(self, obj):
        criteria_links = []
        link_html = ""

        if obj.lender_name in self.model.manual_lender_list():
            link_html = '&nbsp;<a href="{}"><strong>Balance</strong></a>&nbsp;'
            criteria_links.append(reverse('admin:followthemoney_lender_balance', args=[obj.pk]))

        return format_html(link_html, *criteria_links)
    lender_balance_link.short_description = 'Lender Balance'
    lender_balance_link.allow_tags = True

    def _general_response_lender_balance(self, request, lender_id, message, level=messages.SUCCESS):
        self.message_user(request, message, level=level)
        return HttpResponseRedirect(
            reverse('admin:followthemoney_lender_balance', args=[lender_id]))

    def reset_balance(self, request, lender_id):
        general_response = self._general_response_lender_balance
        list_page = HttpResponseRedirect(
            reverse('admin:followthemoney_lendercurrent_changelist'))
        if request.method != 'POST':
            return general_response(request, lender_id, 'Unauthorized', messages.ERROR)

        try:
            with transaction.atomic():
                lender = LenderCurrent.objects.get_or_none(pk=lender_id)
                if not lender:
                    self.message_user(request, "Lender not found", level=messages.ERROR)
                    return list_page

                if lender.lender_name not in LenderCurrent.manual_lender_list():
                    self.message_user(
                        request, f"Lender {lender.lender_name} is not eligible for reset",
                        level=messages.ERROR)
                    return list_page

                # check if OneToOneField exists
                lender_balance = getattr(lender, 'lenderbalancecurrent', None)
                if not lender_balance:
                    return general_response(
                        request, lender_id, "Lender doesn't have a balance", messages.ERROR)

                if lender.lender_status != LenderStatus.INACTIVE:
                    self.message_user(
                        request, f"Lender is not inactive, please inactivate first",
                        level=messages.ERROR)
                    return list_page

                ongoing_loans = Loan.objects.filter(
                    lender_id=lender_id,
                    loan_status_id__in=[
                        LoanStatusCodes.LENDER_APPROVAL,
                        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                        LoanStatusCodes.FUND_DISBURSAL_FAILED,
                    ]
                ).exists()

                if ongoing_loans:
                    error = "There are still ongoing loans (statuses 211, 212, 218), " + \
                        "please wait for a bit and retry later"
                    return general_response(
                        request, lender_id, error, messages.ERROR)

                # finally, reset balance to zero
                lender_balance.available_balance = 0
                lender_balance.save(update_fields=['available_balance'])

                # create records
                transaction_type = LenderTransactionType.objects.get_or_none(
                    transaction_type=LenderTransactionTypeConst.BALANCE_ADJUSTMENT,
                )
                lender_transaction = LenderTransaction.objects.create(
                    lender=lender,
                    transaction_type=transaction_type,
                    lender_balance_current=lender.lenderbalancecurrent,
                    transaction_description=f'balance reset by user: {request.user.id}',
                )
                LenderTransactionMapping.objects.create(
                    lender_transaction=lender_transaction,
                )
                insert_data_into_lender_balance_history(
                    lender_balance=lender_balance,
                    pending_withdrawal=0,
                    snapshot_type=SnapshotType.RESET_BALANCE,
                    remaining_balance=0,
                )
        except Exception as e:
            get_julo_sentry_client().captureException()
            return general_response(request, lender_id, str(e), messages.ERROR)

        return general_response(request, lender_id, "Reset Balance Success!")

    def deposit_balance(self, request, lender_id):
        general_response = self._general_response_lender_balance
        if request.method != 'POST':
            return general_response(request, lender_id, 'Unauthorized', messages.ERROR)
        try:
            with transaction.atomic():
                lender = LenderCurrent.objects.get_or_none(pk=lender_id)
                if not lender:
                    self.message_user(request, "Lender not found", level=messages.ERROR)
                    return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

                if lender.lender_name not in LenderCurrent.manual_lender_list():
                    self.message_user(
                        request, "Unable set balance for %s" % lender.lender_name, level=messages.ERROR)
                    return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

                lender_balance = lender.lenderbalancecurrent
                if not lender_balance:
                    return general_response(
                        request, lender_id, "Lender doesn't have balance", messages.ERROR)

                maximum_repayment_amount = LenderManualRepaymentTracking.objects.filter(
                    lender=lender).aggregate(total=models.Sum('amount'))['total'] or 0

                is_repayment = request.POST['transaction_type'] == LenderTransactionTypeConst.REPAYMENT
                if int(request.POST['deposit_amount']) > maximum_repayment_amount and is_repayment:
                    return general_response(
                        request, lender_id,
                        "Maximum repayment amount updated, please try again!", messages.ERROR)

                deposit_internal_lender_balance(
                    lender, int(request.POST['deposit_amount']), request.POST['transaction_type'])

        except Exception as e:
            sentry_client.captureException()
            logger.error({
                'action': 'deposit_balance',
                'errors': str(e)
            })
            return general_response(
                request, lender_id, 'Failed deposit balance - %s' % str(e), messages.ERROR)

        return general_response(
            request, lender_id, 'Success %s balance' % request.POST['transaction_type'])

    def withdraw_balance(self, request, lender_id):
        general_response = self._general_response_lender_balance

        if request.method != 'POST':
            return general_response(request, lender_id, 'Unauthorized', messages.ERROR)

        lender = LenderCurrent.objects.get_or_none(pk=lender_id)
        if not lender:
            self.message_user(request, "Lender not found", level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        if lender.lender_name not in LenderCurrent.manual_lender_list():
            self.message_user(
                request, "Unable set balance for %s" % lender.lender_name, level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        lender_balance = lender.lenderbalancecurrent
        if not lender_balance:
            return general_response(
                request, lender_id, "Lender doesn't have balance", messages.ERROR)

        new_balance = lender_balance.available_balance - int(request.POST['withdrawal_amount'])
        if new_balance < 0:
            return general_response(
                request, lender_id, 'Insufficient balance', messages.ERROR)

        try:
            with transaction.atomic():
                bank_account = lender.lenderbankaccount_set.filter(
                    bank_account_type=BankAccountType.WITHDRAWAL).first()

                if not bank_account:
                    return general_response(
                        request, lender_id, 'Bank account not found', messages.ERROR)

                lender_withdrawal = new_lender_withdrawal(
                    lender, int(request.POST['withdrawal_amount']), bank_account, is_return=True,
                    is_delay=False)
                lender_withdrawal.update_safely(
                    status=LenderWithdrawalStatus.COMPLETED,
                    reason="%s withdrawal" % lender.lender_name)
                transaction_type = LenderTransactionType.objects.get_or_none(
                    transaction_type=LenderTransactionTypeConst.WITHDRAWAL
                )
                lender_transaction = LenderTransaction.objects.create(
                    lender=lender_withdrawal.lender,
                    transaction_type=transaction_type,
                    transaction_amount=lender_withdrawal.withdrawal_amount,
                    lender_balance_current=lender_withdrawal.lender.lenderbalancecurrent
                )
                LenderTransactionMapping.objects.filter(lender_withdrawal=lender_withdrawal).update(
                    lender_transaction=lender_transaction
                )
                calculate_available_balance(
                    lender_withdrawal.lender.lenderbalancecurrent.id,
                    SnapshotType.TRANSACTION,
                    withdrawal_amount=-lender_withdrawal.withdrawal_amount,
                    is_delay=False
                )

                if lender.lender_name in LenderCurrent.escrow_lender_list():
                    send_warning_message_low_balance_amount.delay(lender.lender_name)

                if lender.lender_name in LenderCurrent.bss_lender_list():
                    jtp = LenderCurrent.objects.filter(lender_name="jtp", lender_status="active").last()
                    if jtp and jtp.lenderbalancecurrent:
                        calculate_available_balance.delay(
                            jtp.lenderbalancecurrent.id, SnapshotType.TRANSACTION)

        except Exception as e:
            sentry_client.captureException()
            logger.error({
                'action': 'withdraw_balance',
                'errors': str(e)
            })
            return general_response(
                request, lender_id, 'Failed withdraw balance - %s' % str(e), messages.ERROR)

        return general_response(request, lender_id, 'Success withdraw balance')

    def process_balance(self, request, lender_id):
        lender = LenderCurrent.objects.get_or_none(pk=lender_id)
        if not lender:
            self.message_user(request, "Lender not found", level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        if lender.lender_name not in LenderCurrent.manual_lender_list():
            self.message_user(
                request, "Unable set balance for %s" % lender.lender_name, level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        if not hasattr(lender, 'lenderbalancecurrent'):
            self.message_user(
                request, "Balance not found for %s" % lender.lender_name, level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        context = self.admin_site.each_context(request)
        context['opts'] = self.model._meta
        context['title'] = "{} ({}) Balance".format(
            lender.lender_display_name, lender.lender_name
        )

        lender_bank_account = lender.lenderbankaccount_set
        context['deposit_va'] = lender_bank_account.filter(
            bank_account_type="deposit_va", bank_account_status="active"
        ).last()
        context['withdrawal'] = lender_bank_account.filter(
            bank_account_type="withdrawal", bank_account_status="active"
        ).last()

        context['available_balance'] = add_thousand_separator(
            str(lender.lenderbalancecurrent.available_balance)) or 0
        context['transactions'] = [
            LenderTransactionTypeConst.DEPOSIT,
            LenderTransactionTypeConst.REPAYMENT,
        ]
        context['total_repayment'] = LenderManualRepaymentTracking.objects.filter(
            lender=lender).aggregate(total=models.Sum('amount'))['total'] or 0
        context['total_repayment_formatted'] = add_thousand_separator(
            str(context['total_repayment']))

        return TemplateResponse(request, 'custom_admin/lender_balance.html', context)

    def lender_status_page(self, request, lender_id):
        lender = LenderCurrent.objects.get_or_none(pk=lender_id)
        if not lender:
            self.message_user(request, "Lender not found", level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        context = self.admin_site.each_context(request)
        context['opts'] = self.model._meta
        context['title'] = "%s (%s) Status" % (lender.lender_display_name, lender.lender_name)
        context['lender_status'] = lender.lender_status
        context['status_list'] = LenderStatus.LIST
        return TemplateResponse(request, 'custom_admin/lender_status.html', context)

    def change_status(self, request, lender_id):
        def general_response(self, request, lender_id, message, level=messages.SUCCESS):
            self.message_user(request, message, level=level)
            url = reverse('admin:followthemoney_lender_status', args=[lender_id])
            if level == messages.SUCCESS:
                url = reverse('admin:followthemoney_lendercurrent_changelist')

            return HttpResponseRedirect(url)

        if request.method != 'POST':
            return general_response(self, request, lender_id, 'Unauthorized', messages.ERROR)

        lender = LenderCurrent.objects.get_or_none(pk=lender_id)
        if not lender:
            self.message_user(request, "Lender not found", level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

        try:
            with transaction.atomic():
                lender_status = request.POST['lender_status']
                lender.update_safely(lender_status=lender_status)

                old_status = request.POST['old_lender_status']
                if lender_status == LenderStatus.ACTIVE and old_status != LenderStatus.ACTIVE:
                    reset_lender_disburse_counter()

        except Exception as e:
            sentry_client.captureException()
            logger.error({
                'action': 'lender_status_change',
                'errors': str(e)
            })
            return general_response(
                self, request, lender_id,
                'Failed change lender_status - %s' % str(e), messages.ERROR
            )

        return general_response(
            self, request, lender_id,
            'Success Change %s Status to %s' % (lender.lender_name, lender.lender_status)
        )

    def lender_balance_configuration_page(self, request):
        context = self.admin_site.each_context(request)
        context['opts'] = self.model._meta
        context['title'] = "Lender Balance Configuration"
        context['lenders'] = LenderCurrent.objects.order_by('cdate')
        return TemplateResponse(request, 'custom_admin/lender_balance_configuration.html', context)

    @transaction.atomic
    def submit_balance_configuration(self, request):
        def general_response(self, request, message, level=messages.SUCCESS):
            self.message_user(request, message, level=level)
            url = reverse('admin:followthemoney_lender_balance_configuration')
            if level == messages.SUCCESS:
                url = reverse('admin:followthemoney_lendercurrent_changelist')

            return HttpResponseRedirect(url)

        if request.method != 'POST':
            return general_response(self, request, 'Unauthorized', messages.ERROR)

        try:
            lenders = LenderCurrent.objects.order_by('cdate')
            for lender in lenders:
                fields = [
                    "is_master_lender",
                    "is_manual_lender_balance",
                    "is_low_balance_notification",
                    "is_xfers_lender_flow",
                    "is_bss_balance_include",
                    "is_only_escrow_balance",
                    "minimum_balance",
                    "xfers_token",
                    "is_pre_fund_channeling_flow",
                ]
                updated_dict = dict()
                for field in fields:
                    key = '%s_%s' % (lender.id, field)
                    value = False
                    if key in request.POST:
                        value = request.POST[key]
                    elif field == "minimum_balance":
                        value = 0
                    elif field == "xfers_token":
                        value = lender.xfers_token
                    updated_dict[field] = value
                lender.update_safely(**updated_dict)

        except Exception as e:
            sentry_client.captureException()
            logger.error({
                'action': 'lender_status_change',
                'errors': str(e)
            })
            return general_response(
                self, request, 'Failed change lender_status - %s' % str(e), messages.ERROR
            )

        return general_response(self, request, 'Success Change Lender Balance Configuration')

    def matchmaking_criteria(self, obj):
        link_html = ""
        criteria_links = []

        criteria = dict(customer=LenderCustomerCriteria, product=LenderProductCriteria)
        for label, model in criteria.items():
            model_data = model.objects.filter(lender=obj).last()
            if not model_data:
                model_data = model.objects.create(lender=obj)

            if link_html != "":
                link_html += "|"
            link_html += '&nbsp;<a href="{}"><strong>{}</strong></a>&nbsp;'
            content_type = ContentType.objects.get_for_model(model)
            criteria_links.append(
                reverse(
                    "admin:%s_%s_change" % (content_type.app_label, content_type.model),
                    args=(model_data.id,)
                )
            )
            criteria_links.append(label.title())
        return format_html(link_html, *criteria_links)
    matchmaking_criteria.short_description = 'Matchmaking Criteria'
    matchmaking_criteria.allow_tags = True


class LenderCustomerCriteriaForm(forms.ModelForm):
    credit_score = forms.MultipleChoiceField()
    loan_purpose = forms.MultipleChoiceField()
    min_age = forms.IntegerField(
        widget=forms.NumberInput(attrs={'min': '0', 'max': '70', 'step': '1'}))
    max_age = forms.IntegerField(
        widget=forms.NumberInput(attrs={'min': '0', 'max': '70', 'step': '1'}))
    job_type = forms.MultipleChoiceField()
    job_industry = forms.MultipleChoiceField()
    company_name = forms.CharField(label="Customer Company Name", widget=forms.Textarea)

    # old value
    credit_score_old = forms.CharField(widget=forms.HiddenInput())
    loan_purpose_old = forms.CharField(widget=forms.HiddenInput())
    min_age_old = forms.CharField(widget=forms.HiddenInput())
    max_age_old = forms.CharField(widget=forms.HiddenInput())
    job_type_old = forms.CharField(widget=forms.HiddenInput())
    job_industry_old = forms.CharField(widget=forms.HiddenInput())
    company_name_old = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super(LenderCustomerCriteriaForm, self).__init__(*args, **kwargs)
        fields = [
            'loan_purpose', 'min_age', 'max_age', 'job_type', 'job_industry', 'credit_score',
            'company_name', 'credit_score_old', 'loan_purpose_old', 'min_age_old', 'max_age_old',
            'job_type_old', 'job_industry_old', 'company_name_old'
        ]
        for field in fields:
            self.fields[field].required = False

    class Meta(object):
        model = LenderCustomerCriteria
        fields = (
            'min_age', 'max_age', 'min_income', 'max_income', 'job_type', 'job_industry',
            'credit_score', 'loan_purpose', 'company_name',
        )


class LenderCustomerCriteriaAdmin(ModelAdmin):
    form = LenderCustomerCriteriaForm
    list_display = ('id', 'lender')
    actions_on_bottom = True
    save_on_top = True
    change_form_template = "custom_admin/lender_criteria.html"

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def response_change(self, request, obj):
        super(LenderCustomerCriteriaAdmin, self).response_change(request, obj)
        return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

    def message_user(
            self, request, message, level=messages.INFO, extra_tags='', fail_silently=False):
        pass

    def change_view(self, request, object_id, extra_context=None):
        obj = self.model.objects.get(pk=object_id)
        if obj:
            extra_context = {
                'title': 'Change lender customer criteria for {}'.format(obj.lender.lender_name),
                'show_save_and_continue': False,
            }
        return super(LenderCustomerCriteriaAdmin, self).change_view(
            request, object_id, extra_context=extra_context)

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = LenderCustomerCriteriaForm
        form = super(LenderCustomerCriteriaAdmin, self).get_form(request, *args, **kwargs)

        fields = ['credit_score', 'job_type', 'job_industry']
        for field in fields:
            form.base_fields[field].choices = get_choices_list(field)

        form.base_fields['loan_purpose'].choices = tuple(
            LoanPurpose.objects.values_list('purpose', 'purpose')
        )

        if obj:
            fields = [
                'credit_score', 'loan_purpose', 'min_age', 'max_age', 'job_type', 'job_industry']
            if obj.company_name:
                companies = ", ".join(obj.company_name)
                field = 'company_name'
                form.base_fields[field].initial = companies
                form.base_fields['{}_old'.format(field)].initial = companies

            for field in fields:
                init_data = eval("obj.{}".format(field))

                form.base_fields[field].initial = init_data
                form.base_fields['{}_old'.format(field)].initial = init_data

                if init_data and field not in ('min_age', 'max_age'):
                    form.base_fields['{}_old'.format(field)].initial = ", ".join(init_data)
        return form

    def save_model(self, request, obj, form, change):
        companies = [comp.strip() for comp in request.POST['company_name'].split(",")]
        if request.POST['company_name'] == '':
            companies = None
        customer_criteria = dict(
            credit_score=request.POST.getlist('credit_score') if len(
                request.POST.getlist('credit_score')) > 0 else None,
            loan_purpose=request.POST.getlist('loan_purpose') if len(
                request.POST.getlist('loan_purpose')) > 0 else None,
            min_age=None if request.POST['min_age'] == '' else request.POST['min_age'],
            max_age=None if request.POST['max_age'] == '' else request.POST['max_age'],
            job_type=request.POST.getlist('job_type') if len(
                request.POST.getlist('job_type')) > 0 else None,
            job_industry=request.POST.getlist('job_industry') if len(
                request.POST.getlist('job_industry')) > 0 else None,
            company_name=companies
        )

        obj.update_safely(**customer_criteria)
        fields = [
            'credit_score', 'loan_purpose', 'min_age',
            'max_age', 'job_type', 'job_industry', 'company_name'
        ]
        for field in fields:
            old_field = '{}_old'.format(field)
            data = eval('obj.{}'.format(field))
            post_data = request.POST[old_field]
            if field not in ('max_age', 'min_age'):
                if data:
                    data = set(data)

                if post_data:
                    post_data = set([comp.strip() for comp in post_data.split(",")])

            if data != post_data:
                reset_lender_disburse_counter()
                break

        messages.success(
            request, 'The lender customer criteria for "{}" was changed successfully.'.format(
                obj.lender.lender_name
            )
        )
        super(LenderCustomerCriteriaAdmin, self).save_model(request, obj, form, change)


class LenderProductCriteriaForm(forms.ModelForm):
    product_list = forms.MultipleChoiceField()
    min_duration = forms.IntegerField(
        widget=forms.NumberInput(attrs={'min': '1', 'max': '12', 'step': '1'})
    )
    max_duration = forms.IntegerField(
        widget=forms.NumberInput(attrs={'min': '1', 'max': '12', 'step': '1'})
    )
    product_profile_list = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super(LenderProductCriteriaForm, self).__init__(*args, **kwargs)
        self.fields["product_list"].required = False
        self.fields["product_profile_list"].required = False
        self.fields["min_duration"].required = False
        self.fields["max_duration"].required = False

    class Meta(object):
        model = LenderProductCriteria
        fields = ('product_profile_list', 'min_duration', 'max_duration')


class LenderProductCriteriaAdmin(ModelAdmin):
    form = LenderProductCriteriaForm
    list_display = ('id', 'lender')
    actions_on_bottom = True
    save_on_top = True
    change_form_template = "custom_admin/lender_criteria.html"

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def response_change(self, request, obj):
        super(LenderProductCriteriaAdmin, self).response_change(request, obj)
        return HttpResponseRedirect(reverse('admin:followthemoney_lendercurrent_changelist'))

    def message_user(
            self, request, message, level=messages.INFO, extra_tags='', fail_silently=False):
        pass

    def change_view(self, request, object_id, extra_context=None):
        obj = self.model.objects.get(pk=object_id)
        if obj:
            extra_context = {
                'title': 'Change lender product criteria for {}'.format(obj.lender.lender_name),
                'show_save_and_continue': False,
            }
        return super(LenderProductCriteriaAdmin, self).change_view(
            request, object_id, extra_context=extra_context)

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = LenderProductCriteriaForm
        form = super(LenderProductCriteriaAdmin, self).get_form(request, *args, **kwargs)

        form.base_fields['product_list'].choices = get_choices_list('product_list')
        if obj:
            form.base_fields['product_list'].initial = obj.product_profile_list
        return form

    def save_model(self, request, obj, form, change):
        product_criteria = dict(
            product_profile_list=request.POST.getlist('product_list'),
            type="Product List",
            min_duration=request.POST.get('min_duration'),
            max_duration=request.POST.get('max_duration'),
        )
        obj.update_safely(**product_criteria)
        messages.success(
            request, 'The lender product criteria for "{}" was changed successfully.'.format(
                obj.lender.lender_name
            )
        )
        super(LenderProductCriteriaAdmin, self).save_model(request, obj, form, change)


admin.site.register(LoanAgreementTemplate, LenderLoanAgreementAdmin)
admin.site.register(FeatureSettingProxy, FTMConfigurationAdmin)
admin.site.register(LenderApproval, LenderApprovalAdmin)
admin.site.register(LenderDisbursementMethod, LenderDisbursementMethodAdmin)
admin.site.register(LenderCurrent, LenderCurrentAdmin)
admin.site.register(LenderCustomerCriteria, LenderCustomerCriteriaAdmin)
admin.site.register(LenderProductCriteria, LenderProductCriteriaAdmin)
