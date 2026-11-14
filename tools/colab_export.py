"""Run inside a finished Expressway Watch notebook (Colab) to carry the results home without a file download:

    import requests; exec(requests.get("https://raw.githubusercontent.com/Elmozoop/expressway-watch/main/tools/colab_export.py").text)

Prints one block of text (zip, base64) holding only what tools/build_dashboard.py reads from each stretch: the stage of every
piece in every quarter, and each piece's first-earthwork and first-paved quarters. A few kB instead of the full results zip,
so it can be copied out of the page. Unpack at home with:  python tools/colab_export.py unpack BLOCK.txt results/<prefix>"""
import base64, io, os, sys, zipfile, glob

def pack(out_root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d in sorted(glob.glob(f"{out_root}/km*-*")):
            tag = os.path.basename(d)
            import pandas as pd
            st, ms = f"{d}/segment_quarter_stats.csv", f"{d}/segment_milestones.csv"
            if not (os.path.exists(st) and os.path.exists(ms)):
                print(tag, "skipped: no results"); continue
            s = pd.read_csv(st)[["seg_id", "label", "km_start", "km_end", "period", "stage"]]
            z.writestr(f"{tag}/segment_quarter_stats.csv", s.to_csv(index=False))
            z.writestr(f"{tag}/segment_milestones.csv", pd.read_csv(ms).to_csv(index=False))
    return base64.b64encode(buf.getvalue()).decode()

def unpack(block_file, dest_prefix):
    txt = open(block_file, encoding="utf-8").read()
    data = txt.split("EW-BEGIN", 1)[1].split("EW-END", 1)[0]
    data = "".join(data.split())
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(data))) as z:
        for name in z.namelist():
            tag, fn = name.split("/", 1)
            os.makedirs(f"{dest_prefix}_{tag}", exist_ok=True)
            open(f"{dest_prefix}_{tag}/{fn}", "wb").write(z.read(name))
            print("wrote", f"{dest_prefix}_{tag}/{fn}")

if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "unpack":
    unpack(sys.argv[2], sys.argv[3])
else:
    b64 = pack(OUT_ROOT)
    print(f"{len(b64)} characters")
    print("EW-BEGIN" + b64 + "EW-END")
