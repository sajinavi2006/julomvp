from builtins import str
from builtins import object
import logging
from django.utils import timezone
from django.db import transaction
from django.db.models import F, Q
from datetime import datetime
from .sms import create_sms_history
from ..clients import get_julo_email_client
from ..clients import get_julo_sms_client
from ..constants import (BypassITIExperimentConst,
                         ExperimentConst,
                         FeatureNameConst,
                         NotPremiumAreaConst)
from ...apiv2.credit_matrix2 import get_score_rate, get_salaried
from ..statuses import ApplicationStatusCodes
from ..services import (process_application_status_change,
                        get_credit_score3,
                        experimentation_automate_offer,
                        get_offer_recommendations)
from ..models import Skiptrace
from ..models import ProductLookup
from ..models import Offer
from ..models import ApplicationExperiment
from ..models import ApplicationOriginal
from ..models import Experiment
from ..models import FeatureSetting
from ..models import Application
from ..models import Payment
from ..models import PaymentExperiment
from ..models import ExperimentSetting
from ..models import AffordabilityHistory
from ..formulas import compute_payment_installment
from ..formulas import compute_adjusted_payment_installment
from ..formulas import determine_first_due_dates_by_payday
from ..formulas.experiment import calculation_affordability, calculation_affordability_based_on_affordability_model
from ..formulas.experiment import get_amount_and_duration_by_affordability_mtl
from ..formulas.experiment import get_amount_and_duration_by_affordability_stl
from ..product_lines import ProductLineCodes, ProductLineManager
from ..utils import remove_current_user, experiment_check_criteria, display_rupiah
from ...apiv2.utils import get_max_loan_amount_and_duration_by_score
from ...apiv2.credit_matrix2 import get_score_product

from juloserver.apiv2.models import PdOperationBypassModelResult
from juloserver.ana_api.utils import check_app_cs_v20b
from ...apiv2.models import (PdCreditModelResult, PdWebModelResult)
from juloserver.julocore.python2.utils import py2round
from juloserver.apiv2.services import check_eligible_mtl_extenstion
from juloserver.julo.constants import MTLExtensionConst
from juloserver.apiv2.constants import CreditMatrixType
from juloserver.julo.utils import format_e164_indo_phone_number

logger = logging.getLogger(__name__)


BYPASS_ITI122 = ExperimentConst.BYPASS_ITI122
BYPASS_ITI125 = ExperimentConst.BYPASS_ITI125
BYPASS_FT122 = ExperimentConst.BYPASS_FT122
BYPASS_FAST_TRACK_122 = FeatureNameConst.BYPASS_FAST_TRACK_122
CRITERIA_EXPERIMENT_FT_172 = BypassITIExperimentConst.CRITERIA_EXPERIMENT_FT_172
INTEREST_RATE_MONTHLY_MTL = BypassITIExperimentConst.INTEREST_RATE_MONTHLY_MTL
INTEREST_RATE_MONTHLY_STL = BypassITIExperimentConst.INTEREST_RATE_MONTHLY_STL
MAX_MONTHLY_INCOME = BypassITIExperimentConst.MAX_MONTHLY_INCOME
MAX_RANGE_COMPARE_INSTALLMENT = BypassITIExperimentConst.MAX_RANGE_COMPARE_INSTALLMENT
MIN_AFFORDABILITY_STL = BypassITIExperimentConst.MIN_AFFORDABILITY_STL
MIN_AFFORDABILITY_MTL = BypassITIExperimentConst.MIN_AFFORDABILITY_MTL
MIN_AMOUNT_OFFER_MTL = BypassITIExperimentConst.MIN_AMOUNT_OFFER_MTL
MIN_SCORE_TRESHOLD_MTL = BypassITIExperimentConst.MIN_SCORE_TRESHOLD_MTL
MIN_SCORE_TRESHOLD_STL = BypassITIExperimentConst.MIN_SCORE_TRESHOLD_STL
REDUCE_INSTALLMENT_AMOUNT = BypassITIExperimentConst.REDUCE_INSTALLMENT_AMOUNT
VERSION_CREDIT_SCORE_FAST_TRACK_122 = BypassITIExperimentConst.VERSION_CREDIT_SCORE_FAST_TRACK_122
LOAN_DURATION_ITI = ExperimentConst.LOAN_DURATION_ITI
ITI_LOW_THRESHOLD = ExperimentConst.ITI_LOW_THRESHOLD
MAX_ITI_MONTHLY_INCOME = BypassITIExperimentConst.MAX_ITI_MONTHLY_INCOME


