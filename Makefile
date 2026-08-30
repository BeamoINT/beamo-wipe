.PHONY: test iso demo preview preview-web lint cloud-test

test:
	python3 -m pytest

iso:
	./scripts/build-iso.sh

cloud-test:
	./scripts/ci-cloud.sh

demo preview:
	./preview

preview-web:
	./preview --web
