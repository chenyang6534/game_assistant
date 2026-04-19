# AI 地块识别独立工作区

这个目录用于准备菱形资源点检测、属性分类、导出和离线验证。

它和当前主程序是隔离的：

- 不会被现有 main.py 自动加载
- 不修改现有识别链路
- 只提供数据准备和模型验证能力

## 目录说明

- configs: 训练和模型元数据模板
- datasets/plot_det/raw: 原始截图和标注
- datasets/plot_det/images: 训练/验证/测试图像
- datasets/plot_det/labels: 训练/验证/测试标签
- datasets/plot_attr_cls: 等级/类型/关系 三个分类任务的数据集
- models/tile_detector: 导出的 onnx 和元数据
- outputs: 训练结果、推理可视化、统计输出
- runtime: 独立 onnx 推理器
- scripts: 采样、切分、训练、导出、基准测试脚本
- workbench.py: 可视化工作台入口

当前这套地块识别默认使用一组独立配置：

- configs/plot_label_classes.txt
- configs/plot_node_attributes.json
- configs/plot_model_meta.template.json
- 地块识别标注清单.md

## 建议流程

1. 安装独立训练依赖
2. 直接运行 workbench.py 或 启动AI工作台.bat
3. 在“采样”页里选择目标窗口并开始采样
4. 在“标注与抽检”页里用单类框 + shape attributes 标注
5. 运行同步脚本，自动生成单类检测标签和三份属性分类裁剪集
6. 分别进行检测切分/训练，属性切分/训练
7. 在“导出”页导出检测 onnx
8. 在“基准测试”页做离线速度和识别验证

如果你只想先验证可行性，推荐先走单目标快测：

1. 只标一种目标，比如 5级中立木材
2. 在工作台“单目标快测”页生成独立小数据集
3. 只跑检测切分、检测训练、导出、基准测试
4. 工作台里的检测切分、检测训练、导出、基准测试页默认已经指向这套 5级中立木材快测数据
5. 如果后面要切回完整检测数据，直接点各页里的“切回完整检测数据”按钮
6. 先看速度和 precision / recall，再决定要不要做全量属性方案

如果这轮快测只是手工框了目标、没有填写属性，单目标快测页里保持“忽略属性，直接把所有已框 plot_node 当成当前单目标”为勾选状态即可。

如果 X-AnyLabeling 一导入属性文件就崩，可以先不要导入属性文件，直接在每个框的 description 文本里写属性，例如“5级 木材 敌对”或“等级=5级 类型=木材 关系=敌对”。同步脚本和单目标快测脚本现在会优先读 attributes，缺失时自动回退解析 description。

## 安装依赖

建议在独立虚拟环境中安装：

```powershell
pip install -r ai_tile_mvp/requirements-ai.txt
```

启动可视化工作台：

```powershell
python ai_tile_mvp/workbench.py
```

## 最小命令示例

从 AnyLabeling JSON 生成检测标签和属性分类裁剪集：

```powershell
python ai_tile_mvp/scripts/sync_resource_annotations.py --image-dir ai_tile_mvp/datasets/plot_det/raw/images --json-dir ai_tile_mvp/datasets/plot_det/raw/labels --detection-label-dir ai_tile_mvp/datasets/plot_det/raw/labels --attr-root ai_tile_mvp/datasets/plot_attr_cls --clear-attr-raw
```

生成“5级中立木材”单目标快测数据集：

```powershell
python ai_tile_mvp/scripts/build_single_target_dataset.py --image-dir ai_tile_mvp/datasets/plot_det/raw/images --json-dir ai_tile_mvp/datasets/plot_det/raw/labels --level lv05 --resource-type wood --relation neutral --ignore-attrs --clear-output
```

采样：

```powershell
python ai_tile_mvp/scripts/sample_map_tiles.py --window-title "你的目标窗口标题" --count 300 --interval 1.2
```

交互采样：

```powershell
python ai_tile_mvp/scripts/sample_map_tiles_interactive.py
```

可视化工作台：

```powershell
python ai_tile_mvp/workbench.py
```

标签抽检：

```powershell
python ai_tile_mvp/scripts/check_yolo_labels.py --image-dir ai_tile_mvp/datasets/plot_det/raw/images --label-dir ai_tile_mvp/datasets/plot_det/raw/labels --output-dir ai_tile_mvp/outputs/label_check --sample-count 40
```

切分：

```powershell
python ai_tile_mvp/scripts/split_yolo_dataset.py --source-images ai_tile_mvp/datasets/plot_det/raw/images --source-labels ai_tile_mvp/datasets/plot_det/raw/labels --output-root ai_tile_mvp/datasets/plot_det
```

切分单目标快测数据集：

```powershell
python ai_tile_mvp/scripts/split_yolo_dataset.py --source-images ai_tile_mvp/datasets/smoke_tests/lv05_wood_neutral/raw/images --source-labels ai_tile_mvp/datasets/smoke_tests/lv05_wood_neutral/raw/labels --output-root ai_tile_mvp/datasets/smoke_tests/lv05_wood_neutral --clear-output
```

属性分类切分：

```powershell
python ai_tile_mvp/scripts/split_attribute_classification_dataset.py --source-raw-root ai_tile_mvp/datasets/plot_attr_cls/level/raw --output-root ai_tile_mvp/datasets/plot_attr_cls/level --clear-output
```

训练：

```powershell
python ai_tile_mvp/scripts/train_yolo_tile.py --data ai_tile_mvp/datasets/plot_det/data.yaml --model yolov8n.pt --epochs 120 --imgsz 640 --name plot_node_det_yolov8n
```

属性分类训练：

```powershell
python ai_tile_mvp/scripts/train_yolo_attribute_cls.py --data-root ai_tile_mvp/datasets/plot_attr_cls/level --model yolov8n-cls.pt --epochs 80 --imgsz 224
```

导出：

```powershell
python ai_tile_mvp/scripts/export_yolo_onnx.py --weights ai_tile_mvp/outputs/train/plot_node_det_yolov8n/weights/best.pt --output ai_tile_mvp/models/tile_detector/plot_node_det_yolov8n_640.onnx
```

基准测试：

```powershell
python ai_tile_mvp/scripts/benchmark_onnx_tile.py --model ai_tile_mvp/models/tile_detector/plot_node_det_yolov8n_640.onnx --image-dir ai_tile_mvp/datasets/plot_det/images/test --label-dir ai_tile_mvp/datasets/plot_det/labels/test --output-dir ai_tile_mvp/outputs/benchmark_preview
```

## 当前边界

数据准备、训练和导出仍在这个独立工作区中完成。

当前主程序已经可以继续做“可选 AI 地块识别”的最小接入，但默认不会替换旧模板识别流程。只有在任务步骤里显式选择 AI 地块识别，并且模型文件存在时，才会使用 AI 检测。