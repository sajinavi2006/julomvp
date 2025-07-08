from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import (
    BankAccountCategory,
    BankAccountDestination,
)
from juloserver.disbursement.constants import NameBankValidationVendors
from juloserver.disbursement.models import NameBankValidation
from juloserver.healthcare.constants import (
    REDIS_HEALTHCARE_PLATFORM_AUTO_COMPLETE_HASH_TABLE_NAME,
    FeatureNameConst,
)
from juloserver.healthcare.models import HealthcarePlatform, HealthcareUser
from juloserver.julo.models import FeatureSetting
from juloserver.loan.services.views_related import (
    is_search_feature_with_redis,
    search_data_by_name_with_redis,
)
from juloserver.healthcare.services.feature_related import is_allow_add_new_healthcare_platform
from juloserver.loan.models import LoanRelatedDataHistory, AdditionalLoanInformation


def get_list_active_healthcare_user_by_account(account_id):
    return (
        HealthcareUser.objects.select_related(
            'bank_account_destination',
            'bank_account_destination__bank',
            'bank_account_destination__name_bank_validation',
            'healthcare_platform',
        )
        .filter(account_id=account_id, is_deleted=False)
        .order_by('-id')
    )


def get_healthcare_faq():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.HEALTHCARE_FAQ,
        is_active=True,
    ).last()
    if not feature_setting:
        return []

    return feature_setting.parameters or []


def get_healthcare_platform_id_by_select_or_self_input(
    healthcare_platform_id, healthcare_platform_name
):
    healthcare_platform_create_by_user = None
    if not healthcare_platform_id:
        # if the user want to create a new healthcare_platform
        # that not exists in healthcare_platform list
        # -> only create when not exist (maybe created by other users)
        # to avoid duplicate healthcare_platform
        healthcare_platform_create_by_user, _ = HealthcarePlatform.objects.get_or_create(
            name__iexact=healthcare_platform_name,
            city='',
            defaults={'name': healthcare_platform_name, 'is_active': True, 'is_verified': False},
        )

    return healthcare_platform_id or healthcare_platform_create_by_user.id


def get_healthcare_platform_list_and_allow_adding_feature(limit, q):
    healthcare_platforms = None
    is_enable_search_with_redis = is_search_feature_with_redis(
        FeatureNameConst.SEARCH_HEALTHCARE_PLATFORM_IN_REDIS
    )
    is_search_with_redis_success = False

    if is_enable_search_with_redis:
        is_search_with_redis_success, healthcare_platforms = search_data_by_name_with_redis(
            prefix=REDIS_HEALTHCARE_PLATFORM_AUTO_COMPLETE_HASH_TABLE_NAME, phrase=q, limit=limit
        )

    if not is_enable_search_with_redis or not is_search_with_redis_success:
        _filter = {'is_verified': True, 'is_active': True}
        if q:
            _filter['name__icontains'] = q

        healthcare_platforms = list(
            HealthcarePlatform.objects.filter(**_filter)
            .order_by('name')
            .values('id', 'name')[:limit]
        )

    return {
        'adding_enable': is_allow_add_new_healthcare_platform(),
        'list': healthcare_platforms,
    }


def process_healthcare_user(
    application,
    customer,
    account,
    bank,
    bank_name_validation_log,
    healthcare_platform_id,
    healthcare_platform_name,
    healthcare_user_fullname='',
):
    with transaction.atomic():
        bank_account_destination = create_bank_account_destination(
            bank, bank_name_validation_log, application, customer
        )

        return HealthcareUser.objects.create(
            account=account,
            healthcare_platform_id=get_healthcare_platform_id_by_select_or_self_input(
                healthcare_platform_id, healthcare_platform_name
            ),
            bank_account_destination=bank_account_destination,
            fullname=healthcare_user_fullname,
        )


def delete_healthcare_user(user_id: int, request_user: User) -> None:
    """
    Soft delete a healthcare user for the view
    """
    healthcare_user = get_object_or_404(HealthcareUser, pk=user_id)

    if healthcare_user.account.id != request_user.customer.account.id:
        # deleting others not allowed, throw 403
        raise PermissionDenied

    if not healthcare_user.is_deleted:
        healthcare_user.is_deleted = True
        healthcare_user.save(
            update_fields=['is_deleted'],
        )


