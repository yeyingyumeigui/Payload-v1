"""构建交付物：业务流程梳理文档 HTML 版（目录 + DOC 下载 + 打印/PDF）

运行: python build_docs.py
产物: output/文生载荷业务流程梳理_2026-09-20.html
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from payload_agent import export_html  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")

DOCS = [
    {
        "md": os.path.join(OUT, "文生载荷业务流程梳理_2026-09-20.md"),
        "title": "文生有效载荷业务流程梳理与智能体架构设计",
        "html": os.path.join(OUT, "文生载荷业务流程梳理_2026-09-20.html"),
        "gongwen": False,
    },
]


def main():
    for d in DOCS:
        with open(d["md"], encoding="utf-8") as f:
            md = f.read()
        export_html(md, d["title"], d["html"], gongwen=d.get("gongwen", False))
        size = os.path.getsize(d["html"])
        print(f"已生成: {d['html']}  ({size / 1024:.1f} KB)")
        # 自检关键元素
        with open(d["html"], encoding="utf-8") as f:
            h = f.read()
        checks = {
            "DOCTYPE": "<!DOCTYPE html>" in h,
            "charset": 'charset="utf-8"' in h,
            "目录": '<nav class="toc">' in h,
            "DOC下载": "downloadDoc()" in h,
            "打印PDF": "window.print()" in h,
            "打印样式": "@media print" in h,
            "SVG流程图": h.count("<svg") >= 2,
            "异常分级表": "INT-01" in h and "WOR-02" in h,
            "未转义残留": "&lt;svg" not in h,
        }
        for k, v in checks.items():
            print(f"  {'✅' if v else '❌'} {k}")
        assert all(checks.values()), "HTML 自检未通过"


if __name__ == "__main__":
    main()
