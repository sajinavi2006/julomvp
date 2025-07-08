from django.db import transaction
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from datetime import date, datetime, timedelta

from juloserver.application_form.models.idfy_models import IdfyVideoCall
from juloserver.julo.clients.idfy import IDfyGetProfileError, IDfyServerError, get_idfy_client
from juloserver.followthemoney.utils import general_error_response
from juloserver.julo.models import (
    Application,
    Image,
    ApplicationStatusCodes,
)
from juloserver.apiv3.models import SubDistrictLookup
from juloserver.julo.exceptions import ApplicationNotFound, ForbiddenError
from juloserver.julolog.julolog import JuloLog
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.application_form.exceptions import IDFyException
from juloserver.application_form.tasks.idfy_task import (
    copy_resource_selfie_to_application,
    copy_resource_ktp_to_application,
    copy_resource_additional_document_to_application,
)
from juloserver.julo.tasks import upload_image
from juloserver.apiv1.serializers import ApplicationSerializer
from juloserver.moengage.services.use_cases import (
    send_user_attributes_to_moengage_for_idfy_verification_success,
    send_user_attributes_to_moengage_for_idfy_completed_data,
)
from juloserver.application_form.constants import (
    IDFyApplicationTagConst,
    LabelFieldsIDFyConst,
    ApplicationEditedConst,
    ApplicationDirectionConst,
    IDFyCallbackConst,
    LFS_FIELDS,
    LFS_SPLIT_EMERGENCY_CONTACT_FIELDS,
    LONGFORM_FIELDS,
)
from juloserver.julo.services import process_application_status_change
from juloserver.julo.models import FeatureSetting, FeatureNameConst
from juloserver.julo.utils import get_oss_public_url
from juloserver.julo.constants import OnboardingIdConst
from juloserver.face_recognition.constants import ImageType
from juloserver.application_form.models.idfy_models import IdfyCallBackLog
from juloserver.application_form.constants import IDFyAgentOfficeHoursConst
from juloserver.pii_vault.constants import PiiSource
from juloserver.pii_vault.services import detokenize_for_model_object
from juloserver.julo.services import process_image_upload_direct

logger = JuloLog(__name__)
sentry = get_julo_sentry_client()
idfy_client = get_idfy_client()


def proceed_the_status_response(response):
    import traceback
    from juloserver.application_flow.tasks import application_tag_tracking_task

    resource_image = None
    is_moved_partial_form = False
    data, resources, tasks_data, status_reason = parse_init_idfy_response(response)

    reference_id = data['reference_id']

    idfy_record = IdfyVideoCall.objects.filter(
        reference_id=reference_id,
        status=data['status'],
    ).last()

    application_id = get_application_id(reference_id)
    data['application_id'] = application_id

    if data['status'] in (
        LabelFieldsIDFyConst.KEY_REJECTED,
        LabelFieldsIDFyConst.KEY_COMPLETED,
    ):
        resource_image, resource_text = parse_resource_idfy_response(resources)
        construct_data, is_short_data = parse_data_resource(resource_text)
        construct_task = parse_task_resource(tasks_data)
        mobile_number = construct_data.get('mobile_number', None)
        application, application_update = copy_resource_to_application(
            construct_data,
            construct_task,
            application_id,
        )

        if application_update:
            # Generate zip code from province, city, district, and subdistrict
            if not application_update.get(
                'address_kodepos' or application_update.get('address_kodepos') == ''
            ):
                application_update['address_kodepos'] = get_zipcode_from_idfy_callback(
                    application_update
                )

            with transaction.atomic():
                application.update_safely(**application_update)

            detokenize_applications = detokenize_for_model_object(
                PiiSource.APPLICATION,
                [
                    {
                        'customer_xid': application.customer.customer_xid,
                        'object': application,
                    }
                ],
                force_get_local_data=True,
            )
            application = detokenize_applications[0]

            is_moved_partial_form = is_form_submission_complete(
                application,
                application_update,
                data['status'],
                data['reviewer_action'],
                mobile_number,
            )

            store_agent_edited_data_in_logging_db(
                application_id, data['profile_id'], reference_id, data['status'], tasks_data
            )

    if data['status'] == LabelFieldsIDFyConst.KEY_IN_PROGRESS:
        application_tag_tracking_task.delay(
            application_id,
            None,
            None,
            None,
            IDFyApplicationTagConst.TAG_NAME,
            IDFyApplicationTagConst.IN_PROGRESS_VALUE,
            traceback.format_stack(),
        )

    # check only status tasks are completed can updated data or image
    if data['status'] == LabelFieldsIDFyConst.KEY_COMPLETED:
        url_ktp, url_selfie, url_additional_docs = proceed_split_images(resource_image)
        # execute to copying data to application
        copy_resource_selfie_to_application.delay(
            url_selfie,
            application_id,
        )
        copy_resource_ktp_to_application.delay(
            url_ktp,
            application_id,
        )
        copy_resource_additional_document_to_application.delay(
            url_additional_docs,
            application_id,
        )

        # set function to skip liveness detection
        skip_liveness_detection(application_id)

        if not is_moved_partial_form:
            # send notification to customer
            send_user_attributes_to_moengage_for_idfy_verification_success.delay(application_id)

        application_tag_tracking_task.delay(
            application_id,
            None,
            None,
            None,
            IDFyApplicationTagConst.TAG_NAME,
            IDFyApplicationTagConst.SUCCESS_VALUE,
            traceback.format_stack(),
        )

        if is_moved_partial_form:
            # need to move x105 status
            logger.info(
                {
                    'action': 'idfy-callback > proceed_the_status_response',
                    'message': 'application auto-moved to x105 from idfy callback',
                    'auto-move': True,
                    'application_id': application_id,
                }
            )

            process_application_status_change(
                application_id,
                ApplicationStatusCodes.FORM_PARTIAL,
                change_reason='customer_triggered',
            )
            send_user_attributes_to_moengage_for_idfy_completed_data.delay(application_id)
        else:
            logger.info(
                {
                    'action': 'idfy-callback > proceed_the_status_response',
                    'message': 'application NOT auto-moved to x105 from idfy',
                    'auto-move': False,
                    'application_id': application_id,
                }
            )

    if data['reviewer_action'] == LabelFieldsIDFyConst.KEY_REJECTED:
        if str(status_reason).lower() != LabelFieldsIDFyConst.REASON_TO_CONTINUE_FORM.lower():
            logger.info(
                {
                    'message': 'try to move application x135',
                    'application': application_id,
                    'reason': status_reason,
                }
            )

            process_application_status_change(
                application_id,
                ApplicationStatusCodes.APPLICATION_DENIED,
                status_reason,
            )

            if not idfy_record:
                stored_as_new_record_idfy(
                    data, application_id, reference_id, status_reason=status_reason
                )

            return True

        logger.info(
            {
                'message': 'Application drop off by customer',
                'application': application_id,
                'reason': status_reason,
            }
        )

    if not idfy_record:
        stored_as_new_record_idfy(data, application_id, reference_id, status_reason=status_reason)
        return True

    logger.info(
        {
            'message': 'update the record from idfy',
            'status': data['status_tasks'],
            'application': idfy_record.application_id,
            'reference_id': reference_id,
        }
    )

    # update the record
    update_data = {
        'status_tasks': data['status_tasks'],
        'reviewer_action': data['reviewer_action'],
        'notes': data['notes'],
    }

    if status_reason and data['reviewer_action'] == LabelFieldsIDFyConst.KEY_REJECTED:
        update_data['reject_reason'] = status_reason

    idfy_record.update_safely(**update_data)

    return True


