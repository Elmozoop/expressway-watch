"""Browser test for the built dashboard (docs/index.html and docs/dashboard.html).

    pip install playwright && playwright install chromium
    python tools/build_dashboard.py && python tools/test_dashboard.py [screenshot-dir]

Loads the page in Chromium on a desktop, two phones and a phone held sideways, in light, dark,
reduced-motion, no-JavaScript and print modes. It plays the time-lapse, scrolls through the explainer
and the story, clicks through both highways and checks what should be on screen. The web font is
served from tools/vendor/fonts, so the test runs offline and measures real text widths.
Exits non-zero on any failed check or page error."""
import csv, io, pathlib, sys, tempfile
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = (ROOT / "docs/index.html").as_uri()
SINGLE = (ROOT / "docs/dashboard.html").as_uri()
FONTS = ROOT / "tools/vendor/fonts"
fails, errors = [], []

# the page asks Google Fonts for Overpass; answer with the vendored copies of the same files
FONT_CSS = "".join(
    f"@font-face{{font-family:'{fam}';font-weight:{w};font-display:swap;src:url('https://fonts.gstatic.com/ew/{stem}-{w}-normal.woff2') format('woff2')}}"
    for fam, stem, weights in (("Overpass", "overpass-latin", (400, 500, 600, 700, 800, 900)), ("Overpass Mono", "overpass-mono-latin", (400, 500, 600)))
    for w in weights)
CORS = {"Access-Control-Allow-Origin": "*"}

def serve_fonts(ctx):
    ctx.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=200, content_type="text/css", headers=CORS, body=FONT_CSS))
    ctx.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(status=200, content_type="font/woff2", headers=CORS, body=(FONTS / r.request.url.rsplit("/", 1)[1]).read_bytes()))

def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        fails.append(what)

def watch(pg, name):
    pg.on("pageerror", lambda e: errors.append(f"{name}: {e}"))
    pg.on("console", lambda m: errors.append(f"{name}: {m.text}") if m.type == "error" else None)

def new_page(b, name, **kw):
    ctx = b.new_context(**kw); serve_fonts(ctx)
    pg = ctx.new_page(); watch(pg, name)
    return ctx, pg

def load(pg, url, wait):
    pg.goto("about:blank"); pg.goto(url); pg.wait_for_timeout(wait)    # a fresh load even when only the #hash differs

overflow = lambda pg: pg.evaluate("document.documentElement.scrollWidth - innerWidth")
scroll_to = lambda pg, y: pg.evaluate(f"scrollTo({{top: {y}, behavior: 'instant'}})")

def scroll_through(pg, step=450, pause=150):
    h = pg.evaluate("document.body.scrollHeight")
    for y in range(0, h + step, step):
        scroll_to(pg, y); pg.wait_for_timeout(pause)
    pg.wait_for_timeout(1300)

def at(pg, sel, frac, wait=850):
    """Scroll so that the tall scroll-driven section `sel` is `frac` of the way through."""
    pg.evaluate("([s, f]) => { const e = document.querySelector(s); scrollTo({top: scrollY + e.getBoundingClientRect().top + (e.offsetHeight - innerHeight) * f, behavior: 'instant'}); }", [sel, frac])
    pg.wait_for_timeout(wait)

def imgs_ok(pg, sel):
    return pg.evaluate(f"(() => {{ const i = [...document.querySelectorAll('{sel}')].filter(i => i.getAttribute('src')); return i.length > 0 && i.every(i => i.complete && i.naturalWidth > 0); }})()")

# Overpass draws "·" with no width, so it may only appear in Overpass Mono text
dots_outside_mono = lambda pg: pg.evaluate("""(() => { const bad = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) if (n.nodeValue.includes('·') && !n.parentElement.closest('script, style') && !/Mono/.test(getComputedStyle(n.parentElement).fontFamily)) bad.push(n.nodeValue.trim().slice(0, 50)); return bad; })()""")
no_broken_images = lambda pg: pg.evaluate("[...document.images].filter(i => i.getAttribute('src')).every(i => !i.complete || i.naturalWidth > 0)")
inside_viewport = lambda pg, sel: pg.evaluate(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return r.top >= -1 && r.bottom <= innerHeight + 1; }})()")

EX_STATE = """() => ({q: document.getElementById('pQ').textContent, stage: document.querySelector('#pStage span').textContent,
  step: document.querySelector('#pStep h3').textContent, tag: document.getElementById('pTag').textContent,
  cloud: !document.getElementById('pCloud').hidden, dip: !!document.querySelector('#chB .ex-dip.on'), peak: !!document.querySelector('#chB .ex-note.on:not(.ex-dip)'),
  filled: [...document.querySelectorAll('#chS .ex-cell')].filter(r => r.style.fill !== 'rgb(34, 44, 58)').length})"""

def explainer(pg, frac, wait=850):
    at(pg, "#scene", frac, wait)
    return pg.evaluate(EX_STATE)

def pinned_scenes_fit(pg, label):
    """The explainer and the story are pinned while you scroll: at every step they must fit the screen."""
    for f in pg.evaluate(PHASES_JS):
        at(pg, "#scene", f, 450)
        check(inside_viewport(pg, ".panel"), f"{label}: explainer fits the screen at {f:.2f} ('{pg.text_content('#pStep h3')}', scale {pg.evaluate('document.querySelector(`.panel`).style.scale') or 1})")
    for f in STORY_FRACS:
        at(pg, "#story", f, 500)
        check(inside_viewport(pg, ".storygrid"), f"{label}: story fits the screen at {f} ('{pg.text_content('#chapter h2')}', scale {pg.evaluate('document.querySelector(`.storygrid`).style.scale') or 1})")

