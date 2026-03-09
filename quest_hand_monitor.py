#!/usr/bin/env python3
"""
Quest 人手骨架实时监控窗口
- 显示左右手 24 关节 3D 骨架（OVRSkeleton 关键点）
- 手柄模式时显示占位提示
- 依赖：matplotlib, numpy（tkinter 内置）
- 启动：python3 quest_hand_monitor.py
"""

import collections
import math
import signal
import sys
import time
import tkinter as tk

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
import numpy as np

from quest_receiver import QuestReceiver

# ─── 常量 ────────────────────────────────────────────────────────────────────
PORT       = 8082
REFRESH_MS = 33     # 数据/骨架更新（~30Hz，tkinter Canvas，无阻塞）
PLOT_MS    = 200    # 轨迹 matplotlib 渲染间隔（~5Hz，只剩2个轴，快很多）
HAND_RANGE = 0.22   # 手掌显示半径（m），覆盖腕到指尖约20cm
XYZ_LEN    = 100    # 腕轨迹保留帧数

# ─── 骨架 Canvas 投影参数 ─────────────────────────────────────────────────────
SKEL_W, SKEL_H = 280, 250   # Canvas 尺寸（像素）
SKEL_SCALE     = 850         # 像素/米
_ELEV = math.radians(22)     # 俯视角
_AZIM = math.radians(38)     # 水平旋角
_CE, _SE = math.cos(_ELEV), math.sin(_ELEV)
_CA, _SA = math.cos(_AZIM), math.sin(_AZIM)


def _project(pt3d, cx, cy):
    """3D 关节坐标 → Canvas 像素坐标（正交投影）"""
    x, y, z = float(pt3d[0]), float(pt3d[1]), float(pt3d[2])
    xr =  x * _CA + z * _SA          # 绕 Y 轴旋转
    zr = -x * _SA + z * _CA
    yr =  y * _CE - zr * _SE          # 绕 X 轴旋转（仰角）
    return int(cx + xr * SKEL_SCALE), int(cy - yr * SKEL_SCALE)

# ─── OVRSkeleton 关节索引（BoneId 顺序）────────────────────────────────────
# 0  WristRoot    1  ForearmStub
# 2  Thumb0       3  Thumb1      4  Thumb2      5  Thumb3     19 ThumbTip
# 6  Index1       7  Index2      8  Index3                    20 IndexTip
# 9  Middle1     10  Middle2    11  Middle3                   21 MiddleTip
# 12 Ring1       13  Ring2      14  Ring3                     22 RingTip
# 15 Pinky0      16  Pinky1     17  Pinky2     18  Pinky3     23 PinkyTip

# (起点, 终点, 颜色)
HAND_BONES = [
    # 拇指
    (0, 2,  '#ff5252'), (2, 3,  '#ff5252'), (3, 4,  '#ff5252'),
    (4, 5,  '#ff5252'), (5, 19, '#ff5252'),
    # 食指
    (0, 6,  '#ff9800'), (6, 7,  '#ff9800'), (7, 8,  '#ff9800'), (8, 20, '#ff9800'),
    # 中指
    (0, 9,  '#ffeb3b'), (9, 10, '#ffeb3b'), (10, 11,'#ffeb3b'), (11, 21,'#ffeb3b'),
    # 无名指
    (0, 12, '#4caf50'), (12, 13,'#4caf50'), (13, 14,'#4caf50'), (14, 22,'#4caf50'),
    # 小指
    (0, 15, '#2196f3'), (15, 16,'#2196f3'), (16, 17,'#2196f3'),
    (17, 18,'#2196f3'), (18, 23,'#2196f3'),
    # 掌横连接
    (6, 9,  '#888888'), (9, 12, '#888888'), (12, 15,'#888888'),
]

# 关节点颜色（按指归属）
_JOINT_COLORS = (
    ['#ffffff'] * 2 +          # 0-1  腕/前臂
    ['#ff5252'] * 5 +          # 2-5,19  拇指
    ['#ff9800'] * 4 +          # 6-8,20  食指
    ['#ffeb3b'] * 4 +          # 9-11,21 中指
    ['#4caf50'] * 4 +          # 12-14,22 无名
    ['#2196f3'] * 5            # 15-18,23 小指
)
# 重新排到索引顺序 0-23
_COLOR_BY_IDX = ['#aaaaaa'] * 24
for _i, _c in zip(
    list(range(0, 2)) +
    list(range(2, 6)) + [19] +
    list(range(6, 9)) + [20] +
    list(range(9, 12)) + [21] +
    list(range(12, 15)) + [22] +
    list(range(15, 19)) + [23],
    _JOINT_COLORS
):
    _COLOR_BY_IDX[_i] = _c