@sentry.capture_exceptions
def parse_init_idfy_response(response):
    """
    This to parse response callback from IDFy when:
    in progress and completed the Video Call
    """

    if not response:
        error_msg = 'Unexpected response from IDFY'
        logger.error(
            {
                'message': error_msg,
                'response': str(response),
            }
        )
        raise IDFyException(error_msg)

    performed_video_by = None
    status_tasks = None
    resources = response['resources']
    profile_data = response['profile_data']

    notes = profile_data['notes']
    if len(profile_data['performed_by']) > 0:
        profile_items = profile_data['performed_by'][0]
        performed_video_by = profile_items['email']

    tasks_data = response['tasks']
    if len(tasks_data) > 0:
        status_tasks = tasks_data[0]['status']

    status_reason = get_status_reason(response)
    data = {
        'profile_id': response['profile_id'],
        'reference_id': response['reference_id'],
        'performed_video_call_by': performed_video_by,
        'status': response['status'],
        'status_tasks': status_tasks,
        'reviewer_action': response['reviewer_action'],
        'notes': notes,
    }

    return data, resources, tasks_data, status_reason


@sentry.capture_exceptions
def parse_resource_idfy_response(resources):
    """
    For parsing data resource if video call have completed.
    """

    resource_images = None
    resource_text = None
    if 'images' in resources:
        resource_images = resources['images']

    if 'text' in resources:
        resource_text = resources['text']

    return resource_images, resource_text


def get_application_id(application_xid):
    if not application_xid:
        return None

    application = Application.objects.filter(application_xid=application_xid).values('id').last()

    if not application:
        return None

    return application['id']


def proceed_split_images(resource_images):
    url_selfie = None
    url_ktp = None
    url_additional_docs = None
    for image in resource_images:
        if image['ref_id']:
            ref_id_split = image['ref_id'].split('.')

            if ref_id_split[0] == LabelFieldsIDFyConst.KEY_RESOURCE_KTP:
                url_ktp = image['value']

            if (
                image['type'] == LabelFieldsIDFyConst.KEY_RESOURCE_SELFIE
                and ref_id_split[1] == LabelFieldsIDFyConst.KEY_RESOURCE_SELFIE
            ):
                url_selfie = image['value']

            if ref_id_split[0] == LabelFieldsIDFyConst.KEY_RESOURCE_ADDITIONAL_DOCS:
                url_additional_docs = image['value']

    return url_ktp, url_selfie, url_additional_docs


def upload_file_image_with_filename(image, filename, application_id, image_type):
    # create feature setting
    use_oss = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IDFY_NFS_DEPENDENCY, is_active=True
    ).exists()
    new_image = Image()
    new_image.image_type = image_type
    new_image.image_source = application_id
    new_image.save()
    if use_oss:
        process_image_upload_direct(
            new_image, image, thumbnail=False, delete_if_last_image=True, image_file_name=filename
        )
    else:
        new_image.image.save(filename, image)
        upload_image.apply_async(
            (
                new_image.id,
                False,
                True,
            ),
            queue='high',
            routing_key='high',
        )

    return new_image


