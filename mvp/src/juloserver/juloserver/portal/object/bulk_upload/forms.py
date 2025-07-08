"""
forms.py
declare Django Form
"""

from django import forms

from juloserver.julo.models import Partner
from juloserver.julo.partners import PartnerConstant

from .constants import (
    PARTNER_PILOT_UPLOAD_ACTION_CHOICES,
    LOAN_HALT_ACTION_CHOICES,
    LOAN_RESTRUCTURING_ACTION_CHOICES,
    LOAN_EARLY_WRITE_OFF_ACTION_CHOICES,
    GRAB_REFERRAL_ACTION_CHOICES
)


class UploadFileForm(forms.Form):
    """form to upload file"""
    from juloserver.portal.object.bulk_upload.utils import get_bulk_upload_options \
        as action_options
    partner_field = forms.ModelChoiceField(queryset=Partner.objects.filter(name=PartnerConstant.AXIATA_PARTNER),
                                           widget=forms.Select(attrs={'class': 'form-control'}))
    file_field = forms.FileField(label="File Upload")
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=action_options,
                                     label="Action",
                                     initial=1)


class MerchantFinancingUploadFileForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['partner_field'].queryset = self.fields['partner_field'].queryset.exclude(
            name__in=PartnerConstant.list_partner_merchant_financing_standard()
        )

    """form to upload file"""
    partner_field = forms.ModelChoiceField(
        queryset=Partner.objects.filter(is_csv_upload_applicable=True),
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Partner required'})
    file_field = forms.FileField(label="File Upload",
                                 error_messages={'required': 'Please choose the CSV file'})
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=PARTNER_PILOT_UPLOAD_ACTION_CHOICES,
                                     label="Action",
                                     initial=1,
                                     error_messages={'required': 'Need to choose action'})


class LoanHaltResumeUploadFileForm(forms.Form):
    """form to upload file"""
    partner_field = forms.ModelChoiceField(queryset=Partner.objects.filter(
        name__in=PartnerConstant.loan_halt_or_resume()),
        widget=forms.Select(attrs={'class': 'form-control'}))
    file_field = forms.FileField(label="File Upload")
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=LOAN_HALT_ACTION_CHOICES,
                                     label="Action",
                                     initial=1)


class LoanRestructuringUploadFileForm(forms.Form):
    """form to upload file"""
    partner_field = forms.ModelChoiceField(queryset=Partner.objects.filter(
        name__in=PartnerConstant.loan_halt_or_resume()),
        widget=forms.Select(attrs={'class': 'form-control'}))
    file_field = forms.FileField(label="File Upload")
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=LOAN_RESTRUCTURING_ACTION_CHOICES,
                                     label="Action",
                                     initial=1)


class LoanEarlyWriteOffUploadFileForm(forms.Form):
    """form to upload file"""
    partner_field = forms.ModelChoiceField(queryset=Partner.objects.filter(
        name__in=PartnerConstant.loan_halt_or_resume()),
        widget=forms.Select(attrs={'class': 'form-control'}))
    file_field = forms.FileField(label="File Upload")
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=LOAN_EARLY_WRITE_OFF_ACTION_CHOICES,
                                     label="Action",
                                     initial=1)


class GrabReferralUploadFileForm(forms.Form):
    """form to upload file"""
    partner_field = forms.ModelChoiceField(queryset=Partner.objects.filter(
        name__in=PartnerConstant.loan_halt_or_resume()),
        widget=forms.Select(attrs={'class': 'form-control'}))
    file_field = forms.FileField(label="File Upload")
    action_field = forms.ChoiceField(widget=forms.RadioSelect,
                                     choices=GRAB_REFERRAL_ACTION_CHOICES,
                                     label="Action",
                                     initial=1)
