# -*- coding: utf-8 -*-
"""测试用：启动内置 HTTP 服务（固定端口 8765），供 node DOM stub 端到端测试。"""
import sys
import time

sys.path.insert(0, r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools")
import design_app as DA  # noqa: E402

port = DA.start_http_server("127.0.0.1", 8765)
with open(r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\tools\_test_port.txt", "w") as f:
    f.write(str(port))
print("serving on", port, flush=True)
while True:
    time.sleep(3600)
