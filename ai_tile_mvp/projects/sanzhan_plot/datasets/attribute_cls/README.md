# attribute_cls 说明

这个目录存放当前项目的属性分类数据集。

每个属性任务目录结构如下：

- raw: 从标注框裁剪出来的原始小图
- train: 训练集
- val: 验证集
- test: 测试集
- classes.txt: 当前任务类别列表

当前任务定义：

- 等级 (level): 4级 (lv04), 5级 (lv05), 6级 (lv06), 7级 (lv07), 8级 (lv08), 9级 (lv09), 10级 (lv10)
- 类型 (resource_type): 木材 (wood), 石头 (stone), 铁矿 (iron), 铜矿 (copper), 粮食 (food)
- 关系 (relation): 同盟 (ally), 友盟 (friendly), 中立 (neutral), 敌对 (enemy), 我方 (self)
