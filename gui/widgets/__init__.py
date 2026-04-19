# Widgets submodule
import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from gui.widgets.window_picker import WindowPicker
from gui.widgets.hotkey_editor import HotkeyEditor
from gui.widgets.script_list import ScriptListWidget
from gui.widgets.coordinate_transform_panel import CoordinateTransformPanel

__all__ = ['WindowPicker', 'HotkeyEditor', 'ScriptListWidget', 'CoordinateTransformPanel']
