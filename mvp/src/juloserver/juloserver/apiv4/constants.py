class ListOfApplicationSerializers:
    AppSerializer = 'ApplicationSerializer'
    AppSerializerV3 = 'ApplicationUpdateSerializerV3'
    AppSerializerV4 = 'ApplicationUpdateSerializerV4'
    AgentAssistedSubmissionSerializer = 'AgentAssistedSubmissionSerializer'

    AllowedSerializerForLFS = (AppSerializerV3, AppSerializerV4, AgentAssistedSubmissionSerializer)


class CleanStringListFields:
    """
    This list fields need to clean from data
    """

    FIELDS = [
        'address_provinsi',
        'address_kabupaten',
        'address_kecamatan',
        'address_kelurahan',
        'address_street_num',
        'company_name',
    ]
