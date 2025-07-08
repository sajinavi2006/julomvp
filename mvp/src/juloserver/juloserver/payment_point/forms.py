from django import forms

from juloserver.payment_point.models import AYCProduct, XfersProduct


class XfersProductForm(forms.ModelForm):
    class Meta:
        model = XfersProduct
        fields = '__all__'

        # we don't use product_id (external id from sepulsa)
        # beside with foreign key we can access via sepulsa_product
        exclude = ('product_id',)


class AYCProductForm(forms.ModelForm):
    class Meta:
        model = AYCProduct
        fields = '__all__'

        # we don't use product_id (external id from sepulsa)
        # beside with foreign key we can access via sepulsa_product
        exclude = ('product_id',)
