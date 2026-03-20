AI 模型包

这个目录是可分发的主程序运行包。解压后请保持目录结构不变。

主程序使用方式：
1. 打开主程序任务步骤，识别类型选择“AI 地块识别”
2. 在“识别目标”里优先选择 model_package.gaimodel.json；如果主程序版本较旧，也可以改选 models/detector/sanzhan_plot_det_yolov8n_640.onnx
3. 不要单独把 onnx 从包里拖出来，否则主程序无法自动找到同包里的属性/复检权重

包内内容：
- 检测模型: models/detector/sanzhan_plot_det_yolov8n_640.onnx
- 属性任务数: 3
- 候选框复检: 有
- 已打包属性任务: level, resource_type, relation
- 已打包复检任务: candidate_review