COLOR_BG  = '#1e1e1e'
COLOR_FG  = '#e0e0e0'
COLOR_ACC = '#00bcd4'


# ─── 工具 ─────────────────────────────────────────────────────────────────────
def _style_ax(ax, title=''):
    ax.set_facecolor('#1a1a2e')
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor('#333')
    ax.tick_params(colors='#555', labelsize=5)
    ax.set_xlabel('X', color='#666', fontsize=6, labelpad=0)
    ax.set_ylabel('Y', color='#666', fontsize=6, labelpad=0)
    ax.set_zlabel('Z', color='#666', fontsize=6, labelpad=0)
    if title:
        ax.set_title(title, color='#aaa', fontsize=9, pad=3)


def parse_joints(joint_list):
    """joint_list: 72个float → (24, 3) ndarray"""
    if not joint_list or len(joint_list) < 72:
        return None
    return np.array(joint_list, dtype=float).reshape(24, 3)


# ─── 单手骨架面板（tkinter Canvas，不用 matplotlib，30Hz 无延迟）────────────
class HandSkeletonPanel:
    def __init__(self, parent_frame, side):
        self.side = side

        # 模式提示
        self._mode_lbl = tk.Label(parent_frame, text='', bg=COLOR_BG,
                                   font=('Consolas', 10, 'bold'), anchor='center')
        self._mode_lbl.pack(fill=tk.X, padx=6, pady=(4, 0))

        # 骨架 Canvas（原生 2D 投影，无 matplotlib 开销）
        self._cv = tk.Canvas(parent_frame, width=SKEL_W, height=SKEL_H,
                             bg='#1a1a2e', highlightthickness=0)
        self._cv.pack(pady=2)
        self._cx = SKEL_W // 2
        self._cy = SKEL_H // 2 + 15

        # 腕部坐标
        f = tk.Frame(parent_frame, bg=COLOR_BG)
        f.pack(fill=tk.X, padx=6)
        tk.Label(f, text='腕部 (m)', bg=COLOR_BG, fg='#888',
                 font=('Consolas', 9), width=10, anchor='w').pack(side=tk.LEFT)
        self._lbl = {}
        for k in ['x', 'y', 'z']:
            lb = tk.Label(f, text='---', bg=COLOR_BG, fg=COLOR_FG,
                          font=('Consolas', 10), width=8, anchor='e')
            lb.pack(side=tk.LEFT, padx=2)
            self._lbl[k] = lb

    def update(self, joints):
        """30Hz 直接调用，tkinter Canvas 重绘 <3ms"""
        cv = self._cv
        cv.delete('all')
        cx, cy = self._cx, self._cy

        if joints is None:
            cv.create_text(cx, cy, text='[CTL]\nNo Joint Data',
                           fill='#555', font=('Consolas', 11), justify='center')
            self._mode_lbl.config(text='[CTL] 手柄模式', fg='#4caf50', bg=COLOR_BG)
            for k in ['x', 'y', 'z']:
                self._lbl[k].config(text='---')
            return

        origin = joints[0]
        rel    = joints - origin

        # 骨骼连线
        for i, j, col in HAND_BONES:
            if i < len(rel) and j < len(rel):
                p1 = _project(rel[i], cx, cy)
                p2 = _project(rel[j], cx, cy)
                cv.create_line(p1[0], p1[1], p2[0], p2[1], fill=col, width=2)

        # 关节点
        tip_set = {19, 20, 21, 22, 23}
        n = min(24, len(rel))
        for i in range(n):
            px, py = _project(rel[i], cx, cy)
            r   = 5 if i in tip_set else 3
            col = _COLOR_BY_IDX[i]
            cv.create_oval(px-r, py-r, px+r, py+r, fill=col, outline='')

        # 腕部白色高亮
        px, py = _project(rel[0], cx, cy)
        cv.create_oval(px-5, py-5, px+5, py+5, fill='white', outline='')

        self._mode_lbl.config(text='[HND] 人手模式', fg='#FF9800', bg='#3a2a00')
        self._lbl['x'].config(text=f'{origin[0]:+.3f}')
        self._lbl['y'].config(text=f'{origin[1]:+.3f}')
        self._lbl['z'].config(text=f'{origin[2]:+.3f}')


