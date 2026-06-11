#!/usr/bin/env python3
"""Inline data.json into the HTML template -> index.html (self-contained)."""
import json, os

here = os.path.dirname(__file__)
data = open(os.path.join(here, "data.json"), encoding="utf-8").read()
aio = open(os.path.join(here, "aio.json"), encoding="utf-8").read()
tpl = open(os.path.join(here, "template.html"), encoding="utf-8").read()
html = tpl.replace("/*__DATA__*/null", data).replace("/*__AIO__*/null", aio)
open(os.path.join(here, "index.html"), "w", encoding="utf-8").write(html)
print("Wrote index.html", len(html), "bytes")

gz = open(os.path.join(here, "template-genz.html"), encoding="utf-8").read()
gz = gz.replace("/*__DATA__*/null", data).replace("/*__AIO__*/null", aio)
open(os.path.join(here, "genz.html"), "w", encoding="utf-8").write(gz)
print("Wrote genz.html", len(gz), "bytes")
