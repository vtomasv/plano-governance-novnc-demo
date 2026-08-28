.PHONY: up mac-up down purge test logs status ports diagnose mac-diagnose certs validate

up:
	./scripts/up.sh

mac-up:
	./scripts/mac-up.sh

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

ports:
	@if [ "$$(uname -s)" = "Darwin" ] && [ "$$(uname -m)" = "arm64" ]; then ./scripts/check-publisher-ports.sh; else ./scripts/check-runtime-ports.sh; fi

diagnose:
	@if [ "$$(uname -s)" = "Darwin" ] && [ "$$(uname -m)" = "arm64" ]; then ./scripts/mac-diagnose.sh; else ./scripts/diagnose.sh; fi

mac-diagnose:
	./scripts/mac-diagnose.sh

certs:
	./scripts/generate-ca.sh ./certs

validate:
	./scripts/validate.sh
