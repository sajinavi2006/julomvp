from __future__ import unicode_literals

import json

from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from django import forms
from django.forms.widgets import (
    TextInput,
    RadioSelect,
    Select,
)

from juloserver.channeling_loan.constants import (
    ChannelingStatusConst,
    ARSwitchingConst,
    ChannelingConst,
)
from juloserver.channeling_loan.models import (
    LenderOspTransaction,
    LenderOspAccount,
    LenderLoanLedger,
)
from juloserver.followthemoney.models import LenderCurrent
from juloserver.channeling_loan.services.task_services import get_ar_switching_lender_list
from juloserver.julo.models import FeatureSetting

PERIOD_CHOICES = ((True, _('Hari ini')), (False, _('Bebas')))


class HorizontalRadioRenderer(forms.RadioSelect.renderer):
    def render(self):
        return mark_safe(u'&nbsp;&nbsp;&nbsp;\n'.join([u'%s\n' % w for w in self]))


class ChannelingLoanForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super(ChannelingLoanForm, self).__init__(*args, **kwargs)

    datetime_range = forms.CharField(
        required=False, widget=TextInput(
            attrs={
                'class': 'form-control input-daterange-timepicker',
                'name': "daterange",
            }
        )
    )
    channeling_status = forms.ChoiceField(
        required=False, choices=ChannelingStatusConst.TEMPLATE_CHOICES, widget=Select(
            attrs={'class': 'form-control', }
        )
    )
    status_now = forms.ChoiceField(
        required=False, choices=PERIOD_CHOICES,
        widget=RadioSelect(renderer=HorizontalRadioRenderer)
    )


class UploadFileForm(forms.Form):
    file_field = forms.FileField(label="File Upload", required=False)
    url_field = forms.CharField(label="URL Upload", required=False)

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('file_field')
        url = cleaned_data.get('url_field')
        if file and url:
            msg = 'Please choose fill between file and url'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)
        if not (file or url):
            msg = 'Should filled file'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)
        elif file and file.content_type not in ARSwitchingConst.ALLOWED_CONTENT_TYPE:
            self.add_error('file_field', 'File extension should be .csv / .xls / .xlsx')


class RepaymentFileForm(forms.Form):
    repayment_file_field = forms.FileField(label="Repayment File Upload")


class ReconciliationFileForm(forms.Form):
    reconciliation_file_field = forms.FileField(label="Reconciliation File Upload")


class ARSwitcherForm(forms.Form):
    lender_name = forms.ChoiceField(
        required=True,
        choices=(),
        widget=Select(attrs={
            'class': 'form-control',
        }),
        error_messages={'required': 'Please select Lender destination'}
    )
    file_field = forms.FileField(
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
            }
        ),
        label="File Upload",
        required=False,
        error_messages={'required': 'Please choose the CSV file'}
    )
    url_field = forms.URLField(
        widget=forms.URLInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'URL file'
            }
        ),
        label="URL path",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['lender_name'].choices = (
            (('', 'Select Lender'),) + tuple(get_ar_switching_lender_list())
        )

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('file_field')
        url = cleaned_data.get('url_field')
        lender_name = cleaned_data.get('lender_name')

        if file and url:
            msg = 'Should choose file or URL'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)

        if not (file or url):
            msg = 'Should filled file or URL'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)

        if file and file.content_type not in ARSwitchingConst.ALLOWED_CONTENT_TYPE:
            self.add_error('file_field', 'File extension should be .csv / .xls / .xlsx')

        if lender_name:
            lender_destination = LenderCurrent.objects.filter(lender_name=lender_name).last()
            if not lender_destination:
                self.add_error('lender_name', 'Lender destination not exist')


class WriteOffLoanForm(forms.Form):
    file_field = forms.FileField(
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
            }
        ),
        label="File Upload",
        required=False,
        error_messages={'required': 'Please choose the CSV file'},
    )
    url_field = forms.URLField(
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'URL file'}),
        label="URL path",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get('file_field')
        url = cleaned_data.get('url_field')

        if file and url:
            # both file and URL inputed
            msg = 'Should choose file or URL'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)
        elif not file and not url:
            # no file / URL inputed
            msg = 'Should filled file or URL'
            self.add_error('file_field', msg)
            self.add_error('url_field', msg)
        elif file and file.content_type not in ARSwitchingConst.ALLOWED_CONTENT_TYPE:
            # file format wring
            self.add_error('file_field', 'File extension should be .csv / .xls / .xlsx')


