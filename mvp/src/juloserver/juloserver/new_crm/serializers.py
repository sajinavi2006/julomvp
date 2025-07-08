import io
from copy import deepcopy
from datetime import datetime
from itertools import chain
from typing import List, Union
from django.conf import settings
import pandas as pd
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile

from django.db import transaction
from django.db.models import F, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from juloserver.application_flow.models import ApplicationRiskyCheck
from juloserver.application_flow.services import (
    check_hsfbp_bypass,
    check_sonic_bypass,
    is_experiment_application,
)
from juloserver.julo.application_checklist import application_checklist_update
from juloserver.julo.banks import BankManager
from juloserver.julo.models import (
    Application,
    ApplicationCheckList,
    ApplicationCheckListComment,
    ApplicationFieldChange,
    ApplicationNote,
    ApplicationTemplate,
    LoanPurpose,
    ProductLine,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
)
from juloserver.julo.services import (
    get_application_comment_list,
    get_undisclosed_expense_detail,
    update_application_checklist_data,
    update_application_field,
)
from juloserver.julo.services2.high_score import check_high_score_full_bypass
from juloserver.new_crm.constant import (
    COLL_ROLES,
    FRONTEND_EXTRA_FIELDS,
    FRONTEND_FIELD_MAP,
    DVCFilterMapper,
    MAXIMUM_FILE_SIZE_UPLOAD_USERS,
    UserSegmentError,
)
from juloserver.new_crm.services.application_services import (
    create_application_checklist_comment_data,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.streamlined_communication.models import StreamlinedCommunicationSegment


class BasicAppDetailSerializer(serializers.ModelSerializer):
    status = serializers.IntegerField(source='application_status_id')
    phone = serializers.CharField(source='mobile_phone_1')
    email = serializers.CharField()
    name = serializers.CharField(source='fullname')
    account = serializers.IntegerField(source='account_id')
    tags = serializers.SerializerMethodField('application_tags')
    app_tabs = serializers.SerializerMethodField()
    is_highscore_full_bypass = serializers.SerializerMethodField()
    is_sonic_bypass = serializers.SerializerMethodField()
    fraud_list = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            'status',
            'phone',
            'email',
            'name',
            'account',
            'tags',
            'app_tabs',
            'tags',
            'is_highscore_full_bypass',
            'is_sonic_bypass',
            'fraud_list',
        ]
        read_only_fields = fields

    def application_tags(self, app_obj):
        tags = []
        if app_obj.is_warning:
            tags.append('alert')
        if app_obj.is_uw_overhaul:
            tags.append('new flow')
        return tags

    def get_app_tabs(self, app_obj):
        from juloserver.new_crm.services.application_services import get_tab_list

        user = self.context.get('user')
        if not user:
            return None
        data = get_tab_list(app_obj, user.groups.all())
        return data

    def get_is_highscore_full_bypass(self, app):
        return check_hsfbp_bypass(app) if is_experiment_application(app.id,
            'ExperimentUwOverhaul') and app.is_julo_one() else check_high_score_full_bypass(app)

    def get_is_sonic_bypass(self, app):
        return check_sonic_bypass(app)

    def get_fraud_list(self, app):
        risky_checklist = ApplicationRiskyCheck.objects.filter(application=app).last()
        return None if not risky_checklist else risky_checklist.get_fraud_list()


