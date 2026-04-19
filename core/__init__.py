# Core module
import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.window import WindowManager, WindowInfo
from core.capture import ScreenCapture, CaptureRegion
from core.coordinate_transform import (
    AxisCalibration,
    CoordinateMappingProfile,
    CoordinateMappingStorage,
    CoordinateWorkspaceState,
    CoordinateWorkspaceStateStorage,
    GridCoordinateAnchor,
    resolve_default_workspace_assets_dir,
    resolve_default_workspace_state_path,
    sync_profile_to_isometric_config,
)
from core.grid_detector import GridCellDetectionResult, GridCellModel, detect_grid_cells, hex_polygon_from_basis
from core.recognition import ImageRecognition, MatchResult, ROI
from core.input import InputSimulator, BackgroundInputSimulator, MouseButton, InputConfig

__all__ = ['WindowManager', 'WindowInfo', 'ScreenCapture', 'CaptureRegion',
           'AxisCalibration', 'CoordinateMappingProfile', 'CoordinateMappingStorage',
           'CoordinateWorkspaceState', 'CoordinateWorkspaceStateStorage',
           'GridCoordinateAnchor', 'GridCellDetectionResult', 'GridCellModel',
           'detect_grid_cells', 'hex_polygon_from_basis',
           'resolve_default_workspace_assets_dir', 'resolve_default_workspace_state_path',
           'sync_profile_to_isometric_config',
           'ImageRecognition', 'MatchResult', 'ROI', 'InputSimulator', 
           'BackgroundInputSimulator', 'MouseButton', 'InputConfig']
