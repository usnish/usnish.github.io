import io, subprocess, urllib.request, zipfile
UA = {"User-Agent": "usnish.github.io data probe (mailto:usnishm@gmail.com)"}
def get(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)
        b = r.read(); print(f"== {r.status} {len(b)}B {r.headers.get('content-type')} {url}"); return b
    except Exception as e:
        print(f"== ERR {url}: {e}"); return b""
pdf = b""
for u in ["https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5930133/supplementaryFiles",
          "https://europepmc.org/articles/PMC5930133/bin/NIHMS936313-supplement-Supplemental_Material.pdf",
          "https://pmc.ncbi.nlm.nih.gov/articles/instance/5930133/bin/NIHMS936313-supplement-Supplemental_Material.pdf",
          "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5930133/bin/NIHMS936313-supplement-Supplemental_Material.pdf"]:
    b = get(u)
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b)); print(z.namelist())
        for n in z.namelist():
            if n.lower().endswith(".pdf"): pdf = z.read(n)
    elif b[:4] == b"%PDF":
        pdf = b
    if pdf: break
if pdf:
    open("s.pdf", "wb").write(pdf)
    print(subprocess.run(["pdftotext", "-layout", "s.pdf", "-"], capture_output=True, text=True).stdout)
