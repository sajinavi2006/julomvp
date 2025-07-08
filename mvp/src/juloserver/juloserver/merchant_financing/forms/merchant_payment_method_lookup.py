from django import forms

from juloserver.julo.models import PaymentMethodLookup

class MerchantPaymentMethodLookupAdminForm(forms.ModelForm):
    is_shown_mf = forms.BooleanField(widget=forms.CheckboxInput,
                                     required=False)

    class Meta:
        model = PaymentMethodLookup
        fields = ("code", "name", "image_logo_url", "image_background_url", "bank_virtual_name", "is_shown_mf")

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.get('instance', None)
        super(MerchantPaymentMethodLookupAdminForm, self).__init__(*args, **kwargs)
