from django.conf import settings
from juloserver.julo.utils import get_oss_presigned_url

from datetime import datetime

from django import forms
from django.contrib.postgres.forms import JSONField as JSONFormField
from django.utils import timezone
from juloserver.julo.admin import CustomPrettyJSONWidget
from juloserver.julo.validators import CustomerWhitelistCSVFileValidator
from juloserver.loyalty.constants import (
    DEFAULT_DAILY_REWARD_CONFIG,
    MissionCriteriaTypeConst,
    MissionConfigTargetUserConst,
    MissionCategoryConst,
    MissionRewardTypeConst,
    MissionTargetTypeConst,
    APIVersionConst,
)
from juloserver.loyalty.models import (
    DailyCheckin,
    MissionConfig,
    MissionCriteria,
    MissionReward,
    MissionTarget,
    MissionConfigTarget,
)
from juloserver.loyalty.services.daily_checkin_related import is_validate_input_data
from juloserver.loyalty.constants import MissionCriteriaValueConst
from juloserver.payment_point.models import TransactionMethod
from juloserver.promo.admin import BaseJsonValueForm


class DailyCheckinForm(forms.ModelForm):
    daily_reward = JSONFormField(required=True, widget=CustomPrettyJSONWidget)

    class Meta:
        model = DailyCheckin
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super(DailyCheckinForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if not instance:
            self.fields['daily_reward'].initial = DEFAULT_DAILY_REWARD_CONFIG
            self.fields['is_latest'].initial = True
            self.fields['max_days_reach_bonus'].initial = 7
            self.fields['reward'].initial = 250

    def clean(self):
        is_valid, error_message = is_validate_input_data(self.cleaned_data)
        if not is_valid:
            raise forms.ValidationError(error_message)
        return self.cleaned_data


class MissionConfigForm(forms.ModelForm):
    id = forms.IntegerField(
        widget=forms.HiddenInput(attrs={'class': 'id-mission-config-form'}), required=False
    )
    display_order = forms.IntegerField(required=False)
    max_repeat = forms.IntegerField(
        required=False,
        help_text='Number of times customers can do the mission',
        min_value=1,
    )
    repetition_delay_days = forms.IntegerField(
        required=True,
        help_text='Delay times between mission completions. 0 mean no delay',
        min_value=0,
    )
    icon_image = forms.ImageField(required=False)
    category = forms.ChoiceField(
        required=False, choices=MissionCategoryConst.CHOICES,
    )
    criteria = forms.CharField(
        label='criteria',
        required=False,
    )
    targets = forms.CharField(
        label='targets',
        required=False,
    )
    reward = forms.CharField(
        label='reward',
        required=False,
    )
    hidden_targets = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )
    hidden_criteria = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )
    hidden_reward = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )
    expiry_date = forms.CharField(
        help_text='When this date is reached, the mission will expire, timezone GMT+7',
        widget=forms.TextInput(attrs={'class': 'datetimepicker'}), required=False
    )
    api_version = forms.ChoiceField(
        label='API Version',
        required=True,
        choices=APIVersionConst.CHOICES,
        help_text='Decide which API version this mission is allowed to be shown'
    )

    def __init__(self, *args, **kwargs):
        super(MissionConfigForm, self).__init__(*args, **kwargs)
        if self.instance.id:
            instance = self.instance
            self.fields['hidden_criteria'].initial = ', '.join([
                '{} - {}'.format(item.id, item.name)
                for item in instance.criteria.all()
            ])
            self.fields['hidden_targets'].initial = ', '.join([
                '{} - {}'.format(item.id, item.name)
                for item in instance.targets.all()
            ])
            self.fields['hidden_reward'].initial = '{} - {}'.format(
                instance.reward.id, instance.reward.name
            )
        else:
            self.fields['reward'].required = True

    class Meta:
        model = MissionConfig
        exclude = ['hidden_criteria', 'hidden_targets', 'target_recurring']

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.id:
            cleaned_data['criteria'] = self.instance.criteria.all()
            cleaned_data['targets'] = self.instance.targets.all()
            cleaned_data['reward'] = self.instance.reward
            return cleaned_data
        else:
            criteria = cleaned_data.get('criteria')
            if criteria:
                criteria = cleaned_data['criteria'].split(',')
                cleaned_data['criteria'] = {int(criterion) for criterion in criteria}

            targets = cleaned_data.get('targets')
            if targets:
                targets = cleaned_data['targets'].split(',')
                cleaned_data['targets'] = {int(target) for target in targets}

            reward_id = cleaned_data.get('reward')
            if reward_id:
                reward = MissionReward.objects.get(pk=int(reward_id))
                cleaned_data['reward'] = reward

            expiry_date = cleaned_data.get('expiry_date')
            if expiry_date:
                cleaned_data['expiry_date'] = timezone.localtime(
                    datetime.strptime(expiry_date, "%Y-%m-%d")
                )
            else:
                cleaned_data['expiry_date'] = None
            return cleaned_data