class BypassITIExperimentService(object):

    def set_default_skiptrace(self, customer_id):
        customer_phone = Skiptrace.objects.filter(customer_id=customer_id).order_by('id', '-effectiveness')
        for phone in customer_phone:
            phone.effectiveness = 0
            phone.save()

    def exclusion_bypass_iti_experiment(self, application, affordability, monthly_income):
        exclusion_status = False
        if application.product_line.product_line_code in ProductLineCodes.stl()\
            and affordability < MIN_AFFORDABILITY_STL:
            exclusion_status = True
        elif application.product_line.product_line_code in ProductLineCodes.mtl()\
            and affordability < MIN_AFFORDABILITY_MTL:
            exclusion_status = True
        elif monthly_income >= MAX_MONTHLY_INCOME:
            exclusion_status = True
        return exclusion_status

    def get_amount_and_duration_by_affordability(self, application, affordability, loan_amount_request,
                                                       loan_duration_request, skip_compared=False):
        if application.product_line.product_line_code in ProductLineCodes.stl() + ProductLineCodes.pedestl():
            interest_rate_monthly = INTEREST_RATE_MONTHLY_STL
            loan_amount_offer, loan_duration_offer = get_amount_and_duration_by_affordability_stl(affordability, loan_amount_request)
            if not loan_amount_offer:
                return loan_amount_offer, loan_duration_offer
        elif application.product_line.product_line_code in ProductLineCodes.mtl() + ProductLineCodes.pedemtl():
            interest_rate_monthly = INTEREST_RATE_MONTHLY_MTL
            loan_amount_offer, loan_duration_offer = get_amount_and_duration_by_affordability_mtl(affordability, loan_amount_request)
            if not loan_amount_offer:
                return loan_amount_offer, loan_duration_offer
            credit_score = get_credit_score3(application)
            if credit_score:
                max_loan_amount, max_loan_duration = get_max_loan_amount_and_duration_by_score(credit_score)
                if application.product_line.product_line_code in ProductLineCodes.mtl():
                    score_product = get_score_product(credit_score, "julo",
                        application.product_line.product_line_code, application.job_type)

                    if score_product:
                        max_loan_amount = score_product.max_loan_amount
                        max_loan_duration = score_product.max_duration
                    else:
                        max_loan_amount = application.product_line.max_amount
                        max_loan_duration = application.product_line.max_duration

                if loan_amount_offer > max_loan_amount:
                    loan_amount_offer = max_loan_amount
                if loan_duration_offer > max_loan_duration:
                    loan_duration_offer = max_loan_duration

        # comparison original amount and duration original with modified
        if not skip_compared:
            _, _, original_installment = compute_payment_installment(
                loan_amount_request, loan_duration_request, interest_rate_monthly)
            _, _, modified_installment = compute_payment_installment(
                loan_amount_offer, loan_duration_offer, interest_rate_monthly)
            range_amount = modified_installment - original_installment
            while range_amount > MAX_RANGE_COMPARE_INSTALLMENT and loan_amount_offer > MIN_AMOUNT_OFFER_MTL:
                loan_amount_offer -= REDUCE_INSTALLMENT_AMOUNT
                _, _, modified_installment = compute_payment_installment(
                    loan_amount_offer, loan_duration_offer, interest_rate_monthly)
                range_amount = modified_installment - original_installment
        logger.info({
            'action': 'get_amount_and_duration_by_affordability',
            'application_id': application.id,
            'loan_amount_offer': loan_amount_offer,
            'loan_duration_offer': loan_duration_offer
        })

        if check_eligible_mtl_extenstion(application) and \
            loan_amount_request == MTLExtensionConst.MIN_AMOUNT and \
                MTLExtensionConst.AFFORDABILITY <= affordability:
                loan_duration_offer = MTLExtensionConst.MIN_DURATION
                loan_amount_offer = MTLExtensionConst.MIN_AMOUNT

        return loan_amount_offer, loan_duration_offer

    def calculation_experiment_offer(self, application, loan_amount_offer, loan_duration_offer):
        today = timezone.localtime(timezone.now()).date()
        product_line_code = application.product_line_id
        partner = application.partner
        product_line = ProductLineManager.get_or_none(application.product_line_code)
        rate = product_line.max_interest_rate
        if product_line.product_line_code in ProductLineCodes.mtl():
            credit_score = get_credit_score3(application)
            if credit_score:
                customer = application.customer
                credit_matrix_type = CreditMatrixType.WEBAPP if application.is_web_app() else (
                    CreditMatrixType.JULO if not customer.is_repeated else CreditMatrixType.JULO_REPEAT)
                rate = get_score_rate(credit_score, credit_matrix_type,
                    product_line.product_line_code, rate, application.job_type)

        interest_rate = py2round(rate * 12, 2)

        product_lookup = ProductLookup.objects.filter(
            interest_rate=interest_rate,
            product_line__product_line_code=product_line.product_line_code).first()
        # get first_payment_date
        first_payment_date_requested = determine_first_due_dates_by_payday(
            application.payday, today, product_line_code, loan_duration_offer)
        # get first_installment_requested
        _, _, first_installment_requested = compute_adjusted_payment_installment(
            loan_amount_offer, loan_duration_offer, product_lookup.monthly_interest_rate,
            today, first_payment_date_requested)

        if product_line_code in ProductLineCodes.stl():
            installment_requested = first_installment_requested
        else:
            _, _, installment_requested = compute_payment_installment(
                loan_amount_offer, loan_duration_offer, product_lookup.monthly_interest_rate)
        offer = Offer(
            offer_number=1,
            loan_amount_offer=loan_amount_offer,
            loan_duration_offer=loan_duration_offer,
            installment_amount_offer=installment_requested,
            first_installment_amount=first_installment_requested,
            is_accepted=False,
            application=application,
            product=product_lookup,
            is_approved=True,
            first_payment_date=first_payment_date_requested)
        logger.info({
            'action': 'calculation_experiment_offer',
            'application_id': application.id,
            'accepted_amount': loan_amount_offer,
            'accepted_duration': loan_duration_offer,
            'first_installment_requested': first_installment_requested,
            'first_payment_date_requested': first_payment_date_requested,
            'installment_requested': installment_requested,
            'product': str(product_lookup)
        })
        return offer

    def bypass_iti_122_to_123(self, application):
        # set default Skiptrace
        self.set_default_skiptrace(application.customer_id)

        # process change status 123 to create offer
        status = process_application_status_change(application.id, ApplicationStatusCodes.PRE_REJECTION, 'Bypass ITI')
        logger.info({
            'action': 'bypass_iti_122_to_123',
            'application_id': application.id,
            'result': status
        })

    def bypass_iti_125_to_135(self, application):
        # set default Skiptrace
        self.set_default_skiptrace(application.customer_id)

        # process change status 123 to create offer
        status = process_application_status_change(application.id, ApplicationStatusCodes.APPLICATION_DENIED, 'Bypass ITI')
        logger.info({
            'action': 'bypass_iti_125_to_135',
            'application_id': application.id,
            'result': status
        })

    def bypass_iti_122_to_172(self, application, affordability, loan_amount_request, loan_duration_request, experiment_name):
        #don't record agent_id on bypass
        remove_current_user()
        recomendation_offers = get_offer_recommendations(
            application.product_line_id,
            loan_amount_request,
            loan_duration_request,
            affordability,
            application.payday,
            application.ktp,
            application.id,
            application.partner
        )
        if not recomendation_offers['offers']:
            # if the loan_amount_offer is none then can't change the status
            return

        offer_data = recomendation_offers['offers'][0]
        product = ProductLookup.objects.get(pk=offer_data['product'])
        offer_data['product'] = product
        offer_data['application'] = application
        offer_data['is_approved'] = True
        offer = Offer(**offer_data)

        # set default Skiptrace
        self.set_default_skiptrace(application.customer_id)
        # process change status 141-172 to create offer
        with transaction.atomic():
            offer.save()
            process_application_status_change(application.id,
                ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER, 'Bypass ITI')
            application.refresh_from_db()
            if application.application_status_id == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                status = process_application_status_change(application.id,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING, 'Bypass ITI')
                if experiment_name == BYPASS_FAST_TRACK_122:
                    experiment = Experiment.objects.filter(code=BYPASS_FT122).last()
                else:
                    experiment = Experiment.objects.filter(code=BYPASS_ITI122).last()
                ApplicationExperiment.objects.create(
                    application=application, experiment=experiment)
                logger.info({
                    'action': 'bypass_iti_122_to_172',
                    'experiment_name': experiment_name,
                    'application_id': application.id,
                    'result': status
                })

    def bypass_mae_iti_122_to_172(self, application, affordability, loan_amount_request, loan_duration_request, experiment_name):
        # get_offer_recommendations
        recomendation_offers = get_offer_recommendations(
            application.product_line.product_line_code,
            loan_amount_request,
            loan_duration_request,
            affordability,
            application.payday,
            application.ktp,
            application.id,
            application.partner
        )

        if len(recomendation_offers['offers']) > 0:
            offer_data = recomendation_offers['offers'][0]
            product = ProductLookup.objects.get(pk=offer_data['product'])
            offer_data['product'] = product
            offer_data['application'] = application
            offer_data['is_approved'] = True
            # process change status 141-172 to create offer
            offer = Offer(**offer_data)

            # set default Skiptrace
            self.set_default_skiptrace(application.customer_id)
            with transaction.atomic():
                offer.save()
                process_application_status_change(application.id,
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    'ITILoanGenerationAffordability')
                application.refresh_from_db()
                if application.application_status_id == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                    status = process_application_status_change(application.id,
                        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                        'ITILoanGenerationAffordability')
                    logger.info({
                        'action': 'bypass_mae_iti_122_to_172',
                        'experiment_name': 'ITILoanGenerationAffordability',
                        'application_id': application.id,
                        'result': status
                    })

    def bypass_iti_125_to_141(self, application,
                                    affordability,
                                    loan_amount_request,
                                    loan_duration_request,
                                    skip_compared):
        # set default Skiptrace
        self.set_default_skiptrace(application.customer_id)
        # process change status 141-172 to create offer
        # get_offer_recommendations
        recomendation_offers = get_offer_recommendations(
            application.product_line.product_line_code,
            loan_amount_request,
            loan_duration_request,
            affordability,
            application.payday,
            application.ktp,
            application.id,
            application.partner
        )

        if len(recomendation_offers['offers']) > 0:
            offer_data = recomendation_offers['offers'][0]
            product = ProductLookup.objects.get(pk=offer_data['product'])
            offer_data['product'] = product
            offer_data['application'] = application
            offer_data['is_approved'] = True
            # process change status 141-172 to create offer
            offer = Offer(**offer_data)

        with transaction.atomic():
            offer.save()
            status = process_application_status_change(application.id, ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER, 'Bypass ITI')
            experiment = Experiment.objects.filter(code=BYPASS_ITI125).last()
            ApplicationExperiment.objects.create(
                application=application, experiment=experiment)
            logger.info({
                'action': 'bypass_iti_125_to_141',
                'application_id': application.id,
                'result': status
            })

    def bypass_fasttrack_122(self, application):
        # check feature active
        feature_fast_track_122 = FeatureSetting.objects.filter(
            feature_name=BYPASS_FAST_TRACK_122, is_active=True).last()
        last_application_xid = str(application.application_xid)[-1]
        if feature_fast_track_122 and last_application_xid in CRITERIA_EXPERIMENT_FT_172:
            product_str = application.product_line.product_line_type[:3]
            min_score_treshold = MIN_SCORE_TRESHOLD_MTL if product_str == 'MTL' else MIN_SCORE_TRESHOLD_STL
            score_treshold = PdOperationBypassModelResult.objects.filter(
                application_id=application.id, version=VERSION_CREDIT_SCORE_FAST_TRACK_122,
                product=product_str, probability_fpd__gte=min_score_treshold).last()
            if not score_treshold:
                # when method unlock_app_by_system done use to unlock application here
                return

            # get application original
            application_original = ApplicationOriginal.objects.filter(
                current_application=application.id).last()
            if not application_original:
                return

            # Calculation affordability experiment
            affordability, monthly_income = calculation_affordability(
                application.id, application_original.monthly_income,
                application_original.monthly_housing_cost,
                application_original.monthly_expenses,
                application_original.total_current_debt)

            # run bypass iti 122 to 172
            self.bypass_iti_122_to_172(application, affordability,
                                       application_original.loan_amount_request,
                                       application_original.loan_duration_request,
                                       BYPASS_FAST_TRACK_122)

            # when method unlock_app_by_system done
            return

    def sms_loan_approved(self, application):
        sms_client = get_julo_sms_client()

        try:
            msg, response, template = sms_client.sms_loan_approved(application)

            create_sms_history(response=response,
                               customer=application.customer,
                               application=application,
                               template_code=template,
                               message_content=msg,
                               to_mobile_phone=format_e164_indo_phone_number(response['to']),
                               phone_number_type='mobile_phone_1')
            logger.info({
                'action': 'experiment ac_bypass_sms',
                'phone': application.mobile_phone_1,
                'response': response
            })
        except:
            logger.info({
                'action': 'experiment ac_bypass_sms',
                'phone': application.mobile_phone_1,
                'status': 'failed'
            })

    def ac_bypass_141_to_150(self, application):
        # process change status 141 to 160
        # process change status 141 to 150 changed by this card AM-337
        status = process_application_status_change(
            application.id,
            ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            'AC Bypass Experiment')
        logger.info({
            'action': 'bypass_ac_141_to_150',
            'application_id': application.id,
            'result': status
        })

    def bypass_loan_duration_iti_122_to_172(self, application, affordability, loan_amount_request, loan_duration_request):
        today = timezone.now()
        experiment = ExperimentSetting.objects.get_or_none(
            code=LOAN_DURATION_ITI,
            is_active=True)

        if not experiment:
            return False

        if not (experiment.is_permanent or (experiment.start_date <= today <= experiment.end_date)):
            return False

        # #nth:-1:0,1,2,3,4,5
        pass_application_criteria = experiment_check_criteria(
            'application_id',
            experiment.criteria,
            application.id)

        # MTL1
        product_list = experiment.criteria['product_line']
        if type(product_list) == str:
            product_list = []
            product_list.append(experiment.criteria['product_line'])

        pass_product_criteria = ( application.product_line_id in product_list )

        if not (pass_application_criteria and pass_product_criteria):
            return False

        # don't record agent_id on bypass
        remove_current_user()

        # get_offer_recommendations
        recomendation_offers = get_offer_recommendations(
            application.product_line.product_line_code,
            application.loan_amount_request,
            application.loan_duration_request,
            affordability,
            application.payday,
            application.ktp,
            application.id,
            application.partner
        )

        if len(recomendation_offers['offers']) > 0:
            offer_data = recomendation_offers['offers'][0]
            product = ProductLookup.objects.get(pk=offer_data['product'])
            offer_data['product'] = product
            offer_data['application'] = application
            offer_data['is_approved'] = True
            # process change status 141-172 to create offer
            offer = Offer(**offer_data)

            # set default Skiptrace
            self.set_default_skiptrace(application.customer_id)
            with transaction.atomic():
                offer.save()
                process_application_status_change(application.id,
                    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                    'LoanDurationITI')
                application.refresh_from_db()
                if application.application_status_id == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                    status = process_application_status_change(application.id,
                        ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                        'LoanDurationITI')
                    logger.info({
                        'action': 'bypass_loan_duration_iti_122_to_172',
                        'experiment_name': 'LoanDurationITI',
                        'application_id': application.id,
                        'result': status
                    })

        return True


    def bypass_iti_low_130_to_172(self, application):
        today = timezone.localtime(timezone.now())

        experiment_iti_low = ExperimentSetting.objects.get_or_none(
            code=ITI_LOW_THRESHOLD,
            is_active=True)

        if not experiment_iti_low:
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'Experiment setting not found',
            })
            return False

        if not (experiment_iti_low.is_permanent or (experiment_iti_low.start_date <= today <= experiment_iti_low.end_date)):
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'Experiment setting has expired',
            })
            return False

        # replaced by this card ENH-122 Improve ITI affordability calculation to use Affordability Model
        affordability_status, affordability = calculation_affordability_based_on_affordability_model(
            application, is_with_affordability_value=True)
        if not affordability_status:
            # reject
            process_application_status_change(application.id,
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        'Failed ' + ITI_LOW_THRESHOLD)
            return False

        recomendation_offers = get_offer_recommendations(
            application.product_line.product_line_code,
            application.loan_amount_request,
            application.loan_duration_request,
            affordability,
            application.payday,
            application.ktp,
            application.id,
            application.partner
        )

        if len(recomendation_offers['offers']) == 0:
            process_application_status_change(application.id,
                        ApplicationStatusCodes.APPLICATION_DENIED,
                        'Failed ' + ITI_LOW_THRESHOLD)
            return False

        offer_data = recomendation_offers['offers'][0]
        product = ProductLookup.objects.get(pk=offer_data['product'])
        offer_data['product'] = product
        offer_data['application'] = application
        offer_data['is_approved'] = True
        # process change status 141-172 to create offer
        offer = Offer(**offer_data)

        # set default Skiptrace
        self.set_default_skiptrace(application.customer_id)
        with transaction.atomic():
            offer.save()
            process_application_status_change(application.id,
                ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
                ITI_LOW_THRESHOLD)
            application.refresh_from_db()
            if application.application_status_id == ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                status = process_application_status_change(application.id,
                    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
                    ITI_LOW_THRESHOLD)
                logger.info({
                    'action': '',
                    'experiment_name': ITI_LOW_THRESHOLD,
                    'application_id': application.id,
                    'result': status
                })

        return True

    def bypass_iti_low_122_to_124(self, application):
        today = timezone.localtime(timezone.now())

        experiment_iti_low = ExperimentSetting.objects.get_or_none(
            code=ITI_LOW_THRESHOLD,
            is_active=True)

        if not experiment_iti_low:
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'Experiment setting not found',
            })
            return False

        if not (experiment_iti_low.is_permanent or (experiment_iti_low.start_date <= today <= experiment_iti_low.end_date)):
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'Experiment setting has expired',
            })
            return False

        pass_criteria = experiment_check_criteria(
            'application_id',
            experiment_iti_low.criteria,
            application.id)

        if not pass_criteria:
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'application pass criteria',
            })
            return False

        is_salaried = get_salaried(application.job_type)
        if not is_salaried:
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'application is not salaried',
            })
            return False

        #check credit_score threshold
        credit_model_result = PdCreditModelResult.objects.filter(
            application_id=application.id).last()

        credit_model_result = credit_model_result or PdWebModelResult.objects.filter(
            application_id=application.id).last()
        # try to use pgood instead of probability_fpd
        checking_score = getattr(credit_model_result, 'pgood', None) \
            or credit_model_result.probability_fpd

        threshold = experiment_iti_low.criteria['threshold']
        if not credit_model_result and (threshold['min'] <= checking_score < threshold['max']):
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'application not pass threshold criteria',
            })
            return False

        product_list = experiment_iti_low.criteria['product_line']
        if type(product_list) == str:
            product_list = [product_list]

        if application.product_line_id not in product_list:
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'application not pass productline criteria',
            })
            return False

        if application.monthly_income >= MAX_ITI_MONTHLY_INCOME:
            logger.error({
                'action': 'process_experiment_itt_low_threshold',
                'application_id': application.id,
                'message': 'application has not credit score',
            })
            return False
        # replaced by this card ENH-122 Improve ITI affordability calculation to use Affordability Model
        return calculation_affordability_based_on_affordability_model(application)

    def iti_low_checking(self, application):
        """check whether app affords bypass or not"""
        today = timezone.localtime(timezone.now())

        experiment_iti_low = ExperimentSetting.objects.get_or_none(
            code=ITI_LOW_THRESHOLD,
            is_active=True)

        if not experiment_iti_low:
            logger.error({
                'action': 'affordability_checking',
                'application_id': application.id,
                'message': 'Experiment setting not found',
            })
            return False

        if not (experiment_iti_low.is_permanent or \
                (experiment_iti_low.start_date <= today <= experiment_iti_low.end_date)):
            logger.error({
                'action': 'affordability_checking',
                'application_id': application.id,
                'message': 'Experiment setting has expired',
            })
            return False

        # Calcuation affordability experiment
        criteria_affordability = experiment_iti_low.criteria['affordability']
        affordability_history = AffordabilityHistory.objects.filter(
            application=application,
            application_status_id=ApplicationStatusCodes.FORM_PARTIAL,
            affordability_type='ITI Affordability').last()

        if not affordability_history:
            return False

        affordability = affordability_history.affordability_value
        if affordability < criteria_affordability:
            return False

        return True


