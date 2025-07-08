"""juloserver URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.9/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.conf.urls import url, include
    2. Add a URL to urlpatterns:  url(r'^blog/', include('blog.urls'))
"""
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.conf import settings
from django.contrib import admin

from .collection_vendor.admin import collection_vendor_ratio_admin_site
from .julo.admin import customer_service_admin_site
from .julo.admin import supervisor_admin_site
from .julo.admin import workflow_admin_site, notification_template_admin_site
from .payback.admin import cashback_promo_admin_site

from .portal.core.urls import apps_urlpatterns
from .portal.views import welcome, empty, logout_view
from .portal.views import about_us, promotions
from .julo.views import login_user
from .refinancing.views import collection_offer_j1

OBJECT_APPS = getattr(settings, 'OBJECT_APPS', tuple())

urlpatterns = [
    # Core app urls
    url(r'^csadmin/', customer_service_admin_site.urls),
    url(r'^supervisoradmin/', supervisor_admin_site.urls),
    url(r'^admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
    url(r'^xgdfat82892ddn/statuscheck/', include('celerybeat_status.urls')),
    url(r'^xgdfat82892ddn/', admin.site.urls),
    url(r'^xgdfat82892ddn/', workflow_admin_site.urls),
    url(r'^xgdfat82892ddn/', notification_template_admin_site.urls),
    url(r'^xgdfat82892ddn/', cashback_promo_admin_site.urls),
    url(r'^xgdfat82892ddn/', collection_vendor_ratio_admin_site.urls),
    url(r'^api/sdk/v1/', include('juloserver.sdk.urls')),
    url(r'^api/v1/', include('juloserver.apiv1.urls')),
    url(r'^api/v1/', include('collectioncrm.urls')),
    url(r'^api/v2/', include('juloserver.apiv2.urls')),
    url(r'^api/v2/', include('juloserver.followthemoney.urls.v2_urls')),
    url(r'^api/loc/', include('juloserver.line_of_credit.urls')),
    url(r'^api/docs/', include('rest_framework_docs.urls')),
    url(r'^api/partner/v1/', include('juloserver.partnerapiv1.urls')),
    url(r'^api/qa/v1/', include('juloserver.qaapiv1.urls')),
    url(r'^', include('juloserver.integapiv1.urls')),
    url(r'^ana-api/', include('juloserver.ana_api.urls')),
    url(r'^crm/', include('juloserver.crm.urls')),
    url(r'^julosoap/', include('juloserver.julosoap.urls')),
    url(r'^mock/', include('juloserver.mock.urls')),
    url(r'^api/disbursement/', include('juloserver.disbursement.urls')),
    url(
        r'^disbursement/',
        include('juloserver.disbursement.crm_urls', namespace='disbursement_portal'),
    ),
    url(r'^api/paylater/v1/', include('juloserver.paylater.urls', namespace='paylater')),
    url(r'^api/v3/', include('juloserver.apiv3.urls')),
    url(r'^api/v4/', include('juloserver.apiv4.urls', namespace='api_v4')),
    url(r'^api/revamp/v3/', include('juloserver.apirevampv3.urls')),
    url(r'^api/payback/', include('juloserver.payback.urls')),
    url(r'^api/registration-flow/', include('juloserver.registration_flow.urls')),
    url(r'^api/payback/', include('juloserver.payback.urls')),
    url(r'^api/julo_privy/v1/', include('juloserver.julo_privyid.urls')),
    # web app
    url(r'^api/web/', include('juloserver.webapp.urls')),
    url(r'^urlshortener/', include('juloserver.urlshortener.urls')),
    url(r'^login/$', login_user, name='login'),
    url(r'^logout/$', logout_view, name='logout'),
    # Default URL
    url(r'^$', welcome, name='index'),
    url(r'^welcome$', welcome, name='welcome'),
    url(r'^about_us$', about_us, name='about_us'),
    url(r'^promotions$', promotions, name='promotions'),
    url(r'^empty/', empty, name='empty'),
    url(r'^tinymce/', include('tinymce.urls')),
    url(r'^api/followthemoney/', include('juloserver.followthemoney.urls')),
    url(
        r'^streamlined_communication/',
        include('juloserver.streamlined_communication.urls.crm_urls', namespace='streamlined'),
    ),
    url(
        r'^api/streamlined_communication/v1/',
        include('juloserver.streamlined_communication.urls.api_v1', namespace='streamlined-api'),
    ),
    url(
        r'^api/streamlined_communication/v2/',
        include('juloserver.streamlined_communication.urls.api_v2', namespace='streamlined-api'),
    ),
    url(
        r'^api/streamlined_communication/web/v1/',
        include(
            'juloserver.streamlined_communication.urls.web_v1', namespace='streamlined-web-api'
        ),
    ),
    url(
        r'^api/streamlined_communication/callbacks/v1/',
        include(
            'juloserver.streamlined_communication.urls.callbacks',
            namespace='streamlined-callback-api',
        ),
    ),
    url(
        r'^api/loan_refinancing/v1/',
        include('juloserver.loan_refinancing.urls', namespace='loan_refinancing'),
    ),
    url(r'^androidcard/', include('juloserver.androidcard.urls', namespace='androidcard')),
    url(r'^api/minisquad/', include('juloserver.minisquad.urls', namespace='minisquad')),
    url(r'^api/pre/', include('juloserver.pre.urls', namespace='pre')),
    url(r'^api/bpjs/', include('juloserver.bpjs.urls', namespace='bpjs')),
    url(
        r'^api/customer-module/v1/',
        include('juloserver.customer_module.urls.api_v1', namespace='customer_module'),
    ),
    url(
        r'^api/customer-module/v2/',
        include('juloserver.customer_module.urls.api_v2', namespace='customer_module_apiv2'),
    ),
    url(
        r'^api/customer-module/v3/',
        include('juloserver.customer_module.urls.api_v3', namespace='customer_module_apiv3'),
    ),
    url(
        r'^api/customer-module/v4/',
        include('juloserver.customer_module.urls.api_v4', namespace='customer_module_apiv4'),
    ),
    url(
        r'^api/customer-module/web/v1/',
        include('juloserver.customer_module.urls.web_v1', namespace='customer_module_web_v1'),
    ),
    # url(r'^nexmo_poc/beta/', include('juloserver.poc_nexmo.urls')),
    url(r'^api/pin/', include('juloserver.pin.urls', namespace='pin')),
    url(r'^api/ocr/v1/', include('juloserver.ocr.urls.api_v1', namespace='ocr')),
    url(r'^api/ocr/v2/', include('juloserver.ocr.urls.api_v2', namespace='ocr_v2')),
    url(r'^api/ocr/v3/', include('juloserver.ocr.urls.api_v3', namespace='ocr_v3')),
    url(r'^api/ocr/v4/', include('juloserver.ocr.urls.api_v4', namespace='ocr_v4')),
    url(
        r'^api/application_flow/',
        include('juloserver.application_flow.urls', namespace='application_flow'),
    ),
    url(
        r'^api/application-form/',
        include('juloserver.application_form.urls', namespace='application_form'),
    ),
    url(
        r'^collection_vendor/',
        include('juloserver.collection_vendor.urls', namespace='collection_vendor'),
    ),
    url(
        r'^api/account_payment/',
        include('juloserver.account_payment.urls', namespace='account_payment'),
    ),
    url(r'^api/loan/', include('juloserver.loan.urls', namespace='loan')),
    url(r'^api/booster/v1/', include('juloserver.boost.urls', namespace='boost')),
    url(r'^api/account/v1/', include('juloserver.account.urls.api_v1', namespace='account')),
    url(r'^api/account/v2/', include('juloserver.account.urls.api_v2', namespace='account')),
    url(r'^api/moengage/v1/', include('juloserver.moengage.urls', namespace='moengage')),
    url(
        r'^api/warning_letter/v1/',
        include('juloserver.warning_letter.urls', namespace='warning_letter'),
    ),
    url(r'^waiver/', include('juloserver.waiver.urls.crm', namespace='waiver')),
    url(
        r'^api/payment-point/', include('juloserver.payment_point.urls', namespace='payment_point')
    ),
    url(r'^api/referral/v1/', include('juloserver.referral.urls.api_v1', namespace='referral')),
    url(r'^api/referral/v2/', include('juloserver.referral.urls.api_v2', namespace='referral')),
    url(
        r'^api/partner/', include('juloserver.merchant_financing.urls.axiata_v1')
    ),  # TODO: deprecate
    url(r'^merchant_financing/', include('juloserver.merchant_financing.urls.axiata_v1')),
    url(r'^api/merchant-financing/v1/', include('juloserver.merchant_financing.urls.api_v1')),
    url(r'^api/cashback/v1/', include('juloserver.cashback.urls.api_v1', namespace='cashback')),
    url(r'^api/cashback/v2/', include('juloserver.cashback.urls.api_v2', namespace='cashback')),
    url(r'^refinancing/', include('juloserver.refinancing.urls', namespace='refinancing')),
    url(r'^collection-offer-j1/$', collection_offer_j1, name='refinancing_collection_offer_j1'),
    url(r'^api/partner/grab/', include('juloserver.grab.urls', namespace='grab')),
    url(r'^api/ecommerce/v1/', include('juloserver.ecommerce.urls.api_v1', namespace='ecommerce')),
    url(r'^api/ecommerce/v2/', include('juloserver.ecommerce.urls.api_v2', namespace='ecommerce')),
    url(r'^api/qris/', include('juloserver.qris.urls', namespace='qris')),
    url(r'^api/auth/', include('juloserver.api_token.urls')),
    url(
        r'^api/face_recognition/',
        include('juloserver.face_recognition.urls', namespace='face_recognition'),
    ),
    url(r'^api/otp/', include('juloserver.otp.urls')),
    url(
        r'^collection_hi_season/',
        include('juloserver.collection_hi_season.urls', namespace='collection_hi_season'),
    ),
    url(r'^api/partnership/v1/', include('juloserver.partnership.urls.api_v1')),
    url(r'^api/liveness-detection/', include('juloserver.liveness_detection.urls')),
    url(r'^api/partnership/web/v1/', include('juloserver.partnership.urls.web_v1')),
    url(
        r'^api/partnership/liveness/v1/',
        include('juloserver.partnership.liveness_partnership.urls.api_v1'),
    ),
    url(r'^api/rentee/v1/', include('juloserver.rentee.urls', namespace='rentee')),
    url(
        r'^collection_field/',
        include('juloserver.collection_field_automation.urls', namespace='collection_field'),
    ),
    url(
        r'^collops_qa_automation/',
        include('juloserver.collops_qa_automation.urls', namespace='collops_qa_automation'),
    ),
    url(
        r'^api/magic_link/v1/', include('juloserver.magic_link.urls.api_v1', namespace='magic_link')
    ),
    url(
        r'^api/landing_page/',
        include('juloserver.landing_page_api.urls', namespace='landing_page_api'),
    ),
    url(r'^api/cfs/', include('juloserver.cfs.urls.api_urls', namespace='cfs')),
    url(r'^cfs/', include('juloserver.cfs.urls.crm_urls', namespace='crm_cfs')),
    url(r'^sales-ops/', include('juloserver.sales_ops.urls.crm_urls', namespace='sales_ops.crm')),
    url(r'^julovers/', include('juloserver.julovers.urls.crm_urls', namespace='julovers.crm')),
    # Autodebet BCA
    url(r'^api/autodebet/', include('juloserver.autodebet.urls', namespace='autodebet')),
    url(
        r'^webhook/autodebet/',
        include('juloserver.autodebet.urls.webhook_urls', namespace='webhook_autodebet'),
    ),
    url(
        r'^account-authorization/',
        include('juloserver.autodebet.urls.urls_callback_v1', namespace='callback_autodebet_bca'),
    ),
    url(
        r'^api/user_action_logs/',
        include('juloserver.user_action_logs.urls', namespace='user_action_logs'),
    ),
    url(r'^cashback/', include('juloserver.cashback.urls.crm_urls', namespace='cashback.crm')),
    url(r'^api/promo/v1/', include('juloserver.promo.urls.api_v1', namespace='promo')),
    url(r'^api/promo/v2/', include('juloserver.promo.urls.api_v2', namespace='promo_v2')),
    url(r'^api/promo/v3/', include('juloserver.promo.urls.api_v3', namespace='promo_v3')),
    url(
        r'^api/credit-card/v1/',
        include('juloserver.credit_card.urls.api_v1', namespace='credit_card_v1'),
    ),
    url(r'^api/historical/', include('juloserver.historical.urls', namespace='historical')),
    # Employee Financing
    url(
        r'^employee-financing/',
        include('juloserver.employee_financing.urls.crm_urls', namespace='employee_financing'),
    ),
    url(
        r'^api/employee-financing/pilot/',
        include('juloserver.employee_financing.urls.api_v1', namespace='employee_financing_api'),
    ),
    # OVO
    url(r'^api/ovo/v1/', include('juloserver.ovo.urls.api_push2pay_v1', namespace='ovo')),
    url(
        r'^api/ovo-tokenization/v1/',
        include('juloserver.ovo.urls.api_tokenization_v1', namespace='ovo'),
    ),
    url(
        r'^webhook/ovo-tokenization/v1/',
        include(
            'juloserver.ovo.urls.webhook_tokenization_v1', namespace='webhook_ovo_tokenization'
        ),
    ),
    url(
        r'^api/app-reports/v1/',
        include('juloserver.julo_app_report.urls.api_v1', namespace='julo_app_report'),
    ),
    # Fraud Report
    url(r'^api/fraud_report/', include('juloserver.fraud_report.urls', namespace='fraud_report')),
    # Dana
    url(r'^v1.0/', include('juloserver.dana.urls', namespace='dana')),
    # Julo Savings
    url(
        r'^api/julo-savings/v1/',
        include('juloserver.julo_savings.urls.api_v1', namespace='julo_savings_v1'),
    ),
    # New Crm
    url(r'^new_crm/', include('juloserver.new_crm.urls', namespace='new_crm')),
    url(r'^fraud_security/', include('juloserver.fraud_security.urls', namespace='fraud_security')),
    # Julo Starter
    url(
        r'^api/julo-starter/v1/',
        include('juloserver.julo_starter.urls.api_v1', namespace='julo_starter'),
    ),
    url(
        r'^api/julo-starter/v2/',
        include('juloserver.julo_starter.urls.api_v2', namespace='julo_starter_v2'),
    ),
    url(
        r'^api/julo-starter/v2/',
        include('juloserver.julo_starter.urls.api_v2', namespace='julo_starter_v2'),
    ),
    url(r'^api/education/', include('juloserver.education.urls', namespace='education')),
    url(r'^api/fraud_score/', include('juloserver.fraud_score.urls', namespace='fraud_score')),
    url(r'^api/web-portal/', include('juloserver.merchant_financing.urls.axiata_web')),
    url(
        r'^api/merchant-financing/web-portal/',
        include(
            'juloserver.merchant_financing.urls.web_portal',
            namespace='merchant_financing_web_portal',
        ),
    ),
    url(
        r'^api/balance-consolidation/',
        include('juloserver.balance_consolidation.urls', namespace='balance_consolidation'),
    ),
    url(
        r'^balance-consolidation/',
        include(
            'juloserver.balance_consolidation.urls.crm_urls', namespace='balance_consolidation_crm'
        ),
    ),
    url(
        r'^api/nps/',
        include('juloserver.nps.urls', namespace='nps'),
    ),
    url(
        r'^api/merchant-financing/web-app/',
        include(
            'juloserver.merchant_financing.urls.web_app',
            namespace='merchant_financing_web_app',
        ),
    ),
    url(
        r'^api/merchant-financing/dashboard/',
        include(
            'juloserver.merchant_financing.urls.dashboard_web_app',
            namespace='merchant_financing_dashboard_web_app',
        ),
    ),
    url(
        r'^api/rating/',
        include('juloserver.rating.urls', namespace='rating'),
    ),
    # Channeling loan
    url(
        r'^api/channeling_loan/',
        include('juloserver.channeling_loan.urls', namespace='channeling_loan'),
    ),
    url(
        r'^channeling_loan/',
        include('juloserver.channeling_loan.urls.crm_urls', namespace='channeling_loan_portal'),
    ),
    url(
        r'^api/leadgen/',
        include(
            'juloserver.partnership.leadgenb2b.urls',
            namespace='partnership_leadgenb2b',
        ),
    ),
    # FDC
    url(
        r'^fdc/v1/',
        include('juloserver.fdc.urls', namespace='fdc'),
    ),
    url(
        r'^api/dana-linking/',
        include('juloserver.dana_linking.urls', namespace='dana_linking'),
    ),
    url(
        r'^api/oneklik-bca/',
        include('juloserver.oneklik_bca.urls', namespace='oneklik_bca'),
    ),
    url(
        r'^api/partnership/lender-dashboard/',
        include(
            'juloserver.partnership.lender_dashboard.urls', namespace='partnership_lender_dashboard'
        ),
    ),
    url(r'^api/healthcare/', include('juloserver.healthcare.urls', namespace='healthcare')),
    url(
        r'^api/cx-external-party/',
        include('juloserver.cx_external_party.urls', namespace='cx-external-party'),
    ),
    url(
        r'^api/personal_data_verification/',
        include(
            'juloserver.personal_data_verification.urls', namespace='personal_data_verification'
        ),
    ),
    url(
        r'^api/loyalty/',
        include('juloserver.loyalty.urls', namespace='loyalty'),
    ),
    url(
        r'^api/faq/',
        include('juloserver.faq.urls', namespace='faq'),
    ),
    url(
        r'^api/fraud-portal/',
        include('juloserver.fraud_portal.urls', namespace='fraud_portal'),
    ),
    url(
        r'^api/inapp-survey/',
        include('juloserver.inapp_survey.api_urls', namespace='inapp-survey'),
    ),
    url(
        r'^api/inapp-survey/v1/',
        include('juloserver.inapp_survey.urls.api_v1', namespace='inapp_survey_v1'),
    ),
    url(
        r'^api/inapp-survey/web/v1/',
        include('juloserver.inapp_survey.urls.web_v1', namespace='inapp_survey_web_v1'),
    ),
    url(
        r'^api/julo-financing/',
        include('juloserver.julo_financing.urls', namespace='julo_financing'),
    ),
    url(
        r'^julo-financing/',
        include('juloserver.julo_financing.urls.crm_urls', namespace='julo_financing_crm'),
    ),
    url(
        r'^api/merchant-financing/lender-dashboard/',
        include(
            'juloserver.merchant_financing.lender_dashboard.urls.api',
            namespace='merchant_financing_lender_dashboard',
        ),
    ),
    url(
        r'^api/cx-complaint/',
        include('juloserver.cx_complaint_form.api_urls', namespace='cx_complaint_form'),
    ),
    url(
        r'^api/cx-complaint/v1/',
        include('juloserver.cx_complaint_form.urls.api_v1', namespace='cx_complaint_form_v1'),
    ),
    url(
        r'^api/cx-complaint/web/v1/',
        include('juloserver.cx_complaint_form.urls.web_v1', namespace='cx_complaint_form_web_v1'),
    ),
    url(
        r'^api/digisign/',
        include('juloserver.digisign.urls', namespace='digisign'),
    ),
    # cohort campaign automation
    url(
        r'^cohort-campaign-automation/',
        include(
            'juloserver.cohort_campaign_automation.urls.crm', namespace='cohort_campaign_automation'
        ),
    ),
    url(
        r'^api/graduation/',
        include('juloserver.graduation.urls', namespace='graduation'),
    ),
    url(r'^oneklik/', include('juloserver.oneklik_bca.urls', namespace='oneklik_webhook')),
    url(
        r'^api/partnership/digital-signature/v1/',
        include(
            'juloserver.partnership.urls.api_v1_digital_signature',
            namespace='partnership_digital_signature',
        ),
    ),
    url(
        r'^api/easy_income_upload/',
        include('juloserver.easy_income_upload.urls', namespace='easy_income_upload'),
    ),
    url(r'^easy_income_upload/', include('juloserver.easy_income_upload.urls.crm_urls', namespace='crm_easy_income_upload')),
    url(
        r'^api/payment-gateway/',
        include('juloserver.payment_gateway.urls', namespace='payment_gateway'),
    ),
    url('^api/comms/', include('juloserver.comms.urls')),
    url(
        r'^api/smart-ad-hub/',
        include('juloserver.smart_ad_hub.urls', namespace='smart_ad_hub'),
    ),
]

urlpatterns += apps_urlpatterns(OBJECT_APPS)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# handler500 = 'juloserver.portal.views.custom_500'
