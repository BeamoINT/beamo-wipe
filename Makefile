.PHONY: test iso demo lint

test:
	python3 -m pytest

iso:
	./scripts/build-iso.sh

demo:
	python3 -m beamo_wipe --demo