class MissionCriteriaForm(BaseJsonValueForm):
    value_field_mapping = MissionCriteriaTypeConst.VALUE_FIELD_MAPPING
    optional_value_fields = MissionCriteriaTypeConst.OPTIONAL_VALUE_FIELDS

    id = forms.IntegerField(
        widget=forms.HiddenInput(attrs={'class': 'id-criteria-form'}), required=False
    )
    name = forms.CharField(
        label='Name',
        required=True,
    )
    category = forms.ChoiceField(
        required=True, choices=MissionCategoryConst.CHOICES,
        widget=forms.Select(attrs={'class': 'category-criteria-form'})
    )
    type = forms.ChoiceField(
        required=True, choices=MissionCriteriaTypeConst.CHOICES,
        widget=forms.Select(attrs={'class': 'type-criteria-form'})
    )

    value_target_user = forms.ChoiceField(
        label='Target User',
        required=False,
        choices=MissionConfigTargetUserConst.CHOICES,
    )
    value_tenor = forms.IntegerField(
        label='Tenor',
        required=False,
        help_text='Loan duration must be greater than or equal this value',
        min_value=0
    )
    value_transaction_method_id = forms.ModelChoiceField(
        label='Transaction Method',
        required=False,
        queryset=TransactionMethod.objects.order_by('id').all(),
        empty_label=None
    )
    value_categories = forms.CharField(
        label='Categories',
        required=False,
    )
    value_minimum_loan_amount = forms.IntegerField(
        label='Minimum Loan Amount',
        required=False,
        min_value=0,
    )
    value_utilization_rate = forms.FloatField(
        label='Utilization Rate',
        required=False,
        min_value=0,
        max_value=100,
    )
    # this is an object to define a key list of transaction methods in json
    value_transaction_methods = forms.CharField(required=False)
    value_whitelist_customers_file = forms.FileField(
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
                'accept': '.csv',
            }
        ),
        label="File Upload",
        required=False,
        error_messages={'required': 'Please choose the CSV file'},
        validators=[
            CustomerWhitelistCSVFileValidator(
                allowed_extensions=MissionCriteriaValueConst.ALLOWED_EXTENSIONS,
                max_size=MissionCriteriaValueConst.MAX_FILE_SIZE,
                with_header=False
            )
        ]
    )
    value_duration = forms.IntegerField(
        required=False,
        label="Duration (months)",
        min_value=1,
        max_value=6,
    )
    value_upload_url = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}),
        required=False,
    )
    value_download_url = forms.CharField(
        widget=forms.TextInput(
            attrs={'size': 150}
        ),
        required=False,
        label="Download URL"
    )
    value_status = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}),
        required=False,
    )

    class Meta:
        model = MissionCriteria
        exclude = ('value',)

    def clean(self):
        data = self.data
        transaction_method_group = {}
        for field_name, value in data.items():
            if not field_name.startswith('value_transaction_method_id'):
                continue

            transaction_method_id = value
            parts = field_name.split('value_transaction_method_id')
            order_trx_method = parts[-1]
            transaction_method_group.setdefault(transaction_method_id, set())
            if data['value_categories{}'.format(order_trx_method)]:
                transaction_method_group[transaction_method_id].update(
                    data['value_categories{}'.format(order_trx_method)].split(',')
                )

        if transaction_method_group:
            self.cleaned_data['value_transaction_methods'] = []
            for transaction_method_id, categories in transaction_method_group.items():
                obj = {'transaction_method_id': int(transaction_method_id)}
                if categories:
                    obj['categories'] = list(categories)
                self.cleaned_data['value_transaction_methods'].append(obj)
        self.cleaned_data['value_categories'] = None
        self.cleaned_data['value_transaction_method_id'] = None

        # keep value on db in case update
        if self.instance.id:
            value = self.instance.value
            for field_name, field_value in value.items():
                self.cleaned_data['value_{}'.format(field_name)] = value[field_name]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Standardize the value of your_field before displaying the form
        if kwargs.get('instance'):
            value = kwargs['instance'].value
            if value.get('transaction_methods'):
                # Selectize choice receive value to display with format value1,value2,value3
                self.fields['value_transaction_methods'].initial = value['transaction_methods']
            elif value.get('upload_url'):
                # Display download URL of CSV file
                download_url = get_oss_presigned_url(
                    settings.OSS_MEDIA_BUCKET,
                    value['upload_url']
                )
                self.fields['value_download_url'].initial = download_url


