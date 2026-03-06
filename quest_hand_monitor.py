#!/usr/bin/env python3
"""
Quest 人手骨架实时监控窗口
- 显示左右手 24 关节 3D 骨架（OVRSkeleton 关键点）
- 手柄模式时显示占位提示
- 依赖：matplotlib, numpy（tkinter 内置）
- 启动：python3 quest_hand_monitor.py
"""

import collections
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
REFRESH_MS = 33
PLOT_EVERY = 4      # 3D 每 4 帧渲染一次 ~7Hz，减轻 CPU 负担
HAND_RANGE = 0.22   # 手掌显示半径（m），覆盖腕到指尖约20cm
XYZ_LEN    = 100    # 腕轨迹保留帧数

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


# ─── 单手可视化面板 ────────────────────────────────────────────────────────────
class HandSkeletonPanel:
    def __init__(self, ax, info_frame, side):
        self.ax   = ax
        self.side = side

        # 模式提示
        self._mode_lbl = tk.Label(info_frame, text='', bg=COLOR_BG,
                                   font=('Consolas', 10, 'bold'), anchor='center')
        self._mode_lbl.pack(fill=tk.X, padx=6, pady=(4, 0))

        # 腕部坐标
        f = tk.Frame(info_frame, bg=COLOR_BG)
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
        """joints: (24,3) ndarray 或 None（手柄模式）"""
        ax = self.ax
        ax.cla()
        _style_ax(ax, f'{self.side} Hand')

        if joints is None:
            # 手柄模式：只显示文字占位
            ax.text2D(0.5, 0.5, '[CTL] Controller\nNo Joint Data',
                      transform=ax.transAxes, ha='center', va='center',
                      color='#666', fontsize=10)
            ax.set_xlim(-0.1, 0.1)
            ax.set_ylim(-0.1, 0.1)
            ax.set_zlim(-0.1, 0.1)
            self._mode_lbl.config(text='[CTL] 手柄模式', fg='#4caf50', bg=COLOR_BG)
            for k in ['x', 'y', 'z']:
                self._lbl[k].config(text='---')
            return

        # 以腕部为原点，相对坐标 → 轴刻度稳定
        origin = joints[0]
        rel = joints - origin
        R = HAND_RANGE

        ax.set_xlim(-R, R)
        ax.set_ylim(-R, R)
        ax.set_zlim(-R, R)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_zticks([])

        # 骨骼连线
        for i, j, col in HAND_BONES:
            if i < len(rel) and j < len(rel):
                ax.plot([rel[i, 0], rel[j, 0]],
                        [rel[i, 1], rel[j, 1]],
                        [rel[i, 2], rel[j, 2]],
                        color=col, linewidth=1.5, alpha=0.85)

        # 关节点（批量绘制，按颜色分组）
        n = min(24, len(rel))
        tip_set = {19, 20, 21, 22, 23}
        for color in set(_COLOR_BY_IDX[:n]):
            idx_list = [i for i in range(n) if _COLOR_BY_IDX[i] == color and i not in tip_set]
            if idx_list:
                pts = rel[idx_list]
                ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2],
                           color=color, s=18, zorder=5, depthshade=False)
        # 指尖高亮（大点，批量）
        tip_idx = [i for i in [19, 20, 21, 22, 23] if i < len(rel)]
        if tip_idx:
            pts = rel[tip_idx]
            tip_colors = [_COLOR_BY_IDX[i] for i in tip_idx]
            ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2],
                       c=tip_colors, s=50, zorder=6, depthshade=False)
        # 腕部白点
        ax.scatter([0], [0], [0], color='white', s=50, zorder=7)

        # 更新模式标签和腕部坐标
        self._mode_lbl.config(text='[HND] 人手模式', fg='#FF9800', bg='#3a2a00')
        self._lbl['x'].config(text=f'{origin[0]:+.3f}')
        self._lbl['y'].config(text=f'{origin[1]:+.3f}')
        self._lbl['z'].config(text=f'{origin[2]:+.3f}')


