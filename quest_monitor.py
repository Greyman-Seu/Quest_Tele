#!/usr/bin/env python3
"""
Quest 手柄实时监控窗口
- 左右分栏，上行：轨迹 3D，下行：姿态飞机 3D，底部数值面板
- 依赖：matplotlib, numpy（tkinter 内置）
- 启动：python3 quest_monitor.py
"""

import collections
import math
import tkinter as tk

import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
import numpy as np

from quest_receiver import QuestReceiver

# ─── 常量 ────────────────────────────────────────────────────────────────────
PORT        = 8082
REFRESH_MS  = 33        # ~30 Hz（数值面板刷新率）
PLOT_EVERY  = 3         # 3D图每 N 帧渲染一次 → ~10 Hz
TRAJ_LEN    = 100       # 轨迹历史帧数
TRAJ_RANGE  = 0.5       # 轨迹图坐标轴半径（m）
PLANE_SCALE = 0.30      # 飞机示意缩放（姿态图单位为 1）

LEFT_BUTTONS  = ['Y', 'X', '◉ TS', '⊡ IT', '▣ HT']
RIGHT_BUTTONS = ['B', 'A', '◉ TS', '⊡ IT', '▣ HT']

COLOR_ON  = '#4CAF50'
COLOR_OFF = '#555555'
COLOR_BG  = '#1e1e1e'
COLOR_FG  = '#e0e0e0'
COLOR_ACC = '#00bcd4'


# ─── 数学工具 ─────────────────────────────────────────────────────────────────
def quat_to_rotmat(w, x, y, z):
    n = math.sqrt(w*w + x*x + y*y + z*z)
    if n < 1e-9:
        return np.eye(3)
    w, x, y, z = w/n, x/n, y/n, z/n
    return np.array([
        [1-2*(y*y+z*z),   2*(x*y-w*z),   2*(x*z+w*y)],
        [  2*(x*y+w*z), 1-2*(x*x+z*z),   2*(y*z-w*x)],
        [  2*(x*z-w*y),   2*(y*z+w*x), 1-2*(x*x+y*y)],
    ])


def quat_to_euler(w, x, y, z):
    """→ (roll, pitch, yaw) 度，ZYX"""
    n = math.sqrt(w*w + x*x + y*y + z*z)
    if n < 1e-9:
        return 0.0, 0.0, 0.0
    w, x, y, z = w/n, x/n, y/n, z/n
    roll  = math.degrees(math.atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y)))
    sinp  = 2*(w*y - z*x)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, sinp))))
    yaw   = math.degrees(math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z)))
    return roll, pitch, yaw


def _style_ax(ax, title=''):
    ax.set_facecolor('#1a1a2e')
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor('#333')
    ax.tick_params(colors='#666', labelsize=6)
    ax.set_xlabel('X', color='#888', fontsize=7, labelpad=1)
    ax.set_ylabel('Y', color='#888', fontsize=7, labelpad=1)
    ax.set_zlabel('Z', color='#888', fontsize=7, labelpad=1)
    if title:
        ax.set_title(title, color='#aaa', fontsize=8, pad=2)


# ─── 飞机线段（本地坐标，机鼻=+Z，翼展=±X，垂尾=+Y）────────────────────────
S = PLANE_SCALE
_PLANE_SEGS = [
    # (p_start, p_end, color, linewidth)
    (np.array([0,     0,    -0.7*S]), np.array([0,     0,    1.0*S]),  '#00e5ff', 2.5),  # 机身
    (np.array([-1.2*S, 0,  -0.1*S]), np.array([1.2*S,  0,  -0.1*S]),  '#ffb300', 2.0),  # 主翼
    (np.array([-0.5*S, 0,  -0.65*S]), np.array([0.5*S, 0,  -0.65*S]), '#ffb300', 1.5),  # 平尾
    (np.array([0,     0,   -0.7*S]), np.array([0,   0.5*S, -0.4*S]),   '#ff7043', 1.5),  # 垂尾
]


