from datetime import datetime

from django import forms
from django.utils import timezone

from juloserver.julo.models import FeatureSetting
from juloserver.loan.services.loan_prize_chance import LoanPrizeChanceSetting
from juloserver.promo.models import PromoCode

from juloserver.loan.constants import DDWhitelistLastDigit
from ckeditor.widgets import CKEditorWidget
from juloserver.payment_point.constants import TransactionMethodCode
import json


class MarketingLoanPrizeChanceSettingForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = ('__all__')

    def clean_parameters(self):
        parameters = self.cleaned_data['parameters']
        parameters = self._clean_promo_code_id(parameters)
        parameters = self._clean_time(parameters)
        parameters = self._clean_minimum_amount(parameters)
        parameters = self._clean_bonus_available_limit_threshold(parameters)
        parameters = self._clean_chance_per_promo_code(parameters)

        return parameters

    def _clean_time(self, parameters):
        start_time = parameters.get('start_time')
        end_time = parameters.get('end_time')
        campaign_start_date = parameters.get('campaign_start_date')
        campaign_end_date = parameters.get('campaign_end_date')
        campaign_period = parameters.get('campaign_period')
        if not start_time or not end_time:
            raise forms.ValidationError(
                'start_time and end_time must be specified.'
            )

        try:
            start_time = datetime.strptime(start_time, LoanPrizeChanceSetting.DATETIME_FORMAT)
            end_time = datetime.strptime(end_time, LoanPrizeChanceSetting.DATETIME_FORMAT)
            campaign_start_date = datetime.strptime(
                campaign_start_date, LoanPrizeChanceSetting.DATE_FORMAT)
            campaign_end_date = datetime.strptime(
                campaign_end_date, LoanPrizeChanceSetting.DATE_FORMAT)
            campaign_period = datetime.strptime(campaign_period,
                                                LoanPrizeChanceSetting.PERIOD_FORMAT)
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e

        if end_time < start_time:
            raise forms.ValidationError(
                'end_time must be after start_time.'
            )

        if campaign_end_date < campaign_start_date:
            raise forms.ValidationError(
                'campaign_end_date must be after campaign_start_date.'
            )

        return parameters

    def _clean_minimum_amount(self, parameters):
        minimum_amount = parameters.get('minimum_amount')
        if minimum_amount is None:
            raise forms.ValidationError('minimum_amount must be specified.')

        try:
            minimum_amount = int(minimum_amount)
            if minimum_amount <= 0:
                raise forms.ValidationError('minimum_amount must be greater than 0.')
        except ValueError as e:
            raise forms.ValidationError('minimum_amount must be integer') from e

        parameters['minimum_amount'] = minimum_amount
        return parameters

    def _clean_bonus_available_limit_threshold(self, parameters):
        value = parameters.get('bonus_available_limit_threshold')
        if value is None:
            return parameters

        try:
            value = int(value)
            if value < 0:
                raise forms.ValidationError(
                    'bonus_available_limit_threshold must be greater or equal than 0.'
                )
        except ValueError as e:
            raise forms.ValidationError('bonus_available_limit_threshold must be integer') from e

        parameters['bonus_available_limit_threshold'] = value
        return parameters

    def _clean_promo_code_id(self, parameters):
        value = parameters.get('promo_code_id')
        if value is None:
            return parameters

        try:
            promo_code = PromoCode.objects.get(id=value, is_active=True)
            start_time = timezone.localtime(promo_code.start_date)
            end_time = timezone.localtime(promo_code.end_date)
        except ValueError as e:
            raise forms.ValidationError("promo_code_id must be integer") from e
        except PromoCode.DoesNotExist as e:
            raise forms.ValidationError("promo_code_id does not exist or is not active") from e

        parameters['promo_code_id'] = promo_code.id
        parameters['start_time'] = start_time.strftime(LoanPrizeChanceSetting.DATETIME_FORMAT)
        parameters['end_time'] = end_time.strftime(LoanPrizeChanceSetting.DATETIME_FORMAT)
        return parameters

    def _clean_chance_per_promo_code(self, parameters):
        value = parameters.get('chance_per_promo_code')
        if value is None:
            raise forms.ValidationError('chance_per_promo_code must be specified.')

        try:
            value = int(value)
            if value <= 0:
                raise forms.ValidationError('chance_per_promo_code must be greater than 0.')
        except ValueError as e:
            raise forms.ValidationError('chance_per_promo_code must be integer') from e

        parameters['chance_per_promo_code'] = value
        return parameters


