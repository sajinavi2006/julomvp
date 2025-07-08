from __future__ import unicode_literals


from django import forms


FILTER_CONDITION_CHOICES = [
    ('iexact', 'Sama persis'),
    ('icontains', 'Sebagian'),
    ('gt', 'Lebih besar'),
    ('gte', 'Lebih besar atau sama dengan'),
    ('lt', 'Lebih kecil'),
    ('lte', 'Lebih kecil atau sama dengan'),
]


class LenderOspTransactionSearchForm(forms.Form):

    FILTER_FIELD_CHOICES = [
        ('lender_osp_account__lender_account_name', 'Lender OSP Account'),
        ('balance_amount', 'Balance Amount'),
    ]

    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_condition = forms.ChoiceField(required=False, choices=FILTER_CONDITION_CHOICES)
    filter_keyword = forms.CharField(required=False)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_condition').clean(None)
        self.fields.get('filter_keyword').clean(None)


class LenderRepaymentSearchForm(forms.Form):

    FILTER_FIELD_CHOICES = [
        ('lender_osp_account__lender_account_name', 'Lender OSP Account'),
        ('balance_amount', 'Repayment Amount'),
    ]

    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_condition = forms.ChoiceField(required=False, choices=FILTER_CONDITION_CHOICES)
    filter_keyword = forms.CharField(required=False)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_condition').clean(None)
        self.fields.get('filter_keyword').clean(None)


class LenderAccountSearchForm(forms.Form):

    FILTER_FIELD_CHOICES = [
        ('lender_account_name', 'Lender Account Name'),
        ('balance_amount', 'Balance Amount'),
        ('total_outstanding_principal', 'Total Outstanding Pricipal'),
        ('total_outstanding_principal', 'Total Outstanding Pricipal'),
    ]

    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_condition = forms.ChoiceField(required=False, choices=FILTER_CONDITION_CHOICES)
    filter_keyword = forms.CharField(required=False)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_condition').clean(None)
        self.fields.get('filter_keyword').clean(None)
