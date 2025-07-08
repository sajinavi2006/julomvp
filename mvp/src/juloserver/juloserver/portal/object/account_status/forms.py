from django import forms
from django.forms.widgets import Textarea


class StatusChangesForm(forms.Form):
    """
    please use ModelChoiceField instead of ChoiceField if using queryset
    """

    notes_only = forms.CharField(
        required=False,
        widget=Textarea(
            attrs={'rows': 6, 'class': 'form-control', 'placeholder': 'Insert notes here'}
        ),
    )

    def __init__(self, status_code, *args, **kwargs):
        super(StatusChangesForm, self).__init__(*args, **kwargs)
