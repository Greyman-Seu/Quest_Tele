#!/usr/bin/env python3
"""
Quest 数据接收器
接收 Quest 手柄/人手的位姿和状态（HTTP POST，30Hz）

数据格式（来自 VRController.cs）：
  rightHand / leftHand:
    wristPos[3]      : [x, y, z]，单位米
    wristQuat[4]     : [w, x, y, z]
    triggerState     : float [0,1]，食指扳机（手柄模式有效）
    buttonState[5]   : [B/Y, A/X, Thumbstick, IndexTrigger, HandTrigger]（手柄模式有效）
    isHandTracking   : bool，true=人手追踪，false=手柄追踪
    jointPos[72]     : 24关节×3坐标，人手模式有效；手柄模式为空数组[]
  headPos[3] / headQuat[4]: 头显位姿
  timestamp: float
"""

import collections
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class QuestReceiver:
    """Quest 手柄数据接收器（HTTP POST 服务器封装）"""

    def __init__(self, port=8082):
        self._port = port
        self._lock = threading.Lock()
        self._latest = None
        self._client_ip = None
        self._ts_window = collections.deque(maxlen=60)  # 最近60帧时间戳，用于计算频率
        self._server = None

    def start(self):
        """启动后台 HTTP 监听线程"""
        receiver = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                try:
                    data = json.loads(body)
                    with receiver._lock:
                        receiver._latest = data
                        receiver._client_ip = self.client_address[0]
                        receiver._ts_window.append(time.monotonic())
                except Exception:
                    pass
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass  # 屏蔽每条请求日志

        self._server = HTTPServer(('0.0.0.0', self._port), _Handler)
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()
        print(f"[TactAR] 监听 0.0.0.0:{self._port} ...")
        return self._server

    def get_latest(self):
        """返回最新一帧数据 dict，没有则返回 None"""
        with self._lock:
            return self._latest

    def get_hz(self):
        """滑动窗口计算实际接收频率（Hz）"""
        with self._lock:
            ts = list(self._ts_window)
        if len(ts) < 2:
            return 0.0
        elapsed = ts[-1] - ts[0]
        if elapsed <= 0:
            return 0.0
        return (len(ts) - 1) / elapsed

    def get_client_ip(self):
        """返回最后连接的客户端 IP 字符串"""
        with self._lock:
            return self._client_ip

    def stop(self):
        """关闭 HTTP 服务器"""
        if self._server:
            self._server.shutdown()


# ── 模块级函数（向后兼容）───────────────────────────────────────────
_default_receiver = None


def start_server(port=8082):
    """启动默认全局接收器"""
    global _default_receiver
    _default_receiver = QuestReceiver(port=port)
    return _default_receiver.start()


def get_latest():
    """获取最新一帧数据，没有则返回 None"""
    if _default_receiver is None:
        return None
    return _default_receiver.get_latest()


# ── 直接运行时的演示循环 ──────────────────────────────────────────
if __name__ == '__main__':
    BUTTON_NAMES = ['B/Y', 'A/X', 'Thumbstick', 'IndexTrigger', 'HandTrigger']

    receiver = QuestReceiver(port=8082)
    receiver.start()
    print(f"[TactAR] 在 Quest APP 中将 IP 设为本机 IP，端口 8082")
    print("[TactAR] 等待数据...\n")

    prev_ts = None
    while True:
        data = receiver.get_latest()
        if data and data.get('timestamp') != prev_ts:
            prev_ts = data['timestamp']

            rh = data['rightHand']
            lh = data['leftHand']

            r_pos  = rh['wristPos']
            r_quat = rh['wristQuat']
            r_trig = rh['triggerState']
            r_btn  = rh['buttonState']

            l_pos  = lh['wristPos']
            l_quat = lh['wristQuat']
            l_trig = lh['triggerState']
            l_btn  = lh['buttonState']

            pressed_r = [BUTTON_NAMES[i] for i, v in enumerate(r_btn) if v]
            pressed_l = [BUTTON_NAMES[i] for i, v in enumerate(l_btn) if v]

            hz = receiver.get_hz()
            ip = receiver.get_client_ip()
            print(f"[t={data['timestamp']:.2f}]  {hz:.1f}Hz  客户端={ip}")
            print(f"  右手  pos={[f'{v:.3f}' for v in r_pos]}  quat(wxyz)={[f'{v:.3f}' for v in r_quat]}  trigger={r_trig:.2f}  按键={pressed_r or '无'}")
            print(f"  左手  pos={[f'{v:.3f}' for v in l_pos]}  quat(wxyz)={[f'{v:.3f}' for v in l_quat]}  trigger={l_trig:.2f}  按键={pressed_l or '无'}")

        time.sleep(0.033)  # ~30Hz 轮询
