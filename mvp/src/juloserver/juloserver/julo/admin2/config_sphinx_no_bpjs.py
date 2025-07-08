from django import forms
from juloserver.julo.models import FeatureSetting


class ConfigurationFormSphinxNoBpjs(forms.ModelForm):
    high_score_operator = forms.ChoiceField(
        widget=forms.RadioSelect(attrs={'class': 'action-control'}),
        required=True,
        label='High Score Operator'
    )
    high_score_threshold = forms.CharField(
        widget=forms.NumberInput(attrs={'size': 50}),
        required=True,
        label='Value high score'
    )

    medium_score_operator = forms.ChoiceField(
        widget=forms.RadioSelect(attrs={'class': 'action-control'}),
        required=True,
        label='Medium Score Operator'
    )
    medium_score_threshold = forms.CharField(
        widget=forms.NumberInput(attrs={'size': 50}),
        required=True,
        label='Value medium score'
    )

    # holdout value
    holdout = forms.CharField(
        widget=forms.NumberInput(attrs={'size': 30, 'placeholder': 'to proceed Binary Check'}),
        required=True,
        label='Holdout value (%)'
    )

    def __init__(self, *args, **kwargs):
        super(ConfigurationFormSphinxNoBpjs, self).__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        operators = [
            ('>=', 'greater than or equal to (>=)'),
            ('>', 'greater than (>)'),
        ]

        if instance:
            self.fields['high_score_operator'].choices = operators
            self.fields['medium_score_operator'].choices = operators
            param = instance.parameters
            if instance.parameters:
                self.fields['high_score_operator'].initial = '>=' if param['high_score_operator'] == '>=' else '>'
                self.fields['medium_score_operator'].initial = '>=' if param['medium_score_operator'] == '>=' else '>'
                self.fields['high_score_threshold'].initial = param['high_score_threshold']
                self.fields['medium_score_threshold'].initial = param['medium_score_threshold']
                self.fields['holdout'].initial = param['holdout']

    class Meta:
        model = FeatureSetting
        exclude = ['id', 'parameters']

    def clean(self):
        data = super(ConfigurationFormSphinxNoBpjs, self).clean()

        high_score_operator = data.get('high_score_operator')
        medium_score_operator = data.get('medium_score_operator')

        if not high_score_operator or not medium_score_operator:
            raise forms.ValidationError(
                "Please check one operator."
            )

        high_score_threshold = data.get('high_score_threshold')
        medium_score_threshold = data.get('medium_score_threshold')

        if not high_score_threshold or float(high_score_threshold) <= 0:
            raise forms.ValidationError(
                "High score threshold value is not correct"
            )

        if not medium_score_threshold or float(medium_score_threshold) <= 0:
            raise forms.ValidationError(
                "Medium score threshold value is not correct"
            )

        if float(high_score_threshold) < float(medium_score_threshold):
            raise forms.ValidationError(
                "High score should be greater than medium score threshold"
            )

        holdout = data.get('holdout')
        if holdout:
            try:
                holdout = int(holdout)
                if holdout < 0 or holdout > 100:
                    raise forms.ValidationError(
                        "Holdout is not valid"
                    )
            except ValueError:
                raise forms.ValidationError(
                    "Holdout is not valid"
                )

        return data


def save_model_sphinx_no_bpjs(obj, form):
    data = form.data

    # prepare data field for update
    obj.category = data.get('category')
    obj.description = data.get('description')

    structure_param = {
        "high_score_operator": data.get('high_score_operator'),
        "high_score_threshold": float(data.get('high_score_threshold').replace(',', '.')),
        "medium_score_operator": data.get('medium_score_operator'),
        "medium_score_threshold": float(data.get('medium_score_threshold').replace(',', '.')),
        "holdout": int(data.get('holdout'))
    }

    obj.parameters = structure_param
