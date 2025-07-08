import logging

from celery.task import task

from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.julo.models import (
    Application,
    Customer,
    FDCInquiry,
    FeatureSetting,
    Partner,
    UploadAsyncState,
)
from juloserver.loan.constants import FDCUpdateTypes
from juloserver.loan.services.loan_related import (
    check_eligible_and_out_date_other_platforms,
    is_apply_check_other_active_platforms_using_fdc,
    update_fdc_active_loan_checking,
)

from juloserver.partnership.constants import PartnershipFeatureNameConst
from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.partnership.services.services import (
    partnership_mock_get_and_save_fdc_data,
)

logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


@task(queue="partner_mf_global_queue")
def merchant_financing_max_platform_check(
    application_id: int, initiate: bool = True, loan_id: int = None
) -> None:
    from juloserver.merchant_financing.web_app.non_onboarding.services import (
        merchant_financing_handle_after_fdc_check_success,
    )
    # initiate: True = only to check
    # initiate: False = need to process the loan by sending SKRTP or make the loan status 219
    partnership_feature_setting = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC,
        is_active=True,
    ).first()

    if not partnership_feature_setting:
        if not initiate:
            merchant_financing_handle_after_fdc_check_success(True, loan_id)

        return

    parameters = partnership_feature_setting.parameters
    if is_apply_check_other_active_platforms_using_fdc(application_id, parameters):
        application = (
            Application.objects.filter(id=application_id)
            .select_related("customer", "partnership_customer_data")
            .first()
        )
        outdated_threshold_days = parameters["fdc_data_outdated_threshold_days"]
        number_allowed_platforms = parameters["number_of_allowed_platforms"]

        customer = application.customer
        is_eligible, is_outdated = check_eligible_and_out_date_other_platforms(
            customer.id,
            application.id,
            outdated_threshold_days,
            number_allowed_platforms,
        )
        if is_outdated:
            partnership_customer_data = application.partnership_customer_data
            fdc_inquiry = FDCInquiry.objects.create(
                nik=partnership_customer_data.nik,
                customer_id=customer.id,
                application_id=application_id,
            )
            fdc_inquiry_data = {
                "id": fdc_inquiry.id,
                "nik": partnership_customer_data.nik,
                "fdc_inquiry_id": fdc_inquiry.id,
            }
            params = {
                "application_id": application.id,
                "outdated_threshold_days": outdated_threshold_days,
                "number_allowed_platforms": number_allowed_platforms,
                "fdc_inquiry_api_config": parameters["fdc_inquiry_api_config"],
                "loan_id": loan_id,
            }
            if initiate:
                inquiry_type = FDCUpdateTypes.MERCHANT_FINANCING_INITIATE
            else:
                inquiry_type = FDCUpdateTypes.MERCHANT_FINANCING_SUBMIT_LOAN

            merchant_financing_fdc_inquiry_for_active_loan_task.delay(
                fdc_inquiry_data, customer.id, inquiry_type, params
            )

        elif is_eligible is not None:
            # Here is condition if the data is not oudated and is_eligible = True
            if not initiate:
                merchant_financing_handle_after_fdc_check_success(is_eligible, loan_id)
        else:
            return
    else:
        logger.info(
            {
                "action": "merchant_finacing_max_platform_check",
                "info": "Feature Setting is not active",
                "application_id": application_id,
                "initiate": initiate,
                "loan_id": loan_id,
            }
        )
        # Here is condition if feature setting is not active
        if not initiate:
            merchant_financing_handle_after_fdc_check_success(True, loan_id)
        else:
            return


@task(queue="partner_mf_global_queue")
def merchant_financing_fdc_inquiry_for_active_loan_task(
    fdc_inquiry_data: dict,
    customer_id: int,
    inquiry_type: str,
    params: dict,
    retry_count: int = 0,
):
    from juloserver.merchant_financing.web_app.non_onboarding.services import (
        merchant_financing_handle_after_fdc_check_success,
    )

    function_name = "merchant_financing_fdc_inquiry_for_active_loan_task"
    customer = Customer.objects.filter(id=customer_id).first()

    try:
        partner_fdc_mock_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PARTNERSHIP_FDC_MOCK_RESPONSE_SET,
            is_active=True,
        ).exists()
        if partner_fdc_mock_feature:
            partnership_mock_get_and_save_fdc_data(fdc_inquiry_data)
        else:
            get_and_save_fdc_data(fdc_inquiry_data, 1, False)

        update_fdc_active_loan_checking(customer.id, fdc_inquiry_data)

        if inquiry_type == FDCUpdateTypes.MERCHANT_FINANCING_SUBMIT_LOAN:
            application_id = params["application_id"]
            outdated_threshold_days = params["outdated_threshold_days"]
            number_allowed_platforms = params["number_allowed_platforms"]
            loan_id = params["loan_id"]
            is_eligible, _ = check_eligible_and_out_date_other_platforms(
                customer.id,
                application_id,
                outdated_threshold_days,
                number_allowed_platforms,
            )
            merchant_financing_handle_after_fdc_check_success(is_eligible, loan_id)

        return

    except FDCServerUnavailableException:
        logger.error(
            {
                "action": function_name,
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
            }
        )
    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        logger.info(
            {
                "action": function_name,
                "error": str(e),
                "data": fdc_inquiry_data,
            }
        )

    # retry step
    fdc_api_config = params["fdc_inquiry_api_config"]
    max_retries = fdc_api_config["max_retries"]
    if retry_count >= max_retries:
        logger.info(
            {
                "action": function_name,
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        return

    countdown = int(fdc_api_config["retry_interval_seconds"]) * retry_count
    retry_count += 1
    logger.info(
        {
            "action": function_name,
            "data": fdc_inquiry_data,
            "extra_data": "retry_count={}|count_down={}".format(retry_count, countdown),
        }
    )

    merchant_financing_fdc_inquiry_for_active_loan_task.apply_async(
        (
            fdc_inquiry_data,
            customer_id,
            inquiry_type,
            params,
            retry_count,
        ),
        countdown=countdown,
    )


@task(name='mf_standard_loan_submission', queue='partner_mf_global_queue')
def mf_standard_loan_submission(upload_async_state_id: int, partner_id: int) -> None:
    from juloserver.merchant_financing.web_app.non_onboarding.services import (
        process_mf_standard_loan_submission,
    )

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.MF_STANDARD_CSV_LOAN_UPLOAD,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    partner = Partner.objects.get(id=partner_id)
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "process_mf_standard_loan_submission",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = process_mf_standard_loan_submission(upload_async_state, partner)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.exception(
            {
                'module': 'merchant_financing_standard_product',
                'action': 'process_mf_standard_loan_submission',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
