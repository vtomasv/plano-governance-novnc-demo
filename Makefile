.PHONY: up down purge test logs status diagnose certs validate

up:
	./scripts/up.sh

down:
	./scripts/down.sh

purge:
	./scripts/down.sh --purge

test:
	./scripts/smoke-test.sh

logs:
	./scripts/compose.sh logs --tail=200 --follow plano policy-guard proxy-interceptor governed-agent

status:
	./scripts/compose.sh ps

diagnose:
	./scripts/diagnose.sh

certs:
	./scripts/generate-ca.sh ./certs

validate:
	./scripts/validate.sh