# scroll positions that land on each step of the explainer: the intro, each stage, the closing note
PHASES_JS = """() => { const n = EXPLAIN.stage.length, lead = .07, tail = .1, f = i => lead + (i + .5) / n * (1 - lead - tail), out = [.02];
  [1, 2, 3, 4].forEach(s => { const i = EXPLAIN.stage.indexOf(s); if (i >= 0) out.push(f(i)); }); out.push(.97); return out; }"""
STORY_FRACS = (0.02, 0.35, 0.55, 0.75, 0.98)


def wake(pg):
    """Where WebGL is drawn in software, as in this test, the scene waits for a first scroll before it builds: give it one."""
    pg.evaluate("scrollBy(0, 2)")
    pg.wait_for_function("document.getElementById('intro').classList.contains('i3-ready')", timeout=15000)
    pg.evaluate("scrollTo(0, 0)")
    pg.wait_for_function("Math.abs(I3.p - progressOf(document.getElementById('intro'))) < .002", timeout=15000); pg.wait_for_timeout(300)

def intro_at(pg, frac):
    """Scroll the opening scene `frac` of the way through, and wait for the 3D to catch up with the scroll."""
    at(pg, "#intro", frac, 100)
    pg.wait_for_function("Math.abs(I3.p - progressOf(document.getElementById('intro'))) < .002", timeout=15000)
    pg.wait_for_timeout(450)                                            # the caption and chips fade in CSS

INTRO_STATE = """() => { const box = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  return {mode: I3.mode, cap: document.getElementById('i3cap').classList.contains('on') ? document.querySelector('#i3cap b').textContent : '',
    chip: [...document.querySelectorAll('#i3stages span.on')].map(s => s.textContent).join(),
    title: +getComputedStyle(document.getElementById('i3title')).opacity,
    labels: [...document.querySelectorAll('.i3-lab')].filter(l => +l.style.opacity > .3).map(l => [l.querySelector('b').textContent, ...box(l)]),
    capbox: document.getElementById('i3cap').classList.contains('on') ? box(document.getElementById('i3cap')) : null,
    chips: box(document.getElementById('i3stages')), model: I3.sc ? I3.sc.spanX() : null, W: innerWidth, H: innerHeight,
    low: (() => { const c = document.getElementById('i3cap'); if (!I3.sc || !c.classList.contains('on')) return null; const r = c.getBoundingClientRect(); return I3.sc.lowAt(r.left, r.right); })()}; }"""

# the model's underside, where it is above the caption, stays above it
clear_of_caption = lambda s: s["low"] is None or s["low"] <= s["capbox"][1] + .5

def labels_clear(s):
    """Every label on screen, clear of the model, of each other and of the caption."""
    hit = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    L = [l[1:] for l in s["labels"]]
    return (all(0 <= r[0] and r[2] <= s["W"] + .5 and 0 <= r[1] and r[3] <= s["H"] for r in L)
            and all(r[0] >= s["model"][1] + 4 for r in L)
            and not any(hit(a, b) for i, a in enumerate(L) for b in L[i + 1:])
            and not (s["capbox"] and any(hit(a, s["capbox"]) for a in L)))

# the ground block's box on screen at 501 points through the scene. A jump is a step far bigger than the steps either side
# of it (the first framing moved the model 70px in one step); the quick glide out from beside the title is not one.
JUMPS = """() => { const s = []; for (let i = 0; i <= 500; i++) s.push(I3.sc.span(i / 500));
  const j = s.slice(1).map((v, i) => Math.max(...v.map((x, k) => Math.abs(x - s[i][k]))));
  let worst = 0, at = 0, spike = 0;
  j.forEach((v, i) => { if (v > worst){ worst = v; at = (i + 1) / 500; }
    if (v > 6) spike = Math.max(spike, v / Math.max(j[i - 1] || 0, j[i + 1] || 0, .5)); });
  I3.dirty = true; return [worst, at, spike]; }"""

def no_jumps(pg, label):
    worst, at, spike = pg.evaluate(JUMPS)
    check(worst < 40 and spike < 2.5, f"{label}the model glides from start to end, with no jumps (largest step {worst:.1f}px at {at:.3f}, {spike:.2f}× its neighbours)")

def canvas_contrast(pg, path):
    from PIL import Image, ImageStat
    pg.locator("#i3canvas").screenshot(path=path)
    return ImageStat.Stat(Image.open(path).convert("L")).stddev[0]