class AppDetailSerializer(serializers.ModelSerializer):
    loan_purpose = serializers.CharField()
    credit_score = serializers.SerializerMethodField()
    credit_score_message = serializers.SerializerMethodField()
    imei = serializers.CharField(source='device.imei')
    dob = serializers.DateField()
    product_line = serializers.CharField(source='product_line.product_line_code')
    marital_status = serializers.ChoiceField(choices=ApplicationTemplate.MARITAL_STATUS_CHOICES)
    payday = serializers.IntegerField(min_value=1, max_value=28)
    job_start = serializers.DateField()
    address = serializers.SerializerMethodField()
    gender = serializers.ChoiceField(choices=ApplicationTemplate.GENDER_CHOICES)
    occupied_since = serializers.DateField()
    dialect = serializers.ChoiceField(choices=ApplicationTemplate.DIALECT_CHOICES)
    close_kin_relationship = serializers.ChoiceField(
        choices=ApplicationTemplate.KIN_RELATIONSHIP_CHOICES)
    kin_gender = serializers.ChoiceField(choices=ApplicationTemplate.KIN_GENDER_CHOICES)
    kin_relationship = serializers.ChoiceField(choices=ApplicationTemplate.KIN_RELATIONSHIP_CHOICES)

    facebook_fullname = serializers.CharField(source='facebook_data.fullname')
    facebook_email = serializers.CharField(source='facebook_data.email')
    facebook_gender = serializers.CharField(source='facebook_data.gender')
    facebook_birth_date = serializers.CharField(source='facebook_data.dob')
    facebook_id = serializers.CharField(source='facebook_data.facebook_id')
    facebook_friend_count = serializers.CharField(source='facebook_data.friend_count')
    facebook_open_date = serializers.DateField(source='facebook_data.open_date')
    undisclosed_expense = serializers.SerializerMethodField()
    has_whatsapp_1 = serializers.BooleanField()
    has_whatsapp_2 = serializers.BooleanField()
    vehicle_ownership_1 = serializers.ChoiceField(
        choices=ApplicationTemplate.VEHICLE_OWNERSHIP_CHOICES)

    class Meta:
        model = Application
        exclude = [
            'id',
            'cdate',
            'udate',
            'workflow',
            'device',
            'bss_eligible',
            'is_fdc_risky',
            'validated_qr_code',
            'is_deleted',
        ]
        read_only_fields = [
            'application_status',
            'email',
            'customer',
            'account',
            'dob',
            'credit_score',
            'credit_score_message',
            'marketing_source',
            'code_referral',
            'imei',
            'app_version',
            'occupied_since',
            'home_status',
            'last_education',
            'college',
            'major',
            'graduation_year',
            'gpa',
            'is_own_phone',
            'twitter_username',
            'instagram_username',
            'facebook_data',
            'job_type',
            'job_industry',
            'job_description',
            'income_1',
            'income_2',
            'income_3',
            'has_other_income',
            'other_income_source',
            'vehicle_type_1',
            'undisclosed_expense',
            'facebook_fullname',
            'facebook_email',
            'facebook_gender',
            'facebook_birth_date',
            'facebook_id',
            'facebook_friend_count',
            'facebook_open_date'
        ]

    def get_credit_score(self, app):
        score, message = app.credit_score
        return score

    def get_credit_score_message(self, app):
        score, message = app.credit_score
        return message

    def get_address(self, app):
        return {
            'provinsi': app.address_provinsi,
            'kabupaten': app.address_kabupaten,
            'kecamatan': app.address_kecamatan,
            'kelurahan': app.address_kelurahan,
            'street_num': app.address_street_num,
            'kodepos': app.address_kodepos
        }

    def get_undisclosed_expense(self, app):
        return get_undisclosed_expense_detail(app.id, 'total_current_debt')

    @staticmethod
    def output_filter_groups(field_name: str) -> list:
        """
        Get filter group the field belongs with

        :param field_name: Field for checking its group.
        :return: List of filter group .
        """
        filter_groups = []
        if field_name in DVCFilterMapper.sd_group_fields:
            filter_groups.append('sd')
        if field_name in DVCFilterMapper.dv_group_fields:
            filter_groups.append('dv')
        if field_name in DVCFilterMapper.pve_group_fields:
            filter_groups.append('pve')
        if field_name in DVCFilterMapper.pva_group_fields:
            filter_groups.append('pva')
        if field_name in DVCFilterMapper.fin_group_fields:
            filter_groups.append('fin')
        if field_name in DVCFilterMapper.coll_group_fields:
            filter_groups.append('coll')

        return filter_groups

    @staticmethod
    def fetch_application_check_list(application_id, field_name, user_roles, application_comments):
        """
        Construct checklist and comment data for a field_name
        Args:
            application_id (int): Application model id.
            field_name (str): The field_name of application_check_list.
            user_roles (list): A list of user_roles in string
            application_comments (Union[QuerySet, List[ApplicationCheckListComment]): List or
                QuerySet of ApplicationCheckListComment model data.

        Returns:
            dict: Dictionary of ApplicationCheckList with any comments available grouped together.
        """
        application_valid_checklist = application_checklist_update
        checklist_groups = {}
        if field_name in application_valid_checklist:
            application_checklist = ApplicationCheckList.objects.filter(
                application_id=application_id,
                field_name=field_name
            ).values('sd', 'pv', 'dv', 'ca', 'fin', 'coll').last()
            for valid_group, checklist_status in application_valid_checklist.get(
                field_name).items():
                if not checklist_status:
                    continue

                checklist_group_data = {
                    valid_group: {
                        'value': application_checklist[
                            valid_group] if application_checklist else None,
                        'comment': get_application_comment_list(application_comments, field_name,
                            valid_group),
                        'is_disabled': True
                    }
                }

                # Note that in the FE filter: pv = pve & ca = pva.
                if (
                    (valid_group == 'sd' and 'bo_sd_verifier' in user_roles)
                    or (valid_group == 'dv' and 'bo_data_verifier' in user_roles)
                    or (valid_group == 'pv' and 'bo_outbound_caller' in user_roles)
                    or (valid_group == 'ca' and 'bo_credit_analyst' in user_roles)
                    or (valid_group == 'fin' and 'bo_finance' in user_roles)
                    or (valid_group == 'coll' and any(role in JuloUserRoles for role in user_roles))
                ):
                    checklist_group_data[valid_group]['is_disabled'] = False

                checklist_groups = {**checklist_groups, **checklist_group_data}

        return checklist_groups

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        user_roles = self.context.user.groups.values_list('name', flat=True)
        application_comments = ApplicationCheckListComment.objects.filter(
            application_id=instance.id,
        ).select_related('agent').values(
            'cdate', 'id', 'agent_id', 'agent__username', 'comment', 'group', 'field_name'
        ).order_by('-cdate')
        data = deepcopy(FRONTEND_FIELD_MAP)
        for key, value in representation.items():
            if not data.get(key):
                continue

            if key in self.Meta.read_only_fields:
                data[key]['type'] = f'{FRONTEND_FIELD_MAP[key]["type"]}_readonly'
            if isinstance(value, dict) and value.get('_meta'):
                data[key]['type'] = f'{FRONTEND_FIELD_MAP[key]["type"]}_detailed'

            if key == 'address':
                address_details = self.get_address(instance)
                data[key]['value'] = address_details
            else:
                data[key]['value'] = value

            filter_groups = self.output_filter_groups(key)
            checklist_groups = self.fetch_application_check_list(
                instance.id, key, user_roles, application_comments)

            data[key]['label'] = FRONTEND_FIELD_MAP[key]['label']
            data[key]['filter_groups'] = filter_groups
            data[key]['checklist_groups'] = checklist_groups

        # Fields exclusively contain checklists and/or comments.
        for key, value in FRONTEND_EXTRA_FIELDS.items():
            filter_groups = self.output_filter_groups(key)
            checklist_groups = self.fetch_application_check_list(
                instance.id, key, user_roles, application_comments)

            data[key] = {
                'label': value['label'],
                'type': None,
                'value': None,
                'filter_groups': filter_groups,
                'checklist_groups': checklist_groups,
            }

        # ops.application.loan_purpose does not use ops.loan_purpose as foreign key
        loan_purposes = LoanPurpose.objects.annotate(
            value=F('purpose'), text=F('purpose')).values('value', 'text')
        data['loan_purpose']['value'] = {
            'select': instance.loan_purpose,
            'options': loan_purposes
        }

        today = datetime.today()
        age = today.year - instance.dob.year - (
            (today.month, today.day) < (instance.dob.month, instance.dob.day))
        data['dob']['value'] = {
            'value': instance.dob,
            '_meta': {
                'description': f'Usia: {age} Tahun'
            }
        }

        product_lines = ProductLine.objects.annotate(
            value=F('product_line_code'), text=F('product_line_type')).values('value', 'text')
        data['product_line']['value'] = {
            'select': instance.product_line.product_line_code,
            'options': product_lines
        }

        marital_status_options = []
        for marital_status_choice in ApplicationTemplate.MARITAL_STATUS_CHOICES:
            marital_status_options.append({
                'value': marital_status_choice[0],
                'text': marital_status_choice[1]
            })
        data['marital_status']['value'] = {
            'select': instance.marital_status,
            'options': marital_status_options
        }

        data['payday']['value'] = {
            'value': instance.payday,
            '_meta': {
                'min': 1,
                'max': 28
            }
        }

        if instance.job_start:
            job_duration = today.year - instance.job_start.year - (
                (today.month, today.day) < (instance.job_start.month, instance.job_start.day))
            data['job_start']['value'] = {
                'value': instance.job_start,
                '_meta': {
                    'description': f'Lama: {job_duration} Tahun'
                }
            }

        gender_options = []
        for gender_choice in ApplicationTemplate.GENDER_CHOICES:
            gender_options.append({
                'value': gender_choice[0],
                'text': gender_choice[1]
            })
        data['gender']['value'] = data['kin_gender']['value'] = {
            'select': instance.gender,
            'options': gender_options
        }

        if instance.occupied_since:
            occupied_duration = today.year - instance.occupied_since.year - (
                (today.month, today.day) < (
                instance.occupied_since.month, instance.occupied_since.day))
            data['occupied_since']['value'] = {
                'value': instance.occupied_since,
                '_meta': {
                    'description': f'Lama: {occupied_duration} Tahun'
                }
            }

        dialect_options = []
        for dialect_choice in ApplicationTemplate.DIALECT_CHOICES:
            dialect_options.append({
                'value': dialect_choice[0],
                'text': dialect_choice[1]
            })
        data['dialect']['value'] = {
            'select': instance.dialect,
            'options': dialect_options
        }

        close_kin_relationship_options = []
        for kin_relationship_choice in ApplicationTemplate.KIN_RELATIONSHIP_CHOICES:
            close_kin_relationship_options.append({
                'value': kin_relationship_choice[0],
                'text': kin_relationship_choice[1]
            })
        data['close_kin_relationship']['value'] = data['kin_relationship']['value'] = {
            'select': instance.close_kin_relationship,
            'options': close_kin_relationship_options
        }

        vehicle_ownership_1_options = []
        for vehicle_ownership_choice in ApplicationTemplate.VEHICLE_OWNERSHIP_CHOICES:
            vehicle_ownership_1_options.append({
                'value': vehicle_ownership_choice[0],
                'text': vehicle_ownership_choice[1]
            })
        data['vehicle_ownership_1']['value'] = {
            'select': instance.vehicle_ownership_1,
            'options': vehicle_ownership_1_options
        }

        return data

    def to_internal_value(self, data):
        processed_data = super().to_internal_value(data)
        checklist = data.get('checklist')
        comments = data.get('comments')

        if checklist:
            processed_data['checklist'] = checklist
        if comments:
            processed_data['comments'] = comments

        return processed_data

    def validate_loan_purpose(self, value):
        loan_purpose = LoanPurpose.objects.filter(purpose=value).last()
        if not loan_purpose:
            raise ValidationError(f'{value} is not a valid choice.')
        return value

    def validate(self, attributes):
        for field in self.initial_data.keys():
            if field in chain(self.Meta.exclude, self.Meta.read_only_fields):
                raise ValidationError(
                    {field: ['this field can not be updated']}
                )

        return super().validate(attributes)

    def update(self, instance, validated_data):
        updated_fields = []
        user_roles = self.context.user.groups.values_list('name', flat=True)

        with transaction.atomic():
            validated_checklist_data = validated_data.get('checklist')
            if validated_checklist_data:
                for checklist_key, checklist_data in validated_checklist_data.items():
                    if (
                        checklist_data['group'] == 'sd' and 'bo_sd_verifier' in user_roles) or (
                        checklist_data['group'] == 'dv' and 'bo_data_verifier' in user_roles) or (
                        checklist_data['group'] == 'pve' and 'bo_outbound_caller' in user_roles) or (
                        checklist_data['group'] == 'pva' and 'bo_credit_analyst' in user_roles) or (
                        checklist_data['group'] == 'fin' and 'bo_finance' in user_roles) or (
                        checklist_data['group'] == 'coll' and any(
                                                        role in COLL_ROLES for role in user_roles)
                    ):
                        checklist_data['field_name'] = checklist_key
                        update_application_checklist_data(instance, checklist_data)
                    else:
                        raise serializers.ValidationError({'checklist': [
                            f'This user is not allowed to add/update {checklist_data["group"]} '
                            f'checklist.'
                        ]})
                validated_data.pop('checklist')

            validated_comment_data = validated_data.get('comments')
            if validated_comment_data:
                for comment_key, comment_data in validated_comment_data.items():
                    if (comment_data['group'] == 'sd' and 'bo_sd_verifier' in user_roles) or (
                        comment_data['group'] == 'dv' and 'bo_data_verifier' in user_roles) or (
                        comment_data['group'] == 'pv' and 'bo_outbound_caller' in user_roles) or (
                        comment_data['group'] == 'ca' and 'bo_credit_analyst' in user_roles) or (
                        comment_data['group'] == 'fin' and 'bo_finance' in user_roles) or (
                        comment_data['group'] == 'coll' and any(
                                                        role in COLL_ROLES for role in user_roles)
                    ):
                        comment_data['field_name'] = comment_key
                        create_application_checklist_comment_data(instance, comment_data)
                    else:
                        raise serializers.ValidationError({'comments': [
                            f'This user is not allowed to add/update {comment_data["group"]} '
                            f'comments.'
                        ]})
                validated_data.pop('comments')

            for field, value in validated_data.items():
                result = update_application_field(
                    application=instance,
                    data={
                        'field_name': field,
                        'value': value,
                    }
                )
                # if there is an update
                if result is True:
                    updated_fields.append(field)
        return instance


