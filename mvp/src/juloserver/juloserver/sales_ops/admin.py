from django.contrib import admin
from django import forms
from django.utils.safestring import mark_safe
from django.core.urlresolvers import reverse
from django.contrib.postgres.forms import JSONField as JSONFormField

from juloserver.julo.admin import JuloModelAdmin
from juloserver.julo.admin import CustomPrettyJSONWidget
from juloserver.sales_ops.models import (
    SalesOpsPrioritizationConfiguration,
    SalesOpsBucket,
    SalesOpsVendor,
    SalesOpsVendorBucketMapping,
    SalesOpsVendorAgentMapping
)


class SalesOpsPrioritizationConfigurationAdminForm(forms.ModelForm):
    class Meta:
        model = SalesOpsPrioritizationConfiguration
        exclude = []
        widgets = {
            'segment_name': forms.TextInput()
        }


class SalesOpsPrioritizationConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'segment_name',
        'r_score',
        'm_score',
        'prioritization',
        'is_active',
        'cdate'
    )
    list_filter = (
        'is_active',
    )

    form = SalesOpsPrioritizationConfigurationAdminForm


class SalesOpsVendorBucketMappingForm(forms.ModelForm):
    class Meta:
        model = SalesOpsVendorBucketMapping
        fields = '__all__'

    def clean(self):
        is_active = self.cleaned_data.get('is_active')
        vendor = self.cleaned_data.get('vendor')
        bucket = self.cleaned_data.get('bucket')
        if is_active:
            if bucket and not bucket.is_active:
                raise forms.ValidationError('Bucket "{}" is inactive'.format(bucket.code))
            if vendor and not vendor.is_active:
                raise forms.ValidationError('Vendor "{}" is inactive'.format(vendor.name))

        return self.cleaned_data


class SalesOpsVendorInline(admin.TabularInline):
    model = SalesOpsVendorBucketMapping
    form = SalesOpsVendorBucketMappingForm
    extra = 0


class SalesOpsBucketForm(forms.ModelForm):
    code = forms.CharField(
        required=True,
        help_text="Bucket code won't be editable after created"
    )
    scores = JSONFormField(required=True, widget=CustomPrettyJSONWidget)

    class Meta:
        model = SalesOpsBucket
        fields = '__all__'

    def clean_is_active(self):
        is_active = self.cleaned_data['is_active']
        if not is_active:
            mappings = SalesOpsVendorBucketMapping.objects.filter(
                bucket_id=self.instance.id, is_active=True).exists()
            if mappings:
                raise forms.ValidationError("Bucket is used by vendor_bucket_mapping")

        return is_active


class SalesOpsBucketAdmin(JuloModelAdmin):
    SCORES_TEMPLATE = {
        'r_scores': [],
        'm_scores': []
    }
    actions = None
    form = SalesOpsBucketForm
    inlines = [SalesOpsVendorInline]
    list_display = (
        'id',
        'code',
        'scores',
        'description',
        'is_active'
    )
    list_filter = ('is_active',)
    search_fields = ('id', 'code',)

    list_display_links = ('id', 'code',)
    update_readonly_fields = ['code',]

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        update_readonly_fields = list(getattr(self, 'update_readonly_fields', []))
        if obj:
            readonly_fields.extend(update_readonly_fields)

        return readonly_fields

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['scores'].initial = self.SCORES_TEMPLATE
        return form

    def has_delete_permission(self, request, obj=None):
        return False


class SalesOpsBucketInline(admin.TabularInline):
    model = SalesOpsVendorBucketMapping
    form = SalesOpsVendorBucketMappingForm
    fields = ('bucket', 'ratio', 'is_active', 'link_to_bucket')
    readonly_fields = ('bucket', 'ratio', 'is_active', 'link_to_bucket')

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def link_to_bucket(self, obj):
        if obj and obj.bucket:
            return mark_safe('''<a href="%s">
                                <img src="/static/admin/img/icon-changelink.svg" alt="Change">
                             </a>''' % \
                            reverse('admin:sales_ops_salesopsbucket_change',
                            args=(obj.bucket.id,)))
        return ""


class SalesOpsVendorForm(forms.ModelForm):
    class Meta:
        model = SalesOpsVendor
        fields = '__all__'

    def clean_is_active(self):
        is_active = self.cleaned_data['is_active']
        if not is_active:
            mappings = SalesOpsVendorBucketMapping.objects.filter(
                vendor_id=self.instance.id, is_active=True).exists()
            if mappings:
                raise forms.ValidationError("Vendor is used by vendor_bucket_mapping")

        return is_active


class SalesOpsVendorAdmin(JuloModelAdmin):
    actions = None
    form = SalesOpsVendorForm
    inlines = [SalesOpsBucketInline]
    list_display = (
        'id',
        'name',
        'is_active'
    )
    list_filter = ('is_active',)
    search_fields = ('id', 'name')

    list_display_links = ('id', 'name')

    def has_delete_permission(self, request, obj=None):
        return False


class SalesOpsVendorAgentMappingForm(forms.ModelForm):
    class Meta(object):
        fields = "__all__"

    def clean(self):
        cleaned_data = super(SalesOpsVendorAgentMappingForm, self).clean()
        agent_id = cleaned_data['agent_id']
        mappings = SalesOpsVendorAgentMapping.objects.filter(
            agent_id=agent_id, is_active=True
        ).exists()
        if mappings:
            raise forms.ValidationError("Agent already mapped")

        return cleaned_data


class SalesOpsVendorAgentMappingAdmin(JuloModelAdmin):
    fields = ('agent_id', 'vendor', 'is_active')
    list_display = (
        'id',
        'agent_id',
        'vendor',
        'is_active',
    )

    class Meta:
        model = SalesOpsVendorAgentMapping
        fields = '__all__'

    def get_form(self, request, obj=None, **kwargs):
        self.form = SalesOpsVendorAgentMappingForm
        return super(SalesOpsVendorAgentMappingAdmin, self).get_form(request, obj, **kwargs)


admin.site.register(SalesOpsPrioritizationConfiguration, SalesOpsPrioritizationConfigurationAdmin)
admin.site.register(SalesOpsBucket, SalesOpsBucketAdmin)
admin.site.register(SalesOpsVendor, SalesOpsVendorAdmin)
admin.site.register(SalesOpsVendorAgentMapping, SalesOpsVendorAgentMappingAdmin)
