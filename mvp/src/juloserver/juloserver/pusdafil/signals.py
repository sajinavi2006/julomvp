# this function was deprecated because we already used pusdafill 2.0
# @receiver(signals.post_save, sender=LenderCurrent)
# def pusdafil_lender_creation_handler(sender, instance=None, created=False, **kwargs):
#     lender = instance

#     if settings.ENVIRONMENT != 'prod':
#         return

#     if created:
#         task_report_new_lender_registration.apply_async((lender.id,), countdown=3)


# this function was deprecated because we already used pusdafill 2.0
# @receiver(signals.post_save, sender=Loan)
# def pusdafil_loan_creation_handler(sender, instance=None, created=False, **kwargs):
#     # send to pusdafil
#     loan = instance

#     if settings.ENVIRONMENT != 'prod':
#         return

#     if loan.status < LoanStatusCodes.CURRENT:
#         return

#     application = Application.objects.filter(loan=loan).order_by("cdate").last()

#     if not application:
#         application = Application.objects.filter(account=loan.account).order_by("cdate").last()

#     if application.status in [
#         ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
#         ApplicationStatusCodes.LOC_APPROVED,
#     ]:
#         execute_after_transaction_safely(
#             lambda: bunch_of_loan_creation_tasks.delay(
#                 application.customer.user_id,
#                 application.customer_id,
#                 application.id,
#                 loan.id
#             )
#         )

# this function was deprecated because we already used pusdafill 2.0
# based on this slack discussion
# https://julofinance.slack.com/archives/C048NPDLJG1/p1731976570883209
# @receiver(signals.post_save, sender=Payment)
# def pusdafil_payment_creation_handler(sender, instance=None, created=False, **kwargs):
#
#     if settings.ENVIRONMENT != 'prod':
#         return
#
#     if (instance.payment_status_id < PaymentStatusCodes.PAID_ON_TIME
#             or instance.payment_status_id > PaymentStatusCodes.PAID_LATE
#             or instance.due_amount > 0):
#         return
#
#     # send to pusdafil
#     task_report_new_loan_payment_creation.apply_async((instance.id,), countdown=3)