# ─── 手腕 3D 轨迹面板（嵌入主图）─────────────────────────────────────────────
class WristTrajPanel:
    """预创建轨迹 Line3D，update() 原地更新，无 ax.cla()"""

    def __init__(self, ax, info_frame, side):
        self.ax    = ax
        self.side  = side
        self._traj = collections.deque(maxlen=XYZ_LEN)

        # tkinter：坐标数值标签（30Hz 更新）
        f = tk.Frame(info_frame, bg=COLOR_BG)
        f.pack(fill=tk.X, padx=6, pady=(0, 2))
        tk.Label(f, text='腕轨迹(m)', bg=COLOR_BG, fg='#888',
                 font=('Consolas', 9), width=10, anchor='w').pack(side=tk.LEFT)
        self._lbl = {}
        for k, color in [('x', '#f44336'), ('y', '#4CAF50'), ('z', '#2196F3')]:
            tk.Label(f, text=k, bg=COLOR_BG, fg=color,
                     font=('Consolas', 9, 'bold')).pack(side=tk.LEFT)
            lb = tk.Label(f, text='---', bg=COLOR_BG, fg=COLOR_FG,
                          font=('Consolas', 10), width=7, anchor='e')
            lb.pack(side=tk.LEFT, padx=(0, 4))
            self._lbl[k] = lb

        # 一次性初始化轴
        _style_ax(ax, f'{side} Wrist Traj')
        ax.set_xlim(-0.3, 0.3); ax.set_ylim(-0.3, 0.3); ax.set_zlim(-0.3, 0.3)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])

        # 预创建两段轨迹线 + 当前位置点
        self._ln_old, = ax.plot([], [], [], color='#3a6ea5', linewidth=1.0, alpha=0.4)
        self._ln_new, = ax.plot([], [], [], color='#64b5f6', linewidth=1.6, alpha=0.9)
        self._scat,    = ax.plot([], [], [], 'o', color='white', markersize=5, zorder=6)

    def update_labels(self, pos):
        """30Hz 调用：追加轨迹点 + 更新 tkinter 坐标显示"""
        self._traj.append(np.array(pos, dtype=float))
        self._lbl['x'].config(text=f'{pos[0]:+.3f}')
        self._lbl['y'].config(text=f'{pos[1]:+.3f}')
        self._lbl['z'].config(text=f'{pos[2]:+.3f}')

    def update(self):
        """2Hz 调用：原地更新 matplotlib 轨迹线，无 ax.cla()"""
        if len(self._traj) < 2:
            return
        traj = np.array(self._traj)
        cur  = traj[-1]
        R = 0.3
        self.ax.set_xlim(cur[0]-R, cur[0]+R)
        self.ax.set_ylim(cur[1]-R, cur[1]+R)
        self.ax.set_zlim(cur[2]-R, cur[2]+R)

        n   = len(traj)
        mid = n // 2
        if mid > 1:
            self._ln_old.set_data(traj[:mid, 0], traj[:mid, 1])
            self._ln_old.set_3d_properties(traj[:mid, 2])
        else:
            self._ln_old.set_data([], []); self._ln_old.set_3d_properties([])

        self._ln_new.set_data(traj[mid:, 0], traj[mid:, 1])
        self._ln_new.set_3d_properties(traj[mid:, 2])
        self._scat.set_data([cur[0]], [cur[1]])
        self._scat.set_3d_properties([cur[2]])


