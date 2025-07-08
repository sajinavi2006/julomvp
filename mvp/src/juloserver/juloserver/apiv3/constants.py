class DeviceScrapedConst:

    PROCESS_NAME = 'device_scraped_dsd_json'
    ANA_SERVER_ENDPOINT = '/api/amp/v1/device-scraped-data2/'
    ANA_SERVER_DATA_MISSING_ENDPOINT = '/api/amp/v1/device-scraped-data-missing/'
    KEY_WIFI_DETAILS = 'wifi_details'
    KEY_APP_DETAILS = 'app_details'
    KEY_APPLICATION_ID = 'application_id'
    KEY_BATTERY_DETAILS = 'battery_detail'
    KEY_PHONE_DETAILS = 'phone_details'
    ANA_SERVER_ENDPOINT_FOR_IOS = '/api/amp/v1/ios-device-scraped-data/'

    KEYS_MAP_PARAM = [
        KEY_APPLICATION_ID,
        KEY_APP_DETAILS,
        KEY_BATTERY_DETAILS,
        KEY_PHONE_DETAILS,
        KEY_WIFI_DETAILS,
    ]

    # For clcs DSD
    PROCESS_NAME_CLCS = 'device_scraped_dsd_clcs'
    ANA_SERVER_ENDPOINT_CLCS = '/api/amp/v1/device-scraped-data-clcs2/'


class BankNameWithLogo:

    LIST_BANK = [
        'BCA',
        'BNI',
        'BRI',
        'CIMB_NIAGA',
        'MANDIRI',
        'PERMATA',
        'ROYAL',
        'ARTOS',
        'HARDA_INTERNASIONAL',
        'YUDHA_BHAKTI',
        'KESEJAHTERAAN_EKONOMI',
    ]
