import json
import re
from django import forms
from django.contrib import admin
from django.contrib.postgres.forms import JSONField as JSONFormField

from juloserver.julo.admin import JuloModelAdmin, CustomPrettyJSONWidget
from juloserver.early_limit_release.models import EarlyReleaseExperiment
from juloserver.early_limit_release.constants import (
    ExperimentOption,
    PgoodRequirement,
    OdinRequirement,
)


class EarlyReleaseExperimentForm(forms.ModelForm):
    DEFAULT_CRITERIA = {
        "last_cust_digit": {"from": '', 'to': ''},
        'loan_duration_payment_rules': {},
        "pgood": '',
        "odin": '',
    }
    option = forms.ChoiceField(required=True, choices=ExperimentOption.CHOICES)
    criteria = JSONFormField(required=True, widget=CustomPrettyJSONWidget)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['criteria'] = self.DEFAULT_CRITERIA

    def clean_criteria(self):
        criteria = self.cleaned_data['criteria']
        if not criteria.get('last_cust_digit'):
            raise forms.ValidationError("last_cust_digit key is required")

        last_cust_digit = criteria['last_cust_digit']
        if last_cust_digit.get('from') is None or last_cust_digit.get('to') is None:
            raise forms.ValidationError("from/to key is required inside last_cust_digit")

        _from = last_cust_digit['from']
        _to = last_cust_digit['to']
        _pgood = criteria.get('pgood')
        _odin = criteria.get('odin')

        if not (
            isinstance(_from, str) and isinstance(_to, str) and _from.isdigit() and _to.isdigit()
        ):
            raise forms.ValidationError("from/to key is a digit")

        if not (_pgood or _odin):
            raise forms.ValidationError("pgood or odin key must be filled in")

        float_pattern = re.compile(r'^(0\.[0-9]+|[01](\.0+)?)$')

        if _pgood is not None:
            if not (isinstance(_pgood, str) and bool(float_pattern.match(_pgood))):
                raise forms.ValidationError("pgood key is a digit, remove this key if not use")
            criteria['pgood'] = self.filter_pgood(_pgood)

        if _odin is not None:
            if not (isinstance(_odin, str) and bool(float_pattern.match(_odin))):
                raise forms.ValidationError("odin key is a digit, remove this key if not use")
            criteria['odin'] = self.filter_odin(_odin)

        return criteria

    @staticmethod
    def filter_pgood(value=None):
        return value if PgoodRequirement.BOTTOM_LIMIT <= float(value) <= PgoodRequirement.TOP_LIMIT \
            else f'{PgoodRequirement.DEFAULT}'

    @staticmethod
    def filter_odin(value=None):
        return value if OdinRequirement.BOTTOM_LIMIT <= float(value) <= OdinRequirement.TOP_LIMIT \
            else f'{OdinRequirement.DEFAULT}'

    class Meta:
        model = EarlyReleaseExperiment
        fields = '__all__'


class EarlyReleaseExperimentAdmin(JuloModelAdmin):
    actions = None
    form = EarlyReleaseExperimentForm
    search_fields = ('id', 'experiment_name', 'option')
    list_filter = ('is_active', 'is_delete', 'option')
    list_display = (
        'id',
        'experiment_name',
        'option',
        'description',
        'criteria',
        'is_active',
        'is_delete',
    )
    list_display_links = (
        'id',
        'experiment_name',
    )
    update_readonly_fields = ['criteria', 'option']

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        update_readonly_fields = list(getattr(self, 'update_readonly_fields', []))
        if obj:
            readonly_fields.extend(update_readonly_fields)

        return readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(EarlyReleaseExperiment, EarlyReleaseExperimentAdmin)