def get_ifdfy_record_result(customer_id, application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        raise ApplicationNotFound()

    if application.customer.id != customer_id:
        raise ForbiddenError()

    idfy_record = IdfyVideoCall.objects.filter(application_id=application_id)
    if not idfy_record.exists():
        return {"idfy": False, "video_status": None, "application": {}}

    application_data = {}
    status = LabelFieldsIDFyConst.KEY_IN_PROGRESS

    is_idfy_completed = is_completed_vc(application=application)

    # handle if have status canceled
    has_canceled_status = idfy_record.filter(status=LabelFieldsIDFyConst.KEY_CANCELED).exists()
    if has_canceled_status:
        status = LabelFieldsIDFyConst.KEY_CANCELED

    # Check if office hour or not
    is_office_hours, message = is_office_hours_agent_for_idfy(is_completed=is_idfy_completed)
    if not is_office_hours:
        # override to status is None, so customers will not blocking popup in x100
        status = None
        logger.warning(
            {
                'message': 'Customers open x100 when outside office hours',
                'application': application_id,
                'status': status,
            }
        )

    if is_idfy_completed:
        # Note if status is completed popup will not shown in FE
        status = LabelFieldsIDFyConst.KEY_COMPLETED
        application_data = ApplicationSerializer(application).data

    return {
        "idfy": True,
        "video_status": status,
        "application": application_data,
    }


@sentry.capture_exceptions
def store_agent_edited_data_in_logging_db(
    application_id, profile_id, reference_id, status, tasks_data
):
    """
    Store agent-edited data in the logging database.

    Parameters:
        - application_id (int): The ID of the application.
        - profile_id (int): The ID of the profile.
        - reference_id (str): The reference ID.
        - status (str): The status of the operation.
        - tasks_data (list): A list of tasks data.

    Notes:
        - If `application_id` or `tasks_data` is empty, the function returns without action.
        - Logs an error if the application with the given `application_id` is not found.
        - Extracts `manual_response` from the first task in `tasks_data` if available.
        - Creates a record in the IdfyCallBackLog model.

    Returns:
        None
    """
    if not application_id or not tasks_data:
        return

    application = Application.objects.filter(id=application_id).last()

    if not application:
        logger.error(
            {
                'message': 'Application not found',
                'application': application_id,
            }
        )
        return

    manual_response = None
    if tasks_data[0].get('tasks'):
        for data in tasks_data[0]['tasks']:
            if not data['tasks']:
                continue
            data_key = data['tasks'][0]['key']
            if data_key == 'avkyc_pan_4689':
                manual_response = data['tasks'][0]['result']['manual_response']
    data = {
        'application_id': application_id,
        'profile_id': profile_id,
        'reference_id': reference_id,
        'status': status,
        'callback_log': manual_response,
    }
    IdfyCallBackLog.objects.create(**data)


@sentry.capture_exceptions
def parse_task_resource(tasks_data):
    if not tasks_data:
        return None
    try:
        construct_data = {}
        if tasks_data[0].get('tasks'):
            for data in tasks_data[0]['tasks']:
                if not data['tasks']:
                    continue
                data_key = data['tasks'][0]['key']
                value = data['tasks'][0]['result']['manual_response']

                if not value:
                    continue
                else:
                    value = value.get('value')
                if data_key == 'verifyQA_5' and data['tasks'][0]['status'] == 'completed':
                    construct_data['loan_purpose'] = value
                elif data_key == 'verifyQA_31' and data['tasks'][0]['status'] == 'completed':
                    construct_data['bank_name'] = value
                elif data_key == 'verifyQA_27' and data['tasks'][0]['status'] == 'completed':
                    construct_data['job_description'] = value
                elif data_key == 'verifyQA_3' and data['tasks'][0]['status'] == 'completed':
                    construct_data['job_industry'] = value
                elif data_key == 'verifyQA_1' and data['tasks'][0]['status'] == 'completed':
                    construct_data['close_kin_relationship'] = value
                elif data_key == 'verifyQA_7' and data['tasks'][0]['status'] == 'completed':
                    construct_data['last_education'] = value
                elif data_key == 'avkyc_pan_4689' and data['tasks'][0]['status'] == 'completed':
                    value_dict = data['tasks'][0]['result']['manual_response']['extraction_output']
                    construct_data['address_detail'] = value_dict['alamat']
                    construct_data['address_kecamatan'] = value_dict['kecamatan']
                    construct_data['address_kelurahan'] = value_dict['kel_desa']
                    construct_data['address_kabupaten'] = value_dict['kota_or_kabupaten']
                    construct_data['address_provinsi'] = value_dict['provinci']
                    construct_data['birth_place'] = value_dict['tempat']
                    construct_data['dob'] = value_dict['tgl_lahir']
                    construct_data['gender'] = LabelFieldsIDFyConst.GENDER_MAPPING.get(
                        value_dict['jenis_kelamin']
                    )
                    construct_data['fullname'] = value_dict['nama']
                    construct_data[
                        'marital_status'
                    ] = LabelFieldsIDFyConst.MARITAL_STATUS_MAPPING.get(
                        value_dict['status_perkawinan'], None
                    )
                    construct_data['job_type'] = value_dict['pekerjaan']
                elif (
                    data_key == 'question_name'
                    and data['tasks'][0]['question'] == 'Alamat tempat tinggal masih sama?'
                    and data['tasks'][0]['status'] == 'completed'
                ):
                    value = data['tasks'][0]['result']['manual_response']['value']
                    construct_data['address_same_as_ktp'] = value
    except Exception as error:
        raise IDFyException(str(error))
    return construct_data


@sentry.capture_exceptions
def parse_data_resource(resource_text):
    if not resource_text:
        return None

    is_short_data = True
    try:
        construct_data = {}
        for data in resource_text:
            field = data['ref_id'].split('.')[0]
            if field != 'nil':
                construct_data[field] = data['value']

        if 'mobile_number' in construct_data:
            is_short_data = False

        if 'mobile_number' not in construct_data and 'phone_no' in construct_data:
            construct_data['mobile_number'] = construct_data['phone_no']

        return construct_data, is_short_data

    except Exception as error:
        raise IDFyException(str(error))


def copy_resource_to_application(
    construct_data,
    construct_task,
    application_id,
):
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        logger.error(
            {
                'message': 'Application not found',
                'application': application_id,
            }
        )
        return False, None

    if (
        application.application_status_id != ApplicationStatusCodes.FORM_CREATED
        or not application.is_julo_one()
    ):
        logger.error(
            {
                'message': 'application not allowed',
                'process': 'copying data from IDFy',
                'application': application.id,
                'j1': application.is_julo_one(),
                'application_status_code': application.application_status_id,
            }
        )
        return False, None

    customer = application.customer
    mother_maiden_name = construct_data.get('mothers_name', None)
    ktp_birth_place = construct_data.get('ktp_birth_place', None)
    birth_place = construct_data.get('birth_place', None)

    # init prepare the data
    application_update = {
        'address_street_num': construct_data.get('ktp_address', None),
        'dob': construct_data.get('ktp_dob', None),
        'birth_place': ktp_birth_place or birth_place,
    }

    transform_fields = LabelFieldsIDFyConst.TRANSFORM_FIELDS
    for field_db in transform_fields:
        field_response = transform_fields[field_db]
        value_from_idfy = construct_data.get(field_response, None)
        if not value_from_idfy:
            continue
        application_update[field_db] = value_from_idfy

    if construct_task:
        keys_to_update = [
            'loan_purpose',
            'bank_name',
            'job_description',
            'job_industry',
            'job_type',
            'close_kin_relationship',
            'address_detail',
            'address_kecamatan',
            'address_kabupaten',
            'address_provinsi',
            'address_kelurahan',
            'dob',
            'address_same_as_ktp',
            'marital_status',
            'last_education',
            'gender',
            'fullname',
            'birth_place',
        ]

        for key in keys_to_update:
            if key in construct_task:
                value_from_idfy = construct_task[key] if construct_task[key] else None
                if not value_from_idfy:
                    continue
                application_update[key] = value_from_idfy

    with transaction.atomic():
        if mother_maiden_name:
            customer.update_safely(mother_maiden_name=mother_maiden_name)

    return application, application_update


def is_form_submission_complete(
    application, application_update, status, reviewer_action, mobile_number
):
    if (
        application_update.get('mobile_phone_1')
        and mobile_number == application_update.get('mobile_phone_1')
        and status == LabelFieldsIDFyConst.KEY_COMPLETED
        and reviewer_action == 'approved'
        and check_idfy_application_result(application)
        and application.address_kodepos
    ):
        return True

    return False


def check_idfy_application_result(application: Application) -> bool:
    def _check_has_attr(fields: list) -> bool:
        for field in fields:
            if not getattr(application, field):
                return False
        return True

    if application.onboarding_id == OnboardingIdConst.LONGFORM_SHORTENED_ID:
        return _check_has_attr(LFS_FIELDS)
    if application.onboarding_id == OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT:
        return _check_has_attr(LFS_SPLIT_EMERGENCY_CONTACT_FIELDS)
    if application.onboarding_id == OnboardingIdConst.LONGFORM_ID:
        return _check_has_attr(LONGFORM_FIELDS)

    return False


def stored_as_new_record_idfy(data, application_id, reference_id, status_reason=None):
    # insert as new record
    logger.info(
        {
            'message': 'save new record for idfy',
            'status': data['status_tasks'],
            'application': application_id,
            'reference_id': reference_id,
        }
    )

    idfy_video_call = IdfyVideoCall(**data)
    if status_reason:
        idfy_video_call.reject_reason = status_reason
    idfy_video_call.save()


def skip_liveness_detection(application_id):
    from juloserver.liveness_detection.constants import LivenessCheckStatus
    from juloserver.liveness_detection.models import (
        ActiveLivenessDetection,
        PassiveLivenessDetection,
    )

    if not application_id:
        return

    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return

    customer = application.customer
    current_passive_liveness = PassiveLivenessDetection.objects.filter(
        customer=customer,
        application=application,
    ).last()

    data_set = dict(
        customer=customer,
        application=application,
        status=LivenessCheckStatus.SKIPPED_CUSTOMER,
    )

    with transaction.atomic():

        logger.info(
            {
                'message': 'creating skip customer for active liveness with new data',
                'process': 'skip_liveness_for_idfy_customer',
                'application': application_id,
            }
        )
        ActiveLivenessDetection.objects.create(**data_set)

        if not current_passive_liveness:
            logger.info(
                {
                    'message': 'creating skip customer for active liveness',
                    'process': 'skip_liveness_for_idfy_customer',
                    'application': application_id,
                }
            )
            PassiveLivenessDetection.objects.create(**data_set)

        if current_passive_liveness:
            # case if passive liveness already exists
            current_passive_liveness.update_safely(
                status=LivenessCheckStatus.SKIPPED_CUSTOMER,
            )


def get_idfy_instruction():
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.IDFY_INSTRUCTION_PAGE, is_active=True
    )
    if not feature_setting:
        return None

    parameters = feature_setting.parameters
    try:
        image_url = parameters['instruction_image_url']
        parameters['instruction_image_url'] = get_oss_public_url(
            settings.OSS_PUBLIC_ASSETS_BUCKET, image_url
        )
        return parameters
    except Exception:
        sentry.captureException()
        return None


