#!/bin/bash
# Calibre-Web Automated - Interactive Test Runner
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Print header
print_header() {
    clear
    echo -e "${BOLD}${CYAN}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║        Calibre-Web Automated - Test Suite Runner          ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Print section header
print_section() {
    echo -e "\n${BOLD}${BLUE}▶ $1${NC}"
}

# Print success message
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

# Print error message
print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Print warning message
print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Print info message
print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

# Check if running inside Docker
check_environment() {
    if [ -f /.dockerenv ]; then
        ENVIRONMENT="docker"
        print_info "Running inside Docker container (Dev Container detected)"
        DEFAULT_MODE="dind"
    else
        ENVIRONMENT="host"
        print_info "Running on host machine"
        DEFAULT_MODE="bind"
    fi
}

# Show main menu
show_menu() {
    print_header
    check_environment
    
    echo ""
    echo -e "${BOLD}Select Test Mode:${NC}"
    echo ""
    echo "  ${BOLD}1)${NC} Integration Tests (Bind Mount Mode)"
    echo "     └─ Standard mode - uses temporary directories"
    echo "     └─ Best for: Local development, CI/CD"
    echo ""
    echo "  ${BOLD}2)${NC} Integration Tests (Docker Volume Mode)"
    echo "     └─ DinD compatible - uses Docker volumes"
    echo "     └─ Best for: Dev containers, Docker-in-Docker"
    echo ""
    echo "  ${BOLD}3)${NC} Docker Startup Tests"
    echo "     └─ Tests container initialization and health"
    echo ""
    echo "  ${BOLD}4)${NC} All Tests (Full Suite)"
    echo "     └─ Run everything available"
    echo ""
    echo "  ${BOLD}5)${NC} Quick Test (Single Integration Test)"
    echo "     └─ Fast verification - runs one test"
    echo ""
    echo "  ${BOLD}6)${NC} Custom Test Selection"
    echo "     └─ Choose specific test file or pattern"
    echo ""
    echo "  ${BOLD}7)${NC} Show Test Info & Status"
    echo ""
    echo "  ${BOLD}q)${NC} Quit"
    echo ""
    echo -ne "${BOLD}Enter your choice [1-7, q]:${NC} "
}

# Run integration tests in bind mount mode
run_integration_bind() {
    print_header
    print_section "Running Integration Tests (Bind Mount Mode)"
    echo ""
    
    print_info "Starting test container with bind mounts..."
    print_info "This will take ~3-4 minutes"
    echo ""
    
    # Check if pytest is available
    if ! command -v pytest &> /dev/null; then
        print_error "pytest not found! Installing..."
        pip install -q pytest pytest-timeout pytest-flask pytest-mock faker
    fi
    
    # Run tests
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    
    if pytest tests/integration/test_ingest_pipeline.py -v --tb=short; then
        echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        print_success "All integration tests passed!"
    else
        echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        print_error "Some tests failed. Check output above."
    fi
    
    echo ""
    read -p "Press Enter to continue..."
}

# Run integration tests in Docker volume mode
run_integration_dind() {
    print_header
    print_section "Running Integration Tests (Docker Volume Mode)"
    echo ""
    
    print_info "Starting test container with Docker volumes..."
    print_info "This will take ~3-4 minutes"
    print_warning "Note: One test (cwa_db_tracks_import) will be skipped"
    echo ""
    
    # Check if pytest is available
    if ! command -v pytest &> /dev/null; then
        print_error "pytest not found! Installing..."
        pip install -q pytest pytest-timeout pytest-flask pytest-mock faker
    fi
    
    # Run tests with volume mode enabled
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    
    if USE_DOCKER_VOLUMES=true pytest tests/integration/test_ingest_pipeline.py -v --tb=short; then
        echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        print_success "All runnable tests passed! (19/20, 1 skipped)"
    else
        echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        print_error "Some tests failed. Check output above."
    fi
    
    echo ""
    read -p "Press Enter to continue..."
}

# Run Docker startup tests
run_docker_tests() {
    print_header
    print_section "Running Docker Startup Tests"
    echo ""
    
    print_info "Testing container initialization..."
    echo ""
    
    if [ ! -f tests/docker/test_container_startup.py ]; then
        print_error "Docker tests not found at tests/docker/test_container_startup.py"
        echo ""
        read -p "Press Enter to continue..."
        return
    fi
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    
    if pytest tests/docker/ -v --tb=short; then
        echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        print_success "Docker tests passed!"
    else
        echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        print_error "Some Docker tests failed."
    fi
    
    echo ""
    read -p "Press Enter to continue..."
}

# Run all tests
run_all_tests() {
    print_header
    print_section "Running Full Test Suite"
    echo ""
    
    print_info "This will run all available tests"
    print_warning "Estimated time: 5-7 minutes"
    echo ""
    echo -ne "Continue? [y/N]: "
    read -r confirm
    
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        return
    fi
    
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    
    # Determine mode based on environment
    if [ "$DEFAULT_MODE" = "dind" ]; then
        print_info "Using Docker Volume mode (DinD environment detected)"
        USE_DOCKER_VOLUMES=true pytest tests/ -v --tb=short || true
    else
        print_info "Using Bind Mount mode"
        pytest tests/ -v --tb=short || true
    fi
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    read -p "Press Enter to continue..."
}

# Run quick test
run_quick_test() {
    print_header
    print_section "Quick Test - Single Integration Test"
    echo ""
    
    print_info "Running: test_ingest_epub_already_target_format"
    print_info "This verifies basic ingest functionality (~30 seconds)"
    echo ""
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    
    if [ "$DEFAULT_MODE" = "dind" ]; then
        USE_DOCKER_VOLUMES=true pytest tests/integration/test_ingest_pipeline.py::TestBookIngestInContainer::test_ingest_epub_already_target_format -v
    else
        pytest tests/integration/test_ingest_pipeline.py::TestBookIngestInContainer::test_ingest_epub_already_target_format -v
    fi
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    read -p "Press Enter to continue..."
}

# Custom test selection
run_custom_test() {
    print_header
    print_section "Custom Test Selection"
    echo ""
    
    echo "Available test files:"
    echo "  1) tests/integration/test_ingest_pipeline.py (20 tests)"
    echo "  2) tests/docker/test_container_startup.py (9 tests)"
    echo ""
    echo "Or enter a custom pytest pattern (e.g., tests/integration/ -k metadata)"
    echo ""
    echo -ne "Enter choice [1-2 or custom pattern]: "
    read -r choice
    
    case $choice in
        1)
            TEST_PATH="tests/integration/test_ingest_pipeline.py"
            ;;
        2)
            TEST_PATH="tests/docker/test_container_startup.py"
            ;;
        *)
            TEST_PATH="$choice"
            ;;
    esac
    
    echo ""
    print_info "Running: $TEST_PATH"
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    
    if [ "$DEFAULT_MODE" = "dind" ]; then
        USE_DOCKER_VOLUMES=true pytest $TEST_PATH -v
    else
        pytest $TEST_PATH -v
    fi
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    read -p "Press Enter to continue..."
}

