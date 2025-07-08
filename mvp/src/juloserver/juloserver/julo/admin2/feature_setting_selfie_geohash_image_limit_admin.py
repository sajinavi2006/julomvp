from django import forms

from juloserver.julo.models import FeatureSetting


class SelfieGeohashCrmImageLimitForm(forms.ModelForm):
    class Meta(object):
        fields = ('__all__')
        model = FeatureSetting

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if 'days' not in parameters:
            raise forms.ValidationError(
                'Parameters field must have days key.'
                'E.g: {"days": 1}'
            )

        days = parameters['days']
        if (not isinstance(days, int)):
            raise forms.ValidationError(
                'Parameters field dictionary \'days\' must be a number value.'
                'E.g: {"days": 2}'
            )

        if days < 0:
            raise forms.ValidationError(
                'days value must be equal or larger than 0.'
            )

        return cleaned_data