def get_status_reason(data):
    status_reason = None
    if 'tasks' in data:
        for item in data['tasks']:
            if 'key' in item:
                if item['key'] == 'assisted_video.video_pd':
                    manual_response = item['result']['manual_response']
                    if manual_response:
                        status_reason = manual_response.get('status_reason', None)

    return status_reason


def has_identity_images(application_id):
    """
    Check if application have image KTP or selfie or crop selfie in ops.image
    """

    is_exists = Image.objects.filter(
        Q(image_source=application_id)
        & (
            Q(image_type=ImageType.SELFIE)
            | Q(image_type=ImageType.CROP_SELFIE)
            | Q(image_type='ktp_self')
        )
    ).exists()

    logger.info(
        {'message': 'Check has identity images', 'result': is_exists, 'application': application_id}
    )

    return is_exists


@sentry.capture_exceptions
def process_response_from_idfy(profile_id, reference_id, status, session_status):
    if not profile_id and not reference_id:
        error_message = "profile_id and reference_id are empty."
        logger.error(error_message)
        return general_error_response(error_message)

    if (status == "capture_pending" and session_status != "complete") or (
        reference_id and status == "capture_pending"
    ):
        try:
            api_data = idfy_client.get_profile_details(profile_id, reference_id)
            logger.info(
                {
                    'message': 'Successfully fetched profile details for profile_id',
                    'profile_id': profile_id,
                }
            )

            parsed_data, is_short_data = parse_data_resource(
                api_data.get("resources", {}).get("text")
            )

            logger.info({'message': 'Parsed profile data for profile_id', 'profile_id': profile_id})

        except (IDfyGetProfileError, IDfyServerError) as e:
            logger.error({'message': str(e), 'profile_id': profile_id})
            return False
        except IDFyException as e:
            logger.error({'message': str(e), 'profile_id': profile_id})
            return False

        phone_number = parsed_data.get("mobile_number")

        if phone_number is not None and phone_number.strip():
            if reference_id:
                application = Application.objects.filter(application_xid=reference_id).last()
            else:
                idfy_data = IdfyVideoCall.objects.filter(profile_id=profile_id).last()
                application = Application.objects.filter(
                    application_xid=idfy_data.reference_id
                ).last()

            if application.mobile_phone_1:
                logger.info(
                    {
                        'message': 'Skip copy/update phone number process for drop off.',
                        'application': application.id,
                        'profile_id': profile_id,
                    }
                )
                return True

            if (
                application.application_status_id <= ApplicationStatusCodes.FORM_PARTIAL
                and not application.mobile_phone_1
            ):
                application.update_safely(mobile_phone_1=phone_number)
                logger.info(
                    {
                        'message': 'Successfully updated mobile_phone_1',
                        'profile_id': profile_id,
                        'phone_number': phone_number,
                    }
                )
                return True
        logger.warning({'message': "Phone number is null or empty.", 'profile_id': profile_id})
        return False
    logger.error(
        {
            'message': 'Invalid input or conditions not met in get_response_from_idfy.',
            'profile_id': profile_id,
        }
    )
    return False


