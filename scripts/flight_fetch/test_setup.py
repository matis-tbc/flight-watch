#!/usr/bin/env python3
"""
Test script to verify the flight fetcher setup
"""
import os
import sys

def test_environment_variables():
    """Test if environment variables are set"""
    print("Testing environment variable setup...")

    client_id = os.environ.get('AMADEUS_CLIENT_ID')
    client_secret = os.environ.get('AMADEUS_CLIENT_SECRET')

    if not client_id:
        print("❌ AMADEUS_CLIENT_ID not set")
        return False
    else:
        print("✅ AMADEUS_CLIENT_ID set")

    if not client_secret:
        print("❌ AMADEUS_CLIENT_SECRET not set")
        return False
    else:
        print("✅ AMADEUS_CLIENT_SECRET set")

    return True

def test_dependencies():
    """Test if required dependencies are installed"""
    print("\nTesting dependencies...")

    try:
        import amadeus
        print("✅ Amadeus SDK installed")
    except ImportError:
        print("❌ Amadeus SDK not installed")
        return False

    return True

def main():
    print("Flight Fetcher Setup Test")
    print("=" * 30)

    env_ok = test_environment_variables()
    deps_ok = test_dependencies()

    if env_ok and deps_ok:
        print("\n✅ Setup is ready!")
        return 0
    else:
        print("\n❌ Setup has issues")
        return 1

if __name__ == "__main__":
    sys.exit(main())