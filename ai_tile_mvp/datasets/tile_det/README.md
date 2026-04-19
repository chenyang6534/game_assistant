# tile_det 标注说明

## 类别

- 只有 1 个检测类别: resource_node

## 标签格式

使用 YOLO 检测标签。

每张图片对应一个同名 txt 文件，每一行格式如下：

```text
0 center_x center_y width height
```

其中：

- center_x, center_y, width, height 都是 0 到 1 的相对值
- 0 表示 resource_node 类别

## 标注规则

- 只标菱形资源点，不标 UI、文字、特效碎片
- 每个框要覆盖整个菱形主体，不要只框数字
- 框里不需要再区分等级、类型、关系，这三项改由 shape attributes 记录
- 框大小保持风格一致，不要把相邻目标一起框进来
- 轻度动画、轻度遮挡但主体仍可判断时可以标
- 严重遮挡且主体无法判断时不标
- 画面边缘如果主体仍可判断，可以标；主体出界严重则不标

## 属性来源

- 等级、类型、关系不再编码进检测类别
- 这三项从 AnyLabeling 的 shape attributes 中读取
- 保存 JSON 后，运行同步脚本即可自动生成：
	- 单类检测 txt 标签
	- 等级分类原始裁剪集
	- 类型分类原始裁剪集
	- 关系分类原始裁剪集

## 数据放置规范

原始未切分数据：

- raw/images
- raw/labels

训练切分后数据：

- images/train
- images/val
- images/test
- labels/train
- labels/val
- labels/test