# Show test information
show_info() {
    print_header
    print_section "Test Suite Information"
    echo ""
    
    print_info "Test Environment: $ENVIRONMENT"
    print_info "Default Mode: $DEFAULT_MODE"
    echo ""
    
    echo -e "${BOLD}Available Tests:${NC}"
    echo ""
    
    # Count tests
    if command -v pytest &> /dev/null; then
        echo "📊 Integration Tests:"
        pytest tests/integration/ --collect-only -q 2>/dev/null | tail -1 || echo "  (pytest needed to count)"
        echo ""
        
        if [ -d tests/docker ]; then
            echo "🐳 Docker Tests:"
            pytest tests/docker/ --collect-only -q 2>/dev/null | tail -1 || echo "  (pytest needed to count)"
            echo ""
        fi
    else
        print_warning "Install pytest to see test counts"
        echo ""
    fi
    
    echo -e "${BOLD}Test Modes:${NC}"
    echo ""
    echo "• ${BOLD}Bind Mount Mode${NC} (Default on host)"
    echo "  └─ Uses temporary directories"
    echo "  └─ 20/20 integration tests pass"
    echo "  └─ Faster cleanup"
    echo ""
    echo "• ${BOLD}Docker Volume Mode${NC} (Default in dev containers)"
    echo "  └─ Uses Docker volumes via docker cp"
    echo "  └─ 19/20 integration tests pass (1 skipped)"
    echo "  └─ Required for Docker-in-Docker"
    echo ""
    
    echo -e "${BOLD}Documentation:${NC}"
    echo "  • tests/DOCKER_VOLUMES.md - Volume mode details"
    echo "  • HYBRID_DOCKER_IMPLEMENTATION.md - Implementation notes"
    echo "  • DIND_MODE_COMPLETE.md - Completion summary"
    echo ""
    
    read -p "Press Enter to continue..."
}

# Main loop
main() {
    # Check for required dependencies
    if ! command -v docker &> /dev/null; then
        print_header
        print_error "Docker is required but not found!"
        echo ""
        echo "Please install Docker and try again."
        exit 1
    fi
    
    while true; do
        show_menu
        read -r choice
        
        case $choice in
            1)
                run_integration_bind
                ;;
            2)
                run_integration_dind
                ;;
            3)
                run_docker_tests
                ;;
            4)
                run_all_tests
                ;;
            5)
                run_quick_test
                ;;
            6)
                run_custom_test
                ;;
            7)
                show_info
                ;;
            q|Q)
                print_header
                print_success "Goodbye!"
                echo ""
                exit 0
                ;;
            *)
                print_header
                print_error "Invalid choice. Please try again."
                sleep 2
                ;;
        esac
    done
}

# Run main function
main
