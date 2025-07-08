from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.face_recognition.constants import FaceMatchingCheckConst
from juloserver.face_recognition.models import FaceMatchingCheck
from juloserver.fraud_portal.models.models import SelfieMatchingResult, FaceMatchingResult
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting, Image, Application
from juloserver.pii_vault.constants import PiiSource


def get_face_matching_info(application_ids: list) -> list:
    face_matching_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_MATCHING_CHECK, is_active=True
    ).last()

    if not face_matching_fs:
        return []

    face_matching_result_list = get_selfie_to_ktp_info(application_ids, face_matching_fs)

    return face_matching_result_list


def get_selfie_to_ktp_info(application_ids: list, face_matching_fs: FeatureSetting) -> list:
    fs_const = FaceMatchingCheckConst.FeatureSetting
    fs_params = face_matching_fs.parameters
    is_active_selfie_x_ktp = fs_params.get(fs_const.parameter_selfie_x_ktp).get('is_active')
    is_active_selfie_x_liveness = fs_params.get(fs_const.parameter_selfie_x_liveness).get(
        'is_active'
    )

    face_matching_result_list = []
    for application_id in application_ids:
        application = Application.objects.get(
            id=application_id
        )  # throw an exception if cant find the app id
        selfie_image_urls = get_selfie_image_url(application_id)
        selfie_to_ktp_info = get_selfie_to_ktp_face_matching_info(
            application_id, is_active_selfie_x_ktp
        )
        selfie_to_liveness_info = get_selfie_to_liveness_info(
            application_id, is_active_selfie_x_liveness
        )
        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application], ['fullname']
        )[0]
        face_matching_result = FaceMatchingResult(
            application_id=application.id,
            application_full_name=detokenized_application.fullname,
            selfie_image_urls=selfie_image_urls,
            selfie_to_ktp=selfie_to_ktp_info,
            selfie_to_liveness=selfie_to_liveness_info,
        )

        face_matching_result_list.append(face_matching_result.to_dict())

    return face_matching_result_list


def get_selfie_to_ktp_face_matching_info(
    application_id: int, fs_active: bool
) -> SelfieMatchingResult:
    if not fs_active:
        return SelfieMatchingResult(is_feature_active=False)

    face_matching_info = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_ktp.value,
    ).last()

    if not face_matching_info:
        return SelfieMatchingResult(is_feature_active=True)

    image_url = []
    if face_matching_info.target_image:
        image_url.append(face_matching_info.target_image.image_url)

    return SelfieMatchingResult(
        is_feature_active=True,
        is_agent_verified=face_matching_info.is_agent_verified,
        image_urls=image_url if image_url else None,
        status=FaceMatchingCheckConst.Status(face_matching_info.status),
    )


def get_selfie_to_liveness_info(application_id: int, fs_active: bool) -> SelfieMatchingResult:
    if not fs_active:
        return SelfieMatchingResult(is_feature_active=False)

    face_matching_info = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
    ).last()
    if not face_matching_info:
        return SelfieMatchingResult(is_feature_active=True)

    face_matching_check = FaceMatchingCheck.objects.filter(
        application_id=application_id,
        process=FaceMatchingCheckConst.Process.selfie_x_liveness.value,
    ).last()

    if not face_matching_check:
        return SelfieMatchingResult(is_feature_active=True)

    return SelfieMatchingResult(
        is_feature_active=True,
        is_agent_verified=face_matching_check.is_agent_verified,
        image_urls=get_image_urls(application_id),
        status=FaceMatchingCheckConst.Status(face_matching_check.status),
    )


def get_image_urls(application_id: int) -> list:
    liveness_images = Image.objects.filter(
        image_source=application_id,
        image_type__contains='liveness',  # we dont have enum for liveness image type
    )
    image_urls = [image.image_url for image in liveness_images]

    return image_urls


def get_selfie_image_url(
    application_id: int,
) -> list:
    selfie_images = Image.objects.filter(image_source=application_id, image_type__contains='selfie')

    if not selfie_images:
        return None

    image_urls = [image.image_url for image in selfie_images]

    return image_urls
