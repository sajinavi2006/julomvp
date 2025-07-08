import logging

from django.db import transaction
from django.db.models import F

from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.models import BankAccountDestination, BankAccountCategory
from juloserver.disbursement.constants import NameBankValidationVendors
from juloserver.disbursement.models import NameBankValidation
from juloserver.education.constants import (
    ErrorMessage,
    FeatureNameConst,
)
from juloserver.julo.exceptions import JuloException

from juloserver.education.models import (
    StudentRegister,
    School,
    LoanStudentRegister,
    StudentRegisterHistory,
)
from juloserver.education.services.search_school_with_redis import (
    is_search_school_with_redis,
    search_school_by_name_with_redis,
)
from juloserver.julo.models import (
    Bank,
    FeatureSetting,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes

logger = logging.getLogger(__name__)
BASE_PATH = 'juloserver.education.services.views_related'


def is_eligible_for_education(application, account):
    # Application status at least x121 for JTurbo
    if application.is_jstarter:
        if application.status < ApplicationStatusCodes.JULO_STARTER_LIMIT_GENERATED:
            return False, ErrorMessage.APPLICATION_STATUS_AT_LEAST_109
    else:
        # Application status must be x190
        if application.status != ApplicationStatusCodes.LOC_APPROVED:
            return False, ErrorMessage.APPLICATION_STATUS_MUST_BE_190

        # Account status must be x420
        if account.status.status_code != JuloOneCodes.ACTIVE:
            return False, ErrorMessage.ACCOUNT_STATUS_MUST_BE_420

    return True, None


def get_list_student_register(account):
    student_registers = (
        StudentRegister.objects.filter(account=account, is_deleted=False)
        .annotate(
            school_name=F('school__name'),
            school_city=F('school__city'),
            bank_id=F('bank_account_destination__bank_id'),
            bank_code=F('bank_account_destination__bank__xfers_bank_code'),
            bank_name=F('bank_account_destination__bank__bank_name'),
            account_name=F('bank_account_destination__name_bank_validation__name_in_bank'),
            account_number=F('bank_account_destination__account_number'),
        )
        .values(
            'id',
            'school_id',
            'school_name',
            'school_city',
            'bank_account_destination_id',
            'bank_id',
            'bank_code',
            'bank_name',
            'account_name',
            'account_number',
            'student_fullname',
            'note',
        )
        .order_by('-id')
    )

    banks = Bank.objects.filter(
        id__in=set(student_register['bank_id'] for student_register in student_registers)
    )
    mapping_bank_id_logo = {bank.id: bank.bank_logo for bank in banks}

    return {
        'student': [
            {
                'id': student_register['id'],
                'name': student_register['student_fullname'],
                'note': student_register['note'],
                'school': {
                    'id': student_register['school_id'],
                    'name': student_register['school_name'],
                    'city': student_register['school_city'],
                },
                'bank': {
                    'bank_account_destination_id': student_register['bank_account_destination_id'],
                    'code': student_register['bank_code'],
                    'logo': mapping_bank_id_logo[student_register['bank_id']],
                    'name': student_register['bank_name'],
                    'account_number': student_register['account_number'],
                    'account_name': student_register['account_name'],
                },
            }
            for student_register in student_registers
        ]
    }


def get_school_id_by_select_or_self_input(school_id, school_name):
    school_create_by_user = None
    if not school_id:
        # if the user want to create a new school that not exists in school list
        # -> only create when not exist (maybe created by other users) to avoid duplicate school
        school_create_by_user, _ = School.objects.get_or_create(
            name__iexact=school_name,
            city='',
            defaults={'name': school_name, 'is_active': True, 'is_verified': False},
        )

    return school_id or school_create_by_user.id


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
            category=BankAccountCategoryConst.EDUCATION
        ),
        customer=customer,
        bank=bank,
        account_number=bank_name_validation_log.account_number,
        name_bank_validation=name_bank_validation,
    )


def process_student_register(
    application,
    customer,
    account,
    bank,
    bank_name_validation_log,
    school_id,
    school_name,
    student_fullname,
    note,
):
    with transaction.atomic():
        bank_account_destination = create_bank_account_destination(
            bank, bank_name_validation_log, application, customer
        )

        student_register = StudentRegister.objects.create(
            account=account,
            school_id=get_school_id_by_select_or_self_input(school_id, school_name),
            bank_account_destination=bank_account_destination,
            student_fullname=student_fullname,
            note=note.strip(),
        )

        return student_register.id, bank_account_destination.id


