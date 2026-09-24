"""ClipForge dashboard launcher — the easy command.

    python start.py

Opens the dashboard in your browser. No reinstall, no waiting.

First time here? Run `python setup.py` instead — it installs everything
and then opens the dashboard by itself.
(On Windows you can also just double-click ClipForge.bat,
 on Mac double-click "Start ClipForge.command".)
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))


def main():
    try:
        from clipforge import dashboard_server as DS
    except ImportError:
        sys.exit("Dependencies missing hain — pehle ek baar "
                 "`python setup.py` chalao, phir `python start.py`.")
    print("ClipForge dashboard khul raha hai browser mein...")
    DS.run(open_browser=True)


if __name__ == "__main__":
    main()
