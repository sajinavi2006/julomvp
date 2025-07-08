import datetime

from django.contrib.staticfiles.templatetags.staticfiles import static
from django.db.models import Q
from django.utils import timezone

from juloserver.antifraud.services.pii_vault import detokenize_pii_antifraud_data
from juloserver.face_recognition.models import (
    FaceSearchResult,
    IndexedFace,
    FraudFaceSearchResult,
    IndexedFaceFraud,
    FaceImageResult,
    FaceSearchProcess,
    FaceRecommenderResult,
    FraudFaceSearchProcess,
    FraudFaceRecommenderResult,
)
from juloserver.fraud_portal.models.models import FaceComparisonInfo, FaceSimilarityInfo
from juloserver.fraud_portal.services.face_matching import get_selfie_image_url
from juloserver.geohash.models import AddressGeolocationGeohash
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import (
    Application,
    FeatureSetting,
    Image,
    AddressGeolocation,
    AddressGeolocationQuerySet,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julocore.data.models import CustomQuerySet
from juloserver.pii_vault.constants import PiiSource


def get_face_similarity_info(application_ids: list) -> list:
    face_similarity_info_list = []

    for application_id in application_ids:
        application = Application.objects.get(id=application_id)

        selfie_image_urls = get_selfie_image_url(application_id)
        face_comparison_info = get_face_comparison_info(application)
        face_comparison_by_geohash = get_face_similarity_by_geohash6(application)

        detokenized_application = detokenize_pii_antifraud_data(
            PiiSource.APPLICATION, [application], ['fullname']
        )[0]
        face_similarity_info = FaceSimilarityInfo(
            application_id=int(application.id),
            application_full_name=detokenized_application.fullname,
            selfie_image_urls=selfie_image_urls,
            face_comparison=face_comparison_info,
            face_comparison_by_geohash=face_comparison_by_geohash,
        )
        face_similarity_info_list.append(face_similarity_info.to_dict())

    return face_similarity_info_list


def get_face_comparison_info(application: Application) -> dict:
    # get similarity fraud face info
    fraud_face_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FRAUDSTER_FACE_MATCH, is_active=True
    ).last()
    fraud_face_status = get_fraud_face_similarity_status(application, fraud_face_fs)
    fraud_face_similarity_info = get_fraud_face_similarity(application, fraud_face_fs)

    # get similarity face info
    similar_face_fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FACE_RECOGNITION, is_active=True
    ).last()
    similarity_face_status = get_face_similarity_status(application, similar_face_fs)
    face_similarity_info = get_similar_face(application, similar_face_fs)

    return {
        "fraud_face_status": fraud_face_status,
        "fraud_face": fraud_face_similarity_info,
        "similarity_face_status": similarity_face_status,
        "similar_face": face_similarity_info,
    }


def get_fraud_face_similarity(application: Application, fraud_face_fs: FeatureSetting) -> list:
    fraud_face_similarity_info = {}

    if not fraud_face_fs:
        return []
    matched_faces_limit = fraud_face_fs.parameters['fraud_face_match_settings']["max_face_matches"]
    search_result = FraudFaceSearchResult.objects.select_related("face_search_process").filter(
        face_search_process__application_id=application
    )[:matched_faces_limit]

    indexed_faces = None
    if search_result and search_result.values('matched_face_image_id'):
        indexed_faces = IndexedFaceFraud.objects.filter(
            image__in=search_result.values('matched_face_image_id')
        )

    if not indexed_faces:
        image_selfie = Image.objects.filter(pk__in=search_result.values('matched_face_image_id'))
        matched_selfie = {
            image.image_source: getattr(image, 'image_url', None) for image in image_selfie
        }
        matched_applications = image_selfie.values('image_source')
    else:
        matched_selfie = {
            indexed_face.application.id: getattr(indexed_face.image, 'image_url', None)
            if indexed_face.image
            else None
            for indexed_face in indexed_faces
        }
        matched_applications = indexed_faces.values('application')
    fraud_face_similarity_info['matched_selfie'] = matched_selfie

    image_matched = Image.objects.filter(
        image_source__in=matched_applications,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ],
        image_type__in=['ktp_self', 'ktp'],
    )

    fraud_face_similarity_info['matched_ktp'] = {
        image.image_source: image.image_url for image in image_matched
    }

    return construct_face_comparison_info_json(fraud_face_similarity_info, matched_applications)


def get_similar_face(application: Application, similar_face_fs: FeatureSetting) -> list:
    fraud_face_similarity_info = {}

    if not similar_face_fs:
        return []

    matched_faces_limit = similar_face_fs.parameters["max_face_matches"]
    search_result = FaceSearchResult.objects.select_related("face_search_process").filter(
        face_search_process__application_id=application
    )[:matched_faces_limit]

    indexed_faces = None
    if search_result and search_result.values('matched_face_image_id'):
        indexed_faces = IndexedFace.objects.filter(
            image__in=search_result.values('matched_face_image_id')
        )

    if not indexed_faces:
        image_selfie = Image.objects.filter(pk__in=search_result.values('matched_face_image_id'))
        matched_selfie = {
            image.image_source: getattr(image, 'image_url', None) for image in image_selfie
        }
        matched_applications = image_selfie.values('image_source')
    else:
        matched_selfie = {
            indexed_face.application.id: getattr(indexed_face.image, 'image_url', None)
            if indexed_face.image
            else None
            for indexed_face in indexed_faces
        }
        matched_applications = indexed_faces.values('application')
    fraud_face_similarity_info['matched_selfie'] = matched_selfie

    image_matched = Image.objects.filter(
        image_source__in=matched_applications,
        image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ],
        image_type__in=['ktp_self', 'ktp'],
    )
    fraud_face_similarity_info['matched_ktp'] = {
        image.image_source: image.image_url for image in image_matched
    }

    return construct_face_comparison_info_json(fraud_face_similarity_info, matched_applications)