class PaymentExperimentAction(object):
    def __init__(self, payment, experiment):
        self.payment = payment
        self.experiment = experiment
        self.note = 'experiment - {}, payment - {}'.format(experiment.code, payment.id)
        self.payment_experiment = PaymentExperiment.objects.create(
            experiment_setting=self.experiment, payment=self.payment, note_text=self.note)

    def send_email_blast(self, subject, template):
        email_client = get_julo_email_client()
        application = self.payment.loan.application
        email = application.email
        gender = application.gender
        fullname = application.fullname
        subject = subject
        try:
            status, headers, subject, msg = email_client.custom_for_blast(
                email, gender, fullname, subject, template)
            logger.info({
                'action': 'experiment send_email_blast',
                'email': email,
                'status': status,
                'payment': self.payment.id
            })
        except Exception as e:
            logger.info({
                'action': 'experiment send_email_blast',
                'email': email,
                'status': 'failed',
                'payment': self.payment.id
            })
            return False, str(e)

        if status == 202:
            return True, 'success'

        return False, status

    def send_sms_blast(self, template):
        sms_client = get_julo_sms_client()
        application = self.payment.loan.application
        phone = application.mobile_phone_1

        try:
            msg, status = sms_client.blast_custom(phone, template)
            logger.info({
                'action': 'experiment send_sms_blast',
                'phone': phone,
                'status': status,
                'payment': self.payment.id
            })
        except Exception as e:
            logger.info({
                'action': 'experiment send_sms_blast',
                'phone': phone,
                'status': 'failed',
                'payment': self.payment.id
            })
            return False, e.message
        if status['status'] != '0':
            return False, status['status']

        return True, 'success'

    def send_lottery_cash(self):
        # send email
        subject = 'Mau Uang Tunai 5 Juta? Bayar Cicilan Anda Sekarang'
        email_template = 'email_lotterycash_21_jan'
        is_email_sent, email_status = self.send_email_blast(subject, email_template)

        # send sms
        sms_template = 'sms_lotterycash_21_jan'
        is_sms_sent, sms_status = self.send_sms_blast(sms_template)

        # update experiment note
        self.note = '{} - {} send email : {} - {} send sms: {}'.format(
            self.note, 'success' if is_email_sent else 'failed', email_status,
            'success' if is_sms_sent else 'failed', sms_status)
        self.payment_experiment.note_text = self.note
        self.payment_experiment.save()

    def send_lottery_phone(self):
        # send email
        subject = 'Mau HP Oppo F9 Gratis? Bayar Cicilan Anda Sekarang'
        email_template = 'email_lotteryphone_21_jan'
        is_email_sent, email_status = self.send_email_blast(subject, email_template)

        # send sms
        sms_template = 'sms_lotteryphone_21_jan'
        is_sms_sent, sms_status = self.send_sms_blast(sms_template)

        # update experiment note
        self.note = '{} - {} send email : {} - {} send sms: {}'.format(
            self.note, 'success' if is_email_sent else 'failed', email_status,
            'success' if is_sms_sent else 'failed', sms_status)
        self.payment_experiment.note_text = self.note
        self.payment_experiment.save()


