.PHONY: install test lint demo gate mutate redteam compare llm idp idp-check idp-down all

install:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

demo:
	.venv/bin/python run_demo.py

gate:
	.venv/bin/python adjudication/eval/run_eval.py

mutate:
	.venv/bin/python adjudication/eval/test_gate_can_fail.py

redteam:
	.venv/bin/python adjudication/redteam/suite.py

compare:
	.venv/bin/python compare.py

# Needs a live backend on :8001 (vLLM) or :11434 (Ollama).
llm:
	.venv/bin/python verify_llm.py

# A real sign-in service: Keycloak in Docker, with one officer and one clerk
# from hack/keycloak/council-realm.json. The passwords in that file are for
# this laptop demo and nothing else.
# Docker starts it again after a reboot, until `make idp-down`.
idp:
	docker rm -f council-idp >/dev/null 2>&1 || true
	docker run -d --name council-idp --restart unless-stopped -p 127.0.0.1:8089:8080 \
		-e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=demo-only-admin \
		-v $(CURDIR)/hack/keycloak:/opt/keycloak/data/import:ro \
		quay.io/keycloak/keycloak:26.8.2 start-dev --import-realm
	@until curl -sf -o /dev/null http://localhost:8089/realms/council/.well-known/openid-configuration; \
		do sleep 2; done; echo "Keycloak is up at http://localhost:8089"

# One referred case decided by an officer who signed in at Keycloak. Needs `make idp`.
idp-check:
	.venv/bin/python verify_idp.py

idp-down:
	docker rm -f council-idp

all: lint test gate mutate redteam compare
