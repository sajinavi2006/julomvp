from juloserver.fraud_score.models import MonnaiInsightRequest
from juloserver.fraud_score.monnai_services import get_monnai_repository


def fetch_monnai_device_details(application_id, customer_id, advertising_id):
    """
    Fetch monnai device detail only.
    The script is for https://juloprojects.atlassian.net/browse/PLAT-1400

    Args:
        application_id (int): The application's primary key
        customer_id (int): The customer's primary key
        advertising_id (str): The advertising_id from customer table

    Returns:
        MonnaiInsightRequest
    """
    monnai_repository = get_monnai_repository()
    payloads = {
        'eventType': 'ACCOUNT_UPDATE',
        'deviceIds': [advertising_id] if advertising_id else [],
        'countryCode': 'ID',
    }
    monnai_request = MonnaiInsightRequest(
        application_id=application_id,
        customer_id=customer_id,
        action_type=payloads['eventType'],
    )
    return monnai_repository.fetch_insight(
        monnai_request=monnai_request,
        packages=['DEVICE_DETAILS'],
        payloads=payloads,
    )
