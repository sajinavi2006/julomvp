import json
import logging
from copy import copy

from django import forms

from juloserver.julo.models import Partner
from juloserver.julo.admin2.job_data_constants import (
    JOB_DESC_LIST,
    JOB_INDUSTRY_LIST,
    JOB_MAPPING,
    JOB_TYPE,
    PROVINCE,
)

logger = logging.getLogger(__name__)


class HighScoreFullBypassForm(forms.ModelForm):
    form_data = forms.CharField(
        widget=forms.HiddenInput(attrs={'readonly': 'readonly'}), required=False
    )
    threshold = forms.FloatField(label="Threshold")
    province = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'special-event-binary-setting-control_area'}),
    )
    is_premium_area = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={'class': 'is_premium_area', 'onclick': 'OnChangeIsPremiumArea(this)'}
        ),
    )
    is_salaried = forms.BooleanField(
        required=False, widget=forms.CheckboxInput(attrs={'class': 'is_salaried'})
    )
    job_description = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={'class': 'job-description-control'})
    )
    job_industry = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={'class': 'job-industry-control'})
    )
    job_type = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(
            attrs={'class': 'special-event-binary-setting-control_job', 'id': 'job'}
        ),
    )
    agent_assisted_partner_ids = forms.MultipleChoiceField(
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'agent-assisted-partner-ids-control'}),
    )
    partner_ids = forms.MultipleChoiceField(
        required=False, widget=forms.SelectMultiple(attrs={'class': 'partner-ids-control'})
    )

    def __init__(self, *args, **kwargs):
        super(HighScoreFullBypassForm, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        selected_job_industry = []
        if args:
            selected_job_industry = copy(args[0].getlist('job_industry'))
        self.fields['form_data'].initial = json.dumps(JOB_MAPPING)
        self.fields['job_industry'].choices = JOB_INDUSTRY_LIST
        self.fields['job_description'].choices = JOB_DESC_LIST
        self.fields['job_type'].choices = JOB_TYPE
        self.fields['province'].choices = PROVINCE

        partners_active = (
            Partner.objects.filter(is_active=True, is_csv_upload_applicable=False)
            .exclude(type='lender')
            .all()
            .values('id', 'name')
        )
        partner_choices = []
        for partner_active in partners_active:
            partner_choices.append((partner_active['id'], partner_active['name']))
        self.fields['agent_assisted_partner_ids'].choices = partner_choices
        self.fields['partner_ids'].choices = partner_choices

        try:
            if instance.parameters:
                self.fields['form_data'].initial = json.dumps(JOB_MAPPING)
                self.fields['job_industry'].initial = instance.parameters.get('job_industry')
                self.fields['job_type'].initial = instance.parameters.get('job_type')
                self.fields['province'].initial = instance.parameters.get('province')
                self.fields['job_description'].initial = instance.parameters.get('job_description')
                selected_partner = []
                for key in instance.parameters.get('partner_ids'):
                    selected_partner.append(key)
                self.fields['partner_ids'].initial = selected_partner
                # QOALA PARTNERSHIP - Leadgen Agent Assisted 20-11-2024
                selected_agent_assisted_partner = []
                for key in instance.parameters.get('agent_assisted_partner_ids'):
                    selected_agent_assisted_partner.append(key)
                self.fields['agent_assisted_partner_ids'].initial = selected_agent_assisted_partner

        except Exception:
            self.fields['form_data'].initial = json.dumps(JOB_MAPPING)
            self.fields['job_industry'].choices = JOB_INDUSTRY_LIST
            self.fields['job_description'].choices = JOB_DESC_LIST
            self.fields['job_type'].choices = JOB_TYPE
            self.fields['province'].choices = PROVINCE
            self.fields['agent_assisted_partner_ids'].choices = partner_choices
            self.fields['partner_ids'].choices = partner_choices

        if self.fields['job_industry'].initial:
            for job_industry in self.fields['job_industry'].initial:
                if job_industry not in selected_job_industry:
                    selected_job_industry.append(job_industry)

        for job_industry in selected_job_industry:
            for job_desc_ele in JOB_MAPPING.get(job_industry, []):
                new_choice = "%s:%s" % (job_industry, job_desc_ele)
                self.fields['job_description'].choices.append((new_choice, new_choice))

    def clean(self):
        cleaned_data = super(HighScoreFullBypassForm, self).clean()

        return cleaned_data


def save_form_hsfb(obj, form):

    cleaned_data = form.cleaned_data

    job_type = JOB_TYPE
    fix_job_type = []
    salaried_job = ['Pegawai swasta', 'Pegawai negeri']
    provinces = []

    if cleaned_data['is_premium_area'] is True:
        cleaned_data['province'] = None
    else:
        if len(cleaned_data['province']) == 0:
            for provinsi in PROVINCE:
                provinces.append(provinsi[0])
            cleaned_data['province'] = provinces

    if cleaned_data['is_salaried'] is False:
        for job in job_type:
            if job[0] not in salaried_job:
                fix_job_type.append(job[0])
    else:
        fix_job_type = salaried_job

    cleaned_data.pop('form_data')
    cleaned_data['job_type'] = fix_job_type
    obj.parameters = cleaned_data
