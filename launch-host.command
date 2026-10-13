#!/bin/bash
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10 or newer with Tk, then reopen this launcher."
  echo "See docs/HOST_LAUNCHER.md for setup help."
  read -r -n 1 -p "Press any key to close..."
  exit 1
fi
python3 launch_editor.py
status=$?
if [ $status -ne 0 ]; then
  echo "The host window requires Python 3.10+ with Tk. See README for the command-line alternative."
  read -r -n 1 -p "Press any key to close..."
fi
exit $status
