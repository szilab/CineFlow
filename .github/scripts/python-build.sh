#!/bin/bash

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
source "$SCRIPT_DIR/utils.sh"

print_header "🔧 Starting CineFlow Python Build"

ensure_project_root

export VERSION=$(get_version)

install_base_deps
install_dev_deps

clean_build


echo ""
echo "📦 Building packages..."
echo "========================"

if python -m build; then
    print_status "Build completed successfully"
else
    print_error "Build failed"
    exit 1
fi

ls -la dist/


echo ""
echo "🔍 Checking distribution packages..."
echo "====================================="

if twine check dist/*; then
    print_status "Distribution packages are valid"
else
    print_error "Distribution package check failed"
    exit 1
fi


echo ""
print_status "Build completed successfully! 🎉"
clean_build