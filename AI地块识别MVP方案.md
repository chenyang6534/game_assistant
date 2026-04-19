# AI 地块识别最小可行方案

## 1. 目标

本方案只解决一个问题：

- 在目标窗口画面中稳定找出当前可见地块的中心点。
- 输出结果继续复用现有的“识别坐标 -> 逻辑坐标”流程，不改动坐标转换算法。

首版不追求：

- 精确六边形轮廓分割
- 地块类型细分
- 端到端直接输出逻辑坐标

这样可以把训练、标注、接入和验证成本压到最低。

## 2. MVP 输出定义

模型输入：

- 一张窗口截图，优先使用已裁剪的地图 ROI

模型输出：

- 多个地块框，每个框只服务于“中心点定位”
- 每个结果包含：x, y, w, h, confidence

运行时只取：

- 框中心点 center_x, center_y

后处理：

- 用现有去重/NMS逻辑或模型内置 NMS
- 将中心点写入现有 recognition regions
- 继续走 recognition_to_logic_coord

## 3. 为什么选检测而不是分割或关键点

MVP 推荐单类目标检测，而不是语义分割或关键点网络。

原因：

- 标注最简单，CVAT 或 Label Studio 都能很快上手。
- 训练工具成熟，导出 ONNX 容易。
- 你的现有执行链路本来就依赖识别框中心点，天然适配。
- 分割虽然理论上更精细，但训练、推理和后处理复杂度都更高。
- 单关键点模型也可行，但标注和部署路径不如检测成熟，首版没必要。

## 4. 标注格式

推荐格式：YOLO 检测格式。

目录结构建议：

- datasets/tile_det/images/train
- datasets/tile_det/images/val
- datasets/tile_det/images/test
- datasets/tile_det/labels/train
- datasets/tile_det/labels/val
- datasets/tile_det/labels/test
- datasets/tile_det/data.yaml

类别：

- 只保留 1 类：tile

每张图片对应一个同名 txt 文件，每行格式：

class_id center_x center_y width height

说明：

- 全部使用相对坐标，范围 0 到 1。
- class_id 固定为 0。
- 标的是“中心框”，不是一定要包住整个六边形。

标注原则：

- 框中心必须落在地块几何中心附近。
- 框大小保持一致风格，建议覆盖地块主体的 35% 到 55%。
- 被特效遮挡但人眼仍可判断中心的地块，继续标。
- 严重遮挡、边缘只露一角、中心无法判断的地块不标。
- 贴边地块如果中心仍在画面内，可以标；中心已出界则不标。

data.yaml 示例：

```yaml
path: datasets/tile_det
train: images/train
val: images/val
test: images/test
names:
  0: tile
```

## 5. 样本量

因为一张图里通常会出现很多地块，所以按“截图张数”估算更合理。

最小可行样本量：

- 训练集：200 到 300 张截图
- 验证集：40 到 60 张截图
- 测试集：40 到 60 张截图

推荐首轮样本量：

- 训练集：400 到 600 张截图
- 验证集：80 到 120 张截图
- 测试集：80 到 120 张截图

按地块实例数估算，大致会有：

- MVP：6000 到 15000 个 tile 实例
- 较稳版本：15000 到 40000 个 tile 实例

补样优先级：

- 动画最强的地块
- 透视最明显的边缘区域
- 缩放变化最大的画面
- 底图颜色最接近地块的场景
- 当前模板匹配最容易误判和漏判的画面

## 6. 采样策略

不要连续录一段视频然后每帧都标，这会让样本重复度过高。

建议按下面维度抽样：

- 缩放等级：近、中、远
- 地图位置：中心区、边缘区、角落区
- 动画状态：静止帧、半动画帧、强动画帧
- 背景复杂度：纯净、一般、复杂
- UI 干扰：无遮挡、轻度遮挡、重度遮挡

抽样规则：

- 同一镜头最多每 8 到 15 帧取 1 张
- 每次新增数据优先从失败案例回收
- 测试集必须固定，不参与反复补样

## 7. 模型选择

MVP 首选：YOLO 小模型做单类检测，导出 ONNX 运行。

推荐顺序：

1. YOLOv8n 检测模型，输入 640
2. 如果 CPU 太慢，改为输入 512 或 448
3. 如果小目标漏检明显，再尝试 640 保持不变并缩小地图 ROI

不建议首版使用：

- 分割模型
- 大模型检测器
- 直接用 SAM 一类通用分割工具跑在线推理
- 端到端回归逻辑坐标

理由：

- 你的部署是 Windows 桌面工具，CPU 推理现实约束很强。
- 小模型导出 ONNX 后最容易接进现有 Python 项目。
- 现有链路只需要中心点，不需要更重的输出。

## 8. 推理框架选择

运行时推荐：ONNX Runtime。

原因：

- Windows Python 工程集成简单。
- 模型文件单独分发方便。
- CPU 推理稳定，后续也能切换 DirectML 或 CUDA。

模型交付物建议：

- models/tile_detector/tile_yolov8n_640.onnx
- models/tile_detector/labels.json
- models/tile_detector/model_meta.json

model_meta.json 建议字段：

- input_size
- conf_threshold
- iou_threshold
- class_names
- normalization
- letterbox
- version

## 9. 训练建议

