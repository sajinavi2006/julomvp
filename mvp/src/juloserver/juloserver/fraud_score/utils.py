from typing import List


def check_application_experiment_monnai_eligibility(application_id: int, test_group: List) -> bool:
    """
    Check if an application_id passes the condition for Monnai's test group based on the last 3rd
    and 4th characters of the application_id.

    Args:
        application_id (int): The ID property of an Application object.

    Returns:
        bool: Returns True if application is eligible. Returns False otherwise.
    """
    if not test_group:
        raise Exception('No test group found.')

    application_id_extracted_characters = str(application_id)[-4:-2]

    for group in test_group:
        ranges = group.split('-')
        if len(ranges) == 2:
            start, end = int(ranges[0]), int(ranges[1])
            if start <= int(application_id_extracted_characters) <= end:
                return True
    return False