class AppStatusCheckListSerializer(serializers.Serializer):
    field_name = serializers.CharField(required=True)
    group = serializers.CharField(required=True)
    value = serializers.BooleanField(required=True)


class AppStatusChangeReadSerializer(serializers.Serializer):
    # object passed should be an instance of julosever.julo.statuses.Status
    status = serializers.IntegerField(source='code')
    description = serializers.CharField(source='desc')
    change_reasons = serializers.ListField()


class AppStatusChangeWriteSerializer(serializers.Serializer):
    status = serializers.IntegerField(required=True)
    change_reason = serializers.CharField(required=True)


class AppStatusCheckListCommentSerializer(serializers.Serializer):
    field_name = serializers.CharField(required=True)
    group = serializers.CharField(required=True)
    value = serializers.CharField(required=True)


class AppStatusCheckListCommentsSerializer(serializers.Serializer):
    comments = AppStatusCheckListCommentSerializer(many=True)


class AppNoteSerializer(serializers.ModelSerializer):
    class Meta(object):
        model = ApplicationNote
        fields = ('__all__')


class AppSecurityTabSerializer(serializers.Serializer):
    nama = serializers.CharField(source='fullname')
    tanggal_lahir = serializers.SerializerMethodField()
    nama_ibu_kandung = serializers.CharField(source='customer.mother_maiden_name')
    nama_bank = serializers.CharField(source='bank_name')
    nama_pemilik_rekening = serializers.CharField(source='name_in_bank')
    nomor_handphone = serializers.CharField(source='mobile_phone_1')
    limit_kredit = serializers.SerializerMethodField()
    nomor_rekening = serializers.CharField(source='bank_account_number')
    email_lama = serializers.CharField(source='email')
    set_email_baru = serializers.SerializerMethodField()

    def get_limit_kredit(self, obj):
        from juloserver.portal.core.templatetags.unit import format_rupiahs

        account = obj.account
        account_limit = account.accountlimit_set.last() if account else None
        if account_limit:
            return format_rupiahs(account_limit.set_limit, 'no')
        return None

    def get_tanggal_lahir(self, obj):
        from babel.dates import format_date

        if obj.dob:
            return format_date(obj.dob, "dd MMMM yyyy", locale='id_ID')
        return None

    def get_set_email_baru(self, obj):
        user = self.context.get('user')
        if user:
            return user.groups.filter(name__in=[
                JuloUserRoles.BO_FULL,
                JuloUserRoles.ADMIN_FULL,
                JuloUserRoles.CS_TEAM_LEADER]).exists()
        return False


