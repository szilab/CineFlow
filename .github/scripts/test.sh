#!/bin/bash

set -e

source "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/utils.sh"

print_header "🧪 Starting CineFlow Tests"

install_dev_deps
install_base_deps
clean_build

print_header "🔍 Running linters..."

if flake8 . --count --max-complexity=10 --max-line-length=120 --statistics --exclude .venv; then
    print_status "Flake8 passed"
else
    print_error "Flake8 failed"
    exit 1
fi

if pylint $(find "./$PYTHON_PACKAGE" -name "*.py") -d="E0401,F0001,C0116" --max-line-length=120 2>/dev/null; then
    print_status "Pylint passed"
else
    print_error "Pylint failed"
    exit 1
fi

print_header "🔧 Testing setup.py..."

if python setup.py check --metadata --strict; then
    print_status "Setup.py metadata check passed"
else
    print_error "Setup.py metadata check failed"
    exit 1
fi

print_header "📦 Testing package build..."

# Ensure the 'build' package is installed
pip install build --quiet

if python -m build --sdist --wheel --outdir .tmp_build_check; then
    print_status "Package build check passed"
    rm -rf .tmp_build_check
else
    print_error "Package build check failed"
    exit 1
fi

print_header "📦 Testing package installation..."

if pip install -e .; then
    print_status "Package installation successful"
else
    print_error "Package installation failed"
    exit 1
fi

if python -c "import $PYTHON_PACKAGE.main; print('Main module imported successfully')"; then
    print_status "Import test passed"
else
    print_error "Import test failed"
    exit 1
fi

print_header "🧪 Running pytest..."

if [ -d "tests" ]; then
    if pytest tests/ -v --cov=. --cov-report=xml --cov-report=term; then
        print_status "Pytest passed"
    else
        print_error "Pytest failed"
        exit 1
    fi
else
    print_warning "No tests directory found, skipping pytest"
fi

print_status "All tests completed successfully! 🎉"
clean_build