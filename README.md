# Quest_Tele

基于 Meta Quest 3 的 VR 手柄 6DOF 位姿采集与遥操作系统。APP 实时采集双手手柄的位置、姿态和按键状态，通过局域网 HTTP 发送至工作站，供机器人遥操作使用。

---

## 目录

1. [硬件与环境要求](#1-硬件与环境要求)
2. [第一步：编译 APK](#第一步编译-apk)
3. [第二步：开启开发者模式并通过 ADB 安装](#第二步开启开发者模式并通过-adb-安装)
4. [第三步：配置与使用](#第三步配置与使用)
5. [Python 接收数据](#python-接收数据)
6. [数据格式说明](#数据格式说明)

---

## 1. 硬件与环境要求

### 硬件
- Meta Quest 3（已验证）
- 工作站（Linux / Windows / macOS 均可）
- USB-C 数据线（编译时连接 Quest 使用）
- 路由器（Quest 与工作站需在同一局域网）

### 软件
- [Unity Hub](https://unity.com/download)
- Unity Editor **2022.3.x LTS**（安装时需勾选 Android Build Support）
- [Android SDK & ADB](https://developer.android.com/tools/releases/platform-tools)（或使用 Unity 自带的）
- Python 3.8+（工作站接收数据用）

---

## 第一步：编译 APK

### 1.1 安装 Unity

1. 下载并安装 [Unity Hub](https://unity.com/download)

2. 在 Unity Hub 中安装 **Unity 2022.3.x LTS**，安装时必须勾选以下模块：
   - **Android Build Support**
   - **Android SDK & NDK Tools**
   - **OpenJDK**

   ![android build support](./Image/android.png)

### 1.2 打开项目

1. 克隆本仓库：
   ```bash
   git clone git@github.com:Greyman-Seu/Quest_Tele.git
   ```

2. 打开 Unity Hub，点击 **Add**，选择克隆下来的项目文件夹，等待项目加载完成。

   ![add project](./Image/add_project.png)

3. 在 **Project** 窗口中找到并双击打开场景：`Assets/Scenes/Teleoperation`

   ![scene](./Image/scene.png)

### 1.3 修改默认参数（可选）

在 **Hierarchy** 窗口中点击 `Main` 对象，在右侧 **Inspector** 中找到 `VRController` 组件：

![main object](./Image/main.png)
![script settings](./Image/script.png)

可修改的参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `IP` | 工作站的局域网 IP | `192.168.2.187` |
| `Port` | 工作站监听端口 | `8082` |
| `Hz` | 数据发送频率 | `60` |

> 提示：IP 也可以在 APP 运行时通过界面修改，不一定需要在这里改。

### 1.4 构建 APK

1. 点击菜单栏 `File` → `Build Settings`

2. 按下图配置：
   - Platform 选择 **Android**
   - 点击 **Switch Platform**
   - Texture Compression 选择 **ASTC**

   ![build settings](./Image/build.png)

3. 用 USB-C 线将 Quest 3 连接到电脑（需要先完成第二步的开发者模式设置）

4. 在 `Run Device` 下拉框中选择你的 Quest 3 设备

5. 点击 **Build And Run**，等待编译完成后 APK 会自动安装并启动

> 若只需要 APK 文件（后续手动安装），点击 **Build** 即可生成 `.apk` 文件。

---

## 第二步：开启开发者模式并通过 ADB 安装

Quest 3 默认不允许安装第三方 APK，需要先开启开发者模式。

### 2.1 注册 Meta 开发者账号

1. 访问 [Meta 开发者平台](https://developers.meta.com/) 并登录
2. 点击右上角头像 → **My Apps** → **Create New App**，随便填写应用名称，创建完成即可（目的是激活开发者身份）

### 2.2 在 Quest 3 上开启开发者模式

**方法一：通过手机 Meta Horizon APP（推荐）**

1. 手机安装 **Meta Horizon** APP，用同一个账号登录
2. 打开 APP → 设备 → 选择你的 Quest 3
3. 进入 **开发者模式**，将其**打开**
4. 重启 Quest 3

**方法二：通过 Quest 设置**

1. 戴上 Quest，进入 **设置** → **系统** → **开发者**
2. 打开 **USB 调试**

### 2.3 安装 ADB

**Linux / macOS：**
```bash
# Ubuntu / Debian
sudo apt install android-tools-adb

# macOS (Homebrew)
brew install android-platform-tools
```

**Windows：**

下载 [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)，解压后将路径加入系统 PATH。

### 2.4 通过 ADB 安装 APK

1. 用 USB-C 线将 Quest 3 连接到电脑

2. 戴上头显，会弹出「**允许 USB 调试**」对话框，选择**始终允许**

3. 验证连接：
   ```bash
   adb devices
   ```
   输出类似：
   ```
   List of devices attached
   1WMHXXXXXXXXX    device
   ```

4. 安装 APK：
   ```bash
   adb install path/to/Quest_Tele.apk
   ```

5. 安装成功后，在 Quest 的应用列表中找到该 APP（分类选择**未知来源**）

### 2.5 常用 ADB 命令

```bash
# 查看已连接设备
adb devices

# 安装 APK
adb install app.apk

# 覆盖安装（更新版本时使用）
adb install -r app.apk

# 卸载
adb uninstall com.yourcompany.appname

# 查看 Quest 上的日志（调试用）
adb logcat -s Unity
```

---

## 第三步：配置与使用

### 3.1 网络配置

确保 Quest 3 与工作站连接到**同一个局域网**（同一路由器）。

查看工作站 IP：
```bash
# Linux
ip addr show | grep "inet "

# macOS
ifconfig | grep "inet "

# Windows
ipconfig
```

### 3.2 启动工作站接收程序

在工作站上运行 Python 接收服务器（监听端口 `8082`）：

```bash
cd Quest_Tele
python3 quest_receiver.py
```

### 3.3 启动 APP 并配置 IP

1. 在 Quest 应用列表（**未知来源**分类）中找到并启动 APP

2. 查看地面，设置并确认地面边界

3. 在 APP 界面中：
   - **第一行输入框**：输入工作站的局域网 IP（如 `192.3.8.171`）
   - 点击 **Refresh IP** 确认
   - **第二行**会显示当前生效的 IP

   > 端口默认为 `8082`，无需修改。

### 3.4 坐标系校准

首次使用时需要校准虚拟坐标系与机器人真实坐标系的对齐关系：

1. 同时按下**左手柄 X 键**和**右手柄 A 键**，屏幕中出现坐标轴
2. 按住**右手柄食指扳机**，转动手腕调整坐标系**旋转**
3. 按住**左手柄食指扳机**，移动手柄调整坐标系**原点位置**
4. 确保蓝色轴（Z 轴）带球的一端朝向后方
5. 再次同时按 **X + A** 退出校准模式

### 3.5 手柄按键说明

| 按键 | 左手 | 右手 |
|------|------|------|
| `buttonState[0]` | Y | B |
| `buttonState[1]` | X | A |
| `buttonState[2]` | 左摇杆按下 | 右摇杆按下 |
| `buttonState[3]` | 食指扳机（数字） | 食指扳机（数字） |
| `buttonState[4]` | 侧边 Grip 扳机 | 侧边 Grip 扳机 |
| `triggerState` | 食指扳机（模拟 0~1） | 食指扳机（模拟 0~1） |

### 3.6 退出 APP

长按右手柄 **Meta 键**退出。

---

## Python 接收数据

### 快速开始

```bash
python3 quest_receiver.py
```

### 在自己的程序中集成

```python
from quest_receiver import start_server, get_latest

# 启动接收服务器（后台线程，非阻塞）
start_server(port=8082)

while True:
    data = get_latest()
    if data:
        # 右手位姿
        r_pos  = data['rightHand']['wristPos']    # [x, y, z]，单位：米
        r_quat = data['rightHand']['wristQuat']   # [w, x, y, z]
        r_trig = data['rightHand']['triggerState'] # 食指扳机 [0, 1]
        r_grip = data['rightHand']['buttonState'][4]  # Grip 是否按下 bool

        # 左手位姿
        l_pos  = data['leftHand']['wristPos']
        l_quat = data['leftHand']['wristQuat']
        l_trig = data['leftHand']['triggerState']
        l_grip = data['leftHand']['buttonState'][4]
```

---

## 数据格式说明

APP 以 HTTP POST 方式将 JSON 数据发送至 `http://{工作站IP}:{端口}/unity`，频率 60Hz。

```json
{
  "timestamp": 123.45,
  "rightHand": {
    "wristPos":    [x, y, z],
    "wristQuat":   [w, x, y, z],
    "triggerState": 0.0,
    "buttonState": [false, false, false, false, false]
  },
  "leftHand": {
    "wristPos":    [x, y, z],
    "wristQuat":   [w, x, y, z],
    "triggerState": 0.0,
    "buttonState": [false, false, false, false, false]
  },
  "headPos":  [x, y, z],
  "headQuat": [w, x, y, z]
}
```

> 坐标系：Unity 世界坐标系，经用户校准变换后输出。四元数格式为 `[w, x, y, z]`。