def is_completed_vc(application):
    """
    Check if application J1 using iDFy and completed video call
    """

    if application.is_julo_one():
        is_completed = IdfyVideoCall.objects.filter(
            application_id=application.id,
            status=LabelFieldsIDFyConst.KEY_COMPLETED,
        ).exists()

        return is_completed

    logger.warning(
        {
            'message': 'is_completed_vc J1 is False',
            'application': application.id if application else None,
        }
    )

    return False


def process_change_status_idfy(customer_id, data):
    """
    to change status IDFy video call
    """

    application_id = data.get('application_id', None)
    is_canceled = data.get('is_canceled')
    if not application_id:
        logger.error(
            {
                'message': 'Invalid case application_id empty',
                'application': application_id,
                'is_canceled': is_canceled,
            }
        )
        raise ApplicationNotFound()

    application = Application.objects.filter(pk=application_id).last()
    if application.status != ApplicationStatusCodes.FORM_CREATED:
        logger.info(
            {
                'message': 'Invalid case application not allowed',
                'application': application_id,
                'application_status_code': application.application_status_id,
                'is_canceled': is_canceled,
            }
        )
        return False, None

    if application.customer_id != customer_id:
        logger.info(
            {
                'message': 'Invalid case not match customer_id',
                'application': application_id,
                'application_status_code': application.application_status_id,
                'is_canceled': is_canceled,
            }
        )
        raise ForbiddenError()

    idfy_call = IdfyVideoCall.objects.filter(application_id=application_id).last()
    if not idfy_call:
        destination_page = None
        # check condition if canceled is false -> go to video call
        if not is_canceled:
            destination_page = ApplicationDirectionConst.VIDEO_CALL_SCREEN
            is_office_hours, message = is_office_hours_agent_for_idfy()
            if not is_office_hours:
                raise IDFyException(message)

        logger.info(
            {
                'message': 'customer not registered as idfy flow',
                'application': application_id,
                'application_status_code': application.application_status_id,
                'is_canceled': is_canceled,
            }
        )

        return True, destination_page

    if is_completed_vc(application):
        if not is_canceled:
            logger.info(
                {
                    'message': 'Already completed video call',
                    'application': application_id,
                    'application_status_code': application.application_status_id,
                    'is_canceled': is_canceled,
                }
            )
            raise IDFyException('Anda sudah selesai melakukan video call')

        logger.info(
            {
                'message': 'already completed video call and go to form',
                'application': application_id,
                'application_status_code': application.application_status_id,
                'is_canceled': is_canceled,
            }
        )

        return True, None

    status = LabelFieldsIDFyConst.KEY_CANCELED
    if not is_canceled:
        status = LabelFieldsIDFyConst.KEY_IN_PROGRESS

    if idfy_call.status == status:
        logger.info(
            {
                'message': 'return with same status',
                'application': application_id,
                'result': status,
                'is_canceled': is_canceled,
            }
        )
        return True, None

    logger.info(
        {
            'message': 'process update status IDFy',
            'application': application_id,
            'result': status,
            'is_canceled': is_canceled,
        }
    )

    # update status
    idfy_call.update_safely(
        status=status,
    )
    return True, None


