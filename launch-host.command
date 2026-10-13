#!/bin/bash
cd "$(dirname "$0")" || exit 1
python3 launch_editor.py
status=$?
if [ $status -ne 0 ]; then
  echo "The host window requires Python 3.10+ with Tk. See README for the command-line alternative."
  read -r -n 1 -p "Press any key to close..."
fi
exit $status
