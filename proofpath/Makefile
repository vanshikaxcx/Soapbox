.PHONY: lint typecheck test openapi-check dev-api dev-web

lint:
	ruff check services tests
	cd web && npm run lint

typecheck:
	mypy
	cd web && npm run typecheck

test:
	pytest
	cd web && npm test

openapi-check:
	openapi-spec-validator contracts/openapi.yaml
	cd web && npm run generate:api
	git diff --exit-code -- web/src/api/generated || \
		(echo "Generated TS client is stale. Commit the regenerated schema." && exit 1)

dev-api:
	uvicorn services.api.local_app:app --reload --port 8000

dev-web:
	cd web && npm run dev
