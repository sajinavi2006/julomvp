from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.face_recognition.models import (
    AwsRecogResponse,
    FaceCollection,
    FaceImageResult,
    FaceRecommenderResult,
    FaceSearchProcess,
    FaceSearchResult,
    IndexedFace,
    FraudFaceSearchProcess,
    FraudFaceSearchResult,
    FraudFaceRecommenderResult,
    FaceMatchingCheck,
    IndexedFaceFraud,
)
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    ImageFactory,
)


class FaceImageResultFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceImageResult

    image = SubFactory(ImageFactory)
    sharpness = 94
    brightness = 95
    detected_faces = 2
    passed_filter = True
    latency = 235
    is_alive = False
    configs = {
        "client_settings": {
            "max_faces": 10,
            "attributes": ["ALL"],
            "quality_filter": "LOW",
            "face_match_threshold": 75,
            "face_comparison_threshold": 80,
        },
        "service_settings": {
            "crop_padding": 0.15,
            "allowed_faces": 2,
            "image_dimensions": 640,
            "sharpness_threshold": 50,
            "brightness_threshold": 50,
            "similarity_threshold": 80,
        },
    }


class FaceCollectionFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceCollection

    face_collection_name = "face_collection_x105"
    status = "active"


class FaceSearchProcessFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceSearchProcess

    status = "pending"


class FaceSearchResultFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceSearchResult

    search_face_confidence = 99.97
    similarity = 99.27
    face_collection = SubFactory(FaceCollectionFactory)
    latency = 0.03
    configs = {
        "client_settings": {
            "max_faces": 10,
            "attributes": ["ALL"],
            "quality_filter": "LOW",
            "face_match_threshold": 75,
            "face_comparison_threshold": 80,
        },
        "service_settings": {
            "crop_padding": 0.15,
            "allowed_faces": 2,
            "image_dimensions": 640,
            "sharpness_threshold": 50,
            "brightness_threshold": 50,
            "similarity_threshold": 99,
        },
    }


