import logging
import os
from django.conf import settings
from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils import timezone
from datetime import timedelta


from juloserver.julo.utils import execute_after_transaction_safely
from juloserver.julo.admin import JuloModelAdmin
from juloserver.julo.models import Image
from juloserver.julo.utils import upload_file_to_oss
from juloserver.julocore.constants import DbConnectionAlias
from juloserver.julocore.context_manager import db_transactions_atomic
from juloserver.loyalty.constants import (
    MissionCriteriaTypeConst,
    MissionRewardTypeConst,
    MissionTargetTypeConst,
)
from juloserver.loyalty.forms import (
    DailyCheckinForm,
    MissionConfigForm,
    MissionCriteriaForm,
    MissionRewardForm,
    MissionTargetForm,
)
from juloserver.loyalty.models import (
    DailyCheckin,
    MissionConfig,
    MissionCriteria,
    MissionReward,
    MissionConfigCriteria,
    MissionTarget,
    MissionConfigTarget,
)
from juloserver.loyalty.services.mission_related import (
    add_criteria_mappings,
    delete_whitelist_mission_criteria_on_redis,
    upload_whitelist_customers_csv_to_oss,
    add_target_mappings,
)
from juloserver.loyalty.tasks import (
    process_whitelist_mission_criteria,
    delete_mission_progress_task,
)
from juloserver.portal.core import functions

logger = logging.getLogger(__name__)


class DailyCheckinAdmin(JuloModelAdmin):
    list_display = (
        'id',
        'daily_reward',
        'reward',
        'max_days_reach_bonus',
        'is_latest',
    )
    actions = None
    form = DailyCheckinForm
    update_readonly_fields = ['daily_reward', 'reward', 'max_days_reach_bonus', 'is_latest']

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        update_readonly_fields = list(getattr(self, 'update_readonly_fields', []))
        if obj:
            readonly_fields.extend(update_readonly_fields)

        return readonly_fields

    def save_model(self, request, obj, form, change):
        if change:
            return

        DailyCheckin.objects.filter(is_latest=True).update(is_latest=False)
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False


class MissionDynamicValueBaseAdmin(JuloModelAdmin):
    value_field_mapping = {}
    type_choices = []

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        self.init_fieldsets()
        super(MissionDynamicValueBaseAdmin, self).__init__(*args, **kwargs)

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

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        disabled_fields = ['category', 'type']
        for field_name in disabled_fields:
            if obj:
                form.base_fields[field_name].disabled = True
            else:
                form.base_fields[field_name].disabled = False

        return form


class MissionConfigAdmin(JuloModelAdmin):
    form = MissionConfigForm
    list_display = (
        'id',
        'title',
        'category',
        'max_repeat',
        'repetition_delay_days',
        'expiry_date',
        'api_version',
        'is_active',
        'is_deleted',
    )
    add_form_template = "custom_admin/mission_config.html"
    change_form_template = "custom_admin/mission_config.html"
    readonly_fields = ('icon_image_preview',)
    update_readonly_fields = [
        'max_repeat', 'repetition_delay_days', 'expiry_date'
    ]

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        update_readonly_fields = list(getattr(self, 'update_readonly_fields', []))
        if obj:
            if obj.is_deleted:
                update_readonly_fields.append('is_deleted')
            readonly_fields.extend(update_readonly_fields)

        return readonly_fields

    def save_model(self, request, obj, form, change):
        with db_transactions_atomic(DbConnectionAlias.utilization()):
            criteria_ids = form.cleaned_data.pop('criteria', [])
            target_ids = form.cleaned_data.pop('targets', [])
            super(MissionConfigAdmin, self).save_model(request, obj, form, change)
            if not change:
                add_criteria_mappings(obj, criteria_ids)
                add_target_mappings(obj, target_ids)
        if request.FILES and request.FILES['icon_image']:
            icon_image = request.FILES['icon_image']
            _, file_extension = os.path.splitext(icon_image.name)

            image = Image()
            image.image_source = obj.pk
            image.image_type = 'loyalty_icon'
            image.save()

            remote_path = 'loyalty/icon{}'.format(image.pk)
            image.update_safely(url=remote_path)
            file = functions.upload_handle_media(icon_image, "loyalty/icon")
            if file:
                upload_file_to_oss(
                    settings.OSS_MEDIA_BUCKET,
                    file['file_name'],
                    remote_path
                )
        # Delete all mission progresses 1 day after mission config is_deleted
        if obj.is_deleted:
            execute_time = timezone.localtime(timezone.now()) + timedelta(days=1)
            delete_mission_progress_task.apply_async(
                (obj.id, ),
                eta=execute_time
            )

    @staticmethod
    def icon_image_preview(obj):
        return mark_safe('<img src="{url}" width="{width}" />'.format(
            url=obj.icon,
            width=300
        ))


