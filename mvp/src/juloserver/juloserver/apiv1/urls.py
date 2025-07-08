from django.conf.urls import include, url
from rest_framework import routers

from . import views

router = routers.DefaultRouter()

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^api-token/', views.ObtainJuloToken.as_view()),
    # Application endpoints
    url(r'^applications/$', views.ApplicationListCreateView.as_view()),
    url(
        r'^applications/(?P<application_id>[0-9]+)/$', views.ApplicationRetrieveUpdateView.as_view()
    ),
    # Collateral enpoints
    url(r'^collaterals/$', views.CollateralListCreateView.as_view()),
    # PaymentMethod endpoints
    url(r'^payment_methods/$', views.PaymentMethodRetrieveView.as_view()),
    # Devices endpoints
    url(r'^devices/$', views.DeviceListCreateView.as_view()),
    url(r'^devices/(?P<device_id>[0-9]+)/$', views.DeviceRetrieveUpdateView.as_view()),
    # Customer endpoints
    url(r'^customer/$', views.CustomerRetrieveView.as_view()),
    url(r'^customer/(?P<customer_id>[0-9]+)/$', views.CustomerRetrieveView.as_view()),
    url(
        r'^customer-agreement/(?P<customer_id>.*)/$', views.CustomerAgreementRetrieveView.as_view()
    ),
    # Offer endpoints
    url(r'^applications/(?P<application_id>[0-9]+)/offers/$', views.OfferListView.as_view()),
    url(
        r'^applications/(?P<application_id>[0-9]+)/offers/' r'(?P<offer_id>[0-9]+)/$',
        views.OfferRetrieveUpdateView.as_view(),
    ),
    # Image endpoints
    url(r'^images/$', views.ImageListCreateViewV1.as_view()),
    # Get Images by application_id
    url(r'^applications/(?P<application_id>[0-9]+)/images/$', views.ImageListView.as_view()),
    # Voice recording upload
    url(r'^voice-records/$', views.VoiceRecordCreateView.as_view()),
    # Voice recording get script endpoint
    url(
        r'^voice-records/(?P<application_id>[0-9]+)/script/$', views.VoiceRecordScriptView.as_view()
    ),
    # Get recordings by application_id
    url(r'^voice-records/(?P<application_id>[0-9]+)/$', views.VoiceRecordListView.as_view()),
    # sign up with username and password
    url(r'^rest-auth/registration/$', views.ObtainUsertoken.as_view()),
    # sign up with username and password
    url(r'^rest-auth/registration/email/resend/$', views.ResendEmail.as_view()),
    # send error report to dev
    url(r'^report/email/dev/$', views.SendEmailToDev.as_view()),
    # send feedback to cs
    url(r'^report/email/feedback/$', views.SendFeedbackToCS.as_view()),
    # email status
    url(r'^rest-auth/registration/email/$', views.EmailStatus.as_view()),
    # login
    url(r'^rest-auth/login/$', views.Login.as_view()),
    url(r'^auth/v2/login/?$', views.LoginWithUnverifiedEmailView.as_view()),
    # reset password
    url(r'^rest-auth/password/reset/$', views.ResetPassword.as_view()),
    # Loan endpoints
    url(r'^loans/$', views.LoanListView.as_view()),
    url(r'^loans/(?P<loan_id>[0-9]+)/$', views.LoanRetrieveUpdateView.as_view()),
    # Payments endpoints
    url(r'^loans/(?P<loan_id>[0-9]+)/payments/$', views.PaymentListView.as_view()),
    url(
        r'^loans/(?P<loan_id>[0-9]+)/payments/(?P<payment_id>[0-9]+)/$',
        views.PaymentRetrieveView.as_view(),
    ),
    url(r'^payment-info/(?P<payment_id>.+)/$', views.PaymentInfoRetrieveView.as_view()),
    # verify email
    url(
        r'^rest-auth/registration/verify-email/(?P<verification_key>.+)/$',
        views.VerifyEmail.as_view(),
    ),
    # reset password page
    url(
        r'^rest-auth/password/reset/confirm/(?P<reset_key>.+)/$',
        views.ResetPasswordConfirm.as_view(),
    ),
    # AddressGeolocation endpoints
    url(
        r'^applications/(?P<application_id>[0-9]+)/addressgeolocations/$',
        views.AddressGeolocationListCreateView.as_view(),
    ),
    url(
        (
            r"^applications/(?P<application_id>[0-9]+)/"
            "addressgeolocations/(?P<address_geolocation_id>[0-9]+)/$"
        ),
        views.AddressGeolocationRetrieveUpdateView.as_view(),
    ),
    # DeviceGeolocation endpoints
    url(
        r'^devices/(?P<device_id>[0-9]+)/devicegeolocations/$',
        views.DeviceGeolocationListCreateView.as_view(),
    ),
    # home screen
    url(r'^homescreen/$', views.HomeScreen.as_view()),
    # facebookdata
    url(r'^facebookdata/$', views.FacebookDataListCreateView.as_view()),
    url(
        r'^facebookdata/(?P<facebook_data_id>[0-9]+)/$',
        views.FacebookDataRetrieveUpdateView.as_view(),
    ),
    # customer
    url(r'^customers/$', views.CustomerRetrieveView.as_view()),
    url(r'^customer/referral_data/$', views.PartnerReferralRetrieveView.as_view()),
    # device scraped data
    url(r'^scrapeddata/$', views.ScrapedDataViewSet.as_view()),
    url(r'^scrapeddata/(?P<pk>[0-9]+)/$', views.ScrapedDataMultiPartParserViewSet.as_view()),
    # credentials for bank scraping (mandiri and BCA)
    # url(r'^applications/external-data-imports/?$', views.BankScrapingStart.as_view()),
    # url(
    #     r'^applications/external-data-imports/(?P<job_id>[0-9]+)/$', views.BankScrapingGet.as_view()
    # ),
    # get user's total application
    url(r'^applications/total_application/$', views.GetCustomerTotalApplication.as_view()),
    # terms
    url(r'^privacy/$', views.Privacy.as_view()),
    url(r'^terms/$', views.Terms.as_view()),
    url(r'^partner-referrals/$', views.PartnerReferralListView.as_view()),
    # app version history
    url(r'^appversionhistory/$', views.AppVersionHistoryListView.as_view()),
    url(r'^product-line/(?P<product_line_code>[0-9]+)/dropdown_data/', views.DropDownApi.as_view()),
    # Product line endpoints
    url(r'^first-product-lines$', views.FirstProductlineListView.as_view()),
    url(r'^product-lines$', views.ProductLineListView.as_view()),
    url(
        r'^applications/(?P<application_id>[0-9]+)/bank_credential/$',
        views.BankCredentialListCreateView.as_view(),
    ),
    url(r'^site-map-content$', views.SiteMapArticleView.as_view()),
    #######################
    #  DEPRECATED BELLOW  #
    #######################
    # mobile dropdowns endpoint DEPRECATED: now under product-lines endpoint
    url(
        r'^dropdowns/',
        include(
            [
                url(r'^versions$', views.DropDownVersion.as_view()),
                url(r'^jobs$', views.DropDownJobs.as_view()),
                url(r'^colleges$', views.DropDownCollege.as_view()),
                url(r'^banks$', views.DropDownBank.as_view()),
                url(r'^majors$', views.DropDownMajor.as_view()),
                url(r'^addresses$', views.DropDownAddress.as_view()),
                url(r'^marketingsources$', views.DropDownMarketingSource.as_view()),
            ]
        ),
    ),
    url(
        r'^product-lines/(?P<product_line_code>[0-9]+)/dropdowns/',
        include(
            [
                url(r'^versions$', views.DropDownVersionListView.as_view()),
                url(r'^jobs$', views.DropDownJobs.as_view()),
                url(r'^colleges$', views.DropDownCollege.as_view()),
                url(r'^banks$', views.DropDownBank.as_view()),
                url(r'^majors$', views.DropDownMajor.as_view()),
                url(r'^addresses$', views.DropDownAddress.as_view()),
                url(r'^marketingsources$', views.DropDownMarketingSource.as_view()),
                url(r'^loanpurposes$', views.DropDownLoanPurpose.as_view()),
                url(r'^companies$', views.DropDownCompany.as_view()),
            ]
        ),
    ),
]
