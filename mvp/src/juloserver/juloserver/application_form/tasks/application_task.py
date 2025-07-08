from celery import task
from django.db.utils import IntegrityError
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
import traceback

from juloserver.julo.models import (
    Application,
    SmsHistory,
    FeatureSetting,
    ApplicationHistory,
    ApplicationFieldChange,
)
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    remove_double_space,
)
from juloserver.application_form.utils import generate_sms_message, update_emergency_contact_consent
from juloserver.application_form.constants import EmergencyContactConst
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.clients.sms import JuloSmsClient
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.utils import post_anaserver
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.application_form.constants import (
    GoodFDCX100Const,
    SimilarityTextConst,
)
from juloserver.ana_api.models import EligibleCheck
from juloserver.julo.constants import WorkflowConst, FeatureNameConst

from juloserver.application_form.models.agent_assisted_submission import AgentAssistedWebToken
from juloserver.application_form.utils import (
    regenerate_web_token_data,
    generate_web_token,
    get_expire_time_token,
)
from juloserver.application_form.exceptions import WebTokenGenerationError
from juloserver.apiv3.models import (
    ProvinceLookup,
    CityLookup,
    DistrictLookup,
    SubDistrictLookup,
)
from juloserver.ocr.services import get_config_similarity
from juloserver.application_flow.models import (
    ApplicationPathTag,
    ApplicationPathTagStatus,
)
from juloserver.application_flow.services import ApplicationTagTracking
from juloserver.application_flow.tasks import application_tag_tracking_task
from juloserver.application_form.models import CompanyLookup

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()


@task(queue="application_normal")
def trigger_sms_for_emergency_contact_consent(application_id):
    logger.info(
        {
            'action': 'trigger_sms_for_emergency_contact_consent',
            'message': 'Task triggered for sending sms to emergency contact',
            'application_id': application_id,
        }
    )
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return

    sms_count = SmsHistory.objects.filter(
        application_id=application_id,
        template_code=EmergencyContactConst.SMS_TEMPLATE_NAME,
        to_mobile_phone=format_e164_indo_phone_number(application.kin_mobile_phone),
    ).count()

    # Check if the SMS has already been sent twice
    if sms_count >= 2:
        logger.info(
            {
                'message': 'SMS already sent 2 times, number will flagged as ignored',
                'application_id': application_id,
                'is_kin_approved': EmergencyContactConst.CONSENT_IGNORED,
            }
        )

        # Will be flagged as accepted as per opt out method
        update_emergency_contact_consent(application, EmergencyContactConst.CONSENT_IGNORED)
        return

    # Proceed with sending SMS if not already sent twice
    if application.is_kin_approved not in EmergencyContactConst.CONSENT_RESPONDED_VALUE:
        run_send_sms_for_emergency_contact_consent(application)

        # Schedule the task again after 24 hours
        trigger_sms_for_emergency_contact_consent.apply_async((application_id,), countdown=86400)


def run_send_sms_for_emergency_contact_consent(application):
    message = generate_sms_message(application)

    phone_number = format_e164_indo_phone_number(application.kin_mobile_phone)
    sms_client = JuloSmsClient()

    message, response = sms_client.send_sms(phone_number, message)
    response = response['messages'][0]

    if response["status"] != "0":
        logger.warn(
            {
                "send_status": response["status"],
                "message_id": response.get("message-id"),
                "sms_client_method_name": "run_send_sms_for_emergency_contact_consent",
                "error_text": response.get("error-text"),
            }
        )

    sms = create_sms_history(
        response=response,
        customer=application.customer,
        application=application,
        message_content=message,
        to_mobile_phone=format_e164_indo_phone_number(phone_number),
        phone_number_type="kin_mobile_phone",
        template_code=EmergencyContactConst.SMS_TEMPLATE_NAME,
    )
    if sms:
        logger.info(
            {
                'message': 'Sending new sms consent code',
                'action': 'run_send_sms_for_emergency_contact_consent',
                'application_id': application.id,
                'to_mobile_phone': phone_number,
                'sms': {
                    "status": "sms_created",
                    "sms_history_id": sms.id,
                    "message_id": sms.message_id,
                },
            }
        )


