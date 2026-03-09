#!/usr/bin/env python3
"""
Quest 手柄实时监控窗口
- 左右分栏，上行：轨迹 3D，下行：姿态飞机 3D，底部数值面板
- 依赖：numpy（tkinter 内置）
- 启动：python3 quest_monitor.py
"""

import collections
import math
import signal
import sys
import time
import tkinter as tk

import numpy as np

from quest_receiver import QuestReceiver

# ─── 常量 ────────────────────────────────────────────────────────────────────
PORT        = 8082
REFRESH_MS  = 33        # ~30 Hz 全量刷新（Canvas 无阻塞）
TRAJ_LEN    = 200       # 轨迹历史帧数
BTN_HOLD_S  = 0.20      # 按键松开后保持亮起的时间（秒）
TRAJ_RANGE  = 0.5       # 轨迹显示范围（m）
PLANE_SCALE = 0.30      # 飞机示意缩放

# ─── Canvas 投影参数 ──────────────────────────────────────────────────────────
TRAJ_CV_W, TRAJ_CV_H     = 210, 170   # 轨迹 Canvas 尺寸
ORIENT_CV_W, ORIENT_CV_H = 200, 165   # 姿态 Canvas 尺寸
TRAJ_SCALE   = 150   # 像素/米（±0.5m → ±75px）
ORIENT_SCALE = 260   # 像素/单位（PLANE_SCALE=0.30 → ±78px）

_PE, _PA = math.radians(28), math.radians(42)   # 投影仰角 / 水平角
_CE, _SE = math.cos(_PE), math.sin(_PE)
_CA, _SA = math.cos(_PA), math.sin(_PA)


def _proj(pt3d, cx, cy, scale):
    """3D → Canvas 像素（正交投影）"""
    x, y, z = float(pt3d[0]), float(pt3d[1]), float(pt3d[2])
    xr =  x * _CA + z * _SA
    zr = -x * _SA + z * _CA
    yr =  y * _CE - zr * _SE
    return int(cx + xr * scale), int(cy - yr * scale)

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


# ─── 飞机线段（本地坐标，机鼻=+Z，翼展=±X，垂尾=+Y）────────────────────────
S = PLANE_SCALE
_PLANE_SEGS = [
    # (p_start, p_end, color, linewidth)
    (np.array([0,     0,    -0.7*S]), np.array([0,     0,    1.0*S]),  '#00e5ff', 2.5),  # 机身
    (np.array([-1.2*S, 0,  -0.1*S]), np.array([1.2*S,  0,  -0.1*S]),  '#ffb300', 2.0),  # 主翼
    (np.array([-0.5*S, 0,  -0.65*S]), np.array([0.5*S, 0,  -0.65*S]), '#ffb300', 1.5),  # 平尾
    (np.array([0,     0,   -0.7*S]), np.array([0,   0.5*S, -0.4*S]),   '#ff7043', 1.5),  # 垂尾
]



