#!/usr/bin/env python3
"""
TactAR APP 数据接收器
接收 Quest 手柄的 6DOF 位姿和按键状态（HTTP POST，30Hz）

数据格式（来自 VRController.cs）：
  rightHand / leftHand:
    wristPos[3]    : [x, y, z]，单位米
    wristQuat[4]   : [w, x, y, z]
    triggerState   : float [0,1]，食指扳机
    buttonState[5] : [B/Y, A/X, Thumbstick, IndexTrigger, HandTrigger]
  headPos[3] / headQuat[4]: 头显位姿
  timestamp: float
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8082

# 最新数据（线程安全）
_lock = threading.Lock()
_latest = None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            with _lock:
                global _latest
                _latest = data
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # 屏蔽每条请求日志


def get_latest():
    """获取最新一帧数据，没有则返回 None"""
    with _lock:
        return _latest


def start_server(port=PORT):
    server = HTTPServer(('0.0.0.0', port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[TactAR] 监听 0.0.0.0:{port}/unity ...")
    return server


# ── 直接运行时的演示循环 ──────────────────────────────────────────
if __name__ == '__main__':
    BUTTON_NAMES = ['B/Y', 'A/X', 'Thumbstick', 'IndexTrigger', 'HandTrigger']

    start_server(PORT)
    print(f"[TactAR] 在 Quest APP 中将 IP 设为本机 IP，端口 {PORT}")
    print("[TactAR] 等待数据...\n")

    prev_ts = None
    while True:
        data = get_latest()
        if data and data.get('timestamp') != prev_ts:
            prev_ts = data['timestamp']

            rh = data['rightHand']
            lh = data['leftHand']

            r_pos  = rh['wristPos']    # [x, y, z]
            r_quat = rh['wristQuat']   # [w, x, y, z]
            r_trig = rh['triggerState']
            r_btn  = rh['buttonState'] # [B, A, Thumbstick, IndexTrigger, HandTrigger]

            l_pos  = lh['wristPos']
            l_quat = lh['wristQuat']
            l_trig = lh['triggerState']
            l_btn  = lh['buttonState']

            pressed_r = [BUTTON_NAMES[i] for i, v in enumerate(r_btn) if v]
            pressed_l = [BUTTON_NAMES[i] for i, v in enumerate(l_btn) if v]

            print(f"[t={data['timestamp']:.2f}]")
            print(f"  右手  pos={[f'{v:.3f}' for v in r_pos]}  quat(wxyz)={[f'{v:.3f}' for v in r_quat]}  trigger={r_trig:.2f}  按键={pressed_r or '无'}")
            print(f"  左手  pos={[f'{v:.3f}' for v in l_pos]}  quat(wxyz)={[f'{v:.3f}' for v in l_quat]}  trigger={l_trig:.2f}  按键={pressed_l or '无'}")

        time.sleep(0.033)  # ~30Hz 轮询
