from django import forms
from .constants import OverpaidConsts


class OverpaidVerificationForm(forms.Form):
    CHOICES = [
        (OverpaidConsts.Statuses.ACCEPTED, 'ACCEPT'),
        (OverpaidConsts.Statuses.REJECTED, 'REJECT'),
    ]

    decision = forms.ChoiceField(
        choices=CHOICES,
        widget=forms.Select(
            attrs={'class': 'btn btn-primary'}
        ),
        required=True,
    )

    agent_note = forms.CharField(
        widget=forms.Textarea, label='Agent Note (*)', max_length=1000, required=True
    )