def payment_experiment_daily(experiments):
    for experiment in experiments:
        logger.info({
            'action': 'payment_experiment_daily',
            'experiment_setting': experiment.code,
            'criteria': experiment.criteria
        })
        criteria = experiment.criteria
        payments = []
        qs = Payment.objects.normal().filter(loan__application__customer__can_notify=True)
        if 'is_paid' in criteria:
            if not criteria['is_paid']:
                qs = qs.not_paid_active()
            elif criteria['is_paid']:
                qs = qs.paid()

        if 'payment_id' in criteria:
            criteria_ids = []
            splicing = None
            items = criteria['payment_id'].split(':')
            if items[0] == '#last':
                splicing = int(items[1])
                end = 10
                start = end - (splicing - 1)
                criteria_ids = items[2].split(',')
            if len(criteria_ids) > 0:
                qs = qs.extra(where=["SUBSTRING(CAST(payment_id as Varchar), %s, %s) in %s"],
                              params=[start, end, tuple(criteria_ids)])

        if 'payment_number' in criteria:
            op, q_method, number = criteria['payment_number'].split(':')
            if q_method:
                qs = eval('qs.{}({},"{}")'.format(q_method, number, op))

        if 'dpd' in criteria:
            for dpd in criteria['dpd']:
                payments += list(qs.dpd(int(dpd)))

        elif 'dpd' not in criteria:
            payments = list(qs)

        for payment in payments:
            payment_experiment = PaymentExperimentAction(payment, experiment)
            action = 'payment_experiment.{}()'.format(experiment.action)
            try:
                eval('payment_experiment.{}()'.format(experiment.action))
            except Exception as e:
                logger.warn({
                    'action': action,
                    'payment': payment.id,
                    'error': str(e)
                })
                continue