class MissionRewardForm(BaseJsonValueForm):
    value_field_mapping = MissionRewardTypeConst.VALUE_FIELD_MAPPING
    optional_value_fields = MissionRewardTypeConst.OPTIONAL_VALUE_FIELDS

    id = forms.IntegerField(
        widget=forms.HiddenInput(attrs={'class': 'id-reward-form'}), required=False
    )
    name = forms.CharField(
        label='Name',
        required=False,
    )
    category = forms.ChoiceField(
        required=True, choices=MissionCategoryConst.CHOICES,
        widget=forms.Select(attrs={'class': 'category-reward-form'})
    )
    type = forms.ChoiceField(
        required=True, choices=MissionRewardTypeConst.CHOICES,
        widget=forms.Select(attrs={'class': 'type-reward-form'})
    )

    value_fixed = forms.IntegerField(
        label='Fixed point reward',
        required=False,
        min_value=0
    )
    value_percentage = forms.FloatField(
        label='Percentage point reward',
        required=False,
        min_value=0,
        max_value=100,
    )
    value_max_points = forms.IntegerField(
        label='Max point',
        required=False,
        min_value=0,
    )

    class Meta:
        model = MissionReward
        exclude = ('value',)

    def clean(self):
        cleaned_data = super(BaseJsonValueForm, self).clean()
        # keep value on db in case update
        if self.instance.id:
            value = self.instance.value
            for field_name, field_value in value.items():
                cleaned_data['value_{}'.format(field_name)] = value[field_name]
        return cleaned_data


class MissionTargetForm(forms.ModelForm):
    id = forms.IntegerField(
        widget=forms.HiddenInput(attrs={'class': 'id-target-form'}), required=False
    )
    name = forms.CharField(
        label='Name',
        required=True,
    )
    category = forms.ChoiceField(
        required=True, choices=MissionCategoryConst.CHOICES,
        widget=forms.Select(attrs={'class': 'category-target-form'})
    )
    type = forms.ChoiceField(
        required=True, choices=MissionTargetTypeConst.CHOICES,
        widget=forms.Select(attrs={'class': 'type-target-form'})
    )

    value_recurring = forms.IntegerField(
        label='Target Recurring',
        required=False,
        help_text='Number of transactions customers need to make to complete the mission.',
        min_value=1,
    )
    # Fields for transaction
    value_total_transaction_amount = forms.IntegerField(
        label='Total Transaction Amount',
        required=False,
        help_text='Total loan amount need to be created to get the rewards',
        min_value=0
    )

    class Meta:
        model = MissionTarget
        exclude = ('value',)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            if self.instance.type == MissionTargetTypeConst.RECURRING:
                self.fields['value_recurring'].initial = self.instance.value
            elif self.instance.type == MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT:
                self.fields['value_total_transaction_amount'].initial = self.instance.value


    def clean(self):
        cleaned_data = super().clean()
        type_ = cleaned_data.get('type')

        if type_ == MissionTargetTypeConst.RECURRING:
            value = cleaned_data.get('value_recurring')
            if value is None:
                self.add_error('value_recurring', 'This field is required.')
            cleaned_data['value'] = value

        elif type_ == MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT:
            value = cleaned_data.get('value_total_transaction_amount')
            if value is None:
                self.add_error('value_total_transaction_amount', 'This field is required.')
            cleaned_data['value'] = value

        return cleaned_data
