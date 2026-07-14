#!/usr/bin/env python3
"""本地后端 —— 让 site/live.html 的「运行今日扫描」按钮真正触发管线。

stdlib http.server(无新依赖)。静态服务 site/,外加:
  POST /api/run            起后台线程跑 live_funnel.build(今日,全量),存快照(单跑锁)
  GET  /api/progress       进度 {running,stage,done,total,hits,error,asof}
  GET  /api/snapshots      可用快照日期
  GET  /api/snapshot/<d>   该日快照 JSON

跑:  cd scanner && ../.venv/bin/python serve.py   然后浏览器开 http://localhost:8799/live.html
"""
import http.server
import json
import re
import threading
from pathlib import Path

import live_funnel

BASE = Path(__file__).resolve().parent
SITE = BASE.parent / 'site'
SNAP = BASE / 'snapshots'
PORT = 8799
DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')

RUN = {'running': False, 'stage': '', 'done': 0, 'total': 0, 'hits': 0, 'error': None, 'asof': None}
LOCK = threading.Lock()


def _run_job(refresh=True):
    try:
        def cb(stage, done, total, hits):
            RUN.update(stage=stage, done=done, total=total, hits=hits)
        snap = live_funnel.build(refresh=refresh, progress_cb=cb)   # 全量;refresh 由前端复选框控制
        live_funnel.save_snapshot(snap)
        RUN['asof'] = snap['asof']
    except Exception as e:                              # noqa: BLE001 — 报给前端
        RUN['error'] = str(e)
    finally:
        RUN['running'] = False


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(SITE), **k)

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        if self.path == '/api/run':
            refresh = True
            try:
                n = int(self.headers.get('Content-Length', 0))
                if n:
                    refresh = bool(json.loads(self.rfile.read(n)).get('refresh', True))
            except Exception:
                refresh = True
            with LOCK:
                if RUN['running']:
                    return self._json({'error': '已有任务在跑'}, 409)
                RUN.update(running=True, stage='启动', done=0, total=0, hits=0, error=None, asof=None)
            threading.Thread(target=_run_job, args=(refresh,), daemon=True).start()
            return self._json({'started': True})
        self._json({'error': 'not found'}, 404)

    def do_GET(self):
        if self.path == '/api/progress':
            return self._json(RUN)
        if self.path == '/api/snapshots':
            idx = SNAP / 'index.json'
            if idx.exists():
                return self._json(json.loads(idx.read_text()))
            dates = sorted(p.stem for p in SNAP.glob('*.json') if p.stem != 'index') if SNAP.exists() else []
            return self._json({'dates': dates})
        if self.path.startswith('/api/snapshot/'):
            d = self.path.rsplit('/', 1)[-1]
            if not DATE_RE.match(d):
                return self._json({'error': 'bad date'}, 400)
            f = SNAP / f'{d}.json'
            if not f.exists():
                return self._json({'error': 'no such snapshot'}, 404)
            return self._json(json.loads(f.read_text()))
        if self.path in ('/', ''):
            self.path = '/live.html'
        return super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f"→ http://localhost:{PORT}/live.html  (回测漏斗在 /index.html · Ctrl-C 停)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
