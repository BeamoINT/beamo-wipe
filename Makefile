.PHONY: test iso demo preview preview-web lint

test:
	python3 -m pytest

iso:
	./scripts/build-iso.sh

demo preview:
	./preview

preview-web:
	./preview --web
