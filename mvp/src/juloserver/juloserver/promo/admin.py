import io
import logging
import csv

from django import forms
from django.contrib import admin
from django.db import transaction
from django.forms import MultipleChoiceField

from juloserver.julo.admin import (
    JuloModelAdmin,
)
from juloserver.julo.models import (
    Partner,
    ProductLine,
    CreditMatrix,
    Agent,
)
from juloserver.julo.validators import CustomerWhitelistCSVFileValidator
from juloserver.payment_point.models import TransactionMethod
from juloserver.promo.constants import (
    PromoCodeTypeConst,
    PromoCodeBenefitConst,
    PromoCodeCriteriaConst,
    PromoCodeCriteriaTxnHistory,
    PromoBenefitType,
    PromoCodeTimeConst,
    WhitelistCSVFileValidatorConsts,
)
from juloserver.promo.models import (
    CriteriaControlList,
    PromoCode,
    PromoCodeCriteria,
    PromoCodeBenefit,
    PromoPage,
    PromoCodeAgentMapping,
)
from juloserver.promo.services import (
    group_customers_set,
    create_or_update_whitelist_criteria
)
from juloserver.sales_ops.constants import ScoreCriteria
from juloserver.sales_ops.models import SalesOpsRMScoring

logger = logging.getLogger(__name__)


class SelectizeMultipleChoiceField(MultipleChoiceField):
    def widget_attrs(self, widget):
        return {
            'class': 'selectize-choice',
        }


class SelectizeModelMultipleChoiceField(forms.ModelMultipleChoiceField):
    def widget_attrs(self, widget):
        return {
            'class': 'selectize-choice',
        }

    def label_from_instance(self, instance):
        """
        Purpose: clean up data display in multi-picklist based on the instance
        """
        if instance._meta.model == SalesOpsRMScoring:
            return instance.score
        return instance


class PromoCodeForm(forms.ModelForm):
    promo_code = forms.RegexField(required=True, regex=r'^[a-zA-Z0-9]{4,}$')
    product_line = SelectizeMultipleChoiceField(required=False)
    partner = SelectizeMultipleChoiceField(required=False)
    credit_score = SelectizeMultipleChoiceField(required=False)
    criteria = SelectizeModelMultipleChoiceField(
        required=False,
        queryset=PromoCodeCriteria.objects.order_by('name').all(),
    )

    type = forms.ChoiceField(
        required=True,
        choices=PromoCodeTypeConst.CHOICES,
    )

    def clean_cashback_amount(self):
        if self.cleaned_data['type'] != PromoCodeTypeConst.APPLICATION:
            return self.cleaned_data.get('cashback_amount')

        cashback_amount = self.cleaned_data.get('cashback_amount')
        if self.cleaned_data['promo_benefit'] == PromoBenefitType.CASHBACK:
            if cashback_amount is None:
                raise forms.ValidationError("Missing cashback amount")
            elif cashback_amount < 0:
                raise forms.ValidationError("Cashback amount can't less then zero")
        else:
            if cashback_amount is not None:
                raise forms.ValidationError("promo benefit is not cashback")

        return self.cleaned_data['cashback_amount']

    def clean_criteria(self):
        value = self.cleaned_data.get('criteria')
        if not value:
            return None

        return [criteria.id for criteria in value]

    def clean_is_public(self):
        is_public_value = self.cleaned_data['is_public']
        is_active_value = self.cleaned_data['is_active']
        if is_public_value and not is_active_value:
            raise forms.ValidationError("Can't public when is_active is turned off")

        return is_public_value

    def clean(self):
        cleaned_data = super(PromoCodeForm, self).clean()
        promo_code = cleaned_data.get('promo_code')
        promo_type = cleaned_data.get('type')
        if promo_type != PromoCodeTypeConst.APPLICATION and promo_code:
            cleaned_data['promo_code'] = promo_code.upper()
        return cleaned_data

    def __init__(self, *args, **kwargs):
        super(PromoCodeForm, self).__init__(*args, **kwargs)

        if self.data:
            promo_type = self.data.get('type')
            if promo_type == PromoCodeTypeConst.APPLICATION:
                self.fields['product_line'].required = True
                self.fields['partner'].required = True
                self.fields['credit_score'].required = True
            else:
                self.fields['criteria'].required = True
                self.fields['promo_code_benefit'].required = True


