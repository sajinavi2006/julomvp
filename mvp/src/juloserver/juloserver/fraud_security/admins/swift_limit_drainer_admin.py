from django import forms

from juloserver.julo.admin import FeatureSettingAdminFormMixin


class SwiftLimitDrainerFeatureSettingAdminForm(FeatureSettingAdminFormMixin, forms.ModelForm):
    class ParameterForm(forms.Form):
        jail_days = forms.IntegerField(required=True, min_value=0)
        mycroft_j1 = forms.FloatField(required=True, min_value=0)
        mycroft_jturbo = forms.FloatField(required=True, min_value=0)
