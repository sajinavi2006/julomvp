from django import forms

from juloserver.julo.models import FeatureSetting


class TrustDecisionForm(forms.ModelForm):
    class Meta(object):
        fields = ('__all__')
        model = FeatureSetting

    def clean(self):
        cleaned_data = super().clean()

        parameters = cleaned_data.get('parameters')
        if not parameters:
            raise forms.ValidationError('There is something wrong with your parameters field.')

        if 'trust_guard' not in parameters or 'finscore' not in parameters:
            raise forms.ValidationError(
                'Missing one or more parameters field.'
                'Parameters field must have key "trust_guard" and "finscore".'
                'E.g: {"trust_guard": true, "finscore": true}'
            )

        trust_guard = parameters['trust_guard']
        finscore = parameters['finscore']
        if (not isinstance(trust_guard, bool) or not isinstance(finscore, bool)):
            raise forms.ValidationError(
                'Parameters field dictionary "trust_guard" and "finscore" value must be: '
                'False/True. E.g: {"trust_guard": false, "finscore": true}'
            )

        return cleaned_data
