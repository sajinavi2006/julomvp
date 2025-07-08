default:

test:
	# Examples:
	# >>> make test k=TestLoanCalculation
	# >>> make test k=juloserver/loan/tests/
	# >>> make test k="'TestABC or TestLoanCalculation'"

	# With optional path param for faster test lookup
	# >>> make test k=TestLoanCalculation path=juloserver/loan/tests/

	pytest --no-migrations -q -rx -k ${k} ${path}

test_verbose:
	pytest --no-migrations -v -rx -k ${k} ${path}

test_subapp_with_coverage:
	# Examples:
	# >>> make test_subapp_with_coverage k=juloserver/loan/
	# >>> make test_subapp_with_coverage k=juloserver/cfs/

	pytest --no-migrations -v -rx -k ${k} ${path} --cov=${k}

test_all:
	pytest --no-migrations -v -rx


# retroload
retroload:
	# Creating retroload file for updating data

	# Examples:
	# >>> make retroload app=followthemoney name=add_new_lender

	./manage.py centralized_makeretroloads ${app} --name ${name}


applyload:
	# Applying all retroload files

	# Examples:
	# >>> make applyload 

	./manage.py centralized_retroload