def draw_plane(ax, R):
    """在 ax 上以旋转矩阵 R 绘制飞机（居中于原点）"""
    for p1l, p2l, col, lw in _PLANE_SEGS:
        p1w = R @ p1l
        p2w = R @ p2l
        ax.plot([p1w[0], p2w[0]], [p1w[1], p2w[1]], [p1w[2], p2w[2]],
                color=col, linewidth=lw)
    # 机鼻方向小圆点
    nose = R @ np.array([0, 0, 1.0*S])
    ax.scatter([nose[0]], [nose[1]], [nose[2]], color='#00e5ff', s=20)


# ─── 手柄面板（一侧）────────────────────────────────────────────────────────
class HandPanel:
    def __init__(self, parent_frame, ax_traj, ax_orient, btn_labels):
        self.ax_traj   = ax_traj
        self.ax_orient = ax_orient
        self.traj      = collections.deque(maxlen=TRAJ_LEN)

        # ── 追踪模式提示条 ────────────────────────────────────────────────
        self._mode_lbl = tk.Label(
            parent_frame, text='', bg=COLOR_BG,
            font=('Consolas', 10, 'bold'), anchor='center')
        self._mode_lbl.pack(fill=tk.X, padx=6)

        # ── 数值面板 ──────────────────────────────────────────────────────
        info = tk.Frame(parent_frame, bg=COLOR_BG)
        info.pack(fill=tk.X, padx=6, pady=2)
        self._lbl = {}

        def row(label, keys):
            f = tk.Frame(info, bg=COLOR_BG)
            f.pack(fill=tk.X)
            tk.Label(f, text=label, bg=COLOR_BG, fg='#888',
                     font=('Consolas', 9), width=12, anchor='w').pack(side=tk.LEFT)
            for k in keys:
                lbl = tk.Label(f, text='---', bg=COLOR_BG, fg=COLOR_FG,
                               font=('Consolas', 10), width=8, anchor='e')
                lbl.pack(side=tk.LEFT, padx=2)
                self._lbl[k] = lbl

        row('Pos (m)',    ['px', 'py', 'pz'])
        row('Euler (°)',  ['roll', 'pitch', 'yaw'])
        row('Quat wxyz',  ['qw', 'qx', 'qy', 'qz'])

        # ── 扳机进度条 ────────────────────────────────────────────────────
        tf = tk.Frame(info, bg=COLOR_BG)
        tf.pack(fill=tk.X, pady=(4, 2))
        tk.Label(tf, text='食指扳机', bg=COLOR_BG, fg='#888',
                 font=('Consolas', 9), width=12, anchor='w').pack(side=tk.LEFT)
        self._trig_cv = tk.Canvas(tf, width=140, height=16,
                                  bg='#333', highlightthickness=0)
        self._trig_cv.pack(side=tk.LEFT, padx=4)
        self._trig_lbl = tk.Label(tf, text='0.00', bg=COLOR_BG,
                                  fg=COLOR_FG, font=('Consolas', 10))
        self._trig_lbl.pack(side=tk.LEFT, padx=4)

        # ── 按键指示器 ────────────────────────────────────────────────────
        bf = tk.Frame(info, bg=COLOR_BG)
        bf.pack(fill=tk.X, pady=(4, 6))
        self._btn_cvs = []
        for lbl in btn_labels:
            col = tk.Frame(bf, bg=COLOR_BG)
            col.pack(side=tk.LEFT, padx=4)
            c = tk.Canvas(col, width=38, height=24, bg=COLOR_BG,
                          highlightthickness=0)
            c.pack()
            c.create_rectangle(1, 1, 37, 23, fill=COLOR_OFF, outline='', tags='btn')
            tk.Label(col, text=lbl, bg=COLOR_BG, fg='#aaa',
                     font=('Consolas', 8)).pack()
            self._btn_cvs.append(c)

    # ── 轨迹图（相对坐标，轴刻度固定）────────────────────────────────────────
    def update_traj(self, pos):
        ax = self.ax_traj
        ax.cla()
        _style_ax(ax, '轨迹')
        ax.set_xlim(-TRAJ_RANGE, TRAJ_RANGE)
        ax.set_ylim(-TRAJ_RANGE, TRAJ_RANGE)
        ax.set_zlim(-TRAJ_RANGE, TRAJ_RANGE)

        self.traj.append(np.array(pos, dtype=float))
        offset = self.traj[-1]
        traj   = np.array(self.traj)
        rel    = traj - offset          # 当前位置 = 原点
        if len(rel) >= 2:
            ax.plot(rel[:, 0], rel[:, 1], rel[:, 2],
                    color='#4488cc', alpha=0.7, linewidth=1.2)
        ax.scatter([0], [0], [0], color='white', s=40, zorder=5)

    # ── 姿态图（飞机居中，不受位置影响）──────────────────────────────────────
    def update_orient(self, quat):
        ax = self.ax_orient
        ax.cla()
        _style_ax(ax, '姿态')
        lim = PLANE_SCALE * 1.4
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_zlim(-lim, lim)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_zticks([])

        # 世界系参考网格线（淡灰虚线）
        g = lim * 0.9
        for v in [-g*0.5, 0, g*0.5]:
            ax.plot([-g, g], [v, v], [0, 0], color='#444', linewidth=0.4, linestyle='--')
            ax.plot([v, v], [-g, g], [0, 0], color='#444', linewidth=0.4, linestyle='--')

        w, x, y, z = quat
        R = quat_to_rotmat(w, x, y, z)
        draw_plane(ax, R)

        # 机鼻方向标注
        ax.text(0, 0, lim * 0.95, '↑ +Z 前向', color='#00e5ff',
                fontsize=6, ha='center')

    # ── 追踪模式提示 ──────────────────────────────────────────────────────────
    def update_mode(self, is_hand):
        if not is_hand:
            self._mode_lbl.config(text='[CTL] 手柄模式', fg='#4CAF50', bg=COLOR_BG)
        else:
            self._mode_lbl.config(text='[HND] 人手模式  ! 无按键/扳机', fg='#FF9800', bg='#3a2a00')

    # ── 数值面板 ──────────────────────────────────────────────────────────────
    def update_info(self, pos, quat, trig, btns):
        px, py, pz = pos
        w, x, y, z = quat
        roll, pitch, yaw = quat_to_euler(w, x, y, z)

        self._lbl['px'].config(text=f'{px:+.3f}')
        self._lbl['py'].config(text=f'{py:+.3f}')
        self._lbl['pz'].config(text=f'{pz:+.3f}')
        self._lbl['roll'].config(text=f'{roll:+.1f}°')
        self._lbl['pitch'].config(text=f'{pitch:+.1f}°')
        self._lbl['yaw'].config(text=f'{yaw:+.1f}°')
        self._lbl['qw'].config(text=f'{w:+.3f}')
        self._lbl['qx'].config(text=f'{x:+.3f}')
        self._lbl['qy'].config(text=f'{y:+.3f}')
        self._lbl['qz'].config(text=f'{z:+.3f}')

        # 扳机
        self._trig_cv.delete('fill')
        fw = int(140 * max(0.0, min(1.0, trig)))
        if fw > 0:
            self._trig_cv.create_rectangle(0, 0, fw, 16,
                                           fill=COLOR_ACC, outline='', tags='fill')
        self._trig_lbl.config(text=f'{trig:.2f}')

        # 按键
        for i, c in enumerate(self._btn_cvs):
            on = (i < len(btns)) and bool(btns[i])
            c.itemconfig('btn', fill=COLOR_ON if on else COLOR_OFF)