class PromoCodeAdmin(JuloModelAdmin):
    search_fields = ('promo_code', 'promo_name')
    list_filter = ('is_active', 'type', 'promo_code_benefit')
    list_display = (
        'promo_name',
        'promo_code',
        'type',
        'is_active',
        'is_public',
        'start_date',
        'end_date',
        'promo_code_benefit'
    )

    fieldsets = (
        ('General', {
            'fields': ('promo_name', 'promo_code', 'description', 'is_active', 'is_public','start_date', 'end_date', 'type')
        }),
        ('Application Promo Setting', {
            'classes': ('application-promo-setting', ),
            'fields': (
                'partner', 'product_line', 'credit_score', 'promo_benefit', 'cashback_amount',
            )
        }),
        ('Loan Promo Setting', {
            'classes': ('loan-promo-setting', ),
            'fields': (
                'criteria', 'promo_code_benefit',
            )
        })
    )

    add_form_template = "promo/custom_admin/promo_code.html"
    change_form_template = "promo/custom_admin/promo_code.html"

    def get_form(self, request, obj=None, *args, **kwargs):
        kwargs['form'] = PromoCodeForm
        form = super(PromoCodeAdmin, self).get_form(request, *args, **kwargs)

        selected_all = (('All', 'All'),)

        product_line = tuple(
            ProductLine.objects.values_list('product_line_code', 'product_line_type')
        )

        form.base_fields['product_line'].choices = product_line + selected_all
        form.base_fields['partner'].choices = tuple(
            Partner.objects.values_list('name', 'name')) + selected_all

        credit_choices = (
            ('A+', 'A+'), ('A-', 'A-'), ('A', 'A'), ('B+', 'B+'),
            ('B-', 'B-'), ('B', 'B'), ('C', 'C')
        )

        form.base_fields['credit_score'].choices = credit_choices + selected_all

        return form


class BaseJsonValueForm(forms.ModelForm):
    value_field_mapping = {}
    optional_value_fields = set()

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance:
            for field_name in self.fields.keys():
                if not field_name.startswith('value_'):
                    continue

                value_field_name = field_name.replace('value_', '')
                value = instance.get_value(value_field_name)
                self.fields[field_name].initial = value

        # Set the required fields, optional fields
        if self.data:
            current_type = self.data.get('type')
            fields_mappings = self.value_field_mapping.get(current_type, set())
            required_fields = fields_mappings - self.optional_value_fields

            for field_name in required_fields:
                self.fields[f'value_{field_name}'].required = True

            for field_name in self.optional_value_fields:
                self.fields[f'value_{field_name}'].required = False

    def clean(self):
        cleaned_data = super(BaseJsonValueForm, self).clean()

        for field_name, field in self.fields.items():
            if not isinstance(field, forms.ModelMultipleChoiceField):
                continue

            data = cleaned_data.get(field_name)
            if not data:
                continue

            key = field.to_field_name if field.to_field_name else 'pk'
            cleaned_data[field_name] = [getattr(obj, key) for obj in data]

        return cleaned_data

    def save(self, commit=True):
        self.instance.value = {}
        for field_name in self.fields.keys():
            value = self.cleaned_data[field_name]
            if field_name.startswith('value_') and value is not None:
                if isinstance(value, str) and not value:
                    # remove empty string value, but keep value 0 as integer setting
                    continue
                value_field_name = field_name.replace('value_', '')
                self.instance.value[value_field_name] = value
        return super().save(commit)


