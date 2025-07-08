from django.shortcuts import render

from .models import OtherLoan


def other_loan_view(request):
    context = dict(
        other_loans=OtherLoan.objects.filter(is_active=True, url__isnull=False)
    )

    return render(request, 'other_loan.html', context)
