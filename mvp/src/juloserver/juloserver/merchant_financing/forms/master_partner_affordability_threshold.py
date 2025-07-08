from django import forms

from juloserver.julo.models import Partner
from juloserver.merchant_financing.models import MasterPartnerAffordabilityThreshold


class MasterPartnerAffordabilityThresholdForm(forms.ModelForm):

    class Meta:
        model = MasterPartnerAffordabilityThreshold
        fields = ("partner", "minimum_threshold", "maximum_threshold")

    def __init__(self, *args, **kwargs):
        super(MasterPartnerAffordabilityThresholdForm, self).__init__(*args, **kwargs)
        if not self.instance.id:
            self.fields['partner'].queryset = Partner.objects.filter(is_active=True)
        dict_error_messages = {
            'required': 'This field is required.',
            'invalid': ""
        }
        self.fields['minimum_threshold'].error_messages.update(dict_error_messages)
        self.fields['maximum_threshold'].error_messages.update(dict_error_messages)

    def clean(self):
        cleaned_data = super().clean()
        minimum_threshold = self.cleaned_data.get("minimum_threshold")
        maximum_threshold = self.cleaned_data.get("maximum_threshold")

        # when value is negative or value is not integer
        # variable minimum and maximum will filled by None
        err_message = "This value is cannot lower than 1 or must be integer value"
        if minimum_threshold is None:
            raise forms.ValidationError(
                {'minimum_threshold': [err_message, ]}
            )
        elif maximum_threshold is None:
            raise forms.ValidationError(
                {'maximum_threshold': [err_message, ]}
            )

        if minimum_threshold >= maximum_threshold:
            raise forms.ValidationError(
                {'minimum_threshold': ["Minimum threshold must lower than Maximum threshold", ]}
            )

        return cleaned_data
