.PHONY: up down purge test logs status certs validate

up:
	./scripts/up.sh

down:
	./scripts/down.sh

purge:
	./scripts/down.sh --purge

test:
	./scripts/smoke-test.sh

logs:
	sudo docker compose logs --tail=200 --follow plano policy-guard proxy-interceptor governed-agent

status:
	sudo docker compose ps

certs:
	./scripts/generate-ca.sh ./certs

validate:
	sudo docker compose config >/dev/null
	python3 -m pytest -q policy-guard/test_policy.py
	python3 -m py_compile policy-guard/app.py provider-sim/app.py governed-agent/app.py proxy-interceptor/governance.py
	node --check desktop/extension/background.js
	node --check desktop/extension/content.js