class AppAppSecurityTabFetchSerializer(serializers.Serializer):
    security_note = serializers.CharField()


class AppStatusAndNoteHistorySerializer(serializers.Serializer):
    id = serializers.CharField()
    status_old = serializers.CharField(required=False)
    status_new = serializers.CharField(required=False)
    change_reason = serializers.CharField(required=False)
    note_text = serializers.CharField(required=False)
    type = serializers.SerializerMethodField()
    agent = serializers.SerializerMethodField()
    updated_at = serializers.CharField(source='cdate')

    def get_type(self, obj):
        if obj._meta.model.__name__ == 'AccountNote':
            return "Account Notes"
        elif obj._meta.model.__name__ == 'AccountStatusHistory':
            return "Account Status Change"
        elif obj._meta.model.__name__ == 'ApplicationNote':
            return "Application Notes"
        elif obj._meta.model.__name__ == 'ApplicationHistory':
            return "Status Change"
        elif obj._meta.model.__name__ == 'SecurityNote':
            return "Security Change"
        return None

    def get_agent(self, obj):
        if hasattr(obj, 'changed_by'):
            return obj.changed_by.username if obj.changed_by else None
        elif hasattr(obj, 'added_by'):
            if not obj.added_by:
                return None

            if isinstance(obj.added_by, str):
                return obj.added_by
            return obj.added_by.username if obj.added_by else None
        return None