class PromoCodeBenefitForm(BaseJsonValueForm):
    value_field_mapping = PromoCodeBenefitConst.VALUE_FIELD_MAPPING
    optional_value_fields = PromoCodeBenefitConst.OPTIONAL_VALUE_FIELDS

    name = forms.CharField(required=True)
    type = forms.ChoiceField(required=True, choices=PromoCodeBenefitConst.CHOICES)

    value_percent = forms.IntegerField(required=False,
                                       help_text="Value before per cent (0-100). Ex: 10, 25, 50")
    value_duration = forms.IntegerField(required=False, help_text="Installment duration")
    value_max_cashback = forms.IntegerField(required=False)
    value_max_amount = forms.IntegerField(required=False, help_text='Max amount discount per month')
    value_amount = forms.IntegerField(required=False)
    value_percentage_provision_rate_discount = forms.FloatField(
        required=False,
        label='Provision rate discount',
        help_text='Provision rate discount percentage. Ex: 0.01, 0.02, 0.03.' \
        'adjust_provision_rate = original_provision_rate - value_percentage_provision_discount',
    )

    class Meta:
        model = PromoCodeBenefit
        exclude = ('value',)

    def clean(self):
        clean_data = super(BaseJsonValueForm, self).clean()
        non_zero_value_fields = ['value_percent', 'value_duration', 'value_max_cashback'
                                 'value_max_amount', 'value_amount']
        for k_field in non_zero_value_fields:
            if clean_data.get(k_field) is not None and clean_data[k_field] < 1:
                raise forms.ValidationError({k_field: "0 value is not allowed in this field"})
        return clean_data


class PromoCodeDynamicValueBaseAdmin(JuloModelAdmin):
    value_field_mapping = {}
    type_choices = []

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        self.init_fieldsets()
        super(PromoCodeDynamicValueBaseAdmin, self).__init__(*args, **kwargs)

    @classmethod
    def init_fieldsets(cls):
        for benefit_type, fields in cls.value_field_mapping.items():
            form_fields = [f'value_{field_name}' for field_name in fields]

            benefit_text = None
            for choice in cls.type_choices:
                if choice[0] == benefit_type:
                    benefit_text = choice[1]
                    break

            cls.fieldsets.append((
                f'{benefit_text}', {
                    'classes': (f'section_{benefit_type}', ),
                    'fields': form_fields
                }
            ))


class PromoCodeBenefitAdmin(PromoCodeDynamicValueBaseAdmin):
    form = PromoCodeBenefitForm
    add_form_template = "promo/custom_admin/promo_code_benefit.html"
    change_form_template = "promo/custom_admin/promo_code_benefit.html"
    value_field_mapping = PromoCodeBenefitConst.VALUE_FIELD_MAPPING
    type_choices = PromoCodeBenefitConst.CHOICES

    list_filter = ('type',)
    search_fields = ('name', )
    list_display = (
        'id',
        'name',
        'type',
        'value',
        'udate',
        'promo_page',
    )

    list_display_links = ('id', 'name',)

    fieldsets = [
        ('General', {
            'classes': ('', ),
            'fields': ['name', 'type', 'promo_page']
        }),
    ]


