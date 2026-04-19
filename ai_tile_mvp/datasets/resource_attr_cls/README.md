# resource_attr_cls 说明

这个目录存放三个属性分类任务的数据集：

- level: 等级分类
- resource_type: 资源类型分类
- relation: 关系分类

每个任务目录结构如下：

- raw/<class_name>: 从 AnyLabeling JSON 裁剪出来的原始小图
- train/<class_name>: 训练集
- val/<class_name>: 验证集
- test/<class_name>: 测试集
- classes.txt: 当前任务的类别列表

三个任务的标准类别分别是：

- level: lv04, lv05, lv06, lv07, lv08, lv09, lv10
- resource_type: wood, stone, iron, copper, food
- relation: ally, friendly, neutral, enemy, self

原始裁剪图由以下脚本自动生成：

```powershell
python ai_tile_mvp/scripts/sync_resource_annotations.py --image-dir ai_tile_mvp/datasets/tile_det/raw/images --json-dir ai_tile_mvp/datasets/tile_det/raw/labels --detection-label-dir ai_tile_mvp/datasets/tile_det/raw/labels --attr-root ai_tile_mvp/datasets/resource_attr_cls --clear-attr-raw
```

切分时分别对三个任务单独执行：

```powershell
python ai_tile_mvp/scripts/split_attribute_classification_dataset.py --source-raw-root ai_tile_mvp/datasets/resource_attr_cls/level/raw --output-root ai_tile_mvp/datasets/resource_attr_cls/level --clear-output
```