class AppDetailUpdateHistorySerializer(serializers.ModelSerializer):
    agent = serializers.CharField(source='agent.username')

    class Meta(object):
        model = ApplicationFieldChange
        exclude = ('id', 'application')


class SkiptraceHistorySerializer(serializers.ModelSerializer):
    call_result_name = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    contact_source = serializers.SerializerMethodField()
    app_id = serializers.SerializerMethodField()

    class Meta(object):
        model = SkiptraceHistory
        fields = ('phone_number', 'contact_source', 'agent_name', 'callback_time', 'spoke_with',
                  'app_id', 'start_ts', 'end_ts', 'cdate', 'call_result_name')

    def get_call_result_name(self, obj):
        return obj.call_result.name

    def get_phone_number(self, obj):
        return str(obj.skiptrace.phone_number)

    def get_contact_source(self, obj):
        return obj.skiptrace.contact_source

    def get_app_id(self, obj):
        return obj.application.id


class EmailAndSmsHistorySerializer(serializers.Serializer):
    cdate = serializers.CharField()
    type_data = serializers.CharField()
    to_email = serializers.CharField(required=False)
    cc_email = serializers.CharField(required=False)
    status = serializers.CharField()
    subject = serializers.CharField(required=False)
    message_content = serializers.CharField()
    phone_number_type = serializers.CharField(required=False)
    to_mobile_phone = serializers.CharField(required=False)
    category = serializers.CharField()


