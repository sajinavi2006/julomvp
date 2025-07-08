from juloserver.dana.models import DanaCustomerData
from juloserver.julo.models import CreditScore


def add_dana_credit_score(limiter: int) -> None:
    dana_customers = DanaCustomerData.objects.select_related(
        'application',
    ).filter(application__creditscore__isnull=True)

    counter = 0
    success = 0
    unidentified = 0
    julo_credit_score_data_list = []

    if limiter == 0:
        limiter = 500

    for dana_customer in dana_customers.iterator():
        counter += 1
        dana_credit_score = dana_customer.credit_score
        julo_credit_score = ''

        if dana_credit_score > 750:
            julo_credit_score = 'A+'
        elif dana_credit_score <= 750 and dana_credit_score > 500:
            julo_credit_score = 'A-'
        elif dana_credit_score <= 500 and dana_credit_score > 250:
            julo_credit_score = 'B+'
        elif dana_credit_score <= 250 and dana_credit_score >= 0:
            julo_credit_score = 'B-'

        if not julo_credit_score:
            unidentified += 1
            print(
                'Unidentified dana credit score: {}, Process Application ID: {}'.format(
                    dana_credit_score, dana_customer.application.id
                )
            )
        else:
            success += 1
            julo_credit_score_data = CreditScore(
                application_id=dana_customer.application.id, score=julo_credit_score
            )
            julo_credit_score_data_list.append(julo_credit_score_data)

            print(
                'Success mapping credit score: {} -> {}, Process Application ID: {}'.format(
                    dana_credit_score, julo_credit_score, dana_customer.application.id
                )
            )

            if len(julo_credit_score_data_list) == limiter:
                CreditScore.objects.bulk_create(julo_credit_score_data_list, batch_size=limiter)
                print(
                    'END - Total: {}, Success: {}, Unidentified: {}'.format(
                        counter, success, unidentified
                    )
                )
                julo_credit_score_data_list = []

    CreditScore.objects.bulk_create(julo_credit_score_data_list)
    print('END - Total: {}, Success: {}, Unidentified: {}'.format(counter, success, unidentified))
