"""Re-render docs/index.html and docs/dashboard.html from tools/dashboard_template.html, reusing the data
already built into those pages.

    python tools/render_pages.py

For changes to the page itself (layout, styles, scripts) when the results/ folders that
build_dashboard.py reads aren't at hand. The highway data, satellite images, GSAP, three.js and
the build date are carried over unchanged from each page; run build_dashboard.py to refresh them."""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "tools/dashboard_template.html").read_text(encoding="utf-8")

def grab(pattern, page, name, flags=re.M):
    m = re.search(pattern, page, flags)
    if not m:
        raise SystemExit(f"{name} not found; rebuild this page with build_dashboard.py instead")
    return m.group(1)

def render(path):
    page = path.read_text(encoding="utf-8")
    vals = {
        "__HWIDS__": grab(r"var d = document\.documentElement, ids = (\[.*?\]);", page, "highway ids"),
        # GSAP and three.js sit between the font <noscript> block and the page's <style>
        "__GSAP__\n__THREE__": grab(r"</noscript>\n(?:<!--.*?-->\n<script src=[^\n]*\n)?(.*?)\n<style>", page, "GSAP / three.js", re.S).split("</style></noscript>\n", 1)[-1],
        "__HEROSTATS__": grab(r'<div class="herostats" id="herostats" data-in>(.*?)</div>\n', page, "hero stats", re.S),
        "__DATA__": grab(r"^const HIGHWAYS = (.*);$", page, "highway data"),
        "__IMAGES__": grab(r"^const IMAGES = (.*);$", page, "images"),
        "__EXPLAIN__": grab(r"^const EXPLAIN = (.*);$", page, "explainer"),
        "__BUILT__": grab(r'BUILT = "(.*?)";', page, "build date"),
    }
    out = TEMPLATE
    for k, v in vals.items():
        if k not in out:
            raise SystemExit(f"{k} missing from the template")
        out = out.replace(k, v, 1)
    path.write_text(out, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)} ({len(out) // 1024} KB)")

for name in ("docs/index.html", "docs/dashboard.html"):
    render(ROOT / name)