首轮训练设置建议：

- 单类检测
- 输入尺寸：640
- batch：按显存决定
- epoch：80 到 150
- 早停：15 到 20
- 数据增强：轻量即可

增强建议保留：

- 亮度/对比度变化
- 轻微缩放
- 轻微仿射
- 少量模糊

增强建议谨慎：

- 大角度旋转
- 过强透视变换
- 大面积 mosaic

原因是目标画面视角变化有边界，过强增强会制造不存在的数据分布。

## 10. 质量门槛

MVP 是否可用，不看学术指标，优先看业务指标。

建议验收标准：

- 单张图地块召回率 >= 95%
- 单张图误检率 <= 5%
- 中心点误差中位数 <= 8 像素
- 经过 recognition_to_logic_coord 后，逻辑坐标正确率 >= 95%
- 常用分辨率下单次推理耗时：CPU 目标 40 到 120 ms

如果你的地图 ROI 很大，CPU 超过 120 ms 也不一定不可用，但要看任务循环频率。

## 11. 最小接入方案

### 11.1 新增模块

新增一个独立检测器模块：

- core/ai_tile_detector.py

职责：

- 加载 ONNX 模型
- 预处理截图
- 执行推理
- 后处理框和置信度
- 输出与现有 MatchResult 类似的数据结构

建议定义：

- TileDetectionResult
- AITileDetector

字段尽量贴近现有 MatchResult：

- x
- y
- width
- height
- confidence
- label

这样能减少执行器改动。

### 11.2 主窗口初始化

当前主窗口在启动时初始化了模板识别器和 OCR，后续可以并列增加 AI 检测器。

现有位置：main_window.py 中 MainWindow.__init__ 的核心组件初始化。

最小改动：

- 保留 ImageRecognition
- 新增 self._ai_tile_detector
- 模型未配置时允许为空，不影响现有流程

### 11.3 任务模型接入

当前识别类型只有 image、text、multi_image、none。

建议新增：

- recognition_type = ai_tile

原因：

- AI 地块检测和模板匹配不是同一语义，不应该塞进 image_match_mode。
- 单独一个 recognition_type 更清晰，也更方便未来扩展参数。

建议新增配置字段：

- ai_model_path
- ai_conf_threshold
- ai_iou_threshold
- ai_max_detections
- ai_use_map_roi

其中首版也可以先不做成每步骤独立字段，而是统一走全局配置。

### 11.4 执行器接入

当前执行器在 _recognize_single_target 里按 recognition_type 分发。

最小接入方式：

- 新增 _recognize_ai_tile
- 在 _recognize_single_target 中增加 ai_tile 分支

_recognize_ai_tile 的输出要求：

- 返回单个目标时：返回选中的中心点和框大小
- 返回多个目标时：写入 _last_recognition_regions
- recognition_type 字段写 ai_tile

这样下面这些既有动作可以直接复用：

- highlight_match
- save_recognition_coords
- drag_match_to_center
- recognition_to_logic_coord

### 11.5 任务面板接入

当前任务面板的识别类型下拉框只暴露模板匹配、OCR、多图像和无识别。

建议新增：

- AI 地块识别

界面最小化原则：

- 先复用现有阈值控件
- 先隐藏“图像匹配方式”控件
- 先保留 ROI 控件
- 识别目标输入框可以先不使用，或固定显示模型名/地图 ROI 名

这样 UI 改动最少。

## 12. 地图 ROI 建议

如果直接对整窗推理，速度和误检都会变差。

MVP 强烈建议先做地图 ROI。

优先级：

1. 先用固定百分比 ROI
2. 如果固定 ROI 不稳定，再做一次性手工标定 ROI
3. 只有在界面布局频繁变化时，才考虑再上自动地图区域识别

ROI 做好以后，AI 成本会明显下降。

## 13. 推荐实施顺序

第一阶段：数据

1. 做 300 到 500 张截图采样
2. 用 YOLO 检测框标注 tile 中心框
3. 固定一份测试集

第二阶段：模型

1. 训练单类 YOLOv8n
2. 导出 ONNX
3. 在离线脚本里测速度和召回

第三阶段：接入

1. 新增 ai_tile_detector 模块
2. 执行器增加 ai_tile 分支
3. 复用现有 recognition_to_logic_coord

第四阶段：补样

1. 收集误检和漏检截图
2. 每轮补 50 到 100 张困难样本
3. 迭代 2 到 3 轮

## 14. 失败边界

下面这些情况，AI 也不会自动解决：

- 地块中心本身没有稳定视觉定义
- 大量 UI 遮挡把中心完全盖住
- 同一地块在不同状态下外观差异过大且训练集没覆盖
- 推理仍然在整窗上跑，ROI 过大导致速度过慢

所以 AI 不是魔法，它的前提是：

- 目标定义清晰
- 数据覆盖到位
- ROI 先收窄

## 15. 一句话版本

你的最小可行 AI 方案就是：

- 用 300 到 500 张地图截图做单类 tile 检测标注
- 训练一个 YOLOv8n 单类检测模型
- 导出 ONNX 在本地 CPU 推理
- 只取检测框中心点
- 直接接到现有 recognition_to_logic_coord 链路

这是当前项目里训练成本、接入成本和收益最平衡的一条路。