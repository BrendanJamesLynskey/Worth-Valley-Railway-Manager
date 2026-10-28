#!/usr/bin/env python3
"""Put the built world data (kwvr_data.js) and the line map's background (map.jpg) into index.html, between the
<!--KWDATA--> markers. Usage: embed_data.py <cache dir>"""
import sys, os, base64, re
C = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(here, "..", "index.html")
s = open(P).read()
js = open(os.path.join(C, "kwvr_data.js")).read().strip()
img = base64.b64encode(open(os.path.join(C, "map.jpg"), "rb").read()).decode()
block = ("<!--KWDATA-->\n<script>\n// The Worth Valley as surveyed: OpenStreetMap (© OpenStreetMap contributors, ODbL) and the AWS Terrain Tiles,\n"
         "// built by tools/build_kwvr_data.py\n" + js + "\nconst KW_MAPIMG = \"data:image/jpeg;base64," + img + "\";\n</script>\n<!--/KWDATA-->")
if "<!--KWDATA-->" in s:
    s = re.sub(r"<!--KWDATA-->.*?<!--/KWDATA-->", lambda m: block, s, flags=re.S)
else:
    i = s.index('<script>\n"use strict";')
    s = s[:i] + block + "\n" + s[i:]
open(P, "w").write(s)
print("embedded", len(js), "bytes of data and", len(img), "of map")