def is_office_hours_agent_for_idfy(is_completed=False):
    """
    To check still in office hours or not
    and expected if run this function with application not completed
    video call IDFy.
    """

    message = None
    if is_completed:
        logger.info(
            {
                'action': 'is_office_hours_agent_for_idfy',
                'message': 'Already completed video call',
                'result': False,
                'is_completed_vc': is_completed,
            }
        )
        message = 'Kamu sudah pernah melakukan video call'
        return False, message

    dynamic_configuration = get_scheduler_message_for_idfy()
    is_available = dynamic_configuration['is_available']
    title = dynamic_configuration['title']

    if not is_available and not title:
        logger.info(
            {
                'action': 'is_office_hours_agent_for_idfy',
                'message': 'Office hours feature setting is off',
                'result': False,
                'is_completed_vc': is_completed,
            }
        )
        message = 'Video call tidak tersedia saat ini'
        return False, message

    office_hours = dynamic_configuration['office_hours']
    if is_available:
        logger.info(
            {
                'message': 'In office hours and not completed video call',
                'result': True,
                'is_completed_vc': is_completed,
                'office_hours': office_hours,
            }
        )
        return True, message

    logger.info(
        {
            'action': 'is_office_hours_agent_for_idfy',
            'message': 'Outside office hours',
            'result': False,
            'is_completed_vc': is_completed,
            'office_hours': office_hours,
        }
    )

    message = (
        'Video call hanya bisa dilakukan pada jam {0:02d}.{1:02d} - {2:02d}.{3:02d} WIB'.format(
            office_hours['open']['hour'],
            office_hours['open']['minute'],
            office_hours['close']['hour'],
            office_hours['close']['minute'],
        )
    )

    return False, message


def compare_application_data_idfy(application):
    """
    Compare application data with callback record on logging.idfy_callback_log table.

    Parameters:
        - application: instance of Application Model

    Returns:
        - is_different: Booelan - there are difference between application callback log
        - different_data: list of attributes that are different
    """
    is_different, different_data = False, []

    if (
        not application
        or not application.is_julo_one()
        or application.application_status_id < ApplicationStatusCodes.FORM_PARTIAL
    ):
        return is_different, different_data

    callback_log = get_data_from_video_call(application)
    if not callback_log or callback_log.status != 'completed':
        return is_different, different_data

    time_created_callback = callback_log.cdate
    time_range_copy_file = time_created_callback + timedelta(
        minutes=IDFyCallbackConst.MAX_TIME_OF_DELAY_IDFY_CALLBACK,
    )

    # get value for image ktp and selfie
    target_images = ['ktp_self', 'selfie']
    callback_image = {}
    for field in target_images:
        image = Image.objects.filter(
            image_source=application.id,
            image_type=field,
            cdate__gte=time_created_callback,
            cdate__lte=time_range_copy_file,
        ).last()
        callback_image[field] = image.id if image else None

    normal_image = {}
    for field in target_images:
        image = Image.objects.filter(
            image_source=application.id,
            image_type=field,
        ).last()
        normal_image[field] = image.id if image else None

    for field in target_images:
        if not normal_image[field] or not callback_image[field]:
            continue

        if normal_image[field] != callback_image[field]:
            different_data.append(field)

    callback_log = callback_log.callback_log
    if not callback_log:
        return is_different, different_data

    callback_data = callback_log.get('extraction_output')
    if not callback_data:
        return is_different, different_data

    compare_fields = ApplicationEditedConst.APPLICATION_FIELDS_MAPPING
    for callback_field in compare_fields:
        if hasattr(application, compare_fields[callback_field]):
            application_value = getattr(application, compare_fields[callback_field])
            callback_value = callback_data[callback_field]
            if callback_field in ['tgl_lahir']:
                try:
                    callback_dob = (
                        datetime.strptime(callback_value, "%Y-%m-%d")
                        if isinstance(callback_value, str)
                        else callback_value
                    )

                    application_dob = (
                        datetime.strptime(application.dob, "%Y-%m-%d")
                        if isinstance(application.dob, str)
                        else application.dob
                    )

                    callback_dob = (
                        callback_dob.date() if isinstance(callback_dob, datetime) else callback_dob
                    )
                    if application_dob != callback_dob:
                        different_data.append(callback_field)
                except Exception as e:
                    logger.warning(
                        {
                            "message": "Incorrect date on callback data",
                            "action": "compare_applciation_data_idfy",
                            "error": str(e),
                            "application_id": application.id,
                        }
                    )
                    continue
            else:
                if str(callback_value).lower() != str(application_value).lower():
                    different_data.append(callback_field)

    if len(different_data) > 0:
        is_different = True

    return is_different, different_data