def bulk_payment_robocall_experiment(experiment, payment_ids):
    payment_experiments = []
    for payment_id in payment_ids:
        note = 'experiment - {}, payment - {}'.format(experiment.code, payment_id)
        robo_experiment = PaymentExperiment(experiment_setting=experiment,
                                            payment_id=payment_id,
                                            note_text=note)
        payment_experiments.append(robo_experiment)

    PaymentExperiment.objects.bulk_create(payment_experiments)


def get_payment_experiment_ids(date, experiment_code):
    return PaymentExperiment.objects.filter(
        experiment_setting__code=experiment_code,
        cdate__date=date).values_list('payment_id', flat=True)

def parallel_bypass_experiment():
    setting = ExperimentSetting.objects.get_or_none(code="ParallelHighScoreBypassExperiments", is_active=True)
    if setting and setting.start_date <= timezone.now() <= setting.end_date:
        return setting
    return None

def is_high_score_parallel_bypassed(application, parameter):
    credit_score_type = 'B' if check_app_cs_v20b(application) else 'A'
    credit_model_result = PdCreditModelResult.objects.filter(
        application_id=application.id,
        credit_score_type=credit_score_type).last()
    if not credit_model_result:
        return None
    probability_fpd = credit_model_result.probability_fpd
    if probability_fpd >= parameter['low_probability_fpd']:
        return ExperimentConst.REPEATED_HIGH_SCORE_ITI_BYPASS
    else:
        return None