def construct_face_comparison_info_json(
    fraud_face_similarity_info: dict, matched_applications: CustomQuerySet
) -> list:
    fraud_face_result = []
    for matched_application in matched_applications:
        application_id = matched_application.get('application')
        if not application_id:
            application_id = matched_application.get('image_source')
        face_comparison_info = FaceComparisonInfo(
            application_id=application_id,
            matched_ktp=fraud_face_similarity_info['matched_ktp'].get(application_id),
            matched_selfie=fraud_face_similarity_info['matched_selfie'].get(application_id),
        ).to_dict()
        fraud_face_result.append(face_comparison_info)

    return fraud_face_result


def get_face_similarity_by_geohash6(application: Application) -> list:
    curr_add_geohash = AddressGeolocationGeohash.objects.filter(
        address_geolocation__application=application
    ).last()

    if not curr_add_geohash:
        return []

    geohash = curr_add_geohash.geohash6
    product_line_filter = (ProductLineCodes.TURBO, ProductLineCodes.J1, application.product_line_id)

    selfie_geohash_image_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.SELFIE_GEOHASH_CRM_IMAGE_LIMIT, is_active=True
    )

    similar_applications = get_similar_application_by_geohash(
        application, geohash, product_line_filter, selfie_geohash_image_feature_setting
    )

    selfie_images = Image.objects.filter(
        image_source__in=similar_applications,
        image_type='selfie',
        image_status=Image.CURRENT,
    ).order_by('-image_source')
    data = []
    similar_applications_list = list(similar_applications)
    for selfie_image in selfie_images:
        geohash_data = {
            'application_id': selfie_image.image_source,
            'image_url': selfie_image.image_url,
        }
        data.append(geohash_data)
        similar_applications_list.remove(int(selfie_image.image_source))

    # Handle incase there are application that doesn't have selfie image
    for application_id in similar_applications_list:
        data.append(
            {
                'application_id': application_id,
                'image_url': static('/images/icons/ic-placeholder.png'),
            }
        )

    return data


def get_similar_application_by_geohash(
    application: Application,
    geohash: str,
    product_line_filter: tuple,
    selfie_geohash_image_feature_setting: FeatureSetting,
) -> AddressGeolocationQuerySet:
    if selfie_geohash_image_feature_setting:
        current_date = timezone.localtime(timezone.now()).date()
        similar_applications = (
            AddressGeolocation.objects.filter(
                Q(addressgeolocationgeohash__geohash6=geohash)
                | Q(addressgeolocationgeohash__geohash8=geohash)
                | Q(addressgeolocationgeohash__geohash9=geohash)
            )
            .filter(
                application__cdate__gt=current_date
                - datetime.timedelta(days=selfie_geohash_image_feature_setting.parameters['days']),
                application__applicationhistory__status_new=ApplicationStatusCodes.FORM_PARTIAL,
                application__product_line_id__in=product_line_filter,
            )
            .exclude(
                application_id=application.id,
            )
            .distinct()
            .values_list('application_id', flat=True)
            .order_by('-application_id')
        )
    else:
        similar_applications = (
            AddressGeolocation.objects.filter(
                Q(addressgeolocationgeohash__geohash6=geohash)
                | Q(addressgeolocationgeohash__geohash8=geohash)
                | Q(addressgeolocationgeohash__geohash9=geohash)
            )
            .filter(
                application__applicationhistory__status_new=ApplicationStatusCodes.FORM_PARTIAL,
                application__product_line_id__in=product_line_filter,
            )
            .exclude(
                application_id=application.id,
            )
            .distinct()
            .values_list('application_id', flat=True)
            .order_by('-application_id')
        )

    return similar_applications


def get_face_similarity_status(application: Application, similar_face_fs: FeatureSetting) -> str:
    if application.is_grab():
        return "skipped"
    if not similar_face_fs:
        return "inactive"

    face_image_result = FaceImageResult.objects.filter(application=application).last()

    if not face_image_result:
        return "skipped"

    if not face_image_result.passed_filter:
        return "skipped"

    face_search_process = FaceSearchProcess.objects.filter(application=application).last()
    if not face_search_process:
        return "skipped"

    face_recommender_result = FaceRecommenderResult.objects.filter(
        application_id=application.id
    ).last()

    if face_recommender_result:
        return "checked"

    return face_search_process.status


def get_fraud_face_similarity_status(
    application: Application, similar_fraud_face_fs: FeatureSetting
) -> str:
    if application.is_grab():
        return "skipped"

    if not similar_fraud_face_fs:
        return "inactive"

    face_image_result = FaceImageResult.objects.filter(application=application).last()

    if not face_image_result:
        return "skipped"

    if not face_image_result.passed_filter:
        return "skipped"

    fraud_face_search_process = FraudFaceSearchProcess.objects.filter(
        application=application
    ).last()

    if not fraud_face_search_process:
        return "skipped"

    fraud_face_recommender_result = FraudFaceRecommenderResult.objects.filter(
        application_id=application.id
    ).last()

    if fraud_face_recommender_result:
        return "checked"

    return fraud_face_search_process.status