def main():
    OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="ew-shots-"))
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()                  # its WebGL is drawn in software (SwiftShader), so the scene runs on its plainest setting

        print("desktop, light, with motion")
        ctx, pg = new_page(b, "desktop", viewport={"width": 1280, "height": 860}, accept_downloads=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        pg.goto(URL); pg.wait_for_timeout(3000)
        check(pg.evaluate("!!window.gsap && !!window.ScrollTrigger"), "GSAP is inlined and loaded")
        check(pg.evaluate("!window.THREE && !document.querySelector('script[src*=\"three\"]')"), "three.js is not fetched before the scene needs it")
        check(pg.evaluate("document.fonts.check('900 20px Overpass') && document.fonts.check('600 20px \"Overpass Mono\"')"), "web font loaded (served from tools/vendor/fonts)")
        check(pg.evaluate("Object.values(IMAGES).flat().every(p => Object.values(p.imgs).every(v => v.startsWith('img/sat/')))"), "index.html links the satellite images instead of embedding them")
        check(overflow(pg) == 0, "no sideways scroll")
        check(pg.evaluate("[...document.querySelectorAll('#home [data-reveal], .hw, .herotext [data-in]')].every(n => getComputedStyle(n).opacity === '1') && [...document.querySelectorAll('.hero h1 .line>span')].every(s => new DOMMatrix(getComputedStyle(s).transform).m42 === 0)"),
              "everything below the opening scene rests fully drawn before any scrolling")

        print("desktop: opening scene")
        check(pg.evaluate("I3.q === 0 && I3.mode === 'motion' && !I3.sc && !document.getElementById('intro').classList.contains('i3-ready') && getComputedStyle(document.getElementById('i3title')).opacity === '1'"),
              "drawn in software (as here), the scene shows its title and waits for a first scroll before it builds")
        wake(pg); s = pg.evaluate(INTRO_STATE)
        check(pg.evaluate("!!window.THREE && document.querySelectorAll('script[src=\"vendor/three.min.js\"]').length === 1"), "then three.js is fetched once, from docs/vendor/")
        check(s["mode"] == "motion" and pg.evaluate("document.getElementById('intro').classList.contains('i3-ready')"), "the 3D opening scene is running (three.js, WebGL)")
        check(canvas_contrast(pg, OUT / "d0_intro_canvas.png") > 18, "the road is drawn")
        check(s["title"] > .95 and s["cap"] == "" and not s["labels"], "it opens on the title")
        no_jumps(pg, "")
        pg.screenshot(path=OUT / "d0_intro.png")
        for frac, cap, chip, nlab in [(0.11, "Asphalt surface", "Paved", 1), (0.30, "Embankment", "Earthwork", 5), (0.45, "Five layers on top of the fields", "", 6),
                                      (0.53, "The way the satellite sees it", "", 0), (0.585, "Not started", "Not started", 0), (0.64, "Clearing", "Clearing", 0),
                                      (0.72, "Earthwork", "Earthwork", 0), (0.81, "Paved", "Paved", 0), (1.0, "From 786 km up", "Paved", 0)]:
            intro_at(pg, frac); s = pg.evaluate(INTRO_STATE)
            check(s["cap"] == cap and s["chip"] == chip and len(s["labels"]) == nlab and s["title"] < .05 and clear_of_caption(s),
                  f"opening scene at {frac}: '{s['cap']}', stage '{s['chip']}', {len(s['labels'])} labels, model clear of the caption")
            if nlab: check(labels_clear(s), "  labels on screen, clear of the model, of each other and of the caption")
            if frac in (0.11, 0.45, 0.72, 1.0): pg.screenshot(path=OUT / f"d0_intro_{frac:.2f}.png")
        intro_at(pg, 0.2); pg.click(".i3-skip"); pg.wait_for_timeout(2200)
        check(abs(pg.evaluate("document.getElementById('hero').getBoundingClientRect().top")) < 4, "'Skip to the tracker' jumps to the hero")

        pg.evaluate("document.getElementById('hero').scrollIntoView({behavior: 'instant'})"); pg.wait_for_timeout(3200)
        check(pg.evaluate("[...document.querySelectorAll('.hero h1 .line>span')].every(s => getComputedStyle(s).visibility === 'visible' && new DOMMatrix(getComputedStyle(s).transform).m42 === 0)"), "hero headline has risen into place")
        check(pg.evaluate("getComputedStyle(document.getElementById('scope')).visibility === 'visible' && getComputedStyle(document.getElementById('scopeImg')).opacity === '1'"), "time-lapse is visible")
        check(imgs_ok(pg, "#scopeImg img") and not pg.evaluate("document.getElementById('scopeImg').classList.contains('loading')"), "time-lapse image loaded")
        stats = pg.evaluate("[...document.querySelectorAll('#herostats b')].map(b => b.textContent)")
        check(stats == ["260 km", "27", "94%"], f"hero stats counted up to final values {stats}")
        check("NHAI" in pg.text_content("#cta"), "primary button points to the live NHAI project")
        pg.screenshot(path=OUT / "d1_hero.png")

        seen = []
        for _ in range(30):
            q = pg.text_content("#tq")
            if q not in seen: seen.append(q)
            pg.wait_for_timeout(250)
        check(len(seen) >= 3, f"time-lapse steps through the years on its own {seen}")
        pg.click("#tplay"); pg.wait_for_timeout(1300)                        # a wipe already under way finishes
        q = pg.text_content("#tq"); pg.wait_for_timeout(3300)
        check(pg.text_content("#tq") == q and pg.get_attribute("#tplay", "aria-label") == "Play the time-lapse", f"pause holds the time-lapse on {q}")
        pg.click(".t-dot[data-k='3']"); pg.wait_for_timeout(1500)
        check(pg.text_content("#tq") == "2026 Q3" and pg.text_content("#tstage span") == "Paved" and pg.get_attribute("#scopeImg img.cur", "src").endswith("2026Q3.jpg"),
              "year button shows the finished road in 2026 Q3")
        check(pg.evaluate("[...document.querySelectorAll('.t-dot')].map(d => d.style.getPropertyValue('--f'))") == ["100%"] * 4, "  with every progress bar full")
        check(pg.is_visible("#thint") and "older highway" in pg.text_content("#thint"), "time-lapse says what to look for")
        pg.screenshot(path=OUT / "d1b_timelapse_2026.png")

        print("desktop: explainer")
        for frac, q, step, filled in [(0.02, "2020 Q1", "One piece of road, six years", 1), (0.2, "2021 Q1", "Farmland", 5),
                                      (0.45, "2023 Q1", "Earthwork", 13), (0.85, "2026 Q2", "Paved", 26), (0.97, "2026 Q3", "One square per quarter", 27)]:
            s = explainer(pg, frac)
            check(s["q"] == q and s["step"] == step and s["filled"] == filled, f"explainer at {frac}: {s['q']}, '{s['step']}', {s['filled']} squares filled")
            check(s["cloud"] == ("2024 Q3" in s["tag"]), f"  cloud note only on the cloudy 2024 Q3 image ({s['tag']})")
            check(imgs_ok(pg, "#pFrame img.on"), "  photo loaded")
            if frac == 0.45:
                check(s["stage"] == "Earthwork" and "2024 Q3" in s["tag"] and "same stage" in s["tag"] and not s["dip"] and not s["peak"], "  earthwork quarter shows an earthwork photo, labelled as such; the peak and dip notes wait")
                pg.screenshot(path=OUT / "d2_explainer_earthwork.png")
            if frac == 0.85:
                check(s["dip"] and s["peak"], "  the peak and the ignored dip are labelled once the line has passed them")
                pg.screenshot(path=OUT / "d2_explainer_paved.png")
        check(pg.evaluate("getComputedStyle(document.querySelector('.panel')).opacity") == "1", "explainer panel fully in view inside the scene")
        pinned_scenes_fit(pg, "1280×860")

        print("desktop: story, picker, trust")
        chapters = []
        for f in STORY_FRACS:
            at(pg, "#story", f, 950); chapters.append(pg.text_content("#chapter h2"))
        check(len(set(chapters)) == 5, f"story walks through 5 chapters: {chapters}")
        pg.screenshot(path=OUT / "d3_story.png")
        pg.evaluate("document.getElementById('pick').scrollIntoView({behavior: 'instant'})"); pg.wait_for_timeout(1300)
        check(pg.evaluate("[...document.querySelectorAll('button.hw')].map(b => b.innerText.includes(b.querySelector('h3').textContent) && b.innerText.includes('Open the tracker') && !b.hasAttribute('aria-label'))") == [True, True],
              "two highway cards, each named by its own text")
        pg.screenshot(path=OUT / "d4_picker.png")
        pg.fill("#q", "zzz"); pg.wait_for_timeout(200)
        check("issues/new" in (pg.get_attribute("#empty a", "href") or "") and pg.evaluate("document.querySelectorAll('.hw').length") == 0, "empty search offers a GitHub suggestion link")
        pg.fill("#q", "<b>x</b>"); pg.wait_for_timeout(100)
        check(pg.evaluate("!document.querySelector('#empty b')"), "search text is escaped")
        pg.fill("#q", "punjab"); pg.wait_for_timeout(200)
        check(pg.evaluate("[...document.querySelectorAll('.hw h3')].map(h => h.textContent)") == ["Delhi–Amritsar–Katra Expressway"], "search by state finds the highway")
        pg.fill("#q", ""); pg.wait_for_timeout(200)
        scroll_through(pg)
        check(pg.evaluate("[...document.querySelectorAll('#home [data-reveal], .hw')].every(n => getComputedStyle(n).opacity === '1')"), "home sections fully revealed after scrolling")
        trust = pg.evaluate("[...document.querySelectorAll('#trustgrid .big')].map(b => b.textContent)")
        trust_p = pg.evaluate("document.querySelector('#trustgrid p').textContent")
        check(trust == ["66 / 70", "km 210", "10 m"] and "paved by 2026\u00a0Q1, the quarter before it opened (29 April 2026)" in trust_p,
              f"trust section: {trust}; {trust_p[:90]}")
        foot = pg.text_content("#foot1")
        check("Built by" in foot and "@Elmozoop" in foot and "page built" in foot and "Satellite images to 2026 Q3" in foot and "@gmail" not in pg.content(), "footer credits the author and shows freshness")
        check(no_broken_images(pg), "no broken images on the home page")
        check(not dots_outside_mono(pg), f"no zero-width middle dots on the home page {dots_outside_mono(pg)}")
        pg.evaluate("document.getElementById('trust').scrollIntoView({behavior: 'instant'})"); pg.wait_for_timeout(600)
        pg.screenshot(path=OUT / "d5_trust.png")

        print("desktop: live project page")
        scroll_to(pg, 0); pg.wait_for_timeout(300); pg.click("#cta"); pg.wait_for_timeout(2800)
        check(pg.evaluate("!document.getElementById('view').hidden && document.getElementById('home').hidden") and pg.title().startswith("Delhi"), f"CTA opens Delhi–Amritsar–Katra, title '{pg.title()}'")
        check(pg.evaluate("location.hash") == "#delhi-amritsar-katra", "address bar points at the highway")
        check(pg.evaluate("[...document.querySelectorAll('#view [data-reveal]')].every(n => getComputedStyle(n).opacity === '1') && [...document.querySelectorAll('.g-bar')].every(b => new DOMMatrix(getComputedStyle(b).transform).a === 1)"),
              "highway page rests fully drawn before any scrolling")
        legend = pg.evaluate("[...document.querySelectorAll('#rblegend b')].map(b => parseInt(b.textContent))")
        rows = pg.evaluate("[...document.querySelectorAll('.g-row')].map(b => (b.querySelector('.g-label b').textContent + ' ' + b.querySelector('.g-label small').textContent + ' | ' + b.querySelector('.g-what').textContent).replace(/\\s+/g, ' '))")
        print("    " + "\n    ".join(rows))
        check(len(rows) == 5 and any("km 300–320" in r and "Earthwork since 2022 Q3" in r for r in rows), "stalled chart shows the km 300–320 earthwork")
        check(any("km 240–250" in r and "No earthwork yet" in r for r in rows), "stalled chart shows km 240–250 with no earthwork")
        check(any(r.startswith("km 230–240 4 of 5 pieces") for r in rows), "a group with another piece inside it says so (4 of 5 pieces)")
        note = pg.text_content("#stallcard .note")
        check(note.startswith("10 more pieces") and "3 in km" in note.replace("\u00a0", " "), f"tool misses are set apart and counted per place: '{note[:90]}…'")
        tiles = dict(pg.evaluate("[...document.querySelectorAll('.tile')].map(t => [t.dataset.st, t.getAttribute('aria-pressed')])"))
        check(len(tiles) == 6 and tiles.get("km300-320") == "true", f"6 stretch tiles, the biggest stall selected: {tiles}")
        check(pg.text_content("#sdetail h3").startswith("km 300–320"), "the selected stretch is shown in detail")
        check(pg.evaluate("document.querySelectorAll('#ovsvg .pc').length") == 60, "overview draws all 60 pieces")
        check(pg.evaluate("(() => { const s = document.getElementById('ovsel'); return +s.getAttribute('width') > 0; })()"), "overview brackets the selected stretch")
        other = pg.get_attribute(".tile[aria-pressed='false']", "data-st")
        pg.click(f".tile[data-st='{other}']"); pg.wait_for_timeout(700)
        check(pg.get_attribute(f".tile[data-st='{other}']", "aria-pressed") == "true" and pg.text_content("#sdetail h3").startswith(pg.text_content(f".tile[data-st='{other}'] b")), f"clicking a tile opens {other}")
        pg.click(".g-row:has-text('km 300–320')"); pg.wait_for_timeout(1400)
        check(pg.text_content("#sdetail h3").startswith("km 300–320"), "clicking a stalled row opens that stretch")
        pg.evaluate("document.getElementById('hwCmp').scrollIntoView({behavior: 'instant', block: 'center'})"); pg.wait_for_timeout(700)
        check(pg.evaluate("document.querySelectorAll('.place').length") == 2 and imgs_ok(pg, "#hwCmp img"), "two places to compare, images loaded")
        first_src = pg.get_attribute("#hwCmp img.after", "src")
        pg.click(".place[data-i='1']"); pg.wait_for_timeout(900)
        check(pg.get_attribute("#hwCmp img.after", "src") != first_src and "Punjab" in pg.text_content(".place[aria-pressed='true']") and imgs_ok(pg, "#hwCmp img"), "switching place swaps the images")
        with pg.expect_download() as dl:
            pg.click("#csv")
        data = list(csv.reader(io.StringIO(pathlib.Path(dl.value.path()).read_text(encoding="utf-8-sig"))))
        check(data[0][:5] == ["piece", "stretch", "first earthwork", "first paved", "stage in 2026 Q3"] and len(data) == 61 and len(data[0]) == 32, f"CSV has a header and 60 pieces × 27 quarters ({len(data) - 1})")
        check(dl.value.suggested_filename == "delhi-amritsar-katra-stages.csv", "CSV file name")
        paved = sum(r[4] == "Paved" for r in data[1:])
        check(sum(legend) == 120 and legend[0] == 2 * paved, f"road bar legend {legend} km adds up to 120 and matches the CSV's {paved} paved pieces")
        check(pg.text_content("#bigPct") == f"{round(100 * paved / 60)}%", f"big number {pg.text_content('#bigPct')} is the paved share")
        scroll_to(pg, 0); pg.wait_for_timeout(300); pg.click("#share"); pg.wait_for_timeout(400)
        copied = pg.evaluate("navigator.clipboard.readText()")
        check(copied.endswith("#delhi-amritsar-katra") and not pg.is_hidden("#toast"), "share copies the page link")
        pg.screenshot(path=OUT / "d6_live_top.png")
        scroll_through(pg)
        check(pg.evaluate("[...document.querySelectorAll('#view [data-reveal]')].every(n => getComputedStyle(n).opacity === '1')"), "highway page sections fully revealed")
        check(pg.evaluate("[...document.querySelectorAll('.g-bar')].every(b => new DOMMatrix(getComputedStyle(b).transform).a === 1)"), "stalled bars grew to full length")
        check(pg.evaluate("[...document.querySelectorAll('#ovsvg .pc')].every(r => getComputedStyle(r).opacity === '1')"), "overview pieces faded in")
        check(float(pg.evaluate("document.querySelector('#wipe rect').getAttribute('width')")) > 700, "area chart wiped in")
        check(no_broken_images(pg), "no broken images on the highway page")
        check(not dots_outside_mono(pg), f"no zero-width middle dots on the highway page {dots_outside_mono(pg)}")
        pg.screenshot(path=OUT / "d7_live_full.png", full_page=True)
        scroll_to(pg, 0); pg.wait_for_timeout(300)
        pg.click("#play"); pg.wait_for_timeout(1500)
        # read the quarter and press pause in one go: a separate read and click can straddle the next step (every 320 ms)
        q = pg.evaluate("() => { const q = document.getElementById('qlab').textContent; document.getElementById('play').click(); return q; }"); pg.wait_for_timeout(700)
        check(q == pg.text_content("#qlab") and q != "2026 Q3", f"timeline plays and pauses ({q})")
        check(pg.text_content("#bigTxt").endswith(q), "the headline number follows the timeline")
        pg.click("#back"); pg.wait_for_timeout(1500)
        check(pg.evaluate("!document.getElementById('home').hidden && document.getElementById('view').hidden") and pg.title() == "Expressway Watch" and pg.evaluate("location.hash") == "", "back returns home and restores the title and address")
        s = explainer(pg, 0.45)
        check(s["q"] == "2023 Q1" and s["filled"] == 13, "explainer still works after coming back")
        at(pg, "#story", 0.6); check(pg.text_content("#chapter h2") != "", "story still works after coming back")
        at(pg, "#story", 0.55, 1000)
        words, chip, q_on_map = pg.evaluate("[document.querySelector('#chapter p').textContent.replace(/\\s+/g, ' '), [...document.querySelectorAll('#storychips span')].find(s => s.textContent.startsWith('Earthwork')).textContent.replace(/\\s+/g, ' '), document.getElementById('storyq').textContent]")
        check(f"In {q_on_map}, " in words and chip.split()[-1] in words, f"story words match the map and chips: '{words[-60:]}' / {chip} / {q_on_map}")

        print("desktop: finished project page")
        pg.goto("about:blank"); pg.goto(URL + "#ganga-expressway"); pg.wait_for_timeout(120)
        check(pg.evaluate("getComputedStyle(document.getElementById('home')).display === 'none' && !document.getElementById('view').hidden"), "a link to a highway opens it without the home page showing first")
        check(pg.evaluate("!document.querySelector('#scopeImg img.cur').complete || document.querySelector('#scopeImg img.cur').loading === 'lazy'"), "  and without fetching the home page's time-lapse")
        check(pg.evaluate("I3.pending && !I3.sc && !window.THREE"), "  or building the 3D opening scene, or fetching three.js")
        pg.wait_for_timeout(2700)
        check(pg.title().startswith("Ganga"), f"opens straight from the link, title '{pg.title()}'")
        checks = pg.evaluate("[...document.querySelectorAll('.check')].map(c => c.textContent.replace(/\\s+/g, ' '))")
        check(len(checks) == 2 and any("66 of 70 pieces paved by 2026 Q1, before it opened" in c for c in checks), f"'Did it get it right?' compares 2 reported dates: {checks}")
        check(pg.evaluate("!document.getElementById('stallcard')") and "Worth a second look" in pg.content(), "finished road has no stalled chart, keeps its misses card")
        check(pg.evaluate("document.querySelectorAll('.tile').length") == 7 and pg.evaluate("document.querySelectorAll('#ovsvg .pc').length") == 70, "7 stretch tiles and 70 pieces")
        pg.evaluate("document.getElementById('hwCmp').scrollIntoView({behavior: 'instant', block: 'center'})"); pg.wait_for_timeout(700)
        check(pg.evaluate("document.querySelectorAll('.place').length") == 0 and imgs_ok(pg, "#hwCmp img"), "single place, images loaded")
        scroll_through(pg); pg.screenshot(path=OUT / "d8_ganga_full.png", full_page=True)
        scroll_to(pg, 0); pg.click("#back"); pg.wait_for_timeout(1600)
        check(pg.evaluate("!document.getElementById('home').hidden") and imgs_ok(pg, "#scopeImg img") and pg.evaluate("document.querySelectorAll('#chS .ex-cell').length") == 27,
              "coming home from a shared link draws the home page (time-lapse, explainer)")
        wake(pg); check(pg.evaluate("!!I3.sc && I3.mode === 'motion' && !I3.pending"), "  and builds the 3D opening scene")
        s = explainer(pg, 0.45); check(s["q"] == "2023 Q1" and s["filled"] == 13, "  and the explainer follows the scroll")
        at(pg, "#story", 0.6); check(pg.evaluate("document.querySelectorAll('#storymap text').length") >= 4 and pg.text_content("#chapter h2") != "", "  and the story map is drawn with its labels")
        ctx.close()

        for name, (w, h) in [("phone390", (390, 844)), ("phone360", (360, 740)), ("landscape844", (844, 390)), ("landscape667", (667, 375))]:
            print(name)
            ctx, pg = new_page(b, name, viewport={"width": w, "height": h}, is_mobile=True, has_touch=True, device_scale_factor=2)
            pg.goto(URL); pg.wait_for_timeout(3600)
            check(pg.evaluate("innerWidth") == w, "page is laid out at the phone's width (viewport tag works)")
            check(overflow(pg) == 0, "no sideways scroll on home")
            if w < 600:
                check(pg.evaluate("(() => { const b = [...document.querySelectorAll('#herostats b')].map(x => x.getBoundingClientRect()); return b.every(r => r.height < 40 && Math.abs(r.left - b[0].left) < 1) && b[1].top > b[0].bottom; })()"), "hero stats stack as a list, numbers on one line")
            check(pg.evaluate("getComputedStyle(document.querySelector('.nav')).display === 'none'") == (w <= 520), "top links hidden only on narrow phones")
            wake(pg); s = pg.evaluate(INTRO_STATE)
            check(s["mode"] == "motion" and s["title"] > .95 and canvas_contrast(pg, OUT / f"{name}_0canvas.png") > 18, "opening scene draws the road beside its title")
            no_jumps(pg, "  ")
            pg.screenshot(path=OUT / f"{name}_0intro.png")
            for f in (0.11, 0.30, 0.45):
                intro_at(pg, f); s = pg.evaluate(INTRO_STATE)
                check(labels_clear(s) and clear_of_caption(s) and s["chips"][2] <= s["W"] + .5 and s["capbox"] and s["capbox"][2] <= s["W"] + .5 and s["capbox"][3] <= s["chips"][1],
                      f"opening scene at {f}: {len(s['labels'])} labels on screen, clear of the model, of each other and of the caption; model clear of the caption, caption above the stage chips")
                if h < 520: check(s["model"][0] >= s["capbox"][2] + 4, "  held sideways, the model stays beside the words, not under them")
                pg.screenshot(path=OUT / f"{name}_0intro_{f:.2f}.png")
            for f in (0.72, 1.0):
                intro_at(pg, f); s = pg.evaluate(INTRO_STATE)
                check(clear_of_caption(s) and s["model"][0] >= -.5 and s["model"][1] <= s["W"] + .5, f"opening scene at {f}: the model is on screen and clear of the caption")
                pg.screenshot(path=OUT / f"{name}_0intro_{f:.2f}.png")
            pg.evaluate("document.getElementById('hero').scrollIntoView({behavior: 'instant'})"); pg.wait_for_timeout(2600)
            pg.screenshot(path=OUT / f"{name}_1hero.png")
            pinned_scenes_fit(pg, name)
            at(pg, "#story", 0.55, 700); pg.screenshot(path=OUT / f"{name}_3story.png")
            for f in (0.02, 0.45):
                at(pg, "#scene", f, 900); pg.screenshot(path=OUT / f"{name}_2explainer_{f:.2f}.png")
            check(pg.evaluate("Math.min(...[...document.querySelectorAll('#dots button, .t-dot')].map(b => b.getBoundingClientRect().height))") >= 24, "story and time-lapse buttons are 24px+ touch targets")
            for hid in ("delhi-amritsar-katra", "ganga-expressway"):
                load(pg, URL + "#" + hid, 2600)
                scroll_through(pg, 500, 120)
                check(overflow(pg) == 0, f"no sideways scroll on {hid}")
                check(pg.evaluate("(() => { const s = document.querySelector('#mini svg'), b = document.querySelector('#mini'); return s.getBoundingClientRect().width <= b.getBoundingClientRect().width + 1; })()"), "stretch grid fits the card")
                check(pg.evaluate("""(() => { const rows = {}; document.querySelectorAll('.tile').forEach(t => { const k = Math.round(t.getBoundingClientRect().top);
                    (rows[k] = rows[k] || []).push(t.querySelector('.t-cells').getBoundingClientRect().top); });
                    return Object.values(rows).every(v => Math.max(...v) - Math.min(...v) <= 1); })()"""), "tile contents line up across each row")
                check(pg.evaluate("Math.min(...[...document.querySelectorAll('.yr, .tile, .g-row, .place')].map(b => b.getBoundingClientRect().height))") >= 32, "buttons are 32px+ on a touch screen")
                check(pg.evaluate("(() => { const r = [...document.querySelectorAll('#area .ar-mst')].map(t => t.getBoundingClientRect()); return r.every((a, i) => r.every((b, j) => i >= j || a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)); })()"),
                      "progress chart milestone names don't overlap")
                pg.screenshot(path=OUT / f"{name}_{hid}.png", full_page=True)
            ctx.close()

        print("other screen sizes")
        for w, h in [(1920, 1080), (1366, 657), (1024, 600), (900, 800), (768, 1024)]:
            ctx, pg = new_page(b, f"{w}x{h}", viewport={"width": w, "height": h})
            pg.goto(URL); pg.wait_for_timeout(3000)
            check(overflow(pg) == 0, f"{w}×{h}: no sideways scroll")
            wake(pg); no_jumps(pg, f"{w}×{h}: ")
            for f in (0.11, 0.45, 0.72):
                intro_at(pg, f); s = pg.evaluate(INTRO_STATE)
                check((len(s["labels"]) == 6 or f != 0.45) and labels_clear(s) and clear_of_caption(s),
                      f"{w}×{h}: opening scene at {f}: labels on screen, clear of the model, of each other and of the caption; model clear of the caption")
                pg.screenshot(path=OUT / f"size_{w}x{h}_intro_{f:.2f}.png")
            pinned_scenes_fit(pg, f"{w}×{h}")
            ctx.close()

        print("dark mode")
        ctx, pg = new_page(b, "dark", viewport={"width": 1280, "height": 860}, color_scheme="dark")
        pg.goto(URL); pg.wait_for_timeout(2500)
        check(pg.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(10, 14, 20)", "dark page background")
        pg.evaluate("document.getElementById('pick').scrollIntoView({behavior: 'instant'})"); pg.wait_for_timeout(1200)
        pg.screenshot(path=OUT / "dark_picker.png")
        load(pg, URL + "#delhi-amritsar-katra", 2500); scroll_through(pg, 600, 150)
        check(pg.evaluate("getComputedStyle(document.querySelector('.card')).backgroundColor") == "rgb(19, 25, 35)", "cards switch to the dark surface")
        pg.screenshot(path=OUT / "dark_live.png", full_page=True); ctx.close()

        print("reduced motion")
        ctx, pg = new_page(b, "reduce", viewport={"width": 1280, "height": 860}, reduced_motion="reduce")
        pg.goto(URL); pg.wait_for_function("document.getElementById('intro').classList.contains('i3-ready')", timeout=15000); pg.wait_for_timeout(300)
        check(pg.evaluate("I3.mode === 'still' && document.getElementById('intro').classList.contains('i3-still') && !document.getElementById('i3static').classList.contains('sr-only')")
              and pg.evaluate("document.querySelectorAll('#i3static li').length") == 11 and canvas_contrast(pg, OUT / "reduce_canvas.png") > 18,
              "opening scene is a still picture, with the layers and stages listed")
        pg.wait_for_timeout(800); check(pg.evaluate("I3.raf === 0 && getComputedStyle(document.getElementById('i3stage')).position !== 'sticky'"), "  no animation loop, nothing pinned to the screen")
        pg.screenshot(path=OUT / "reduce_intro.png", full_page=False)
        check(pg.evaluate("getComputedStyle(document.querySelector('.hero h1 .line>span')).transform") == "none", "headline not animated")
        check(pg.evaluate("[...document.querySelectorAll('#herostats b')].map(b => b.textContent)") == ["260 km", "27", "94%"], "stats shown as final numbers")
        check(pg.text_content("#tq") == "2026 Q3" and pg.is_hidden("#tplay"), "time-lapse opens on the finished road, with no autoplay")
        pg.wait_for_timeout(3000); check(pg.text_content("#tq") == "2026 Q3", "time-lapse stays still")
        pg.click(".t-dot[data-k='0']"); pg.wait_for_timeout(300)
        check(pg.text_content("#tq") == "2020 Q1" and pg.get_attribute("#scopeImg img.cur", "src").endswith("2020Q1.jpg"), "year buttons still step through the images")
        s = explainer(pg, 0.5, 400)
        check(s["stage"] == "Earthwork" and s["filled"] > 0, "explainer follows the scroll without animation")
        load(pg, URL + "#delhi-amritsar-katra", 800)
        check(pg.evaluate("[...document.querySelectorAll('.g-bar')].every(b => getComputedStyle(b).transform === 'none')"), "stalled bars drawn at full length")
        ctx.close()

        print("single-file download (docs/dashboard.html)")
        ctx, pg = new_page(b, "single", viewport={"width": 1280, "height": 860})
        pg.goto(SINGLE); pg.wait_for_timeout(2600)
        check(pg.evaluate("Object.values(IMAGES).flat().every(p => Object.values(p.imgs).every(v => v.startsWith('data:image/jpeg')))"), "every satellite image is embedded")
        check(imgs_ok(pg, "#scopeImg img") and pg.evaluate("document.querySelectorAll('link[rel=preload]').length") == 0, "time-lapse shows without any other files")
        wake(pg); check(pg.evaluate("document.querySelectorAll('script[src]').length === 0 && I3.mode === 'motion' && !!I3.sc") and canvas_contrast(pg, OUT / "single_canvas.png") > 18,
                        "the 3D opening scene works from the single file (three.js inlined)")
        load(pg, SINGLE + "#delhi-amritsar-katra", 2600)
        pg.evaluate("document.getElementById('hwCmp').scrollIntoView({behavior: 'instant', block: 'center'})"); pg.wait_for_timeout(500)
        check(imgs_ok(pg, "#hwCmp img") and pg.evaluate("document.querySelectorAll('.g-row').length") == 5, "live project page works from the single file")
        ctx.close()

        print("no JavaScript")
        ctx, pg = new_page(b, "nojs", viewport={"width": 390, "height": 844}, java_script_enabled=False)
        pg.goto(URL); pg.wait_for_timeout(600)
        check(pg.is_visible(".noscript") and "GitHub" in pg.text_content(".noscript"), "explains that JavaScript is needed and links to GitHub")
        check(pg.is_visible(".hero h1") and "from space." in pg.text_content(".hero h1"), "the headline still shows")
        check(pg.is_visible("#brand1") and pg.text_content("#brand1") == "Expressway Watch", "so does the name at the top")
        check(not any(pg.is_visible(sel) for sel in ("#scope", ".ctas", "#pick", "#learn", "#story", "#trust", "#i3stage", "#i3static")), "parts that need JavaScript are hidden, not shown empty")
        pg.screenshot(path=OUT / "nojs.png"); ctx.close()

        print("no WebGL")
        b2 = p.chromium.launch(args=["--disable-webgl", "--disable-3d-apis"])
        ctx, pg = new_page(b2, "nowebgl", viewport={"width": 1280, "height": 860})
        pg.goto(URL); pg.wait_for_timeout(1500)
        check(pg.evaluate("I3.mode === 'none' && document.getElementById('intro').classList.contains('i3-none')") and pg.is_visible("#i3static") and pg.is_visible("#i3title") and not pg.is_visible("#i3canvas"),
              "without WebGL the opening scene is its title and the list of layers")
        check(overflow(pg) == 0, "  no sideways scroll")
        pg.screenshot(path=OUT / "nowebgl.png", full_page=True); ctx.close(); b2.close()

        print("print")
        ctx, pg = new_page(b, "print", viewport={"width": 1100, "height": 900})
        pg.goto(URL); pg.wait_for_timeout(1500); pg.emulate_media(media="print")
        check(pg.evaluate("getComputedStyle(document.getElementById('intro')).display") == "none", "the 3D opening scene is left out of print")
        pg.emulate_media(media="screen")
        pg.goto(URL + "#delhi-amritsar-katra"); pg.wait_for_timeout(2500)
        scroll_to(pg, 1200); pg.wait_for_timeout(250); scroll_to(pg, 0); pg.wait_for_timeout(300)       # charts part-way into their animation
        pg.emulate_media(media="print")
        check(pg.evaluate("""[...document.querySelectorAll('.g-bar')].every(b => getComputedStyle(b).transform === 'none')
          && [...document.querySelectorAll('#ovsvg .pc')].every(r => getComputedStyle(r).opacity === '1')
          && [...document.querySelectorAll('.chartbox [clip-path]')].every(g => getComputedStyle(g).clipPath === 'none')"""), "charts print complete even before they have animated")
        pg.emulate_media(media="screen"); scroll_through(pg, 700, 100)
        pg.emulate_media(media="print")
        check(pg.evaluate("getComputedStyle(document.querySelector('#view h1')).color") == "rgb(17, 17, 17)", "title prints dark on white")
        check(pg.evaluate("getComputedStyle(document.querySelector('.scrub')).display") == "none", "controls are hidden in print")
        pg.pdf(path=str(OUT / "print_live.pdf"), print_background=False)
        ctx.close()
        b.close()

    print("\npage errors:", errors or "none")
    print(f"{len(fails)} failed" if fails else "all checks passed", "· screenshots in", OUT)
    sys.exit(1 if fails or errors else 0)


if __name__ == "__main__":
    main()