# ─── 主窗口 ───────────────────────────────────────────────────────────────────
class QuestMonitor:
    def __init__(self, root):
        self.root = root
        root.title('Quest 手柄监控')
        root.configure(bg=COLOR_BG)
        root.geometry('1100x780')

        self.receiver = QuestReceiver(port=PORT)
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

        # ── matplotlib：2行×2列 3D子图 ────────────────────────────────────
        # 行0: 左轨迹 | 右轨迹
        # 行1: 左姿态 | 右姿态
        self.fig = plt.Figure(figsize=(11, 5.5), facecolor='#1a1a2e')
        self.fig.subplots_adjust(left=0.02, right=0.98,
                                  top=0.95, bottom=0.05,
                                  wspace=0.1, hspace=0.25)

        self.ax_lt = self.fig.add_subplot(2, 2, 1, projection='3d')  # 左轨迹
        self.ax_rt = self.fig.add_subplot(2, 2, 2, projection='3d')  # 右轨迹
        self.ax_lo = self.fig.add_subplot(2, 2, 3, projection='3d')  # 左姿态
        self.ax_ro = self.fig.add_subplot(2, 2, 4, projection='3d')  # 右姿态

        for ax, title in [(self.ax_lt, '左手轨迹'), (self.ax_rt, '右手轨迹'),
                          (self.ax_lo, '左手姿态'), (self.ax_ro, '右手姿态')]:
            _style_ax(ax, title)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.X, padx=4)

        # ── 底部左右数值面板 ──────────────────────────────────────────────
        bottom = tk.Frame(self.root, bg=COLOR_BG)
        bottom.pack(fill=tk.BOTH, expand=True)

        lf = tk.Frame(bottom, bg=COLOR_BG)
        rf = tk.Frame(bottom, bg=COLOR_BG)
        lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        rf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)

        for f, title in [(lf, '左手'), (rf, '右手')]:
            tk.Label(f, text=title, bg=COLOR_BG, fg=COLOR_ACC,
                     font=('Consolas', 11, 'bold')).pack(anchor='w', padx=6)

        self.left_panel  = HandPanel(lf, self.ax_lt, self.ax_lo, LEFT_BUTTONS)
        self.right_panel = HandPanel(rf, self.ax_rt, self.ax_ro, RIGHT_BUTTONS)

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

        # leftHand/rightHand 对调（修正左右互换）
        lh = data.get('rightHand', {})
        rh = data.get('leftHand',  {})

        def safe(hand, key, default):
            return hand.get(key, default)

        l_pos   = safe(lh, 'wristPos',     [0.0, 0.0, 0.0])
        l_quat  = safe(lh, 'wristQuat',    [1.0, 0.0, 0.0, 0.0])
        l_trig  = safe(lh, 'triggerState', 0.0)
        l_btn   = safe(lh, 'buttonState',  [False]*5)
        l_is_hand = safe(lh, 'isHandTracking', False)

        r_pos   = safe(rh, 'wristPos',     [0.0, 0.0, 0.0])
        r_quat  = safe(rh, 'wristQuat',    [1.0, 0.0, 0.0, 0.0])
        r_trig  = safe(rh, 'triggerState', 0.0)
        r_btn   = safe(rh, 'buttonState',  [False]*5)
        r_is_hand = safe(rh, 'isHandTracking', False)

        # 数值面板：每帧更新（30Hz，纯 tkinter Label，几乎无开销）
        self.left_panel.update_mode(l_is_hand)
        self.right_panel.update_mode(r_is_hand)
        self.left_panel.update_info(l_pos, l_quat, l_trig, l_btn)
        self.right_panel.update_info(r_pos, r_quat, r_trig, r_btn)

        # 3D 图：降频渲染（~10Hz），避免 matplotlib 占满主线程
        self._frame += 1
        if self._frame % PLOT_EVERY == 0:
            self.left_panel.update_traj(l_pos)
            self.left_panel.update_orient(l_quat)
            self.right_panel.update_traj(r_pos)
            self.right_panel.update_orient(r_quat)
            self.canvas.draw_idle()


# ─── 入口 ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    app = QuestMonitor(root)
    root.mainloop()
