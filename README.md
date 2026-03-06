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

### HandMessage 字段

| 字段 | 类型 | 有效模式 | 说明 |
|------|------|----------|------|
| `wristPos` | `float[3]` | 两种 | 手腕世界坐标 `[x, y, z]`，米 |
| `wristQuat` | `float[4]` | 两种 | 手腕四元数 `[w, x, y, z]` |
| `isHandTracking` | `bool` | 两种 | `true`=人手，`false`=手柄 |
| `triggerState` | `float` | 手柄 | 食指扳机 `[0, 1]` |
| `thumbstick` | `float[2]` | 手柄 | 摇杆 XY `[-1, 1]` |
| `buttonState` | `bool[5]` | 手柄 | 见下表 |
| `jointPos` | `float[72]` | 人手 | 24 关节世界坐标，reshape 为 `(24,3)` |

### buttonState 索引

| 索引 | 左手 | 右手 |
|------|------|------|
| `[0]` | Y | B |
| `[1]` | X | A |
| `[2]` | 左摇杆按下 | 右摇杆按下 |
| `[3]` | 食指扳机（数字） | 食指扳机（数字） |
| `[4]` | Grip 侧边扳机 | Grip 侧边扳机 |

### jointPos 关节索引（OVRSkeleton BoneId）

| 索引 | 关节 | 索引 | 关节 | 索引 | 关节 |
|------|------|------|------|------|------|
| 0 | WristRoot | 8 | Index3 | 16 | Pinky1 |
| 1 | ForearmStub | 9 | Middle1 | 17 | Pinky2 |
| 2 | Thumb0 | 10 | Middle2 | 18 | Pinky3 |
| 3 | Thumb1 | 11 | Middle3 | 19 | ThumbTip |
| 4 | Thumb2 | 12 | Ring1 | 20 | IndexTip |
| 5 | Thumb3 | 13 | Ring2 | 21 | MiddleTip |
| 6 | Index1 | 14 | Ring3 | 22 | RingTip |
| 7 | Index2 | 15 | Pinky0 | 23 | PinkyTip |

> 坐标系：Unity 世界坐标系，经校准变换后输出。四元数格式统一为 `[w, x, y, z]`。
