from __future__ import unicode_literals


from django import forms
from django.forms import ModelChoiceField

from juloserver.cfs.models import CfsAction


class MissionChoiceField(ModelChoiceField):
    def label_from_instance(self, obj):
        return '{} - {}'.format(obj.id, obj.action_code)


class CFSSearchForm(forms.Form):

    FILTER_FIELD_CHOICES = [
        ('cfs_action_assignment__customer__email', 'Email'),
        ('cfs_action_assignment__customer__fullname', 'Full name'),
        ('cfs_action_assignment__id', 'Assignment ID'),
        ('account__id', 'Account ID'),
    ]

    FILTER_CONDITION_CHOICES = [
        ('icontains', 'Sebagian'),
        ('iexact', 'Sama persis'),
        ('gt', 'Lebih besar'),
        ('gte', 'Lebih besar dan sama'),
        ('lt', 'Lebih kecil'),
        ('lte', 'Lebih kecil dan sama'),
    ]

    filter_action = MissionChoiceField(
        queryset=CfsAction.objects.all(),
        to_field_name='id',
        required=False
    )
    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_condition = forms.ChoiceField(required=False, choices=FILTER_CONDITION_CHOICES)
    filter_keyword = forms.CharField(required=False)
    sort_q = forms.CharField(widget=forms.HiddenInput(), required=False)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_condition').clean(None)
        self.fields.get('filter_keyword').clean(None)
        self.fields.get('filter_action').clean(None)
