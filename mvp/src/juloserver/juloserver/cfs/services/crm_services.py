from django.db import transaction
from juloserver.cfs.services.core_services import send_cfs_ga_event, \
    create_or_update_cfs_action_assignment
from juloserver.cfs.models import CfsAssignmentVerification
from juloserver.cfs.constants import (
    CfsActionId, PhoneContactType, GoogleAnalyticsActionTracking
)
from juloserver.cfs.constants import (
    MAP_VERIFY_ACTION_WITH_VERIFY_STATUS, VerifyAction, VerifyStatus
)
from juloserver.application_form.services.cfs_application_service import (
    update_application_monthly_income,
    update_affordability,
)
from juloserver.account.services.credit_limit import (
    update_account_max_limit_pre_matrix_with_cfs,
)


def update_agent_verification(assignment_verification_id, agent, agent_note=None,
                              to_verify_status=None):
    update_data = {}
    if agent_note is not None:
        update_data['message'] = agent_note
    if to_verify_status is not None:
        update_data['verify_status'] = to_verify_status
    if not update_data:
        return None
    update_data['agent'] = agent
    affected_count = CfsAssignmentVerification.objects.filter(
        id=assignment_verification_id
    ).update(**update_data)
    return affected_count


def change_pending_state_assignment(application, cfs_action_assignment, assignment_verification,
                                    to_action_assignment_status, verify_action, agent):
    action_id = cfs_action_assignment.action_id
    with transaction.atomic():
        if verify_action == VerifyAction.APPROVE:
            phone_number = cfs_action_assignment.extra_data.get('phone_number')
            if action_id == CfsActionId.VERIFY_FAMILY_PHONE_NUMBER and phone_number is not None:
                contact_type = cfs_action_assignment.extra_data['contact_type']
                contact_name = cfs_action_assignment.extra_data['contact_name']
                if contact_type == PhoneContactType.COUPLE:
                    application.spouse_name = contact_name
                    application.spouse_mobile_phone = phone_number
                elif contact_type == PhoneContactType.PARENT:
                    application.kin_name = contact_name
                    application.kin_mobile_phone = phone_number
                    application.kin_relationship = PhoneContactType.PARENT
                else:
                    application.close_kin_name = contact_name
                    application.close_kin_mobile_phone = phone_number
                    application.close_kin_relationship = contact_type
                application.save()
            elif action_id == CfsActionId.VERIFY_OFFICE_PHONE_NUMBER and phone_number is not None:
                application.company_name = cfs_action_assignment.extra_data['company_name']
                application.company_phone_number = phone_number
                application.save()

        create_or_update_cfs_action_assignment(application, action_id, to_action_assignment_status)
        to_verify_status = MAP_VERIFY_ACTION_WITH_VERIFY_STATUS[verify_action]
        assignment_verification.verify_status = to_verify_status
        update_agent_verification(
            assignment_verification.id, agent, to_verify_status=to_verify_status
        )
        if to_verify_status == VerifyStatus.APPROVE:
            send_cfs_ga_event(
                cfs_action_assignment.customer, cfs_action_assignment.action.id,
                GoogleAnalyticsActionTracking.APPROVE
            )
        elif to_verify_status == VerifyStatus.REFUSE:
            send_cfs_ga_event(
                cfs_action_assignment.customer, cfs_action_assignment.action.id,
                GoogleAnalyticsActionTracking.REFUSE
            )


def update_after_upload_payslip_bank_statement_verified(application, agent, new_monthly_income):
    # Common function for updating:
    # --- monthly income
    # --- affordability
    # --- max limit (pre-matrix)

    is_monthly_income_updated = update_application_monthly_income(
        application, agent, new_monthly_income
    )

    if not is_monthly_income_updated or application.is_jstarter:
        return

    affordability_history = update_affordability(
        application, new_monthly_income
    )

    if not affordability_history:
        return

    update_account_max_limit_pre_matrix_with_cfs(application, affordability_history)


def record_monthly_income_value_change(assignment_verification, old_monthly_income,
                                       new_monthly_income):
    extra_data = assignment_verification.extra_data or {}
    extra_data.update({
        'monthly_income': {
            'value_old': old_monthly_income,
            'value_new': new_monthly_income
        },
    })
    assignment_verification.update_safely(monthly_income=new_monthly_income, extra_data=extra_data)
