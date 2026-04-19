# detection 说明

这个目录用于当前项目的检测数据集。

- raw/images: 原始截图
- raw/labels: AnyLabeling JSON 和同步后的 YOLO txt
- images/train|val|test: 切分后的检测图片
- labels/train|val|test: 切分后的检测标签
- data.yaml: 检测训练配置

当前检测类别只有 1 个: test1_node
