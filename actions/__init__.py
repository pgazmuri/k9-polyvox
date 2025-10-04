import os

if os.environ.get("USE_MOCK_ACTIONS") == "1":
    print("[actions] Using MOCK preset actions.")
    from mock_preset_actions import *  # noqa: F401,F403
else:
    print("[actions] Using REAL preset actions.")
    from preset_actions import *  # noqa: F401,F403