@task(queue="application_high")
def trigger_generate_good_fdc_x100(application_id):

    process_name = 'GoodFDCX100'
    logger.info(
        {
            'message': '{}: start trigger generate_good_fdc'.format(process_name),
            'application_id': application_id,
        }
    )

    is_exists_checking = EligibleCheck.objects.filter(
        application_id=application_id,
        check_name=GoodFDCX100Const.KEY_CHECK_NAME,
    ).exists()

    if is_exists_checking:
        logger.warning(
            {
                'message': '{}: Application already have check in eligible check table'.format(
                    process_name
                ),
                'application_id': application_id,
            }
        )
        return

    application = Application.objects.filter(pk=application_id).last()
    if (
        not application.is_julo_one()
        or application.application_status_id != ApplicationStatusCodes.FORM_CREATED
    ):
        logger.error(
            {
                'message': '{}: Application is not allowed is not J1 or not x100'.format(
                    process_name
                ),
                'application_id': application_id,
            }
        )
        return

    response = post_anaserver(
        GoodFDCX100Const.API_ENDPOINT,
        data={
            'application_id': application_id,
        },
    )
    logger.info(
        {
            'message': '{}: response from ana server',
            'endpoint': GoodFDCX100Const.API_ENDPOINT,
            'application_id': application_id,
            'response_status': response.status_code if response else None,
        }
    )
    return True


@task(queue="application_high")
def trigger_generate_session_token_form(application_id):

    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return False

    if (
        not application.is_julo_one()
        or application.application_status_id != ApplicationStatusCodes.FORM_PARTIAL
    ):
        return False

    application_xid = application.application_xid
    last_session_token = AgentAssistedWebToken.objects.filter(
        application_id=application_id,
    ).last()
    if last_session_token:
        regenerate_web_token_data(last_session_token, application_xid)
        logger.info(
            {
                'message': 'Success regenerate session token',
                'application_id': application_id,
            }
        )
        return False

    # create new session token
    expire_time_session_token = get_expire_time_token()
    session_token = generate_web_token(
        expire_time=expire_time_session_token, application_xid=application_xid
    )

    session_data = None
    try:
        session_data = AgentAssistedWebToken.objects.create(
            session_token=session_token,
            application_id=application_id,
            is_active=True,
            expire_time=expire_time_session_token,
        )
        return True
    except IntegrityError as error:
        logger.info(
            {
                'message': str(error),
                'application_id': application_id,
                'session_data': session_data.id if session_data else None,
            }
        )
        raise WebTokenGenerationError(str(error))