class AppFinanceSerializer(serializers.ModelSerializer):
    basic_installment = serializers.SerializerMethodField()
    basic_installment_discount = serializers.SerializerMethodField()
    is_dti_passed = serializers.SerializerMethodField()
    is_basic_financial_passed = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = (
            'id',
            'loan_amount_request',
            'loan_duration_request',
            'default_interest_rate',
            'basic_installment',
            'basic_installment_discount',
            'monthly_income',
            'monthly_housing_cost',
            'monthly_expenses',
            'total_current_debt',
            'basic_financial',
            'dti_multiplier',
            'dti_capacity',
            'is_dti_passed',
            'is_basic_financial_passed'
        )

    def get_basic_installment(self, obj):
        try:
            return obj.basic_installment
        except TypeError:
            return None

    def get_basic_installment_discount(self, obj):
        try:
            return obj.basic_installment_discount
        except TypeError:
            return None

    def get_is_dti_exceed_installment(self, obj):
        return obj.dti_capacity >= self.get_basic_installment_discount(obj)

    def get_is_dti_passed(self, obj):
        basic_installment_discount = self.get_basic_installment_discount(obj)
        return bool(
            basic_installment_discount
            and obj.dti_capacity
            and obj.dti_capacity >= basic_installment_discount
        )

    def get_is_basic_financial_passed(self, obj):
        basic_installment_discount = self.get_basic_installment_discount(obj)
        return bool(
            basic_installment_discount
            and obj.basic_financial
            and obj.basic_financial >= basic_installment_discount
        )


class SkiptraceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skiptrace
        exclude = [
            'customer',
        ]


class SkiptraceResultChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkiptraceResultChoice
        fields = [
            'id',
            'name',
        ]


class StreamlinedCommsImportUsersUploadFileSerializer(serializers.Serializer):
    file_data_type = serializers.ChoiceField(
        choices=['application_id', 'account_id', 'customer_id', 'phone_number'],
        required=True,
    )
    customer_segment_name = serializers.CharField(required=True)
    csv_file = serializers.FileField(required=True, error_messages={'required': 'This file is requied'})

    def validate_csv_file(self, file):
        if file.size == 0:
            return None, UserSegmentError.INVALID_DATA
        if file.size > MAXIMUM_FILE_SIZE_UPLOAD_USERS:
            return None, UserSegmentError.FILE_SIZE
        if not file.name.endswith('.csv'):
            return None, UserSegmentError.INVALID_FORMAT
        try:
            df = pd.read_csv(file)
            df_unique = df.drop_duplicates()

            cleaned_file = io.StringIO()
            df_unique.to_csv(cleaned_file, index=False)
            cleaned_file.seek(0)
            cleaned_content = cleaned_file.getvalue()
            content_file = ContentFile(cleaned_content.encode('utf-8'))

            deduplicated_file = InMemoryUploadedFile(
                content_file, None, file.name, 'text/csv', content_file.size, None  # Size
            )
        except Exception as e:
            return None, UserSegmentError.INVALID_DATA
        file.seek(0)
        return deduplicated_file, None

    def validate_customer_segment_name(self, value):
        if not value:
            return None, UserSegmentError.INVALID_DATA
        value = value.lower().replace(' ', '_')
        if len(value) > 50:
            return None, UserSegmentError.CHARACTER_LIMIT
        if StreamlinedCommunicationSegment.objects.filter(segment_name=value).exists():
            return None, UserSegmentError.ALREADY_EXIST
        return value, None


class StreamlinedCommunicationSegmentSerializer(serializers.ModelSerializer):
    uploaded_date = serializers.CharField(source='cdate')
    download_link = serializers.SerializerMethodField()
    delete_link = serializers.SerializerMethodField()
    uploader_name = serializers.CharField(source='uploaded_by.username')
    status = serializers.CharField()

    class Meta:
        model = StreamlinedCommunicationSegment
        fields = [
            'id',
            'uploaded_date',
            'uploader_name',
            'segment_name',
            'csv_file_name',
            'download_link',
            'delete_link',
            'status',
        ]

    def get_download_link(self, segment):
        link = (
            settings.BASE_URL
            + '/new_crm/v1/streamlined/segment_data_action/'
            + str(segment.id)
            + '?action=download'
        )
        return link
    
    def get_delete_link(self, segment):
        link = (
            settings.BASE_URL
            + '/new_crm/v1/streamlined/segment_data_action/'
            + str(segment.id)
            + '?action=delete'
        )
        return link
