#!/usr/bin/env python3
"""本地循环监控：每10分钟运行一次 trading_monitor.py"""

import sys, os, time, subprocess
from datetime import datetime, time as dtime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CST = timezone(timedelta(hours=8))
INTERVAL = 600  # 10秒*60 = 10分钟
MONITOR = os.path.join(BASE, "scripts", "trading_monitor.py")
FEISHU_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")

print(f"本地实时监控启动")
print(f"  每 {INTERVAL//60} 分钟检查一次")
print(f"  交易时段: 09:30~15:00 CST")
print(f"  飞书: {'✅ 已配置' if FEISHU_URL else '❌ 未设置'}")
print()

while True:
    now = datetime.now(CST)
    t = now.time()
    if dtime(9, 30) <= t <= dtime(15, 0):
        print(f"[{now.strftime('%H:%M:%S')}] 运行...")
        env = os.environ.copy()
        if FEISHU_URL:
            env["FEISHU_WEBHOOK_URL"] = FEISHU_URL
        subprocess.run([sys.executable, MONITOR], env=env, cwd=BASE)
    elif t > dtime(15, 0):
        print(f"[{now.strftime('%H:%M:%S')}] 收盘，监控结束")
        break
    else:
        print(f"[{now.strftime('%H:%M:%S')}] 等待开盘...")
    time.sleep(INTERVAL)
