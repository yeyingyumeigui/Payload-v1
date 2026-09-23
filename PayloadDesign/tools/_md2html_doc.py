# -*- coding: utf-8 -*-
"""把 载荷方案设计器_软件说明.md 转为带打印/下载按钮的独立 HTML。
仅支持本文档用到的语法：#~#### 标题、表格、无序/有序列表、代码块、行内代码、
粗体、引用块、水平线、段落。"""
import html as H
import re
import os

SRC = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\载荷方案设计器_软件说明.md"
DST = r"D:\ZWL\文生载荷Workbuddy\PayloadDesign\output\载荷方案设计器_软件说明.html"


def inline(s):
    s = H.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", s)
    return s


def convert(lines):
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            buf = []
            while j < n and not lines[j].startswith("```"):
                buf.append(lines[j]); j += 1
            out.append("<pre>" + H.escape("\n".join(buf)) + "</pre>")
            i = j + 1
            continue
        if re.match(r"^-{3,}\s*$", ln):
            out.append("<hr/>"); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            lv = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lv, inline(m.group(2)), lv)); i += 1; continue
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(inline(lines[i].lstrip("> ").rstrip())); i += 1
            out.append("<blockquote>" + "<br/>".join(buf) + "</blockquote>"); continue
        if ln.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>" + "".join("<th>%s</th>" % inline(c) for c in head) + "</tr></thead><tbody>"]
            for r in rows:
                t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in r) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t)); continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", ln)
        if m:
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            items = []
            while i < n:
                m2 = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", lines[i])
                if not m2:
                    break
                items.append("<li>%s</li>" % inline(m2.group(3))); i += 1
            out.append("<%s>%s</%s>" % (tag, "".join(items), tag)); continue
        if not ln.strip():
            i += 1; continue
        buf = []
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,4}\s|```|>|\||\s*[-*]\s|\s*\d+\.\s|-{3,}\s*$)", lines[i]):
            buf.append(inline(lines[i].rstrip())); i += 1
        out.append("<p>%s</p>" % "<br/>".join(buf))
    return "\n".join(out)


CSS = """
:root{--ink:#1a2332;--mut:#5a6b82;--acc:#1450a0;--line:#d8e0ea;--bg:#f4f7fb;--card:#ffffff;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:var(--ink);background:var(--bg);line-height:1.75;font-size:15px}
.toolbar{position:sticky;top:0;z-index:9;background:#0e2a52;color:#fff;padding:10px 24px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.toolbar .ttl{font-weight:700;margin-right:auto;font-size:15px}
.toolbar button{background:#1d4f91;color:#fff;border:1px solid #3a6db5;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:13px}
.toolbar button:hover{background:#2a63b0}
.wrap{max-width:980px;margin:24px auto;padding:40px 52px;background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 14px rgba(20,40,80,.06)}
h1{font-size:26px;color:var(--acc);border-bottom:3px solid var(--acc);padding-bottom:12px;margin:6px 0 18px}
h2{font-size:20px;color:var(--acc);margin:30px 0 12px;padding-left:10px;border-left:5px solid var(--acc)}
h3{font-size:16.5px;margin:20px 0 8px;color:#0e2a52}
h4{font-size:15px;margin:14px 0 6px}
p{margin:8px 0}
hr{border:none;border-top:1px dashed var(--line);margin:22px 0}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}
th{background:#eaf1fa;color:#0e2a52;font-weight:700;text-align:left;padding:8px 10px;border:1px solid var(--line)}
td{padding:7px 10px;border:1px solid var(--line);vertical-align:top}
tr:nth-child(even) td{background:#f8fafd}
code{background:#eef2f7;color:#b03060;border-radius:4px;padding:1px 6px;font-family:Consolas,monospace;font-size:13px}
pre{background:#0f1c2e;color:#d8e4f2;border-radius:8px;padding:14px 18px;overflow-x:auto;font-family:Consolas,monospace;font-size:13px;line-height:1.6;margin:12px 0}
pre code{background:none;color:inherit;padding:0}
blockquote{background:#fff8e6;border-left:4px solid #e6a817;border-radius:0 8px 8px 0;padding:10px 16px;margin:12px 0;color:#6b5312;font-size:14px}
ul,ol{margin:8px 0 8px 26px}
li{margin:4px 0}
strong{color:#0e2a52}
@media print{.toolbar{display:none}.wrap{border:none;box-shadow:none;max-width:none;margin:0;padding:0}body{background:#fff}h2{page-break-after:avoid}table,pre,blockquote{page-break-inside:avoid}}
"""

JS = """
function doPrint(){window.print();}
function doDownloadDoc(){
  var body=document.getElementById('doc').innerHTML;
  var html='<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">'
    +'<head><meta charset="utf-8"><title>载荷方案设计器软件说明</title>'
    +'<style>body{font-family:"Microsoft YaHei",sans-serif;font-size:12pt;line-height:1.7}'
    +'h1{font-size:20pt;color:#1450a0}h2{font-size:16pt;color:#1450a0}h3{font-size:13pt}'
    +'table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;padding:5px 8px;font-size:10.5pt}'
    +'th{background:#eaf1fa}pre{background:#f2f2f2;padding:10px;font-family:Consolas,monospace;font-size:10pt}'
    +'blockquote{background:#fff8e6;border-left:4px solid #e6a817;padding:8px 12px;margin:8px 0}</style></head>'
    +'<body>'+body+'</body></html>';
  var blob=new Blob(['\\ufeff',html],{type:'application/msword'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='载荷方案设计器_软件说明.doc';a.click();URL.revokeObjectURL(a.href);
}
"""


def main():
    with open(SRC, encoding="utf-8") as f:
        lines = f.read().splitlines()
    body = convert(lines)
    page = ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\"/>\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>\n"
            "<title>载荷方案设计器 · 软件说明</title>\n<style>" + CSS + "</style>\n</head>\n<body>\n"
            "<div class=\"toolbar\"><span class=\"ttl\">载荷方案设计器 · 软件说明 v4.1</span>"
            "<button onclick=\"doDownloadDoc()\">⬇ 下载 Word（.doc）</button>"
            "<button onclick=\"doPrint()\">🖨 打印 / PDF</button></div>\n"
            "<div class=\"wrap\"><div id=\"doc\">\n" + body + "\n</div></div>\n"
            "<script>" + JS + "</script>\n</body>\n</html>")
    with open(DST, "w", encoding="utf-8") as f:
        f.write(page)
    # 简易自检：关键内容都进了 HTML
    for kw in ("RESULT: PASS", "resolve_rx_chain", "10.58", "五步闭环", "P0~P14",
               "<table>", "载荷方案设计器.exe", "D 级", "WebView2"):
        assert kw in page or kw.replace("~", "") in page.replace("~", ""), kw
    print("OK", os.path.getsize(DST), "bytes ->", DST)


if __name__ == "__main__":
    main()
