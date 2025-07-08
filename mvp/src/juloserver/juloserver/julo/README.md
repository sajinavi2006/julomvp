# julo
This Django app is Julo core backend.

## Code Organization
* `admin`: code for Django Admin for Julo Backoffice Site
* `apps`: contains this app's configuration class
* `clients`: various interface to third party online services
* `formulas`: heavy math, computation, and logic
* `migrations`: database migration scripts
* `models`: 
    * models representing database tables and their basic queries
    * additional useful just-in-time properties and helper methods
    * constants highly coupled with the models
* `services`: functions that contain business logic to complete julo's various user stories
* `signals`: signal receivers/handlers for some business logic
* `tasks`: tasks triggered periodically or asynchronously
* `tests`: unit tests
* `views`: nothing yet