# ─── 手腕 3D 轨迹面板（嵌入主图）─────────────────────────────────────────────
class WristTrajPanel:
    """手腕空间轨迹，绑定到主 Figure 的一个 3D 子图"""

    def __init__(self, ax, info_frame, side):
        self.ax   = ax
        self.side = side
        self._traj = collections.deque(maxlen=XYZ_LEN)

        # 坐标数值标签
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

    def update(self, pos):
        self._traj.append(np.array(pos, dtype=float))
        self._lbl['x'].config(text=f'{pos[0]:+.3f}')
        self._lbl['y'].config(text=f'{pos[1]:+.3f}')
        self._lbl['z'].config(text=f'{pos[2]:+.3f}')

        ax = self.ax
        ax.cla()
        _style_ax(ax, f'{self.side} Wrist Traj')

        if len(self._traj) < 2:
            return

        traj = np.array(self._traj)
        cur  = traj[-1]
        R = 0.3
        ax.set_xlim(cur[0]-R, cur[0]+R)
        ax.set_ylim(cur[1]-R, cur[1]+R)
        ax.set_zlim(cur[2]-R, cur[2]+R)

        # 单次 plot，旧段半透明，新段不透明
        n = len(traj)
        mid = n // 2
        if mid > 1:
            ax.plot(traj[:mid, 0], traj[:mid, 1], traj[:mid, 2],
                    color='#3a6ea5', linewidth=1.0, alpha=0.4)
        ax.plot(traj[mid:, 0], traj[mid:, 1], traj[mid:, 2],
                color='#64b5f6', linewidth=1.6, alpha=0.9)
        ax.scatter([cur[0]], [cur[1]], [cur[2]], color='white', s=50, zorder=6)


# ─── 主窗口 ───────────────────────────────────────────────────────────────────
class QuestHandMonitor:
    def __init__(self, root):
        self.root = root
        root.title('Quest 人手骨架监控')
        root.configure(bg=COLOR_BG)
        root.geometry('900x620')

        self.receiver  = QuestReceiver(port=PORT)
        self.receiver.start()
        self._prev_ts  = None
        self._frame    = 0

        self._build_ui()
        self._schedule_update()

    def _build_ui(self):
        # 状态栏
        self._status_lbl = tk.Label(
            self.root, text='● 未连接', bg=COLOR_BG, fg='#f44336',
            font=('Consolas', 11), anchor='w', padx=10)
        self._status_lbl.pack(fill=tk.X)

        # matplotlib 图：2行×2列
        # 行0: 左骨架 | 右骨架
        # 行1: 左腕轨迹 | 右腕轨迹
        self.fig = plt.Figure(figsize=(10, 7), facecolor='#1a1a2e')
        self.fig.subplots_adjust(left=0.02, right=0.98,
                                  top=0.96, bottom=0.02,
                                  wspace=0.05, hspace=0.15)
        self.ax_l  = self.fig.add_subplot(2, 2, 1, projection='3d')
        self.ax_r  = self.fig.add_subplot(2, 2, 2, projection='3d')
        self.ax_lt = self.fig.add_subplot(2, 2, 3, projection='3d')
        self.ax_rt = self.fig.add_subplot(2, 2, 4, projection='3d')

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4)

        # 底部信息栏（左右各一列）
        bottom = tk.Frame(self.root, bg=COLOR_BG)
        bottom.pack(fill=tk.X)

        lf = tk.Frame(bottom, bg=COLOR_BG)
        rf = tk.Frame(bottom, bg=COLOR_BG)
        lf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        rf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        for f, t in [(lf, '左手'), (rf, '右手')]:
            tk.Label(f, text=t, bg=COLOR_BG, fg=COLOR_ACC,
                     font=('Consolas', 10, 'bold')).pack(anchor='w')

        self.panel_l  = HandSkeletonPanel(self.ax_l,  lf, 'L')
        self.panel_r  = HandSkeletonPanel(self.ax_r,  rf, 'R')
        self.traj_l   = WristTrajPanel(self.ax_lt, lf, 'L')
        self.traj_r   = WristTrajPanel(self.ax_rt, rf, 'R')

    def _schedule_update(self):
        self._update()
        self.root.after(REFRESH_MS, self._schedule_update)

    def _update(self):
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

        if ts == self._prev_ts:
            return
        self._prev_ts = ts

        # leftHand/rightHand 对调（与 quest_monitor.py 保持一致）
        lh = data.get('rightHand', {})
        rh = data.get('leftHand',  {})

        # 用 jointPos 长度判断是否真正处于人手模式（null 时 or [] 兜底）
        l_is_hand = len(lh.get('jointPos') or []) == 72
        r_is_hand = len(rh.get('jointPos') or []) == 72

        # 手柄模式下不更新人手监控
        if not l_is_hand and not r_is_hand:
            self._frame += 1
            if self._frame % PLOT_EVERY == 0:
                self.panel_l.update(None)
                self.panel_r.update(None)
                self.canvas.draw_idle()
            return

        l_joints = parse_joints(lh.get('jointPos'))
        r_joints = parse_joints(rh.get('jointPos'))

        # 3D 降频渲染
        self._frame += 1
        if self._frame % PLOT_EVERY == 0:
            self.panel_l.update(l_joints)
            self.panel_r.update(r_joints)

            l_pos = lh.get('wristPos', [0.0, 0.0, 0.0])
            r_pos = rh.get('wristPos', [0.0, 0.0, 0.0])
            if l_joints is not None:
                self.traj_l.update(l_pos)
            if r_joints is not None:
                self.traj_r.update(r_pos)

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
