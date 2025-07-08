"""
ops_team_leader.py
declare Django Form
"""
from django import forms
from django.contrib.auth.models import User

class SubmitOPSStatusForm(forms.Form):
    """form to change status"""
    CHANGE_REASONS = [
        ('Wrong Status Change by Agent', 'Wrong Status Change by Agent'),
        ('Error by System', 'Error by System'),
        ('Others', 'Others')
    ]

    agent_field = forms.ChoiceField(required=True)
    application_field = forms.IntegerField(widget=forms.NumberInput(
        attrs={'class': 'form-control ops-team-lead-control'}
        ), required=True)
    status_field = forms.IntegerField(widget=forms.NumberInput(
        attrs={'class': 'form-control ops-team-lead-control'}
        ), required=True)
    reason_field = forms.ChoiceField(choices=CHANGE_REASONS, required=True)
    reason_detail_field = forms.CharField(widget=forms.Textarea(attrs={
        'class': 'form-control ops-team-lead-control', 'style': 'resize: none;', 'size': 255, 'maxlength': 255
        }), required=True)
    hidden_raw_field = forms.ChoiceField(widget=forms.HiddenInput)