def edited_data_comparison(application, different_data=[]):
    if not application or len(different_data) < 1:
        return None

    edited_data_list = {}

    data_field_list = ApplicationEditedConst.FIELDS
    application_fields = ApplicationEditedConst.APPLICATION_FIELDS_MAPPING
    for field in data_field_list:
        if field in ['ktp_self', 'selfie']:
            image = Image.objects.filter(image_source=application.id, image_type=field).last()
            value = image.image_url if image else None
        else:
            value = getattr(application, application_fields[field])

        # change format to yyyy-mm-dd
        if field == 'tgl_lahir' and value:
            original_value = value
            try:
                value = value.strftime('%Y-%m-%d')
            except AttributeError:
                logger.warning(
                    {
                        'message': '[IDFyCRM]: Field tgl_lahir is not valid, '
                        'handle by exception to original value',
                        'original_value': original_value,
                        'application_id': application.id if application else None,
                    }
                )
                value = original_value

        edited_data_list[field] = {
            'value': value,
            'is_different': False,
        }
        if field in different_data:
            edited_data_list[field]['is_different'] = True

    return edited_data_list


def get_data_from_video_call(application):
    callback_log = IdfyCallBackLog.objects.filter(application_id=application.id).last()

    return callback_log


def transform_data_from_video_call(application):
    is_match_for_job = False
    callback_log = get_data_from_video_call(application)

    if not callback_log:
        return None, is_match_for_job

    if callback_log.status != 'completed':
        logger.info(
            {
                'message': 'Callback video call from IDFy still not completed status',
                'application': application.id,
                'status': callback_log.status,
            }
        )
        return None, is_match_for_job

    if not callback_log.callback_log:
        return None, is_match_for_job

    callback_data = callback_log.callback_log.get('extraction_output')
    if not callback_data:
        return None, is_match_for_job

    time_created_callback = callback_log.cdate
    time_range_copy_file = time_created_callback + timedelta(
        minutes=IDFyCallbackConst.MAX_TIME_OF_DELAY_IDFY_CALLBACK,
    )

    data_transform = {}
    for item in callback_data:
        data_transform[item] = callback_data.get(item, None)

    # get value for image ktp and selfie
    target_images = ['ktp_self', 'selfie']
    for field in target_images:
        image = Image.objects.filter(
            image_source=application.id,
            image_type=field,
            cdate__gte=time_created_callback,
            cdate__lte=time_range_copy_file,
        ).last()
        data_transform[field] = image.image_url if image else None

    pekerjaan = application.job_type if application else None
    list_job_type = list(set([x[0] for x in Application().JOB_TYPE_CHOICES]))

    if pekerjaan and pekerjaan in list_job_type:
        is_match_for_job = True

    return data_transform, is_match_for_job


def get_zipcode_from_idfy_callback(application_update):
    kelurahan = application_update.get('address_kelurahan')
    kecamatan = application_update.get('address_kecamatan')
    kota = application_update.get('address_kabupaten')
    provinsi = application_update.get('address_provinsi')

    if not kelurahan or not kecamatan or not kota or not provinsi:
        return None

    sub_district = SubDistrictLookup.objects.filter(
        sub_district__iexact=kelurahan,
        district__district__iexact=kecamatan,
        district__city__city__iexact=kota,
        district__city__province__province__iexact=provinsi,
    ).last()

    if sub_district:
        return sub_district.zipcode