class AwsRecogResponseFactory(DjangoModelFactory):
    class Meta(object):
        model = AwsRecogResponse

    raw_response = (
        {
            'FaceDetails': [
                {
                    'BoundingBox': {
                        'Width': 0.2705426514148712,
                        'Height': 0.517795205116272,
                        'Left': 0.33410701155662537,
                        'Top': 0.17727118730545044,
                    },
                    'AgeRange': {'Low': 22, 'High': 34},
                    'Smile': {'Value': True, 'Confidence': 99.91801452636719},
                    'Eyeglasses': {'Value': False, 'Confidence': 95.4056167602539},
                    'Sunglasses': {'Value': False, 'Confidence': 98.85753631591797},
                    'Gender': {'Value': 'Female', 'Confidence': 99.97718811035156},
                    'Beard': {'Value': False, 'Confidence': 99.9012680053711},
                    'Mustache': {'Value': False, 'Confidence': 99.94380950927734},
                    'EyesOpen': {'Value': True, 'Confidence': 99.59522247314453},
                    'MouthOpen': {'Value': True, 'Confidence': 99.63088989257812},
                    'Emotions': [
                        {'Type': 'HAPPY', 'Confidence': 99.74586486816406},
                        {'Type': 'SURPRISED', 'Confidence': 0.05868169665336609},
                        {'Type': 'CONFUSED', 'Confidence': 0.052685149013996124},
                        {'Type': 'FEAR', 'Confidence': 0.04051491990685463},
                        {'Type': 'DISGUSTED', 'Confidence': 0.03412897512316704},
                        {'Type': 'SAD', 'Confidence': 0.0266125425696373},
                        {'Type': 'ANGRY', 'Confidence': 0.025499163195490837},
                        {'Type': 'CALM', 'Confidence': 0.016010519117116928},
                    ],
                    'Landmarks': [
                        {'Type': 'eyeLeft', 'X': 0.395105242729187, 'Y': 0.38639554381370544},
                        {'Type': 'eyeRight', 'X': 0.5171781778335571, 'Y': 0.3809640407562256},
                        {'Type': 'mouthLeft', 'X': 0.41100013256073, 'Y': 0.564585268497467},
                        {'Type': 'mouthRight', 'X': 0.5132464170455933, 'Y': 0.560184121131897},
                        {'Type': 'nose', 'X': 0.45349663496017456, 'Y': 0.49376827478408813},
                        {
                            'Type': 'leftEyeBrowLeft',
                            'X': 0.35067081451416016,
                            'Y': 0.34157344698905945,
                        },
                        {
                            'Type': 'leftEyeBrowRight',
                            'X': 0.38264429569244385,
                            'Y': 0.3262278139591217,
                        },
                        {
                            'Type': 'leftEyeBrowUp',
                            'X': 0.4170755445957184,
                            'Y': 0.33667516708374023,
                        },
                        {
                            'Type': 'rightEyeBrowLeft',
                            'X': 0.4864703118801117,
                            'Y': 0.3332263231277466,
                        },
                        {
                            'Type': 'rightEyeBrowRight',
                            'X': 0.522445023059845,
                            'Y': 0.31937935948371887,
                        },
                        {
                            'Type': 'rightEyeBrowUp',
                            'X': 0.5619537234306335,
                            'Y': 0.33154523372650146,
                        },
                        {'Type': 'leftEyeLeft', 'X': 0.3741258978843689, 'Y': 0.3846440613269806},
                        {'Type': 'leftEyeRight', 'X': 0.41930437088012695, 'Y': 0.3868368864059448},
                        {'Type': 'leftEyeUp', 'X': 0.3941934406757355, 'Y': 0.3780725300312042},
                        {'Type': 'leftEyeDown', 'X': 0.39586177468299866, 'Y': 0.3942832946777344},
                        {'Type': 'rightEyeLeft', 'X': 0.492895245552063, 'Y': 0.38348397612571716},
                        {
                            'Type': 'rightEyeRight',
                            'X': 0.5392730832099915,
                            'Y': 0.37715697288513184,
                        },
                        {'Type': 'rightEyeUp', 'X': 0.5165701508522034, 'Y': 0.37249311804771423},
                        {'Type': 'rightEyeDown', 'X': 0.5166532397270203, 'Y': 0.38883593678474426},
                        {'Type': 'noseLeft', 'X': 0.4346739649772644, 'Y': 0.5055894255638123},
                        {'Type': 'noseRight', 'X': 0.47959059476852417, 'Y': 0.5034610629081726},
                        {'Type': 'mouthUp', 'X': 0.4580739438533783, 'Y': 0.548276960849762},
                        {'Type': 'mouthDown', 'X': 0.4606373608112335, 'Y': 0.6002307534217834},
                        {'Type': 'leftPupil', 'X': 0.395105242729187, 'Y': 0.38639554381370544},
                        {'Type': 'rightPupil', 'X': 0.5171781778335571, 'Y': 0.3809640407562256},
                        {
                            'Type': 'upperJawlineLeft',
                            'X': 0.33251529932022095,
                            'Y': 0.36969465017318726,
                        },
                        {
                            'Type': 'midJawlineLeft',
                            'X': 0.3628171980381012,
                            'Y': 0.5654845833778381,
                        },
                        {'Type': 'chinBottom', 'X': 0.46622514724731445, 'Y': 0.6868472099304199},
                        {
                            'Type': 'midJawlineRight',
                            'X': 0.5770691633224487,
                            'Y': 0.5550656914710999,
                        },
                        {
                            'Type': 'upperJawlineRight',
                            'X': 0.5968406200408936,
                            'Y': 0.35680148005485535,
                        },
                    ],
                    'Pose': {
                        'Roll': -2.0281147956848145,
                        'Yaw': -2.6159005165100098,
                        'Pitch': -3.027129650115967,
                    },
                    'Quality': {'Brightness': 95.27236938476562, 'Sharpness': 94.08262634277344},
                    'Confidence': 99.99710083007812,
                },
                {
                    'BoundingBox': {
                        'Width': 0.02340914122760296,
                        'Height': 0.04298684746026993,
                        'Left': 0.5517550706863403,
                        'Top': 0.7659989595413208,
                    },
                    'AgeRange': {'Low': 13, 'High': 23},
                    'Smile': {'Value': True, 'Confidence': 57.92810821533203},
                    'Eyeglasses': {'Value': False, 'Confidence': 97.00680541992188},
                    'Sunglasses': {'Value': False, 'Confidence': 98.60675811767578},
                    'Gender': {'Value': 'Female', 'Confidence': 96.45459747314453},
                    'Beard': {'Value': False, 'Confidence': 94.95826721191406},
                    'Mustache': {'Value': False, 'Confidence': 98.09402465820312},
                    'EyesOpen': {'Value': True, 'Confidence': 91.22647094726562},
                    'MouthOpen': {'Value': True, 'Confidence': 64.52558898925781},
                    'Emotions': [
                        {'Type': 'HAPPY', 'Confidence': 34.60333251953125},
                        {'Type': 'SAD', 'Confidence': 24.8159236907959},
                        {'Type': 'FEAR', 'Confidence': 24.494686126708984},
                        {'Type': 'SURPRISED', 'Confidence': 4.952014446258545},
                        {'Type': 'ANGRY', 'Confidence': 3.694199800491333},
                        {'Type': 'CALM', 'Confidence': 3.369157314300537},
                        {'Type': 'DISGUSTED', 'Confidence': 2.533522129058838},
                        {'Type': 'CONFUSED', 'Confidence': 1.5371614694595337},
                    ],
                    'Landmarks': [
                        {'Type': 'eyeLeft', 'X': 0.5599147081375122, 'Y': 0.7856307625770569},
                        {'Type': 'eyeRight', 'X': 0.5705951452255249, 'Y': 0.786020815372467},
                        {'Type': 'mouthLeft', 'X': 0.5606510043144226, 'Y': 0.8025127649307251},
                        {'Type': 'mouthRight', 'X': 0.5695851445198059, 'Y': 0.8028564453125},
                        {'Type': 'nose', 'X': 0.564900815486908, 'Y': 0.796335756778717},
                        {
                            'Type': 'leftEyeBrowLeft',
                            'X': 0.5560216903686523,
                            'Y': 0.7810850143432617,
                        },
                        {
                            'Type': 'leftEyeBrowRight',
                            'X': 0.5590338706970215,
                            'Y': 0.7799821496009827,
                        },
                        {'Type': 'leftEyeBrowUp', 'X': 0.5620751976966858, 'Y': 0.7812450528144836},
                        {
                            'Type': 'rightEyeBrowLeft',
                            'X': 0.5681788325309753,
                            'Y': 0.7814452648162842,
                        },
                        {
                            'Type': 'rightEyeBrowRight',
                            'X': 0.5713321566581726,
                            'Y': 0.7803860306739807,
                        },
                        {
                            'Type': 'rightEyeBrowUp',
                            'X': 0.5745807886123657,
                            'Y': 0.7817066311836243,
                        },
                        {'Type': 'leftEyeLeft', 'X': 0.5580275058746338, 'Y': 0.7852928638458252},
                        {'Type': 'leftEyeRight', 'X': 0.5620098114013672, 'Y': 0.7858566045761108},
                        {'Type': 'leftEyeUp', 'X': 0.5598663091659546, 'Y': 0.7848602533340454},
                        {'Type': 'leftEyeDown', 'X': 0.5599340200424194, 'Y': 0.7863799929618835},
                        {'Type': 'rightEyeLeft', 'X': 0.568454384803772, 'Y': 0.7860857844352722},
                        {'Type': 'rightEyeRight', 'X': 0.5725074410438538, 'Y': 0.7858069539070129},
                        {'Type': 'rightEyeUp', 'X': 0.5705891251564026, 'Y': 0.785241961479187},
                        {'Type': 'rightEyeDown', 'X': 0.5705191493034363, 'Y': 0.786759078502655},
                        {'Type': 'noseLeft', 'X': 0.5630037784576416, 'Y': 0.7971510291099548},
                        {'Type': 'noseRight', 'X': 0.5669655203819275, 'Y': 0.7972840666770935},
                        {'Type': 'mouthUp', 'X': 0.5649339556694031, 'Y': 0.8013400435447693},
                        {'Type': 'mouthDown', 'X': 0.564921498298645, 'Y': 0.8061783909797668},
                        {'Type': 'leftPupil', 'X': 0.5599147081375122, 'Y': 0.7856307625770569},
                        {'Type': 'rightPupil', 'X': 0.5705951452255249, 'Y': 0.786020815372467},
                        {
                            'Type': 'upperJawlineLeft',
                            'X': 0.5539296269416809,
                            'Y': 0.7833666801452637,
                        },
                        {
                            'Type': 'midJawlineLeft',
                            'X': 0.5559144616127014,
                            'Y': 0.8018447160720825,
                        },
                        {'Type': 'chinBottom', 'X': 0.5649651288986206, 'Y': 0.814171552658081},
                        {
                            'Type': 'midJawlineRight',
                            'X': 0.5748365521430969,
                            'Y': 0.802442729473114,
                        },
                        {
                            'Type': 'upperJawlineRight',
                            'X': 0.5772057771682739,
                            'Y': 0.7841132283210754,
                        },
                    ],
                    'Pose': {
                        'Roll': -0.6189110279083252,
                        'Yaw': -3.7064433097839355,
                        'Pitch': -2.650351047515869,
                    },
                    'Quality': {'Brightness': 82.12001037597656, 'Sharpness': 38.89601135253906},
                    'Confidence': 93.03961181640625,
                },
            ],
            'ResponseMetadata': {
                'RequestId': 'cae8d0f7-b053-4d84-b565-e296d685ae30',
                'HTTPStatusCode': 200,
                'HTTPHeaders': {
                    'content-type': 'application/x-amz-json-1.1',
                    'date': 'Wed, 28 Jul 2021 14:37:37 GMT',
                    'x-amzn-requestid': 'cae8d0f7-b053-4d84-b565-e296d685ae30',
                    'content-length': '6656',
                    'connection': 'keep-alive',
                },
                'RetryAttempts': 0,
            },
        },
        4633.9123249053955,
        'aws_rekognition',
    )


