# sanzhan_plot AI 训练项目

这个目录是独立的 AI 训练项目根目录，当前项目需要的目录、配置和命令入口都放在这里。

## 当前项目配置

- 检测标签: sanzhan_plot_node
- 检测训练名: sanzhan_plot_det_yolov8n
当前属性任务：
- 等级 (level): 4级 (lv04), 5级 (lv05), 6级 (lv06), 7级 (lv07), 8级 (lv08), 9级 (lv09), 10级 (lv10)
- 类型 (resource_type): 木材 (wood), 石头 (stone), 铁矿 (iron), 铜矿 (copper), 粮食 (food)
- 关系 (relation): 同盟 (ally), 友盟 (friendly), 中立 (neutral), 敌对 (enemy), 我方 (self)

可选候选框复检模型：
- 默认 task_slug: candidate_review
- 样本类别: 正确样本 (positive) / 错误样本 (negative)
- 训练完成后可把权重放到 outputs/train_attr/candidate_review_yolov8n_cls/weights/best.pt
- 也可以在 project_meta.json 的 review_classifier.weights 里手动指定路径

## 目录说明

- configs: 类别、属性和导出元数据模板
- datasets/detection: 检测数据集
- datasets/attribute_cls: 属性分类数据集
- models/detector: 导出的 ONNX 模型
- outputs: 抽检、训练、基准测试输出
- scripts: 项目专用的一键命令入口

## 建议流程

1. 把截图放进 datasets/detection/raw/images
2. 用 AnyLabeling 加载 configs/label_classes.txt 和 configs/attributes.json
3. 标注 JSON 保存到 datasets/detection/raw/labels
4. 运行 scripts/01_sync_annotations.cmd
5. 运行 scripts/02_check_labels.cmd
6. 运行 scripts/03_split_detection.cmd
7. 分别运行 scripts/05_split_attr_<task>.cmd 和 scripts/06_train_attr_<task>.cmd
8. 运行 scripts/04_train_detection.cmd
9. 运行 scripts/11_export_onnx.cmd
10. 运行 scripts/12_benchmark.cmd
11. 运行 scripts/13_scan_thresholds.cmd，先把 detection conf 和 review threshold 扫一轮
12. 如要比较 YOLOv8n/YOLOv8s 与 640/768，运行 scripts/14_detection_experiments.cmd
13. 如果要启用候选框复检，额外训练一个 candidate_review 二分类模型并放到 outputs/train_attr 下

## 新增优化入口

- scripts/13_scan_thresholds.cmd: 扫描当前项目检测阈值与候选框复检阈值组合，输出到 outputs/threshold_scan
- scripts/14_detection_experiments.cmd: 对比 YOLOv8n/YOLOv8s 和 640/768 组合，输出到 outputs/detection_experiments

## AnyLabeling 使用要点

- 标签文件: configs/label_classes.txt
- 属性文件: configs/attributes.json
- 原图目录: datasets/detection/raw/images
- JSON 输出目录: datasets/detection/raw/labels

如果属性面板异常，也可以把属性写进 description，例如：

- 等级=5级 类型=木材 关系=中立

通用同步脚本会优先读 attributes，缺失时回退解析 description。

## 环境说明

项目脚本默认调用 python 命令。建议先激活和 ai_tile_mvp 一致的虚拟环境，再运行这些 cmd 文件。
