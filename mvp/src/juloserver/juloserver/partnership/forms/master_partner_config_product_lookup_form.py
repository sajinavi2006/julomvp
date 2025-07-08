from django import forms

from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import ProductLookup, Partner, ProductLine
from juloserver.partnership.models import MasterPartnerConfigProductLookup


class MasterPartnerConfigProductLookupForm(forms.ModelForm):

    class Meta:
        model = MasterPartnerConfigProductLookup
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super(MasterPartnerConfigProductLookupForm, self).__init__(*args, **kwargs)
        product_line = ProductLine.objects.filter(product_line_code=ProductLineCodes.MF).first()
        self.fields['product_lookup'].queryset = ProductLookup.objects\
            .filter(is_active=True, product_line=product_line)
        if not self.instance.id:
            self.fields['partner'].queryset = Partner.objects.filter(is_active=True)

        dict_error_messages = {
            'required': 'This field is required.',
            'invalid': ""
        }
        self.fields['minimum_score'].error_messages.update(dict_error_messages)
        self.fields['maximum_score'].error_messages.update(dict_error_messages)

    def clean(self):
        cleaned_data = super().clean()
        minimum_score = self.cleaned_data.get("minimum_score")
        maximum_score = self.cleaned_data.get("maximum_score")
        error_message_invalid_score = 'Maximum 2 digits after decimal place'

        # when value is negative or value is not integer
        # variable minimum and maximum will filled by None
        err_message = "This value is cannot lower than 1"
        if minimum_score is None:
            raise forms.ValidationError(
                {'minimum_score': [err_message, ]}
            )
        elif maximum_score is None:
            raise forms.ValidationError(
                {'maximum_score': [err_message, ]}
            )

        if minimum_score >= maximum_score:
            raise forms.ValidationError(
                {'minimum_score': ["Minimum score must lower than Maximum score", ]}
            )

        if round(minimum_score, 2) != minimum_score:
            raise forms.ValidationError({'minimum_score': [error_message_invalid_score, ]})

        if round(maximum_score, 2) != maximum_score:
            raise forms.ValidationError({'maximum_score': [error_message_invalid_score, ]})

        minimum_score_overlap, maximum_score_overlap = self.score_range_overlap()
        if minimum_score_overlap or maximum_score_overlap:
            error_message_score_overlap = "Score range cannot overlap with other"
            errors_overlap = {}
            if minimum_score_overlap:
                errors_overlap['minimum_score'] = [error_message_score_overlap, ]
            if maximum_score_overlap:
                errors_overlap['maximum_score'] = [error_message_score_overlap, ]
            raise forms.ValidationError(errors_overlap)

        return cleaned_data

    def score_range_overlap(self):
        filter_parameters = {
            'minimum_score__lte': self.cleaned_data.get("maximum_score"),
            'maximum_score__gte': self.cleaned_data.get("minimum_score"),
            'partner': self.cleaned_data.get("partner")
        }
        if self.instance.id:
            filter_parameters['partner'] = self.instance.partner
            master_partner_config_product_lookups = \
                MasterPartnerConfigProductLookup.objects.exclude(pk=self.instance.id).filter(
                    **filter_parameters
                )
        else:
            master_partner_config_product_lookups = MasterPartnerConfigProductLookup.objects.filter(
                **filter_parameters
            )

        minimum_score_overlap = master_partner_config_product_lookups.filter(
            minimum_score__lte=self.cleaned_data.get("minimum_score"),
            maximum_score__gte=self.cleaned_data.get("minimum_score")).exists()

        maximum_score_overlap = master_partner_config_product_lookups.filter(
            minimum_score__lte=self.cleaned_data.get("maximum_score"),
            maximum_score__gte=self.cleaned_data.get("maximum_score")).exists()

        return minimum_score_overlap, maximum_score_overlap