def check_cootek_experiment(data, dpd):
    data_to_return = data
    today = timezone.now().date()
    experiment_setting = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.COOTEK_AI_ROBOCALL_TRIAL_V5,
        is_active=True,
        type="payment",
        start_date__lte=today,
        end_date__gte=today,
    )

    if experiment_setting and (dpd in experiment_setting.criteria['dpd']):
        criteria = experiment_setting.criteria
        items = criteria['loan_id'].split(':')
        criteria_ids = items[2].split(',')
        data_to_return = data_to_return.annotate(last_digit_loan_id=F('loan_id') % 10)\
            .exclude(last_digit_loan_id__in=criteria_ids)\
            .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.mtl())\
            .exclude(loan__application__product_line__product_line_code__in=ProductLineCodes.stl())

    return data_to_return


def check_pn_script_experiment(payment, dpd, message):
    data_to_return = message
    today = timezone.now().date()
    loan = payment.loan
    second_last_loan_id = int(str(loan.id)[-2])
    application = loan.application
    experiment_setting = ExperimentSetting.objects.get_or_none(
        code=ExperimentConst.PN_SCRIPT_EXPERIMENT,
        is_active=True,
        type="notification",
        start_date__lte=today,
        end_date__gte=today,
    )
    if experiment_setting:
        criteria = experiment_setting.criteria
        test_group = criteria['test_group']
        criteria_dpd = criteria['dpd']
        start_due_date = datetime.strptime(criteria['start_due_date'], '%Y-%m-%d').date()
        end_due_date = datetime.strptime(criteria['end_due_date'], '%Y-%m-%d').date()
        if dpd in criteria_dpd and second_last_loan_id in test_group and \
                start_due_date <= payment.due_date <= end_due_date:
            first_name_with_title = application.first_name_with_title
            firstname = application.fullname.split()[0]
            # message_template = {[<body_message>,  <cashback_percentage>]}
            message_template = {
                'T-5': '%s, ingin dapatkan extra cashback? Yuk, segera bayar angsuran Anda hari ini!'
                        % first_name_with_title,
                'T-4': 'Pagi! Hari terakhir untuk raih ekstra cashback. Lebih cepat bayar, lebih banyak untung!',
                'T-3': 'Anda masih punya kesempatan dapat Ekstra Cashback. Bayar angsuran %s sekarang.' % payment.payment_number,
                'T-2': 'Ekstra cashback menunggu Anda %s ! Segera lunasi angsuran Anda hari ini' % firstname,
                'T-1': '%s, masih ada kesempatan untuk raih cashback. '
                        'Bayar angsuran Anda hari ini dan dapatkan ekstra cashback!' % firstname,
                'T0': '%s, tagihan Anda jatuh tempo hari ini! Ayo bayar, '
                       'kesempatan terakhir mendapatkan Cashback' % first_name_with_title
            }
            data_to_return = message_template["T{}".format(dpd)]

    return data_to_return


def get_experiment_setting_by_code(code):
    today = timezone.localtime(timezone.now()).date()
    return (
        ExperimentSetting.objects.filter(code=code, is_active=True)
        .filter(
            (Q(start_date__date__lte=today) & Q(end_date__date__gte=today)) | Q(is_permanent=True)
        ).last()
    )
