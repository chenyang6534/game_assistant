# plot_attr_cls 说明

这个目录存放新一轮地块属性分类数据集。

包含三个任务：

- level: 等级分类
- resource_type: 类型分类
- relation: 关系分类

每个任务目录结构如下：

- raw: 从 AnyLabeling JSON 裁剪出来的原始小图
- train: 训练集
- val: 验证集
- test: 测试集
- classes.txt: 当前任务的类别列表

当前标准类别：

- level: lv04, lv05, lv06, lv07, lv08, lv09, lv10
- resource_type: wood, stone, iron, copper, food
- relation: ally, friendly, neutral, enemy, self

同步命令示例：

```powershell
python ai_tile_mvp/scripts/sync_resource_annotations.py --image-dir ai_tile_mvp/datasets/plot_det/raw/images --json-dir ai_tile_mvp/datasets/plot_det/raw/labels --detection-label-dir ai_tile_mvp/datasets/plot_det/raw/labels --attr-root ai_tile_mvp/datasets/plot_attr_cls --clear-attr-raw
```