class PromoCodeCriteriaForm(BaseJsonValueForm):
    value_field_mapping = PromoCodeCriteriaConst.VALUE_FIELD_MAPPING
    optional_value_fields = PromoCodeCriteriaConst.OPTIONAL_VALUE_FIELDS

    name = forms.CharField(required=True)
    type = forms.ChoiceField(required=True, choices=PromoCodeCriteriaConst.CHOICES)

    value_limit = forms.IntegerField(
        label='Limit',
        required=False,
        help_text="Total usage limit per customer"
    )
    value_limit_per_promo_code = forms.IntegerField(
        label='Limit',
        required=False,
        help_text='Total usage limit per promo code'
    )
    value_partners = SelectizeModelMultipleChoiceField(
        label='Partner',
        required=False,
        queryset=Partner.objects.order_by('name').all()
    )
    value_product_line_codes = SelectizeModelMultipleChoiceField(
        label='Product Line',
        required=False,
        queryset=ProductLine.objects.all()
    )
    value_transaction_method_ids = SelectizeModelMultipleChoiceField(
        label='Transaction Method',
        required=False,
        queryset=TransactionMethod.objects.all()
    )
    value_credit_scores = SelectizeModelMultipleChoiceField(
        label='Credit Score',
        required=False,
        queryset=CreditMatrix.objects.distinct('score').order_by('score').all(),
        to_field_name='score'
    )
    value_minimum_loan_amount = forms.IntegerField(
        label='Minimum loan amount',
        required=False,
        min_value=0,
    )
    value_minimum_tenor = forms.IntegerField(
        label='Minimum tenor',
        required=False,
        help_text='Loan duration must be greater than or equal this value to apply the promo code',
        min_value=0
    )
    value_transaction_history = forms.ChoiceField(
        label='Transaction history',
        required=False,
        choices=PromoCodeCriteriaTxnHistory.CHOICE,
    )
    value_r_scores = SelectizeModelMultipleChoiceField(
        label='R-Score',
        required=False,
        queryset=SalesOpsRMScoring.objects.filter(
            is_active=True, criteria=ScoreCriteria.RECENCY
        ).distinct('score').order_by('score').all(),
        to_field_name='score'
    )
    value_whitelist_customers_file = forms.FileField(
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
                'accept': '.csv',
            }
        ),
        label="File Upload",
        required=False,
        error_messages={'required': 'Please choose the CSV file'},
        validators=[
            CustomerWhitelistCSVFileValidator(
                allowed_extensions=WhitelistCSVFileValidatorConsts.ALLOWED_EXTENSIONS,
                max_size=WhitelistCSVFileValidatorConsts.MAX_FILE_SIZE,
                with_header=False
            )
        ]
    )
    value_times = forms.ChoiceField(
        label='Time',
        required=False,
        choices=PromoCodeTimeConst.CHOICES,
    )
    value_min_churn_day = forms.IntegerField(
        label='Min churn day',
        required=False,
        help_text="Minimum churn day",
        min_value=0
    )
    value_max_churn_day = forms.IntegerField(
        label='Max churn day',
        required=False,
        help_text="Maximum churn day",
        min_value=0
    )
    value_min_days_before = forms.IntegerField(
        label='Minimum application approved days',
        required=False,
        help_text="The nearest days that application is approved",
        min_value=0
    )
    value_max_days_before = forms.IntegerField(
        label='Maximum application approved days',
        required=False,
        help_text="The furthest days that application is approved",
        min_value=0
    )
    value_b_score = forms.FloatField(
        label='B Score min threshold',
        required=False,
        help_text="B Score min threshold",
        min_value=0,
        max_value=1,
    )

    class Meta:
        model = PromoCodeCriteria
        exclude = ('value',)

    def clean(self):
        cleaned_data = super().clean()

        # validate churn_day criteria
        min_churn_day = cleaned_data.get('value_min_churn_day')
        max_churn_day = cleaned_data.get('value_max_churn_day')
        if (
            min_churn_day is not None
            and max_churn_day is not None
            and min_churn_day > max_churn_day
        ):
            raise forms.ValidationError(
                "Max churn day must be greater than or equal min churn day"
            )

        # validate application_approved_day criteria
        min_days_before = cleaned_data.get('value_min_days_before')
        max_days_before = cleaned_data.get('value_max_days_before')
        if (
            min_days_before is not None
            and max_days_before is not None
            and min_days_before > max_days_before
        ):
            raise forms.ValidationError(
                "Max day must be greater than or equal min day"
            )

    def save(self, commit=True):
        self.instance.value = {}
        for field_name in self.fields.keys():
            value = self.cleaned_data[field_name]
            if field_name.startswith('value_') and (value or value == 0):
                value_field_name = field_name.replace('value_', '')
                self.instance.value[value_field_name] = value

        return super(BaseJsonValueForm, self).save(commit)


