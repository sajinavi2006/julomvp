from collections import defaultdict
from juloserver.partnership.constants import PartnershipPreCheckFlag
from juloserver.partnership.models import PartnershipApplicationFlag


def resume_agent_assisted_application_stuck_credit_score(application_ids):
    from juloserver.partnership.tasks import async_process_partnership_application_binary_pre_check

    application_flags = PartnershipApplicationFlag.objects.filter(
        application_id__in=application_ids
    )

    mapping_application_flags = defaultdict(int)
    for application_flag in application_flags:
        mapping_application_flags[application_flag.application_id] = application_flag.name

    counter = 0
    for application_id in application_ids:
        counter += 1
        flag_name = mapping_application_flags.get(application_id)

        if not flag_name:
            print('application_id={} does not have a flag'.format(application_id))
            continue

        if flag_name != PartnershipPreCheckFlag.PENDING_CREDIT_SCORE_GENERATION:
            print(
                'application_id={} flag its not pending_credit_score_generation'.format(
                    application_id
                )
            )
            continue

        async_process_partnership_application_binary_pre_check.delay(application_id)
        print(
            'Row {}, Process Retry Application Binary Check: {} flag={}'.format(
                counter, application_id, flag_name
            )
        )
