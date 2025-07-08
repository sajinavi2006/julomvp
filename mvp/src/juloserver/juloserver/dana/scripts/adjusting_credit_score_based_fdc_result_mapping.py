from collections import defaultdict

from bulk_update.helper import bulk_update
from juloserver.dana.constants import DanaFDCResultStatus
from juloserver.dana.models import DanaFDCResult
from juloserver.julo.models import Application, Loan, CreditScore

from typing import List, Dict


def adjust_credit_score_mapping_fdc_result(application_ids: List) -> Dict:
    applications = Application.objects.filter(id__in=application_ids)
    customer_ids = applications.values_list('customer_id', flat=True)

    dana_fdc_results = DanaFDCResult.objects.filter(application_id__in=application_ids).values(
        'application_id', 'fdc_status'
    )

    fdc_result_mapping = defaultdict(str)
    for dana_fdc_result in dana_fdc_results.iterator():
        fdc_result_mapping[dana_fdc_result['application_id']] = dana_fdc_result['fdc_status']

    customer_has_loan_mapping = defaultdict(int)
    loans = Loan.objects.filter(customer_id__in=customer_ids).values('customer_id', 'id')
    for loan in loans.iterator():
        customer_has_loan_mapping[loan['customer_id']] = loan['id']

    exsting_credit_scores = CreditScore.objects.filter(application_id__in=application_ids).values(
        'application_id', 'score'
    )

    mapping_existing_app_credit_score = defaultdict(str)
    for exsting_credit_score in exsting_credit_scores.iterator():
        mapping_existing_app_credit_score[
            exsting_credit_score['application_id']
        ] = exsting_credit_score['score']

    failed_update_application_credit_score = []
    new_credit_score_mapping = defaultdict(str)
    for application in applications.iterator():
        if application.id not in fdc_result_mapping.keys():
            print('app_id={}, not have fdc_result'.format(application.id))
            failed_update_application_credit_score.append(application.id)
            continue

        fdc_result = fdc_result_mapping[application.id]
        old_credit_score = mapping_existing_app_credit_score[application.id]

        new_credit_score = None
        if fdc_result == DanaFDCResultStatus.APPROVE1:
            if application.customer.id in customer_has_loan_mapping.keys():
                new_credit_score = 'C+'
            else:
                new_credit_score = 'C'
        elif fdc_result == DanaFDCResultStatus.APPROVE2:
            new_credit_score = 'B--'
        elif fdc_result == DanaFDCResultStatus.APPROVE3:
            new_credit_score = 'B-'
        elif fdc_result == DanaFDCResultStatus.APPROVE4:
            new_credit_score = 'B'
        elif fdc_result == DanaFDCResultStatus.APPROVE5:
            new_credit_score = 'B+'
        elif fdc_result == DanaFDCResultStatus.APPROVE6:
            new_credit_score = 'A-'
        else:
            print(
                'app_id={}, does not match condition fdc_result {}'.format(
                    application.id, fdc_result
                )
            )
            failed_update_application_credit_score.append(application.id)
            continue

        print(
            'Success update app_id={}, old_credit_score={}, new_credit_score={},'
            'fdc_result={}'.format(application.id, old_credit_score, new_credit_score, fdc_result)
        )
        new_credit_score_mapping[application.id] = new_credit_score

    credit_scores = CreditScore.objects.filter(application_id__in=new_credit_score_mapping.keys())
    updated_credit_score = []
    for credit_score in credit_scores.iterator():
        credit_score.score = new_credit_score_mapping[credit_score.application_id]
        updated_credit_score.append(credit_score)

    bulk_update(updated_credit_score, update_fields=['score'], batch_size=100)

    return {
        'app_success': new_credit_score_mapping.keys(),
        'app_failed': failed_update_application_credit_score,
    }
