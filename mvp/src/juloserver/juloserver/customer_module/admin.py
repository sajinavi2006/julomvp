from django import forms

from juloserver.julo.models import FeatureSetting


class CustomerDataChangeRequestSettingAdminForm(forms.ModelForm):
    class Meta:
        model = FeatureSetting
        exclude = ['id']

    class ParameterForm(forms.Form):
        payslip_income_multiplier = forms.FloatField(required=False, min_value=1.0)
        request_interval_days = forms.IntegerField(required=False, min_value=1)
        supported_app_version_code = forms.IntegerField(required=False, min_value=1)
        supported_payday_version_code = forms.IntegerField(required=False, min_value=1)

        def flatten_errors(self):
            errors = []
            for field, error_list in self.errors.items():
                errors.append('"{}": {}'.format(field, ', '.join(error_list)))
            return errors

    def clean(self):
        parameters = self.cleaned_data.get('parameters', {})

        if not parameters:
            return self.cleaned_data

        parameter_form = self.ParameterForm(parameters)
        if not parameter_form.is_valid():
            raise forms.ValidationError({'parameters': parameter_form.flatten_errors()})

        cleaned_data = {
            field: value
            for field, value in parameter_form.cleaned_data.items()
            if value is not None
        }
        self.cleaned_data['parameters'] = cleaned_data
        return self.cleaned_data
