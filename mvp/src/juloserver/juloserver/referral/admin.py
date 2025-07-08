from django import forms
from django.contrib import admin

from juloserver.julo.admin import JuloModelAdmin
from juloserver.referral.constants import ReferralBenefitConst, ReferralLevelConst
from juloserver.referral.models import ReferralBenefit, ReferralLevel


class ReferralBenefitForm(forms.ModelForm):
    benefit_type = forms.ChoiceField(required=True, choices=ReferralBenefitConst.CHOICES)

    class Meta:
        model = ReferralBenefit
        fields = '__all__'


class ReferralBenefitAdmin(JuloModelAdmin):
    actions = None
    form = ReferralBenefitForm
    list_display = (
        'id',
        'benefit_type',
        'referrer_benefit',
        'referee_benefit',
        'min_disburse_amount',
        'is_active',
        'cdate',
        'udate'
    )
    list_filter = ('benefit_type', 'is_active')
    list_display_links = ('id', 'benefit_type',)

    def has_delete_permission(self, request, obj=None):
        return False


class ReferralLevelForm(forms.ModelForm):
    benefit_type = forms.ChoiceField(required=True, choices=ReferralLevelConst.CHOICES)

    class Meta:
        model = ReferralLevel
        fields = '__all__'

    def clean_referrer_level_benefit(self):
        referrer_level_benefit = self.cleaned_data['referrer_level_benefit']
        benefit_type = self.cleaned_data['benefit_type']
        if benefit_type == ReferralLevelConst.PERCENTAGE and referrer_level_benefit > 100:
            raise forms.ValidationError(
                "Ensure this value is lower than or equal to 100 with percentage type."
            )
        return referrer_level_benefit


class ReferralLevelAdmin(JuloModelAdmin):
    actions = None
    form = ReferralLevelForm
    search_fields = ('level',)
    list_display = (
        'id',
        'level',
        'benefit_type',
        'referrer_level_benefit',
        'min_referees',
        'is_active',
        'cdate',
        'udate'
    )
    list_filter = ('benefit_type', 'is_active')
    list_display_links = ('id', 'level',)

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ReferralBenefit, ReferralBenefitAdmin)
admin.site.register(ReferralLevel, ReferralLevelAdmin)