class IndexedFaceFactory(DjangoModelFactory):
    class Meta(object):
        model = IndexedFace

    face_collection = SubFactory(FaceCollectionFactory)
    image = SubFactory(ImageFactory)
    application = SubFactory(ApplicationFactory)
    customer = SubFactory(CustomerFactory)
    match_status = 'active'
    collection_face_id = '10414a53-8e24-4d37-abcb-03404e1bb835'
    collection_image_id = '994a9449-62ab-3bc0-9dbc-2133f95c55f0'
    collection_image_url = 'cust_1001739020/application_2005603088/crop_selfie_14894434_preseed.jpg'
    application_status_code = 121
    latency = 0.01


class FaceRecommenderResultFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceRecommenderResult

    is_match = True
    match_application_id = 2000009876
    apply_date = "2021-04-06"
    geo_location_distance = "0.0 km"
    address = "Jl. Casablanca Raya Kav. 88"
    provinsi = "Jakarta"
    kabupaten = "Jakarta Selatan"
    kecamatan = "Tebet"
    kelurahan = "Menteng Dalam"
    nik = "1620220101016886"
    email = "test+integration1620226886@julo.co.id"
    full_name = "prod only"
    birth_place = "Gotham City"
    dob = "1992-12-12"
    bank_name = "BANK MANDIRI (PERSERO), Tbk "
    bank_account_name = "prod only"
    bank_account_number = "1620226886"
    device_name = "VIVO"


