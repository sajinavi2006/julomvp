from django.contrib import admin
from django import forms
from django.core.validators import ValidationError

from juloserver.julo.admin import JuloModelAdmin

from juloserver.sales_ops.models import (
    SalesOpsBucket
)
from juloserver.sales_ops.constants import CustomerType
from juloserver.sales_ops_pds.models import AIRudderAgentGroupMapping



class AIRudderAgentGroupMappingForm(forms.ModelForm):
    id = forms.IntegerField(
        widget=forms.HiddenInput(), required=False
    )
    bucket_code = forms.ChoiceField(widget=forms.Select(), required=True)
    customer_type = forms.ChoiceField(choices=CustomerType.choices(), required=True)
    agent_group_name = forms.CharField(
        label="AIRudder agent group", max_length=100, required=True
    )

    def get_bucket_code(self):
        buckets = SalesOpsBucket.objects.filter(is_active=True)
        return list(
            map(
                lambda bucket: (bucket.code, bucket.name), buckets
            )
        )

    def __init__(self, *args, **kwargs):
        super(AIRudderAgentGroupMappingForm, self).__init__(*args, **kwargs)
        self.fields['bucket_code'].choices = self.get_bucket_code()


    def clean(self):
        cleaned_data = super(AIRudderAgentGroupMappingForm, self).clean()
        if (
            AIRudderAgentGroupMapping.objects
            .exclude(id=cleaned_data.get("id"))
            .filter(
                bucket_code=cleaned_data.get("bucket_code"),
                customer_type=cleaned_data.get("customer_type"),
                agent_group_name=cleaned_data.get("agent_group_name")
            )
            .exists()
        ):
            raise ValidationError("Duplicated agent group name mapping")


class AIRudderAgentGroupMappingAdmin(JuloModelAdmin):
    actions = None
    form = AIRudderAgentGroupMappingForm
    list_display = (
        'id',
        'bucket_code',
        'customer_type',
        'agent_group_name',
        'is_active'
    )
    list_filter = ('is_active',)
    search_fields = ('id', 'bucket_code', 'customer_type')

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(AIRudderAgentGroupMapping, AIRudderAgentGroupMappingAdmin)
