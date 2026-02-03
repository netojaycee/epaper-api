#!/usr/bin/env python3
"""
Environment Configuration Verification Script
Helps verify that all environment variables are loaded correctly
"""

import os
from dotenv import load_dotenv
from config import settings
from pathlib import Path

def print_section(title):
    """Print a formatted section header"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def verify_env_file():
    """Check if .env file exists"""
    print_section("Environment File Check")
    
    env_file = Path(".env")
    if env_file.exists():
        print(f"✓ .env file found")
        print(f"  Location: {env_file.absolute()}")
        print(f"  Size: {env_file.stat().st_size} bytes")
    else:
        print(f"✗ .env file NOT found")
        print(f"  Create one with: cp .env.example .env")
        return False
    
    return True

def verify_variables():
    """Verify all configuration variables are loaded"""
    print_section("Configuration Variables")
    
    variables = {
        "Application": [
            ("app_env", settings.app_env),
            ("debug", settings.debug),
            ("app_name", settings.app_name),
        ],
        "Server": [
            ("host", settings.host),
            ("port", settings.port),
            ("workers", settings.workers),
        ],
        "File Upload": [
            ("max_upload_size_mb", settings.max_upload_size_mb),
            ("temp_dir", settings.temp_dir),
        ],
        "WordPress": [
            ("wp_url", settings.wp_url),
            ("wp_user", settings.wp_user),
            ("wp_password", f"{'*' * 10}" if settings.wp_password else "(not set)"),
            ("wp_enable_posting", settings.wp_enable_posting),
        ],
        "Ollama": [
            ("ollama_host", settings.ollama_host),
            ("ollama_model", settings.ollama_model),
        ],
        "Logging": [
            ("log_level", settings.log_level),
            ("log_file", settings.log_file or "(console only)"),
        ],
    }
    
    for category, vars_list in variables.items():
        print(f"  {category}:")
        for var_name, var_value in vars_list:
            status = "✓" if var_value else "⚠"
            print(f"    {status} {var_name}: {var_value}")
    
    return True

def check_wordpress_config():
    """Verify WordPress configuration"""
    print_section("WordPress Configuration Check")
    
    checks = [
        ("URL configured", bool(settings.wp_url)),
        ("Username configured", bool(settings.wp_user)),
        ("Password configured", bool(settings.wp_password)),
        ("Posting enabled", settings.wp_enable_posting),
    ]
    
    all_good = True
    for check_name, result in checks:
        status = "✓" if result else "✗"
        print(f"  {status} {check_name}")
        if not result and "URL" in check_name or "Username" in check_name:
            all_good = False
    
    if not all_good:
        print(f"\n  ⚠  Some WordPress settings missing.")
        print(f"  Edit .env and set: WORDPRESS_URL, WORDPRESS_USERNAME, WORDPRESS_PASSWORD")
    
    return True

def check_file_permissions():
    """Check .env file permissions"""
    print_section("File Permissions Check")
    
    env_file = Path(".env")
    if not env_file.exists():
        print("  ✗ .env file not found, skipping permission check")
        return True
    
    # On Windows, file permissions work differently
    import platform
    if platform.system() == "Windows":
        print("  ℹ  Running on Windows (permission checks not applicable)")
        return True
    
    # On Unix-like systems
    mode = oct(env_file.stat().st_mode)
    is_readable = os.access(env_file, os.R_OK)
    
    print(f"  File mode: {mode}")
    print(f"  ✓ Readable: {is_readable}")
    
    # Check if file is world-readable (security issue)
    import stat
    file_stat = env_file.stat()
    if file_stat.st_mode & stat.S_IROTH:
        print(f"  ⚠  WARNING: .env file is world-readable!")
        print(f"  Fix with: chmod 600 .env")
        return False
    
    return True

def print_next_steps():
    """Print next steps"""
    print_section("Next Steps")
    
    print("  1. Edit .env file with your configuration:")
    print("     nano .env")
    print()
    print("  2. Set required variables:")
    print("     - WORDPRESS_URL")
    print("     - WORDPRESS_USERNAME")
    print("     - WORDPRESS_PASSWORD (use app password, not account password)")
    print()
    print("  3. Test the application:")
    print("     python main.py")
    print("     or")
    print("     uvicorn main:app --reload")
    print()
    print("  4. Check logs for any errors")
    print()

def main():
    """Run all verification checks"""
    print("\n" + "="*60)
    print("  Environment Configuration Verification")
    print("="*60)
    
    # Load environment
    load_dotenv()
    
    # Run checks
    checks = [
        ("Environment File", verify_env_file),
        ("Variables Loaded", verify_variables),
        ("WordPress Config", check_wordpress_config),
        ("File Permissions", check_file_permissions),
    ]
    
    results = {}
    for check_name, check_func in checks:
        try:
            results[check_name] = check_func()
        except Exception as e:
            print(f"✗ Error during {check_name} check: {e}")
            results[check_name] = False
    
    # Print summary
    print_section("Summary")
    
    all_passed = all(results.values())
    
    for check_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {check_name}")
    
    if all_passed:
        print(f"\n  ✓ All checks passed!")
        print(f"  Your environment is properly configured.")
    else:
        print(f"\n  ✗ Some checks failed.")
        print(f"  Please fix the issues above.")
        print_next_steps()
    
    print()

if __name__ == "__main__":
    main()
