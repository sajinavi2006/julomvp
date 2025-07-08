from django.shortcuts import redirect, render
from django.core.urlresolvers import reverse

from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.portal.object import (
    julo_login_required,
    julo_login_required_multigroup,
)

from juloserver.cashback.forms import OverpaidVerificationForm
from juloserver.cashback.models import CashbackOverpaidVerification
from juloserver.cashback.services import process_decision_overpaid_case


@julo_login_required
@julo_login_required_multigroup([JuloUserRoles.BO_FINANCE])
def overpaid_detail(request, case_id):
    agent = request.user.agent
    overpaid_case = CashbackOverpaidVerification.objects\
        .select_related('image')\
        .get(pk=case_id)

    template_name = 'cashback/overpaid_detail.html'

    form = OverpaidVerificationForm(request.POST)
    if request.method == 'POST':
        if form.is_valid():
            agent_note = form.cleaned_data['agent_note']
            decision = form.cleaned_data['decision']
            process_decision_overpaid_case(case_id, agent, agent_note, decision)
            url = reverse(
                'cashback.crm:overpaid_detail',
                kwargs={'case_id': case_id}
            )
            return redirect(url)
    else:
        form = OverpaidVerificationForm()

    return render(
        request,
        template_name,
        context={
            'overpaid_case': overpaid_case,
            'agent_id': agent.id,
            'form': form,
        },
    )
