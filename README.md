# Quest_Tele

基于 Meta Quest 3 的 VR 双手位姿采集系统，支持**手柄模式**和**人手追踪模式**，通过局域网 HTTP 实时发送至工作站，用于机器人遥操作。

---

## 快速开始

| 步骤 | 文档 |
|------|------|
| 编译 APK / 从源码构建 | [Docs/Build.md](./Docs/Build.md) |
| APP 使用与坐标校准 | [Docs/User_Guide.md](./Docs/User_Guide.md) |

---

## 追踪模式

APP 自动识别当前模式，无需手动切换：

| 模式 | 触发条件 | 可用数据 |
|------|----------|----------|
| **手柄模式** | 持握 Touch 控制器 | 位姿、按键、扳机、摇杆 |
| **人手追踪模式** | 放下控制器，伸出双手 | 位姿、24 关节坐标 |

---

## Python 实时监控

依赖：`pip install matplotlib numpy`

### 手柄监控

```bash
python3 quest_monitor.py
```

![手柄监控](./Image/monitor.png)

- 左右手腕 3D 运动轨迹 & 姿态飞机图
- 位置 / 欧拉角 / 四元数 / 摇杆 XY / 食指扳机数值
- 摇杆实时可视化、按键状态指示灯
- 人手模式下自动冻结，显示 `[HND]` 提示

### 人手骨架监控

```bash
python3 quest_hand_monitor.py
```

![人手监控](./Image/hand_monitor.png)

- 左右手 24 关节 3D 骨架（彩色按指归属）
- 左右手腕空间轨迹（3D 渐变）
- 腕部实时 XYZ 坐标
- 手柄模式下自动冻结，显示 `[CTL]` 提示

> 关闭窗口或按 `Ctrl+C` 退出监控。

---

## Python 数据接收

### 快速测试

```bash
python3 quest_receiver.py
```

### 集成到自己的程序

```python
from quest_receiver import QuestReceiver

receiver = QuestReceiver(port=8082)
receiver.start()

while True:
    data = receiver.get_latest()
    if data is None:
        continue

    is_hand = data['rightHand']['isHandTracking']  # True=人手, False=手柄

    if not is_hand:
        # 手柄模式
        r_pos   = data['rightHand']['wristPos']       # [x, y, z] 米
        r_quat  = data['rightHand']['wristQuat']      # [w, x, y, z]
        r_trig  = data['rightHand']['triggerState']   # float [0, 1]
        r_stick = data['rightHand']['thumbstick']     # [x, y] [-1, 1]
        r_btns  = data['rightHand']['buttonState']    # bool[5]
    else:
        # 人手追踪模式
        r_pos    = data['rightHand']['wristPos']      # [x, y, z] 米
        r_quat   = data['rightHand']['wristQuat']     # [w, x, y, z]
        r_joints = data['rightHand']['jointPos']      # float[72] → reshape(24,3)

    head_pos  = data['headPos']    # [x, y, z]
    head_quat = data['headQuat']   # [w, x, y, z]
    ts        = data['timestamp']  # 运行时间（秒）
```

---

## 数据格式

APP 以 **HTTP POST / JSON** 发送至 `http://{IP}:{Port}/unity`，默认 60 Hz。

### 顶层结构

