import importlib
import sys


def load_profile(name):
    """Load an AI profile by name from ai_profiles/<name>.py and return its PROFILE dict."""
    try:
        module = importlib.import_module(f"ai_profiles.{name}")
    except ModuleNotFoundError:
        print(f"Error: AI profile '{name}' not found. Expected file: ai_profiles/{name}.py")
        sys.exit(1)
    return module.PROFILE
