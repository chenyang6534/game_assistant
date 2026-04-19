import sys
from pathlib import Path

sys.path.insert(0, r'd:/pytest1/game_assistant')

from core.ai_tile_recognition import AITileRecognition
from ai_tile_mvp.runtime.onnx_tile_detector import load_image
from task.executor import TaskExecutor

model_path = Path(r'd:/pytest1/game_assistant/ai_tile_mvp/projects/sanzhan_plot/models/detector/sanzhan_plot_det_yolov8n_640.onnx')
image_path = Path(r'd:/pytest1/game_assistant/ai_tile_mvp/projects/sanzhan_plot/datasets/detection/images/test/sanzhan_plot_20260317_184924_0004.png')

recognizer = AITileRecognition()
image = load_image(image_path)
results = recognizer.find_tiles(image, model_path=str(model_path), threshold=0.10, max_count=30)
results.sort(key=lambda item: (item.center[1], item.center[0]))
results = recognizer.enrich_tiles(image, results, model_path=str(model_path), selected_indices=[0], enrich_all=True)
chosen = results[0]

print('match_count', len(results))
print('chosen', chosen.to_region_dict())

executor = TaskExecutor()
executor._set_last_recognition_regions([
    dict(result.to_region_dict(), recognition_type='ai_tile') for result in results
], selected_index=0)
print('runtime_result', executor._runtime_vars.get('ai_tile_result'))
print('runtime_results_len', len(executor._runtime_vars.get('ai_tile_results', [])))
print('runtime_level', executor._get_reference_value('ai_tile_result.level'))
print('runtime_type', executor._get_reference_value('ai_tile_result.resource_type'))
print('runtime_relation', executor._get_reference_value('ai_tile_result.relation'))