# ─── 手柄面板（一侧）────────────────────────────────────────────────────────
class HandPanel:
    def __init__(self, parent_frame, btn_labels):
        self.traj = collections.deque(maxlen=TRAJ_LEN)

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
        row('摇杆 XY',    ['sx', 'sy'])

        # ── 摇杆可视化 ────────────────────────────────────────────────────
        sf = tk.Frame(info, bg=COLOR_BG)
        sf.pack(fill=tk.X, pady=(4, 2))
        tk.Label(sf, text='摇杆', bg=COLOR_BG, fg='#888',
                 font=('Consolas', 9), width=12, anchor='w').pack(side=tk.LEFT)
        SZ = 60  # 小窗尺寸
        self._stick_cv = tk.Canvas(sf, width=SZ, height=SZ,
                                   bg='#111', highlightthickness=1,
                                   highlightbackground='#444')
        self._stick_cv.pack(side=tk.LEFT, padx=4)
        # 背景十字线 & 边框圆
        half = SZ // 2
        self._stick_cv.create_line(half, 2, half, SZ-2, fill='#333', width=1)
        self._stick_cv.create_line(2, half, SZ-2, half, fill='#333', width=1)
        self._stick_cv.create_oval(4, 4, SZ-4, SZ-4, outline='#333', width=1)
        # 实时点
        r = 5
        self._stick_dot = self._stick_cv.create_oval(
            half-r, half-r, half+r, half+r, fill=COLOR_ACC, outline='')
        self._stick_sz = SZ

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
        self._btn_last_press = [0.0] * len(btn_labels)
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

        # ── Canvas 可视化（轨迹 + 飞机姿态）──────────────────────────────────
        viz_row = tk.Frame(parent_frame, bg=COLOR_BG)
        viz_row.pack(fill=tk.X, padx=4, pady=2)

        self._cv_traj = tk.Canvas(viz_row, width=TRAJ_CV_W, height=TRAJ_CV_H,
                                  bg='#0d0d1a', highlightthickness=1,
                                  highlightbackground='#333')
        self._cv_traj.pack(side=tk.LEFT, padx=(0, 4))

        self._cv_orient = tk.Canvas(viz_row, width=ORIENT_CV_W, height=ORIENT_CV_H,
                                    bg='#0d0d1a', highlightthickness=1,
                                    highlightbackground='#333')
        self._cv_orient.pack(side=tk.LEFT)

    # ── Canvas：轨迹图 ────────────────────────────────────────────────────────
    def update_traj(self, pos):
        self.traj.append(np.array(pos, dtype=float))
        cv = self._cv_traj
        cv.delete('all')
        cx, cy = TRAJ_CV_W // 2, TRAJ_CV_H // 2

        # 参考十字线
        cv.create_line(cx, 4, cx, TRAJ_CV_H-4, fill='#2a2a3a', width=1)
        cv.create_line(4, cy, TRAJ_CV_W-4, cy, fill='#2a2a3a', width=1)

        traj = np.array(self.traj)
        offset = traj[-1]
        rel    = traj - offset
        if len(rel) >= 2:
            pts = [_proj(p, cx, cy, TRAJ_SCALE) for p in rel]
            n   = len(pts)
            for i in range(1, n):
                alpha = i / n
                r = int(0x44 + (0xaa - 0x44) * alpha)
                g = int(0x88 + (0xcc - 0x88) * alpha)
                col = f'#{r:02x}{g:02x}cc'
                cv.create_line(pts[i-1][0], pts[i-1][1],
                               pts[i][0],   pts[i][1],
                               fill=col, width=2)
        # 当前位置白点
        cv.create_oval(cx-4, cy-4, cx+4, cy+4, fill='white', outline='')
        cv.create_text(4, 4, text='Traj', fill='#555', font=('Consolas', 7), anchor='nw')

    # ── Canvas：姿态飞机图 ────────────────────────────────────────────────────
    def update_orient(self, quat):
        cv = self._cv_orient
        cv.delete('all')
        cx, cy = ORIENT_CV_W // 2, ORIENT_CV_H // 2

        # 参考网格
        for v in [-70, 0, 70]:
            cv.create_line(cx-90, cy+v, cx+90, cy+v, fill='#252535', width=1)
            cv.create_line(cx+v, cy-80, cx+v, cy+80, fill='#252535', width=1)

        w, x, y, z = quat
        R = quat_to_rotmat(w, x, y, z)
        for p1l, p2l, col, lw in _PLANE_SEGS:
            p1w, p2w = R @ p1l, R @ p2l
            x1, y1 = _proj(p1w, cx, cy, ORIENT_SCALE)
            x2, y2 = _proj(p2w, cx, cy, ORIENT_SCALE)
            cv.create_line(x1, y1, x2, y2, fill=col, width=int(lw))
        # 机鼻点
        nose = R @ np.array([0, 0, 1.0 * PLANE_SCALE])
        nx, ny = _proj(nose, cx, cy, ORIENT_SCALE)
        cv.create_oval(nx-4, ny-4, nx+4, ny+4, fill='#00e5ff', outline='')
        cv.create_text(4, 4, text='Orient', fill='#555', font=('Consolas', 7), anchor='nw')

    # ── 追踪模式提示 ──────────────────────────────────────────────────────────
    def update_mode(self, is_hand):
        if not is_hand:
            self._mode_lbl.config(text='[CTL] 手柄模式', fg='#4CAF50', bg=COLOR_BG)
        else:
            self._mode_lbl.config(text='[HND] 人手模式  ! 无按键/扳机', fg='#FF9800', bg='#3a2a00')

    # ── 数值面板 ──────────────────────────────────────────────────────────────
    def update_info(self, pos, quat, trig, btns, stick=None):
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

        sx = stick[0] if stick and len(stick) >= 2 else 0.0
        sy = stick[1] if stick and len(stick) >= 2 else 0.0
        self._lbl['sx'].config(text=f'{sx:+.3f}')
        self._lbl['sy'].config(text=f'{sy:+.3f}')

        # 更新摇杆可视化点（Y 轴向上为正，canvas 向下为正，需翻转）
        SZ = self._stick_sz
        half = SZ // 2
        margin = 6
        r = 5
        cx = half + sx * (half - margin)
        cy = half - sy * (half - margin)
        self._stick_cv.coords(self._stick_dot,
                              cx-r, cy-r, cx+r, cy+r)

        # 扳机
        self._trig_cv.delete('fill')
        fw = int(140 * max(0.0, min(1.0, trig)))
        if fw > 0:
            self._trig_cv.create_rectangle(0, 0, fw, 16,
                                           fill=COLOR_ACC, outline='', tags='fill')
        self._trig_lbl.config(text=f'{trig:.2f}')

        # 按键（松开后保持亮 BTN_HOLD_S 秒）
        now = time.monotonic()
        for i, c in enumerate(self._btn_cvs):
            pressed = (i < len(btns)) and bool(btns[i])
            if pressed:
                self._btn_last_press[i] = now
            on = pressed or (now - self._btn_last_press[i] < BTN_HOLD_S)
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
        self._prev_ts = None

        self._build_ui()
        self._schedule_update()

    def _build_ui(self):
        # 状态栏
        self._status_lbl = tk.Label(
            self.root, text='● 未连接', bg=COLOR_BG, fg='#f44336',
            font=('Consolas', 11), anchor='w', padx=10)
        self._status_lbl.pack(fill=tk.X)

        # 左右数值面板（含 Canvas 轨迹/姿态图）
        main = tk.Frame(self.root, bg=COLOR_BG)
        main.pack(fill=tk.BOTH, expand=True)

        lf = tk.Frame(main, bg=COLOR_BG)
        rf = tk.Frame(main, bg=COLOR_BG)
        lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)
        rf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)

        for f, title in [(lf, '左手'), (rf, '右手')]:
            tk.Label(f, text=title, bg=COLOR_BG, fg=COLOR_ACC,
                     font=('Consolas', 11, 'bold')).pack(anchor='w', padx=6)

        self.left_panel  = HandPanel(lf, LEFT_BUTTONS)
        self.right_panel = HandPanel(rf, RIGHT_BUTTONS)

    def _schedule_update(self):
        self.root.after(REFRESH_MS, self._schedule_update)
        self._update()

    def _update(self):
        """30Hz：全量更新（数值 + Canvas 轨迹/姿态），无 matplotlib 阻塞"""
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

        # leftHand/rightHand 对调（修正左右互换）
        lh = data.get('rightHand', {})
        rh = data.get('leftHand',  {})

        def safe(hand, key, default):
            return hand.get(key, default)

        l_pos   = safe(lh, 'wristPos',     [0.0, 0.0, 0.0])
        l_quat  = safe(lh, 'wristQuat',    [1.0, 0.0, 0.0, 0.0])
        l_trig  = safe(lh, 'triggerState', 0.0)
        l_btn   = safe(lh, 'buttonState',  [False]*5)
        l_stick = safe(lh, 'thumbstick',   [0.0, 0.0])
        l_is_hand = len(safe(lh, 'jointPos', None) or []) == 72

        r_pos     = safe(rh, 'wristPos',     [0.0, 0.0, 0.0])
        r_quat    = safe(rh, 'wristQuat',    [1.0, 0.0, 0.0, 0.0])
        r_trig    = safe(rh, 'triggerState', 0.0)
        r_btn     = safe(rh, 'buttonState',  [False]*5)
        r_stick   = safe(rh, 'thumbstick',   [0.0, 0.0])
        r_is_hand = len(safe(rh, 'jointPos', None) or []) == 72

        # 追踪模式提示（始终更新）
        self.left_panel.update_mode(l_is_hand)
        self.right_panel.update_mode(r_is_hand)

        # 人手模式下冻结手柄监控
        if l_is_hand or r_is_hand:
            return

        self.left_panel.update_info(l_pos, l_quat, l_trig, l_btn, l_stick)
        self.right_panel.update_info(r_pos, r_quat, r_trig, r_btn, r_stick)

        # Canvas 轨迹 + 姿态：tkinter 原生，<5ms，直接在 30Hz 循环里更新
        self.left_panel.update_traj(l_pos)
        self.left_panel.update_orient(l_quat)
        self.right_panel.update_traj(r_pos)
        self.right_panel.update_orient(r_quat)


# ─── 入口 ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    app = QuestMonitor(root)

    def _quit(*_):
        app.receiver.stop()
        root.destroy()
        sys.exit(0)

    signal.signal(signal.SIGINT, _quit)
    root.protocol('WM_DELETE_WINDOW', _quit)

    root.mainloop()