@task(queue="repopulate_zipcode_queue")
def repopulate_zipcode():

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.REPOPULATE_ZIPCODE,
        is_active=True,
    ).last()

    if not setting:
        logger.info(
            {
                'message': 'Repopulate scheduler is not active',
            }
        )
        return

    limit_count = setting.parameters.get('limit_count')
    limit_exclude_apps = setting.parameters.get('limit_exclude_apps')
    is_active_specific_status = bool(setting.parameters.get('is_active_specific_status'))
    only_status_code = setting.parameters.get('only_status_code')

    today = timezone.localtime(timezone.now())
    target_date = None

    is_checked_repopulate_zipcode = ApplicationPathTagStatus.objects.filter(
        application_tag=SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE,
        status=SimilarityTextConst.TAG_STATUS_IS_FAILED,
    ).last()
    exclude_applications = (
        ApplicationPathTag.objects.filter(
            application_path_tag_status=is_checked_repopulate_zipcode,
        )
        .values_list('application_id', flat=True)
        .order_by('-cdate')[:limit_exclude_apps]
    )

    query = Application.objects.exclude(id__in=list(exclude_applications)).filter(
        Q(address_kodepos='')
        & ~Q(address_provinsi='')
        & ~Q(address_kabupaten='')
        & ~Q(address_kecamatan='')
        & ~Q(address_kelurahan='')
        & Q(partner_id__isnull=True)
        & Q(
            workflow__name__in=(
                WorkflowConst.JULO_ONE,
                WorkflowConst.JULO_ONE_IOS,
                WorkflowConst.JULO_STARTER,
            )
        )
    )

    if is_active_specific_status and only_status_code:
        query = query.filter(application_status_id=only_status_code)
    else:
        # 639 days based on data monitoring the target start check on 2023-08-14
        target_date = today - timedelta(days=639)
        yesterday = today - timedelta(days=1)
        query = query.filter(
            Q(application_status_id__gte=ApplicationStatusCodes.FORM_PARTIAL)
            & ~Q(application_status_id=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED)
            & Q(cdate__gte=target_date)
            & Q(cdate__lte=yesterday)
        )

    applications = query.values_list(
        'id',
        'application_status_id',
        'address_provinsi',
        'address_kabupaten',
        'address_kecamatan',
        'address_kelurahan',
        'address_kodepos',
    ).order_by('cdate')[:limit_count]

    logger.info(
        {
            'message': '[repopulate_zipcode] total applications need to execute',
            'total_application': len(applications),
            'cdate_data_target': target_date,
        }
    )

    if not applications:
        logger.info(
            {
                'message': '[repopulate_zipcode] total application selected is empty',
            }
        )
        return

    data = {}
    for (
        id,
        application_status_id,
        address_provinsi,
        address_kabupaten,
        address_kecamatan,
        address_kelurahan,
        address_kodepos,
    ) in applications:

        if (
            not address_provinsi
            or not address_kabupaten
            or not address_kecamatan
            or not address_kelurahan
        ):
            application_tag_tracking_task.delay(
                id,
                None,
                None,
                None,
                SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE,
                SimilarityTextConst.TAG_STATUS_IS_FAILED,
                traceback.format_stack(),
            )
            logger.warning(
                {
                    'message': '[repopulate_zip_code] skip application - some data are empty',
                    'application_id': id,
                }
            )
            continue

        application_history = ApplicationHistory.objects.filter(
            application_id=id,
            status_old=ApplicationStatusCodes.FORM_CREATED,
            status_new=ApplicationStatusCodes.FORM_PARTIAL,
        ).last()

        if not application_history:
            logger.warning(
                {
                    'message': '[repopulate_zip_code] skip application - empty application history',
                    'application_id': id,
                }
            )
            continue

        # prevent application in current date and still in x105
        if (
            application_history.cdate.date() == today.date()
            and application_status_id == ApplicationStatusCodes.FORM_PARTIAL
        ):
            logger.warning(
                {
                    'message': '[repopulate_zip_code] '
                    'skip application - current date is submit to x105',
                    'application_id': id,
                }
            )
            continue

        failed_path_tag = ApplicationPathTagStatus.objects.filter(
            application_tag=SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE,
            status=SimilarityTextConst.TAG_STATUS_IS_FAILED,
        ).last()
        is_exist_failed_tag = ApplicationPathTag.objects.filter(
            application_id=id, application_path_tag_status=failed_path_tag
        ).exists()
        if is_exist_failed_tag:
            logger.warning(
                {
                    'message': '[repopulate_zip_code] '
                    'skip application - already have failed path tag',
                    'application_id': id,
                }
            )
            continue

        # execute subtask
        data['application_id'] = id
        data['address_provinsi'] = address_provinsi
        data['address_kabupaten'] = address_kabupaten
        data['address_kecamatan'] = address_kecamatan
        data['address_kelurahan'] = address_kelurahan
        data['address_kodepos'] = address_kodepos

        repopulate_zipcode_subtask.delay(data)