class DelayDisbursementSetting(object):
    def __init__(self) -> object:
        self.form = None
        self.change_form_template = None
        self.fieldsets = None
        self.cleaned_request = None
        self.cleaned_data = None

    def initialize_form(self, form):
        self.form = form
        self.change_form_template = 'custom_admin/delay_disbursement.html'
        self.fieldsets = (
            (
                None,
                {
                    'fields': (
                        'is_active',
                        'parameters',
                        'parameter_data',
                    ),
                },
            ),
            (
                'Condition',
                {
                    'fields': [
                        ('condition_start_time', 'condition_cut_off'),
                        ('condition_daily_limit', 'condition_monthly_limit'),
                        'condition_list_transaction_method_code',
                        'condition_min_loan_amount',
                        'condition_threshold_duration',
                        'condition_cashback',
                    ],
                },
            ),
            ('Whitelist', {'fields': ['whitelist_last_digit']}),
            (
                'TnC',
                {
                    'fields': [
                        'content_tnc',
                    ]
                },
            ),
        )

    def reconstruct_request(self, request_data):
        condition = self.cleaned_data['condition']
        content = self.cleaned_data['content']
        whitelist = int(self.cleaned_data['whitelist_last_digit'])
        self.cleaned_request = {
            "condition": {
                "start_time": condition['start_time'],
                "cut_off": condition['cut_off'],
                "daily_limit": condition['daily_limit'],
                "monthly_limit": condition['monthly_limit'],
                "list_transaction_method_code": condition['list_transaction_method_code'],
                "min_loan_amount": condition['min_loan_amount'],
                "threshold_duration": condition['threshold_duration'],
                "cashback": condition['cashback'],
            },
            "content": {
                "tnc": content['tnc'],
            },
            "whitelist_last_digit": whitelist,
        }


class DelayDisbursementAdminForm(forms.ModelForm):
    class Meta(object):
        model = FeatureSetting
        fields = '__all__'
        widgets = {'parameters': forms.HiddenInput()}

    is_active = forms.BooleanField(widget=forms.CheckboxInput, required=False)
    parameter_data = forms.CharField(widget=forms.HiddenInput, required=False)

    condition_min_loan_amount = forms.IntegerField(
        required=False, label="Min loan amount", min_value=0
    )

    condition_threshold_duration = forms.IntegerField(
        required=True, label="Threshold Duration in seconds", min_value=1
    )

    condition_list_transaction_method_code = forms.MultipleChoiceField(
        required=False,
        choices=TransactionMethodCode.choices(),
        widget=forms.CheckboxSelectMultiple,
        label="List transaction method",
    )

    condition_start_time = forms.TimeField(
        required=True,
        label="Start Time",
        widget=forms.TimeInput(attrs={'type': 'time'}),
        help_text='Enter time in HH:MM format',
    )

    condition_cut_off = forms.TimeField(
        required=True,
        label="Cut Off",
        widget=forms.TimeInput(attrs={'type': 'time'}),
        help_text='Enter time in HH:MM format',
    )

    condition_daily_limit = forms.IntegerField(required=False, label="Daily Limit", min_value=0)

    condition_monthly_limit = forms.IntegerField(required=False, label="Monthly Limit", min_value=0)

    condition_cashback = forms.IntegerField(required=True, label="Cashback", min_value=1)

    whitelist_last_digit = forms.TypedChoiceField(
        required=False,
        choices=DDWhitelistLastDigit.choices(),
        widget=forms.RadioSelect,
        coerce=int,
        label="Whitelist last digit",
    )

    content_tnc = forms.CharField(
        required=False,
        label="TnC",
        widget=CKEditorWidget(),
    )

    # to fill form
    def __init__(self, *args, **kwargs):
        super(DelayDisbursementAdminForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        if instance:
            data = dict(instance.parameters)
            self.fields['parameter_data'].initial = json.dumps(data)
            self.fields['content_tnc'].initial = data["content"]["tnc"]
            self.fields['whitelist_last_digit'].initial = data["whitelist_last_digit"]

    def is_valid(self):
        if not super().is_valid():
            return False
        # if valid, will reasign into paramaters with cleandata
        clean_data = self.cleaned_data['parameters']
        condition = clean_data['condition']
        content = clean_data['content']

        # Validate min loan amount
        min_loan_amount = self.cleaned_data.get('condition_min_loan_amount')
        condition['min_loan_amount'] = min_loan_amount

        # Validate Daily Limit
        daily_limit = self.cleaned_data.get('condition_daily_limit')
        condition['daily_limit'] = daily_limit

        # Validate Monthly Limit
        monthly_limit = self.cleaned_data.get('condition_monthly_limit')
        condition['monthly_limit'] = monthly_limit

        # Validate List Transaction Method
        list_transaction_method = self.cleaned_data.get('condition_list_transaction_method_code')
        condition['list_transaction_method_code'] = list(map(int, list_transaction_method))

        # Validate Threshold Duration
        threshold_duration = self.cleaned_data.get('condition_threshold_duration')
        condition['threshold_duration'] = threshold_duration

        # Validate Cashback
        cashback = self.cleaned_data.get('condition_cashback')
        condition['cashback'] = cashback

        # validate start date and cut off
        start_time = self.cleaned_data.get('condition_start_time')
        cut_off = self.cleaned_data.get('condition_cut_off')
        condition['start_time'] = start_time.strftime('%H:%M')
        condition['cut_off'] = cut_off.strftime('%H:%M')

        # validate content
        content['tnc'] = self.cleaned_data.get('content_tnc')

        # Re assign into parameters object
        clean_data['condition'] = condition
        clean_data['content'] = content
        clean_data['whitelist_last_digit'] = self.cleaned_data.get('whitelist_last_digit')

        return False if self.errors else True
