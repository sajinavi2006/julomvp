import logging
import json

from copy import copy

from django import forms
from .job_data_constants import JOB_INDUSTRY_LIST, JOB_DESC_LIST
from .job_data_constants import JOB_MAPPING, JOB_TYPE, PROVINCE, ACTION

logger = logging.getLogger(__name__)


class SpecialEventBinaryForm(forms.ModelForm):
    form_data = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}),
        required=False)
    action = forms.ChoiceField(
        widget = forms.RadioSelect(attrs={'class': 'action-control'}),
        required=False)
    province = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'special-event-binary-setting-control'}))
    job_description = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'job-description-control'}))
    job_industry = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'job-industry-control'}))
    job_type = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'special-event-binary-setting-control'}))
    min_age = forms.IntegerField(required=False, max_value=100, min_value=0)
    max_age = forms.IntegerField(required=False, max_value=100, min_value=0)

    def __init__(self, *args, **kwargs):
        super(SpecialEventBinaryForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        selected_job_industry = []
        if args:
            selected_job_industry = copy(args[0].getlist('job_industry'))
        if instance:
            self.fields['form_data'].initial = json.dumps(JOB_MAPPING)
            self.fields['job_industry'].choices = JOB_INDUSTRY_LIST
            self.fields['job_description'].choices = JOB_DESC_LIST
            self.fields['job_type'].choices = JOB_TYPE
            self.fields['province'].choices = PROVINCE
            self.fields['action'].choices = ACTION
            if instance.parameters:
                self.fields['job_industry'].initial = instance.parameters.get('job_industry')
                self.fields['job_type'].initial = instance.parameters.get('job_type')
                self.fields['province'].initial = instance.parameters.get('province')
                self.fields['max_age'].initial = instance.parameters.get('max_age')
                self.fields['min_age'].initial = instance.parameters.get('min_age')
                self.fields['job_description'].initial = instance.parameters.get('job_description')
                self.fields['action'].initial = instance.parameters.get('action')

        if self.fields['job_industry'].initial:
            for job_industry in self.fields['job_industry'].initial:
                if job_industry not in selected_job_industry:
                    selected_job_industry.append(job_industry)

        for job_industry in selected_job_industry:
            for job_desc_ele in JOB_MAPPING.get(job_industry, []):
                new_choice = "%s:%s" % (job_industry, job_desc_ele)
                self.fields['job_description'].choices.append((new_choice, new_choice))

    def clean(self):
        cleaned_data = super(SpecialEventBinaryForm, self).clean()
        max_age = cleaned_data.get('max_age')
        min_age = cleaned_data.get('min_age')
        if max_age is not None and min_age is not None:
            if max_age < min_age:
                raise forms.ValidationError(
                    "Max age must greater than or equal min age"
                )
        return cleaned_data


def save_form_special_event_binary(obj, form):
    cleaned_data = form.cleaned_data
    cleaned_data.pop('form_data')
    obj.is_active = cleaned_data.pop('is_active')
    obj.parameters = cleaned_data