class PromoCodeCriteriaAdmin(PromoCodeDynamicValueBaseAdmin):
    form = PromoCodeCriteriaForm
    add_form_template = "promo/custom_admin/promo_code_benefit.html"
    change_form_template = "promo/custom_admin/promo_code_benefit.html"
    value_field_mapping = PromoCodeCriteriaConst.VALUE_FIELD_MAPPING
    type_choices = PromoCodeCriteriaConst.CHOICES

    list_filter = ('type',)
    search_fields = ('name', )
    list_display = (
        'id',
        'name',
        'type',
        'value',
        'udate',
    )

    list_display_links = ('id', 'name',)

    fieldsets = [
        ('General', {
            'classes': ('', ),
            'fields': ['name', 'type']
        }),
    ]

    def save_model(self, request, obj, form, change):
        customers_insert_set = set()
        customers_update_set = set()
        customers_del_set = set()
        if obj.type == PromoCodeCriteriaConst.WHITELIST_CUSTOMERS:
            csv_in_mem = obj.value['whitelist_customers_file']
            obj.value = {}

            # process csv in memory
            decoded_file = csv_in_mem.read().decode('utf-8')
            csv_io = io.StringIO(decoded_file)
            csv_reader = csv.reader(csv_io, delimiter=',')
            customers_new_set = {int(row[0]) for row in csv_reader}

            # have two customers set: exists in db and new from csv
            # customers_new_set from csv will insert/update to db
            # the rest will be deleted (update is_deleted = True)
            customers_existed_set = set()
            if change:
                customers_existed_set = set(CriteriaControlList.objects.filter(
                    promo_code_criteria_id=obj.id
                ).values_list('customer_id', flat=True))
            customers_insert_set, customers_update_set, customers_del_set =\
                group_customers_set(customers_new_set, customers_existed_set)

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if obj.type == PromoCodeCriteriaConst.WHITELIST_CUSTOMERS:
                create_or_update_whitelist_criteria(
                    customers_insert_set, customers_update_set, customers_del_set, obj
                )

    def group_customers_set(self, customers_new_set, customers_existed_set):
        '''
        insert set:
          - come from customers_new_set except common set between new and existed set \n
        common set (aka update_set):
          - customers are in both new and old set
          - will update is_deleted = False \n
        del set:
          - customers who is in db table, but not belong in new set,
          - will be deleted (is_deleted = True)
        '''
        customers_insert_set = customers_new_set
        customers_update_set = set()
        customers_del_set = set()
        if len(customers_existed_set):
            customers_insert_set = customers_new_set.difference(customers_existed_set)  # or new - exist
            customers_del_set = customers_existed_set.difference(customers_new_set)
            customers_update_set = customers_new_set.intersection(customers_existed_set)

        return customers_insert_set, customers_update_set, customers_del_set


class PromoPageAdminForm(forms.ModelForm):
    title = forms.CharField(required=True)


class PromoPageAdmin(JuloModelAdmin):
    form = PromoPageAdminForm
    list_display = [
        'id', 'title', 'is_active',
    ]
    list_display_links = [
        'id', 'title',
    ]
    list_filter = [
        'is_active',
    ]
    search_fields = [
        'title',
    ]
    fieldsets = (
        (None, {'fields': ('title',)}),
        ('Page Content', {'fields': ('content',)})
    )


class AgentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return "{} : {}".format(obj.id, obj.user)


class AgentUsernameFilter(admin.SimpleListFilter):
    title = 'Agent'  # Label for the filter
    parameter_name = 'agent_id'

    def lookups(self, request, model_admin):
        agents = Agent.objects.all()
        return [(agent.id, agent.user.username) for agent in agents]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(agent_id=self.value())
        return queryset


class PromoCodeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return "{} : {}".format(obj.id, obj.promo_name)


class PromoCodeAgentMappingForm(forms.ModelForm):
    def clean(self):
        agent = self.cleaned_data.get('agent_id', None)
        if agent:
            self.cleaned_data['agent_id'] = agent.id
        return super().clean()


class PromoCodeAgentMappingAdmin(JuloModelAdmin):
    list_display = (
        'promo_code',
        'get_agent_username',
    )
    readonly_fields = ()
    search_fields = ('promo_code__promo_code', 'promo_code__promo_name',)
    list_filter = ('promo_code', AgentUsernameFilter)
    ordering = ('-id',)
    form = PromoCodeAgentMappingForm

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'promo_code':
            return PromoCodeChoiceField(queryset=PromoCode.objects.filter(
                type=PromoCodeTypeConst.LOAN
            ).all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == 'agent_id':
            form_field = AgentChoiceField(queryset=Agent.objects.all())
            form_field.label = 'Agent'
            return form_field
        return super().formfield_for_dbfield(db_field, **kwargs)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if search_term:
            agent_ids = list(
                Agent.objects
                    .filter(user__username=search_term)
                    .values_list('id', flat=True)
            )
            queryset |= self.model.objects.filter(agent_id__in=agent_ids)
        return queryset, use_distinct

    def get_agent_username(self, obj):
        agent = Agent.objects.filter(id=obj.agent_id).last()
        return agent.user.username if agent and agent.user else 'Unknown'

    get_agent_username.short_description = 'Agent'


admin.site.register(PromoCodeAgentMapping, PromoCodeAgentMappingAdmin)
admin.site.register(PromoCode, PromoCodeAdmin)
admin.site.register(PromoCodeBenefit, PromoCodeBenefitAdmin)
admin.site.register(PromoCodeCriteria, PromoCodeCriteriaAdmin)
admin.site.register(PromoPage, PromoPageAdmin)
