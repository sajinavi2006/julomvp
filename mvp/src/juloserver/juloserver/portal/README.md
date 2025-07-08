CRM Code-Manuals
------------------

Portal Path-Structure
------------------
+ src
    +  juloserver
        #  juloserver
            *  portal
                -  authentication
                -  configuration
                -  core
                +  object
                    -  app_status
                    -  dashboard
                    -  julo_status
                    -  loan_app
                    -  loan_status
                    -  offers
                    -  payment
                    -  payment_status
                    -  scraped_data
            * templates
                +  html
                    +  auth
                    +  common
                    +  core
                    +  error
                    +  main
                    +  object
                        -  app_status
                        -  dashboard
                        -  julo_status
                        -  loan_app
                        -  loan_status
                        -  offers
                        -  payment
                        -  payment_status
                        -  scraped_data
                400.html
                403.html
                404.html
                500.html
                503.html
        #  static
            +  default
            +  images
            +  theme
                -  bootstrap
                -  nav-full
                -  nav-iconbar
                -  nav-inverse
                -  nav-mini
                -  nav-modern
                -  plugins
                    -- bower_components
                    -- images
                    -- w3schools
        *  celery.py
        *  urls.py
        *  wsgy.py
    #  run_celery
    #  manage.py

Description for each path/folder:
----------------------------------

Portal Path-Structure
------------------
+ src
    +  juloserver
        #  juloserver
            *  portal
                -  authentication
                    """
                        not used anymore, previously: there is django command for creating new roles
                    """
                -  configuration
                    """
                        not used yet, purpose: configuration app for CRM, such as pagination row or etc
                    """
                -  core
                    """
                        this path used for:
                        - additional django template tags
                        - CRM context processors
                    """
                +  object
                    -  app_status
                       """
                        - urls, views for application listview and change_status
                        - models for application locked feature
                        - ajax for application proccess
                        - dashboard application views
                       """
                    -  dashboard
                       """
                        - urls, views for dashbord view for every user-roles(group)
                        - models for default role and user selection default role
                       """
                    -  julo_status
                        """
                        - not used anymore: view still on admin_full role
                        - this app for add/update reason when app change status
                        - models for app change status - on the fly change - without code-tables
                        """
                    -  loan_app
                        """
                        - use for SPHP views
                        - app-list view for admin-full role
                        - others details view for admin-full role
                        """
                    -  loan_status
                        """
                        - urls, views for loan listview and details/change_status
                        - ajax for loan details
                        - dashboard loan views
                       """
                    -  offers
                        """
                        - urls, views for offers listview and details/change_status
                        - ajax for offers details
                       """
                    -  payment
                        """
                        - payment-list view for admin-full role
                        - others details view for admin-full role
                        """
                    -  payment_status
                        """
                        - urls, views for payment listview and details/change_status
                        - ajax for payment details
                        - dashboard payment views
                        """
                    -  scraped_data
                        """
                        - app-scrapped-data-list view for admin-full role
                        - others details view for admin-full role
                        - download sd file
                        """
            * templates
                +  html
                    +  auth
                    +  common
                    +  core
                    +  error
                    +  main
                    +  object
                        -  app_status
                            """
                            all html inside this path is for object/app_status/ django-app above
                            """
                        -  dashboard
                            """
                            all html inside this path is for object/dashboard/ django-app above
                            """
                        -  julo_status
                            """
                            all html inside this path is for object/julo_status/ django-app above
                            """
                        -  loan_app
                            """
                            all html inside this path is for object/loan_app/ django-app above
                            """
                        -  loan_status
                            """
                            all html inside this path is for object/loan_status/ django-app above
                            """
                        -  offers
                            """
                            all html inside this path is for object/offers/ django-app above
                            """
                        -  payment
                            """
                            all html inside this path is for object/payment/ django-app above
                            """
                        -  payment_status
                            """
                            all html inside this path is for object/payment_status/ django-app above
                            """
                        -  scraped_data
                            """
                            all html inside this path is for object/scraped_data/ django-app above
                            """
                400.html
                403.html
                404.html
                500.html
                503.html
       #  static
            + default
            + images
            + theme
                - bootstrap
                    """
                    this is css style from tweeter-bootstrap as base our CRM CSS
                    """ 
                - nav-full
                    """
                    this theme used for admin-full
                    """ 
                - nav-iconbar
                    """
                    this theme not used yet
                    """ 
                - nav-inverse
                    """
                    this theme not used yet
                    """ 
                - nav-mini
                     """
                    this theme used for ops dashboard
                    """ 
                - nav-modern
                    """
                    this theme not used yet
                    """     
                - plugins
                    -- bower_components
                        """
                        all bower componect for widget
                        notes: please search your widget here before you put any , except there is still not exist
                        you can add it : css and js your widget
                        """
                    -- images
                    -- w3schools