# ─── 主窗口 ───────────────────────────────────────────────────────────────────
class QuestHandMonitor:
    def __init__(self, root):
        self.root = root
        root.title('Quest 人手骨架监控')
        root.configure(bg=COLOR_BG)
        root.geometry('960x680')

        self.receiver  = QuestReceiver(port=PORT)
        self.receiver.start()
        self._prev_ts  = None
        self._plot_data = None

        self._build_ui()
        self._schedule_update()
        self._schedule_plot()

    def _build_ui(self):
        # 状态栏
        self._status_lbl = tk.Label(
            self.root, text='● 未连接', bg=COLOR_BG, fg='#f44336',
            font=('Consolas', 11), anchor='w', padx=10)
        self._status_lbl.pack(fill=tk.X)

        # 上半区：左右骨架 Canvas（tkinter 原生，30Hz 无阻塞）
        top = tk.Frame(self.root, bg=COLOR_BG)
        top.pack(fill=tk.X)

        lf = tk.Frame(top, bg=COLOR_BG)
        rf = tk.Frame(top, bg=COLOR_BG)
        lf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        rf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        for f, t in [(lf, '左手'), (rf, '右手')]:
            tk.Label(f, text=t, bg=COLOR_BG, fg=COLOR_ACC,
                     font=('Consolas', 10, 'bold')).pack(anchor='w')

        self.panel_l = HandSkeletonPanel(lf, 'L')
        self.panel_r = HandSkeletonPanel(rf, 'R')

        # 下半区：腕部轨迹 matplotlib（2个3D轴，5Hz）
        self.fig = plt.Figure(figsize=(10, 3.2), facecolor='#1a1a2e')
        self.fig.subplots_adjust(left=0.02, right=0.98,
                                  top=0.93, bottom=0.05,
                                  wspace=0.05)
        self.ax_lt = self.fig.add_subplot(1, 2, 1, projection='3d')
        self.ax_rt = self.fig.add_subplot(1, 2, 2, projection='3d')

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.X, padx=4)

        # 轨迹面板的 tkinter 标签行
        bottom = tk.Frame(self.root, bg=COLOR_BG)
        bottom.pack(fill=tk.X)
        blf = tk.Frame(bottom, bg=COLOR_BG)
        brf = tk.Frame(bottom, bg=COLOR_BG)
        blf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        brf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.traj_l = WristTrajPanel(self.ax_lt, blf, 'L')
        self.traj_r = WristTrajPanel(self.ax_rt, brf, 'R')

    def _schedule_update(self):
        self.root.after(REFRESH_MS, self._schedule_update)
        self._update()

    def _schedule_plot(self):
        self.root.after(PLOT_MS, self._schedule_plot)
        self._render_plot()

    def _update(self):
        """30Hz：骨架 Canvas 直接渲染（<3ms）+ 缓存轨迹数据"""
        data = self.receiver.get_latest()
        hz   = self.receiver.get_hz()
        ip   = self.receiver.get_client_ip()

        if data is None:
            self._status_lbl.config(text='● 未连接', fg='#f44336')
            return

        ts = data.get('timestamp', 0)
        self._status_lbl.config(
            text=f'● 已连接  {ip or ""}    {hz:.1f} Hz    t={ts:.2f}s',
            fg='#4CAF50')

        if self._prev_ts is not None and abs(ts - self._prev_ts) < 1e-4:
            return
        self._prev_ts = ts

        lh = data.get('rightHand', {})
        rh = data.get('leftHand',  {})

        l_is_hand = len(lh.get('jointPos') or []) == 72
        r_is_hand = len(rh.get('jointPos') or []) == 72

        l_joints = parse_joints(lh.get('jointPos')) if l_is_hand else None
        r_joints = parse_joints(rh.get('jointPos')) if r_is_hand else None

        # 骨架：tkinter Canvas，30Hz，无阻塞
        self.panel_l.update(l_joints)
        self.panel_r.update(r_joints)

        # 轨迹坐标标签 + 缓存腕部位置（供轨迹渲染循环用）
        if l_joints is not None:
            self.traj_l.update_labels(lh.get('wristPos', [0.0, 0.0, 0.0]))
        if r_joints is not None:
            self.traj_r.update_labels(rh.get('wristPos', [0.0, 0.0, 0.0]))

        self._plot_data = (lh, rh)

    def _render_plot(self):
        """5Hz：只渲染 2 个轨迹轴，matplotlib 负担大幅降低"""
        if self._plot_data is None:
            return
        lh, rh = self._plot_data

        l_is_hand = len(lh.get('jointPos') or []) == 72
        r_is_hand = len(rh.get('jointPos') or []) == 72

        if l_is_hand:
            self.traj_l.update()
        if r_is_hand:
            self.traj_r.update()

        self.canvas.draw_idle()


# ─── 入口 ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    app = QuestHandMonitor(root)

    def _quit(*_):
        app.receiver.stop()
        root.destroy()
        sys.exit(0)

    signal.signal(signal.SIGINT, _quit)
    root.protocol('WM_DELETE_WINDOW', _quit)
    # 让 Ctrl+C 能打断 mainloop
    root.after(200, lambda: root.after(200, lambda: None))

    root.mainloop()