@task(queue="repopulate_zipcode_queue")
def repopulate_zipcode_subtask(data):
    from juloserver.application_form.services.application_service import (
        construct_and_check_value,
        record_application_change_field,
    )

    record_data_update = []
    application_id = data['application_id']

    logger.info(
        {
            'message': '[repopulate_zipcode_substask] start execute function',
            'application_id': application_id,
        }
    )

    application = Application.objects.filter(pk=application_id).last()
    if not application:
        logger.warning(
            {
                'message': '[repopulate_zipcode] application is not found',
                'application_id': application_id,
            }
        )
        return

    provinsi = remove_double_space(data['address_provinsi'])
    kota_kabupaten = remove_double_space(data['address_kabupaten'])
    kecamatan = remove_double_space(data['address_kecamatan'])
    kelurahan = remove_double_space(data['address_kelurahan'])
    kodepos = data['address_kodepos']

    pronvice_lookup = ProvinceLookup.objects.filter(
        province__iexact=provinsi, is_active=True
    ).last()

    _, parameters = get_config_similarity()
    list_of_city = CityLookup.objects.filter(
        province=pronvice_lookup,
        is_active=True,
    ).values_list('city', flat=True)

    kota_kabupaten, record_data_update = construct_and_check_value(
        application_id=application_id,
        list_of_source=list_of_city,
        value=kota_kabupaten,
        threshold_value=parameters.get(SimilarityTextConst.KEY_THRESHOLD_CITY),
        field_name='address_kabupaten',
        record_data_update=record_data_update,
    )

    city_lookup = CityLookup.objects.filter(
        province=pronvice_lookup,
        city__iexact=kota_kabupaten,
        is_active=True,
    ).last()

    # Similarity for Kecamatan
    list_district = DistrictLookup.objects.filter(
        city=city_lookup,
        is_active=True,
    ).values_list('district', flat=True)

    kecamatan, record_data_update = construct_and_check_value(
        application_id=application_id,
        list_of_source=list_district,
        value=kecamatan,
        threshold_value=parameters.get(SimilarityTextConst.KEY_THRESHOLD_DISTRICT),
        field_name='address_kecamatan',
        record_data_update=record_data_update,
    )

    # Similarity for Kelurahan
    list_sub_district = SubDistrictLookup.objects.filter(
        district__district__iexact=kecamatan,
        district__city__city__iexact=kota_kabupaten,
        district__city__province__province__iexact=provinsi,
        is_active=True,
    ).values_list('sub_district', flat=True)

    kelurahan, record_data_update = construct_and_check_value(
        application_id=application_id,
        list_of_source=list_sub_district,
        value=kelurahan,
        threshold_value=parameters.get(SimilarityTextConst.KEY_THRESHOLD_VILLAGE),
        field_name='address_kelurahan',
        record_data_update=record_data_update,
    )
    sub_district_and_zipcode = SubDistrictLookup.objects.filter(
        sub_district__iexact=kelurahan,
        district__district__iexact=kecamatan,
        district__city__city__iexact=kota_kabupaten,
        district__city__province__province__iexact=provinsi,
        is_active=True,
    ).last()

    if not sub_district_and_zipcode:
        logger.warning(
            {
                'message': '[repopulate_zipcode] zipcode still empty',
                'application_id': application_id,
                'provinsi': provinsi,
                'kota_kabupaten': kota_kabupaten,
                'kecamatan': kecamatan,
                'kelurahan': kelurahan,
            }
        )
        tag_tracer = ApplicationTagTracking(application=application)
        tag_tracer.adding_application_path_tag(
            SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE,
            SimilarityTextConst.TAG_STATUS_IS_FAILED,
        )
        return

    new_zipcode = sub_district_and_zipcode.zipcode
    record_data_update.append(
        {
            'application_id': application_id,
            'field_name': 'address_kodepos',
            'new_value': new_zipcode,
            'old_value': kodepos,
        }
    )

    # update data in application
    application.update_safely(
        address_provinsi=provinsi,
        address_kabupaten=kota_kabupaten,
        address_kecamatan=kecamatan,
        address_kelurahan=kelurahan,
        address_kodepos=new_zipcode,
    )

    # create record update process
    record_application_change_field(
        application_id=application_id,
        record_data_update=record_data_update,
    )


@task(queue="application_high")
def repopulate_company_address(application_id):

    application = Application.objects.filter(pk=application_id).last()
    if not application or not application.company_name or not application.is_julo_one_or_starter():
        return False

    if application.company_address:
        return False

    application_id = application.id
    company_name = remove_double_space(application.company_name)

    # query based on company name
    company_lookup = CompanyLookup.objects.filter(company_name__iexact=company_name).last()
    if not company_lookup:
        logger.warning(
            {
                'message': '[repopulate_company_address] company lookup is not found',
                'company_name': company_name,
                'application_id': application_id,
            }
        )
        return False

    company_address_lookup = company_lookup.company_address
    if not company_address_lookup:
        logger.warning(
            {
                'message': '[repopulate_company_address] company lookup is found, '
                'but company_address is empty',
                'company_name': company_name,
                'company_lookup_id': company_lookup.id,
                'application_id': application_id,
            }
        )
        return False

    limit_characters = 100
    if len(company_address_lookup) > limit_characters:
        company_address_lookup = company_address_lookup[:limit_characters]

    # record the change
    ApplicationFieldChange.objects.create(
        application=application,
        field_name='company_address',
        old_value=application.company_address,
        new_value=company_address_lookup,
    )

    # do update in ops.application table
    application.update_safely(company_address=company_address_lookup)

    logger.info(
        {
            'message': '[repopulate_company_address] process is success',
            'company_name': company_name,
            'company_address_lookup': company_address_lookup,
            'application_id': application_id,
        }
    )

    return True