class MissionCriteriaAdmin(MissionDynamicValueBaseAdmin):
    form = MissionCriteriaForm
    add_form_template = "custom_admin/mission_criteria.html"
    change_form_template = "custom_admin/mission_criteria.html"
    value_field_mapping = MissionCriteriaTypeConst.VALUE_FIELD_MAPPING
    type_choices = MissionCriteriaTypeConst.CHOICES

    list_filter = ('type',)
    search_fields = ('type', )
    list_display = (
        'id',
        'name',
        'category',
        'type',
        'value',
        'udate',
    )

    list_display_links = ('id', 'name',)

    fieldsets = [
        ('General', {
            'classes': ('general', ),
            'fields': ['id', 'category', 'type', 'name']
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        # Check if the user has permission to delete the object
        if obj and MissionConfigCriteria.objects.filter(criteria_id=obj.id).exists():
            # Optionally, customize the error message
            self.message_user(
                request, "This object is already in use and cannot be deleted",
                level='warning'
            )
            return False
        return True

    def save_model(self, request, obj, form, change):
        if obj.type == MissionCriteriaTypeConst.WHITELIST_CUSTOMERS and not change:
            with db_transactions_atomic(DbConnectionAlias.utilization()):
                csv_in_mem = request.FILES.get('value_whitelist_customers_file')
                obj.value.pop('whitelist_customers_file')
                super(MissionCriteriaAdmin, self).save_model(request, obj, form, change)
                upload_whitelist_customers_csv_to_oss(obj, csv_in_mem)
                execute_after_transaction_safely(
                    lambda: process_whitelist_mission_criteria.delay(obj.id)
                )
        else:
            return super(MissionCriteriaAdmin, self).save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        delete_whitelist_mission_criteria_on_redis(obj)
        obj.delete()


class MissionRewardAdmin(MissionDynamicValueBaseAdmin):
    form = MissionRewardForm
    add_form_template = "custom_admin/mission_reward.html"
    change_form_template = "custom_admin/mission_reward.html"
    value_field_mapping = MissionRewardTypeConst.VALUE_FIELD_MAPPING
    type_choices = MissionRewardTypeConst.CHOICES

    list_filter = ('type',)
    search_fields = ('type', )
    list_display = (
        'id',
        'name',
        'category',
        'type',
        'value',
        'udate',
    )

    list_display_links = ('id', 'name',)

    fieldsets = [
        ('General', {
            'classes': ('', ),
            'fields': ['id', 'category', 'type', 'name']
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        # Check if the user has permission to delete the object
        if obj and MissionConfig.objects.filter(reward_id=obj.id).exists():
            # Optionally, customize the error message
            self.message_user(
                request, "This object is already in use and cannot be deleted",
                level='warning'
            )
            return False
        return True


class MissionTargetAdmin(MissionDynamicValueBaseAdmin):
    form = MissionTargetForm
    add_form_template = "custom_admin/mission_target.html"
    change_form_template = "custom_admin/mission_target.html"
    value_field_mapping = MissionTargetTypeConst.VALUE_FIELD_MAPPING
    type_choices = MissionTargetTypeConst.CHOICES

    list_filter = ('type',)
    search_fields = ('type', )
    list_display = (
        'id',
        'name',
        'category',
        'type',
        'value',
        'udate',
    )

    list_display_links = ('id', 'name',)

    fieldsets = [
        ('General', {
            'classes': ('general', ),
            'fields': ['id', 'category', 'type', 'name']
        }),
    ]

    def has_delete_permission(self, request, obj=None):
        # Check if the user has permission to delete the object
        if obj and MissionConfigTarget.objects.filter(target_id=obj.id).exists():
            # Optionally, customize the error message
            self.message_user(
                request, "This object is already in use and cannot be deleted",
                level='warning'
            )
            return False
        return True

    def save_model(self, request, obj, form, change):
        value_keys = ['value_recurring', 'value_total_transaction_amount']
        for key in value_keys:
            if form.cleaned_data.get(key) is not None:
                obj.value = form.cleaned_data[key]
                break
        super(MissionTargetAdmin, self).save_model(request, obj, form, change)


admin.site.register(DailyCheckin, DailyCheckinAdmin)
admin.site.register(MissionConfig, MissionConfigAdmin)
admin.site.register(MissionReward, MissionRewardAdmin)
admin.site.register(MissionCriteria, MissionCriteriaAdmin)
admin.site.register(MissionTarget, MissionTargetAdmin)