def get_scheduler_message_for_idfy():

    # Init
    btn_message_default = IDFyAgentOfficeHoursConst.BTN_MSG_IN
    messages_response = {
        'is_available': False,
        'title': None,
        'message': None,
        'button_message': None,
        'office_hours': None,
    }

    # today
    today = timezone.localtime(timezone.now())
    today_date = today.date()
    day_of_week = today.weekday()

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
    ).last()

    if not setting or not setting.is_active:
        logger.warning(
            {
                'message': 'IDfy Configuration is off or empty',
                'feature_name': FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
                'message_response': messages_response,
            }
        )
        return messages_response

    # data parameters
    parameters = setting.parameters
    scheduler_messages = parameters.get('scheduler_messages')
    office_hours = get_office_hours_holidays_or_weekdays(setting, day_of_week)
    all_message_set_date = generate_init_message_default(parameters)

    if not scheduler_messages:
        is_available = is_available_in_office_hours(setting, office_hours)
        all_message = '<br>'.join(all_message_set_date)

        messages_response = {
            'is_available': is_available,
            'title': IDFyAgentOfficeHoursConst.TITLE_DEFAULT,
            'message': all_message,
            'button_message': generate_message_info(btn_message_default, office_hours),
            'office_hours': office_hours,
        }
        logger.info(
            {
                'message': 'Rule for scheduler office hours is empty',
                'office_hours': office_hours,
                'message_response': messages_response,
            }
        )

        return messages_response

    for rule_date in scheduler_messages:

        # Concatenating message
        set_date = datetime.strptime(rule_date['set_date'], '%Y-%m-%d')
        set_date_format = date.strftime(set_date, "%d %B")
        all_message_set_date.append(
            set_date_format
            + ': '
            + generate_message_info(
                IDFyAgentOfficeHoursConst.FORMAT_WIB_DEFAULT,
                rule_date,
            )
        )

        # Collect match date for automate message
        if str(today_date) == str(rule_date['set_date']):
            office_hours = rule_date

            # check if today is day off
            if is_day_off_operational(office_hours):
                btn_message_default = IDFyAgentOfficeHoursConst.BTN_MSG_OUTSIDE

    # If nothing match date in scheduler message
    if not office_hours:
        office_hours = get_office_hours_holidays_or_weekdays(setting, day_of_week)
        logger.info(
            {
                'message': 'Nothing match rule for scheduler office hours get date with basic flow',
                'office_hours': office_hours,
            }
        )

    is_available = is_available_in_office_hours(setting, office_hours)

    # In office hours Case
    if is_available:
        messages_response = {
            'is_available': is_available,
            'title': IDFyAgentOfficeHoursConst.TITLE_DEFAULT,
            'message': generate_message_info(
                IDFyAgentOfficeHoursConst.MESSAGE_DEFAULT, office_hours
            ),
            'button_message': generate_message_info(btn_message_default, office_hours),
            'office_hours': office_hours,
        }
        logger.info({'message': 'In office hours', 'message_response': messages_response})
        return messages_response

    # Outside Office Hours Case
    all_message = '<br>'.join(all_message_set_date)
    messages_response = {
        'is_available': is_available,
        'title': IDFyAgentOfficeHoursConst.TITLE_DEFAULT,
        'message': all_message,
        'button_message': generate_message_info(
            btn_message_default, office_hours, is_override_message=False
        ),
        'office_hours': office_hours,
    }

    logger.info({'message': 'Outside office hours', 'message_response': messages_response})

    return messages_response


def generate_message_info(message, office_hours, is_override_message=True):

    if is_day_off_operational(office_hours):
        office_hours = get_office_hours_holidays_or_weekdays()
        if is_override_message:
            return IDFyAgentOfficeHoursConst.MESSAGE_DAY_OFF_OPERATIONAL

    return message.format(
        office_hours['open']['hour'],
        office_hours['open']['minute'],
        office_hours['close']['hour'],
        office_hours['close']['minute'],
    )


def is_day_off_operational(office_hours):
    if (
        office_hours['open']['hour'] == 0
        and office_hours['open']['minute'] == 0
        and office_hours['close']['hour'] == 0
        and office_hours['close']['minute'] == 0
    ):
        logger.info({'message': 'day off operational for video call', 'office_hours': office_hours})
        return True

    return False


def generate_init_message_default(parameters):

    result_message = []
    weekdays = parameters['weekdays']
    join_weekdays = str(weekdays['open']['hour']) + str(weekdays['close']['hour'])

    holidays = parameters['holidays']
    join_holidays = str(holidays['open']['hour']) + str(holidays['close']['hour'])

    if join_weekdays == join_holidays:
        result_message.append(
            generate_message_info(IDFyAgentOfficeHoursConst.MESSAGE_DEFAULT, weekdays)
        )

        return result_message

    # weekday
    result_message.append(
        generate_message_info(IDFyAgentOfficeHoursConst.MESSAGE_WEEKDAYS, weekdays)
    )

    # weekend / holidays
    result_message.append(
        generate_message_info(IDFyAgentOfficeHoursConst.MESSAGE_HOLIDAYS, holidays)
    )

    return result_message


def is_available_in_office_hours(setting: FeatureSetting, office_hours):

    if not setting or not office_hours:
        return False

    # Getting basically date
    today = timezone.localtime(timezone.now())

    # prepare to compare between date
    open_gate = today.replace(
        hour=office_hours['open']['hour'],
        minute=office_hours['open']['minute'],
    )
    closed_gate = today.replace(
        hour=office_hours['close']['hour'],
        minute=office_hours['close']['minute'],
    )

    if open_gate <= today <= closed_gate:
        return True

    return False


def get_office_hours_holidays_or_weekdays(setting=None, day_of_week=None):

    if not setting:
        setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS,
        ).last()

    if not day_of_week:
        today = timezone.localtime(timezone.now())
        day_of_week = today.weekday()

    return setting.parameters['holidays'] if day_of_week >= 5 else setting.parameters['weekdays']