def create_bank_account_destination(bank, bank_name_validation_log, application, customer):
    name_bank_validation = NameBankValidation.objects.create(
        bank_code=bank.xfers_bank_code,
        account_number=bank_name_validation_log.account_number,
        name_in_bank=bank_name_validation_log.validated_name,
        method=NameBankValidationVendors.XFERS,
        validation_id=bank_name_validation_log.validation_id,
        validation_status=bank_name_validation_log.validation_status,
        validated_name=bank_name_validation_log.validated_name,
        mobile_phone=application.mobile_phone_1,
        reason=bank_name_validation_log.reason,
    )

    return BankAccountDestination.objects.create(
        bank_account_category=BankAccountCategory.objects.get(
            category=BankAccountCategoryConst.HEALTHCARE
        ),
        customer=customer,
        bank=bank,
        account_number=bank_name_validation_log.account_number,
        name_bank_validation=name_bank_validation,
    )


def process_healthcare_user_update(
    healthcare_user,
    application,
    customer,
    account,
    bank,
    bank_name_validation_log,
    healthcare_platform_id,
    healthcare_platform_name,
    healthcare_user_fullname,
):
    is_have_field_need_to_update = False
    loan_related_histories = []
    healthcare_user_content_type = ContentType.objects.get_for_model(HealthcareUser)
    updated_healthcare_id = get_healthcare_platform_id_by_select_or_self_input(
        healthcare_platform_id,
        healthcare_platform_name
    )
    with transaction.atomic():
        if healthcare_user.healthcare_platform_id != updated_healthcare_id:
            is_have_field_need_to_update = True
            loan_related_histories.append(
                LoanRelatedDataHistory(
                    field_name='healthcare_platform_id',
                    old_value=healthcare_user.healthcare_platform_id,
                    new_value=updated_healthcare_id,
                    content_type=healthcare_user_content_type,
                    object_id=healthcare_user.pk,
                )
            )

        updated_bank_account_destination = None
        if bank and bank_name_validation_log:
            is_have_field_need_to_update = True
            updated_bank_account_destination = create_bank_account_destination(
                bank, bank_name_validation_log, application, customer
            )
            loan_related_histories.append(
                LoanRelatedDataHistory(
                    field_name='bank_account_destination_id',
                    old_value=healthcare_user.bank_account_destination_id,
                    new_value=updated_bank_account_destination,
                    content_type=healthcare_user_content_type,
                    object_id=healthcare_user.pk,
                )
            )

        if healthcare_user.fullname != healthcare_user_fullname:
            is_have_field_need_to_update = True
            loan_related_histories.append(
                LoanRelatedDataHistory(
                    field_name='fullname',
                    old_value=healthcare_user.fullname,
                    new_value=healthcare_user_fullname,
                    content_type=healthcare_user_content_type,
                    object_id=healthcare_user.pk,
                )
            )

        # if use do not update any field
        # -> return old healthcare user, no need to update and create log
        if not is_have_field_need_to_update:
            return healthcare_user.id, healthcare_user.bank_account_destination_id

        if AdditionalLoanInformation.objects.filter(
            content_type=healthcare_user_content_type,
            object_id=healthcare_user.id
        ).exists():
            # soft delete to keep data for previous loan
            healthcare_user.is_deleted = True
            healthcare_user.save()

            new_healthcare_user = HealthcareUser.objects.create(
                account=account,
                healthcare_platform_id=updated_healthcare_id,
                bank_account_destination=updated_bank_account_destination
                if updated_bank_account_destination
                else healthcare_user.bank_account_destination,
                fullname=healthcare_user_fullname,
            )

            # update new loan related history because we create new healthcare user
            for loan_related_history in loan_related_histories:
                loan_related_history.object_id = new_healthcare_user.pk

            response_healthcare_user_id = new_healthcare_user.id
            response_bank_account_destination_id = new_healthcare_user.bank_account_destination_id

        else:
            healthcare_user.healthcare_platform_id = updated_healthcare_id

            if updated_bank_account_destination:
                healthcare_user.bank_account_destination_id = updated_bank_account_destination.id

            healthcare_user.fullname = healthcare_user_fullname
            healthcare_user.save()

            response_healthcare_user_id = healthcare_user.id
            response_bank_account_destination_id = healthcare_user.bank_account_destination_id
        LoanRelatedDataHistory.objects.bulk_create(loan_related_histories)

        return response_healthcare_user_id, response_bank_account_destination_id
