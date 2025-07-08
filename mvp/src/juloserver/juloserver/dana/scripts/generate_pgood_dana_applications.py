import time
from typing import List

from juloserver.julo.exceptions import JuloException
from juloserver.julo.utils import post_anaserver


def generate_pgood_dana_applications(application_ids: List) -> None:
    """
    Hit ANA API to generate pgood for DANA applications
    """
    url = '/api/amp/v1/dana-score/'
    application_id_list = list(set(application_ids))  # remove duplicate id

    for application_id in application_id_list:
        try:
            ana_data = {'application_id': application_id}
            post_anaserver(url, json=ana_data)

            print('Success generate pgood for application_id {}'.format(application_id))
        except JuloException as err:
            print(
                'Failed generate pgood for application_id {}. Error: {}'.format(application_id, err)
            )

        time.sleep(0.5)
