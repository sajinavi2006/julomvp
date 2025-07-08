from django import forms


class BalanceConsolidationVerificationCRMConditionFilterForm(forms.Form):
    FILTER_FIELD_CHOICES = [
        ('balance_consolidation__customer_id', 'Customer ID'),
        ('balance_consolidation__customer__fullname', 'Full Name'),
        ('balance_consolidation__customer__email', 'Email'),
    ]

    FILTER_CONDITION_CHOICES = [
        ('all', 'All'),
        ('draft', 'Draft'),
        ('on_review', 'On Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('abandoned', 'Abandoned'),
        ('cancelled', 'Cancelled'),
        ('disbursed', 'Disbursed'),
    ]

    filter_field = forms.ChoiceField(required=False, choices=FILTER_FIELD_CHOICES)
    filter_condition = forms.ChoiceField(required=False, choices=FILTER_CONDITION_CHOICES)
    filter_keyword = forms.CharField(required=False)
    sort_q = forms.CharField(widget=forms.HiddenInput(), required=False)

    def reset_filter(self):
        self.fields.get('filter_field').clean(None)
        self.fields.get('filter_condition').clean(None)
        self.fields.get('filter_keyword').clean(None)