class FraudFaceSearchProcessFactory(DjangoModelFactory):
    class Meta(object):
        model = FraudFaceSearchProcess

    status = "pending"


class FraudFaceSearchResultFactory(DjangoModelFactory):
    class Meta(object):
        model = FraudFaceSearchResult

    search_face_confidence = 99.97
    similarity = 99.27
    face_collection = SubFactory(FaceCollectionFactory)
    latency = 0.03
    configs = {
        "client_settings": {
            "max_faces": 10,
            "attributes": ["ALL"],
            "quality_filter": "LOW",
            "face_match_threshold": 75,
            "face_comparison_threshold": 80,
        },
        "service_settings": {
            "crop_padding": 0.15,
            "allowed_faces": 2,
            "image_dimensions": 640,
            "sharpness_threshold": 50,
            "brightness_threshold": 50,
            "similarity_threshold": 99,
        },
    }


class FraudFaceRecommenderResultFactory(DjangoModelFactory):
    class Meta(object):
        model = FraudFaceRecommenderResult

    is_match = True
    match_application_id = 2000009876
    apply_date = "2021-04-06"
    geo_location_distance = "0.0 km"
    address = "Jl. Casablanca Raya Kav. 88"
    provinsi = "Jakarta"
    kabupaten = "Jakarta Selatan"
    kecamatan = "Tebet"
    kelurahan = "Menteng Dalam"
    nik = "1620220101016886"
    email = "test+integration1620226886@julo.co.id"
    full_name = "prod only"
    birth_place = "Gotham City"
    dob = "1992-12-12"
    bank_name = "BANK MANDIRI (PERSERO), Tbk "
    bank_account_name = "prod only"
    bank_account_number = "1620226886"
    device_name = "VIVO"


class FaceMatchingCheckFactory(DjangoModelFactory):
    class Meta(object):
        model = FaceMatchingCheck

    application = SubFactory(ApplicationFactory)
    process = 1
    reference_image = SubFactory(ImageFactory)
    target_image = SubFactory(ImageFactory)
    status = 1
    is_agent_verified = True
    metadata = {}


class IndexedFaceFraudFactory(DjangoModelFactory):
    class Meta(object):
        model = IndexedFaceFraud

    application = SubFactory(ApplicationFactory)
    face_collection = SubFactory(FaceCollectionFactory)
    image = SubFactory(ImageFactory)
    customer = SubFactory(CustomerFactory)
