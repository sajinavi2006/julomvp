from django import forms

from juloserver.partnership.constants import (
    PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES,
    PartnershipProductFlow,
)
from juloserver.julo.models import Partner
from juloserver.application_flow.constants import PartnerNameConstant


# Use this as base form for Agent Assisted Upload Form
class AgentAssistedUploadForm(forms.Form):
    def __init__(self, *args, **kwargs):
        hide_partner = kwargs.get('hide_partner')
        if hide_partner:
            kwargs.pop('hide_partner')

        super().__init__(*args, **kwargs)
        if hide_partner:
            self.fields.pop('partner_field')

    partner_field = forms.ModelChoiceField(
        queryset=Partner.objects.filter(
            partnership_flow_flags__name=PartnershipProductFlow.AGENT_ASSISTED
        ),
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Partner required'}
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )


class ProductFinancingUploadFileForm(forms.Form):
    """form to upload file"""

    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please choose the CSV file'}
    )
    action_field = forms.ChoiceField(
        widget=forms.RadioSelect,
        choices=PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES,
        label="Action",
        initial=1,
        error_messages={'required': 'Need to choose action'},
    )


class PartnershipLoanCancelFileForm(forms.Form):
    partner_field = forms.ModelChoiceField(
        queryset=Partner.objects.filter(name=PartnerNameConstant.AXIATA_WEB),
        widget=forms.Select(attrs={'class': 'form-control'}),
        error_messages={'required': 'Partner required'},
    )
    file_field = forms.FileField(
        label="File Upload", error_messages={'required': 'Please upload CSV file'}
    )
