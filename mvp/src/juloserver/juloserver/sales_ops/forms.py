from datetime import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.forms import ModelChoiceField
from django.utils import timezone

from juloserver.sales_ops.constants import (
    SALES_OPS_FILTER_FIELD_CHOICES_DEFAULT,
    SALES_OPS_FILTER_FIELD_CHOICES_BUCKET_MAP
)
from juloserver.sales_ops.models import SalesOpsAgentAssignment


class SalesOpsAgentChoiceField(ModelChoiceField):
    def label_from_instance(self, obj):
        return '{} - {}'.format(obj.id, obj.user_extension)


class SalesOpsCRMLineupListFilterForm(forms.Form):
    FILTER_FIELD_CHOICES = SALES_OPS_FILTER_FIELD_CHOICES_DEFAULT

    FILTER_CONDITION_CHOICES = [
        ('icontains', 'Sebagian'),
        ('iexact', 'Sama persis'),
        ('gt', 'Lebih besar'),
        ('gte', 'Lebih besar dan sama'),
        ('lt', 'Lebih kecil'),
        ('lte', 'Lebih kecil dan sama'),
    ]
    filter_agent = SalesOpsAgentChoiceField(
        queryset=SalesOpsAgentAssignment.objects.agent_list_queryset(),
        to_field_name='id',
        required=False
    )
    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_condition = forms.ChoiceField(required=False, choices=FILTER_CONDITION_CHOICES)
    filter_keyword = forms.CharField(required=False)
    bucket_code = forms.CharField(widget=forms.HiddenInput(), required=False)
    sort_q = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, bucket_code=None, *args, **kwargs):
        self.declared_fields['filter_field'].choices = (
            SALES_OPS_FILTER_FIELD_CHOICES_BUCKET_MAP.get(
                bucket_code, SALES_OPS_FILTER_FIELD_CHOICES_DEFAULT
            )
        )
        super(SalesOpsCRMLineupListFilterForm, self).__init__(*args, **kwargs)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_condition').clean(None)
        self.fields.get('filter_keyword').clean(None)
        self.fields.get('filter_agent').clean(None)


class SalesOpsCRMLineupDetailForm(forms.Form):
    inactive_until = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={'class': 'form-control datetimepicker'})
    )
    inactive_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': '2'})
    )
    model_field_map = (
        ('inactive_until', 'inactive_until'),
        ('inactive_note', 'reason'),
    )

    def fill_form(self, lineup):
        for field_name, model_field_name in self.model_field_map:
            value = getattr(lineup, model_field_name)
            if isinstance(value, datetime):
                value = timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
            self.fields[field_name].initial = value

    def save(self, lineup):
        save_data = {
            model_field_name: self.cleaned_data[field_name]
            for field_name, model_field_name in self.model_field_map
            if field_name in self.data
        }

        if save_data:
            lineup.update_safely(**save_data)


class SalesOpsCRMLineupCallbackHistoryForm(forms.Form):
    callback_at = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={'class': 'form-control datetimepicker'})
    )
    callback_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': '2'})
    )

    def clean_callback_at(self):
        callback_at = self.cleaned_data['callback_at']
        if not callback_at:
            raise ValidationError('This field is invalid!')
        return callback_at

