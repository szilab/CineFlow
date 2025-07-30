#!/bin/bash

set -e

source "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/utils.sh"

print_header "🔧 Starting CineFlow Python Build"

install_dev_deps
install_base_deps
clean_build

print_header "📦 Building packages..."

if python -m build; then
    print_status "Build completed successfully"
    ls -la dist/
else
    print_error "Build failed"
    exit 1
fi

print_header "🔍 Checking distribution packages..."

if twine check dist/*; then
    print_status "Distribution packages are valid"
else
    print_error "Distribution package check failed"
    exit 1
fi

print_status "🎉 Build completed successfully!"
clean_build