@transaction.atomic
def process_student_register_update(
    student_register,
    application,
    customer,
    account,
    bank,
    bank_name_validation_log,
    school_id,
    school_name,
    student_fullname,
    note,
):
    is_have_field_need_to_update = False
    student_register_histories = []

    updated_school_id = get_school_id_by_select_or_self_input(school_id, school_name)
    if student_register.school_id != updated_school_id:
        is_have_field_need_to_update = True
        student_register_histories.append(
            StudentRegisterHistory(
                old_student_register=student_register,
                new_student_register=student_register,
                field_name='school_id',
                old_value=student_register.school_id,
                new_value=updated_school_id,
            )
        )

    updated_bank_account_destination = None
    if bank and bank_name_validation_log:
        is_have_field_need_to_update = True
        updated_bank_account_destination = create_bank_account_destination(
            bank, bank_name_validation_log, application, customer
        )

        student_register_histories.append(
            StudentRegisterHistory(
                old_student_register=student_register,
                new_student_register=student_register,
                field_name='bank_account_destination_id',
                old_value=student_register.bank_account_destination_id,
                new_value=updated_bank_account_destination.id,
            )
        )

    if student_register.student_fullname != student_fullname:
        is_have_field_need_to_update = True
        student_register_histories.append(
            StudentRegisterHistory(
                old_student_register=student_register,
                new_student_register=student_register,
                field_name='student_fullname',
                old_value=student_register.student_fullname,
                new_value=student_fullname,
            )
        )

    note = note.strip()
    if student_register.note != note:
        is_have_field_need_to_update = True
        student_register_histories.append(
            StudentRegisterHistory(
                old_student_register=student_register,
                new_student_register=student_register,
                field_name='note',
                old_value=student_register.note,
                new_value=note,
            )
        )

    # if use do not update any field
    # -> return old student register, no need to update and create log
    if not is_have_field_need_to_update:
        return student_register.id, student_register.bank_account_destination_id

    # create new student register when old student register is used for create loan
    # -> prevent wrong data for old loan
    if LoanStudentRegister.objects.filter(student_register=student_register).exists():
        # soft delete to keep data for previous loan
        student_register.is_deleted = True
        student_register.save()

        new_student_register = StudentRegister.objects.create(
            account=account,
            school_id=updated_school_id,
            bank_account_destination_id=updated_bank_account_destination.id
            if updated_bank_account_destination
            else student_register.bank_account_destination_id,
            student_fullname=student_fullname,
            note=note,
        )

        # update new student register history because we create new student register
        for student_register_history in student_register_histories:
            student_register_history.new_student_register = new_student_register

        response_student_register_id = new_student_register.id
        response_bank_account_destination_id = new_student_register.bank_account_destination_id

    # update existing student register when old student register is NOT used for create loan
    else:
        student_register.school_id = updated_school_id

        if updated_bank_account_destination:
            student_register.bank_account_destination_id = updated_bank_account_destination.id

        student_register.student_fullname = student_fullname
        student_register.note = note
        student_register.save()

        response_student_register_id = student_register.id
        response_bank_account_destination_id = student_register.bank_account_destination_id

    StudentRegisterHistory.objects.bulk_create(student_register_histories)

    return response_student_register_id, response_bank_account_destination_id


def is_allow_add_new_school():
    return FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ALLOW_ADD_NEW_SCHOOL,
        is_active=True,
    ).exists()


def get_school_list_and_allow_adding_feature(limit, q):
    schools = None
    is_enable_search_with_redis = is_search_school_with_redis()
    is_search_with_redis_success = False

    if is_enable_search_with_redis:
        is_search_with_redis_success, schools = search_school_by_name_with_redis(
            phrase=q, limit=limit
        )

    if not is_enable_search_with_redis or not is_search_with_redis_success:
        _filter = {'is_verified': True, 'is_active': True}
        if q:
            _filter['name__icontains'] = q

        schools = list(
            School.objects.filter(**_filter).order_by('name').values('id', 'name')[:limit]
        )

    return {
        'adding_enable': is_allow_add_new_school(),
        'list': schools,
    }


def assign_student_to_loan(student_id, loan):
    student_register = StudentRegister.objects.get_or_none(pk=student_id)
    if not student_register or not loan:
        logger.info(
            {
                "action": BASE_PATH + ".assign_student_to_loan",
                "loan": loan.id,
                "student_id": student_id,
                "message": "student not registered",
            }
        )
        raise JuloException('No student information found')

    return LoanStudentRegister.objects.create(loan=loan, student_register=student_register)


def get_education_faq():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EDUCATION_FAQ,
        is_active=True,
    ).last()
    if not feature_setting:
        return []

    return feature_setting.parameters or []


def delete_student_register(student_register):
    student_register.is_deleted = True
    student_register.save()

    return True
