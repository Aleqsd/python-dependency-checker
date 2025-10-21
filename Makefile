# Makefile for python-dependency-checker

.PHONY: help test install-dev release

# ==============================================================================
# Help
# ==============================================================================

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  install-dev    Install development dependencies"
	@echo "  test           Run tests"
	@echo "  release        Create a new release. Usage: make release VERSION=v1.2.3"


# ==============================================================================
# Development
# ==============================================================================

install-dev:
	@echo "Installing development dependencies..."
	python -m pip install --upgrade pip
	pip install -r requirements-dev.txt

test:
	@echo "Running tests..."
	python -m pytest

# ==============================================================================
# Release
# ==============================================================================

release:
ifndef VERSION
	$(error VERSION is not set. Usage: make release VERSION=v1.2.3)
endif
	# Check for clean working directory
	@if [ -n "$(shell git status --porcelain)" ]; then \
		echo "Working directory is not clean. Please commit or stash your changes."; \
		exit 1; \
	fi

	$(eval MAJOR_VERSION := $(shell echo $(VERSION) | cut -d. -f1))

	@echo "Releasing version $(VERSION) and major version $(MAJOR_VERSION)..."

	# Create and push the full version tag
	git tag $(VERSION)
	git push origin $(VERSION)

	# Create and push the major version tag
	git tag -f $(MAJOR_VERSION)
	git push origin -f $(MAJOR_VERSION)

	@echo "Release of $(VERSION) and $(MAJOR_VERSION) successful!"
	@echo "Pushed tags to remote."

.DEFAULT_GOAL := help