class LenderOspTransactionForm(forms.ModelForm):

    class Meta:
        model = LenderOspTransaction
        fields = ['lender_osp_account', 'balance_amount']

    def clean_balance_amount(self):
        balance_amount = self.cleaned_data["balance_amount"]
        balance_amount = balance_amount.replace(".", "").replace(",", "")
        return int(balance_amount)

    def __init__(self, *args, **kwargs):
        super(LenderOspTransactionForm, self).__init__(*args, **kwargs)
        if self.instance.id:
            self.fields['lender_osp_account'].disabled = True
            self.fields['balance_amount'].disabled = True

    lender_osp_account = forms.ModelChoiceField(
        queryset=LenderOspAccount.objects.filter(),
        required=True,
        label="Lender OSP Account"
    )
    balance_amount = forms.CharField(
        required=True,
        label="Balance Amount"
    )


class LenderLoanLedgerForm(forms.ModelForm):
    class Meta:
        model = LenderLoanLedger
        fields = ['application_id', 'loan_xid', 'osp_amount', 'tag_type']


class LenderOspAccountForm(forms.ModelForm):

    class Meta:
        model = LenderOspAccount
        fields = [
            'lender_account_name',
            'balance_amount',
            "fund_by_lender",
            "fund_by_julo",
            "total_outstanding_principal",
            "priority"
        ]

    def clean_positive_value(self, field_name):
        value = self.cleaned_data.get(field_name)
        value = value.replace(".", "").replace(",", "")
        value = int(value)
        return value

    def clean_balance_amount(self):
        return self.clean_positive_value('balance_amount')

    def clean_fund_by_lender(self):
        return self.clean_positive_value('fund_by_lender')

    def clean_fund_by_julo(self):
        return self.clean_positive_value('fund_by_julo')

    def clean_total_outstanding_principal(self):
        return self.clean_positive_value('total_outstanding_principal')

    def __init__(self, *args, **kwargs):
        super(LenderOspAccountForm, self).__init__(*args, **kwargs)
        if self.instance.id:
            self.fields['lender_account_name'].disabled = True
            self.fields['balance_amount'].disabled = True
            self.fields['fund_by_lender'].disabled = True
            self.fields['fund_by_julo'].disabled = True
            self.fields['total_outstanding_principal'].disabled = True

    lender_account_name = forms.CharField(
        required=True,
        label="Lender Account Name"
    )

    balance_amount = forms.CharField(
        required=True,
        label="Balance Amount"
    )

    fund_by_lender = forms.CharField(
        required=True,
        label="Fund by Lender"
    )

    fund_by_julo = forms.CharField(
        required=True,
        label="Fund by Julo"
    )

    total_outstanding_principal = forms.CharField(
        required=True,
        label="Total Outstanding Principal"
    )

    priority = forms.CharField(
        required=True,
        label="Priority"
    )