```json
{
  "timestamp": 42.35,
  "rightHand": { ... },
  "leftHand":  { ... },
  "headPos":   [x, y, z],
  "headQuat":  [w, x, y, z]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | `float` | APP 启动后的运行时间，单位秒 |
| `rightHand` | `HandMessage` | 右手数据，见下节 |
| `leftHand` | `HandMessage` | 左手数据，见下节 |
| `headPos` | `float[3]` | 头显世界坐标 `[x, y, z]`，单位米，经校准变换 |
| `headQuat` | `float[4]` | 头显朝向四元数 `[w, x, y, z]`，经校准变换 |

---

### HandMessage 字段

#### 通用字段（两种模式均有效）

| 字段 | 类型 | 说明 |
|------|------|------|
| `wristPos` | `float[3]` | 手腕世界坐标 `[x, y, z]`，单位米，经校准变换 |
| `wristQuat` | `float[4]` | 手腕朝向四元数 `[w, x, y, z]`，经校准变换 |
| `isHandTracking` | `bool` | 当前追踪模式：`true`=人手追踪，`false`=手柄模式 |

#### 手柄模式专用字段（`isHandTracking == false`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `triggerState` | `float` | 食指扳机模拟量，范围 `[0.0, 1.0]`，0=未按，1=完全按下 |
| `thumbstick` | `float[2]` | 摇杆 XY 模拟量 `[x, y]`，范围 `[-1.0, 1.0]`，`[0,0]`=归中 |
| `buttonState` | `bool[5]` | 按键状态数组，见 buttonState 索引表 |

人手追踪模式下以上三个字段值均为零/空，不应使用。

#### 人手追踪模式专用字段（`isHandTracking == true`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `jointPos` | `float[72]` | 24 个关节的世界坐标，展开排列：`[x0,y0,z0, x1,y1,z1, ...]`，经校准变换。使用时 reshape 为 `(24, 3)` |

手柄模式下 `jointPos` 为空数组 `[]`，不应使用。

---

### buttonState 索引

| 索引 | 左手按键 | 右手按键 | 说明 |
|------|----------|----------|------|
| `[0]` | Y | B | 上方圆形按键 |
| `[1]` | X | A | 下方圆形按键 |
| `[2]` | 左摇杆按下 | 右摇杆按下 | 摇杆垂直按下触发 |
| `[3]` | 食指扳机（数字） | 食指扳机（数字） | 食指扳机，按下为 `true` |
| `[4]` | Grip 侧边扳机 | Grip 侧边扳机 | 中指扣住的侧边扳机 |

> `triggerState` 是食指扳机的模拟量（连续值），`buttonState[3]` 是其数字量（布尔值），两者对应同一物理按键。

---

### jointPos 关节索引（OVRSkeleton BoneId）

共 24 个关节，按以下顺序排列，索引 `i` 对应 `jointPos[i*3 : i*3+3]`：

| 索引 | 关节名 | 位置描述 |
|------|--------|----------|
| 0 | WristRoot | 手腕根部 |
| 1 | ForearmStub | 前臂末端 |
| 2 | Thumb0 | 拇指掌骨 |
| 3 | Thumb1 | 拇指近节 |
| 4 | Thumb2 | 拇指中节 |
| 5 | Thumb3 | 拇指远节 |
| 6 | Index1 | 食指近节 |
| 7 | Index2 | 食指中节 |
| 8 | Index3 | 食指远节 |
| 9 | Middle1 | 中指近节 |
| 10 | Middle2 | 中指中节 |
| 11 | Middle3 | 中指远节 |
| 12 | Ring1 | 无名指近节 |
| 13 | Ring2 | 无名指中节 |
| 14 | Ring3 | 无名指远节 |
| 15 | Pinky0 | 小指掌骨 |
| 16 | Pinky1 | 小指近节 |
| 17 | Pinky2 | 小指中节 |
| 18 | Pinky3 | 小指远节 |
| 19 | ThumbTip | 拇指指尖 |
| 20 | IndexTip | 食指指尖 |
| 21 | MiddleTip | 中指指尖 |
| 22 | RingTip | 无名指指尖 |
| 23 | PinkyTip | 小指指尖 |

**读取示例：**

```python
import numpy as np

joints = np.array(data['rightHand']['jointPos']).reshape(24, 3)

wrist      = joints[0]   # WristRoot  [x, y, z]
index_tip  = joints[20]  # IndexTip   [x, y, z]
thumb_tip  = joints[19]  # ThumbTip   [x, y, z]

# 计算捏合距离（拇指指尖 ↔ 食指指尖）
pinch_dist = np.linalg.norm(thumb_tip - index_tip)
```

---

### 坐标系说明

- **坐标系**：Unity 世界坐标系（Y 轴朝上，右手系），经用户校准变换后输出
- **单位**：位置为米（m），旋转为四元数
- **四元数格式**：统一为 `[w, x, y, z]`（注意：Unity 原生格式为 `[x,y,z,w]`，本系统已转换）
