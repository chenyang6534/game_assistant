# plot_det 标注说明

这个目录用于存放新一轮地块检测数据集。

目录结构：

- raw/images: 原始截图
- raw/labels: AnyLabeling JSON 和同步后的 YOLO txt
- images/train: 检测训练集图片
- images/val: 检测验证集图片
- images/test: 检测测试集图片
- labels/train: 检测训练集标签
- labels/val: 检测验证集标签
- labels/test: 检测测试集标签
- data.yaml: 检测训练配置

当前检测类别仍然只有 1 类：

- plot_node

等级、类型、关系不编码进检测类别，而是从 shape attributes 进入属性分类流程。