class ChannelingLoanAdminForm(forms.ModelForm):
    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    form_data = forms.CharField(widget=forms.HiddenInput, required=False)

    vendor_name = forms.ChoiceField(
        choices=ChannelingConst.CHOICES, widget=forms.Select(attrs={'class': 'vendor_choices'})
    )
    vendor_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )

    general_channeling_type = forms.ChoiceField(
        choices=(
            (ChannelingConst.API_CHANNELING_TYPE, ChannelingConst.API_CHANNELING_TYPE),
            (ChannelingConst.MANUAL_CHANNELING_TYPE, ChannelingConst.MANUAL_CHANNELING_TYPE),
            (ChannelingConst.HYBRID_CHANNELING_TYPE, ChannelingConst.HYBRID_CHANNELING_TYPE),
        ),
        widget=forms.Select(attrs={'class': 'channeling_choices'}),
        label="Channeling Type",
    )
    general_lender_name = forms.CharField(required=False, label="Lender name")
    general_buyback_lender_name = forms.CharField(required=False, label="Buyback lender name")
    general_exclude_lender_name = forms.CharField(required=False, label="Exclude lender name")
    general_interest_percentage = forms.FloatField(required=False, label="Interest percentage")
    general_risk_premium_percentage = forms.FloatField(
        required=False, label="Risk Premium percentage"
    )
    general_days_in_year = forms.IntegerField(required=False, label="Days in year")

    rac_tenor = forms.ChoiceField(
        choices=(
            ("Daily", "Daily"),
            ("Monthly", "Monthly"),
        ),
        widget=forms.Select(attrs={'class': 'tenor_choices'}),
        label="Tenor type",
    )
    rac_min_tenor = forms.IntegerField(required=False, label="Min tenor")
    rac_max_tenor = forms.IntegerField(required=False, label="Max tenor")
    rac_min_loan = forms.IntegerField(required=False, label="Min loan")
    rac_max_loan = forms.IntegerField(required=False, label="Max loan")
    rac_min_os_amount_ftc = forms.IntegerField(required=False, label="Min outstanding amount (FTC)")
    rac_max_os_amount_ftc = forms.IntegerField(required=False, label="Max outstanding amount (FTC)")
    rac_min_os_amount_repeat = forms.IntegerField(
        required=False, label="Min outstanding amount (repeat)"
    )
    rac_max_os_amount_repeat = forms.IntegerField(
        required=False, label="Max outstanding amount (repeat)"
    )
    rac_min_age = forms.IntegerField(required=False, label="Min age")
    rac_max_age = forms.IntegerField(required=False, label="Max age")
    rac_min_income = forms.IntegerField(required=False, label="Min income")
    rac_max_ratio = forms.FloatField(required=False, label="Max ratio")
    rac_job_type = forms.CharField(required=False, label="Job type")
    rac_min_worktime = forms.IntegerField(required=False, label="Min worktime")
    rac_transaction_method = forms.CharField(required=False, label="Transaction Method")
    rac_income_prove = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Need income prove?"
    )
    rac_mother_name_fullname = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Mother name is fullname?"
    )
    rac_has_ktp_or_selfie = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Need KTP or Selfie?"
    )
    rac_mother_maiden_name = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Validate mother maiden name?"
    )
    rac_include_loan_adjusted = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Keep channeling if adjusted?"
    )
    rac_dukcapil_check = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Dukcapil check?"
    )
    rac_version = forms.IntegerField(required=False, label="Version")

    cutoff_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    cutoff_channel_after_cutoff = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Channel after cutoff"
    )
    cutoff_opening_time = forms.CharField(required=False, label="Opening time")
    cutoff_cutoff_time = forms.CharField(required=False, label="Cutoff time")
    cutoff_inactive_day = forms.CharField(required=False, label="Inactive days")
    cutoff_inactive_dates = forms.CharField(required=False, label="Inactive dates")
    cutoff_limit = forms.IntegerField(required=False, label="Limit")

    due_date_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    due_date_exclusion_day = forms.CharField(required=False, label="Exclusion date")

    credit_score_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    credit_score_score = forms.CharField(required=False, label="Credit score")

    b_score_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    b_score_min_b_score = forms.FloatField(required=False, label="Min B score")
    b_score_max_b_score = forms.FloatField(required=False, label="Max B score")

    whitelist_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    whitelist_applications = forms.CharField(required=False, label="Applications")

    force_update_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    force_update_version = forms.IntegerField(required=False, label="Version")

    lender_dashboard_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )

    filename_counter_suffix_is_active = forms.BooleanField(
        widget=forms.CheckboxInput, required=False, label="Is active"
    )
    filename_counter_suffix_length = forms.IntegerField(
        required=False,
        label="Length",
        help_text=(
            "Add 0 at the beginning of the counter until it reaches the length "
            "(if length <= length of the counter, no filling is done)"
        ),
    )
    process_approval_response_delay_mins = forms.IntegerField(
        required=False,
        label="Time delay (minutes)",
        help_text=(
            "Estimate time for processing download approval file because it is an async process. "
            "User can create new request to process after the time delay"
        ),
    )

    def __init__(self, *args, **kwargs):
        super(ChannelingLoanAdminForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)
            self.fields['form_data'].initial = json.dumps(data)


class CreditScoreConversionAdminForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        parameters = cleaned_data.get('parameters', {})

        if not parameters:
            return self.cleaned_data

        for channeling_type, configuration in parameters.items():
            ranges = []
            for from_score, to_score, score_grade in configuration:
                if not (0 <= from_score <= 1 and 0 <= to_score <= 1):
                    msg = f"""
                        Configration for {channeling_type} is not correct.\n
                        Range boundary should be between 0 and 1.
                    """
                    self.add_error("parameters", msg)
                    return
                elif from_score >= to_score:
                    msg = f"""
                        Configration for {channeling_type} is not correct.\n
                        `to_score` must be greater than `from_score`.
                    """
                    self.add_error("parameters", msg)
                    return
                ranges.append([from_score, to_score])

            ranges.sort(key=lambda range: range[0])
            for idx in range(1, len(configuration)):
                if ranges[idx][0] < ranges[idx - 1][1]:
                    msg = f"""
                        Configration for {channeling_type} is not correct.\n
                        Range shouldn't be overlapped.
                    """
                    self.add_error("parameters", msg)
                    return
