import json, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
UA = {"User-Agent": "usnish.github.io data probe (mailto:usnishm@gmail.com)"}
def get(url):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90)
        b = r.read(); print(f"== {r.status} {len(b)}B {url}"); return b.decode("utf-8", "replace")
    except Exception as e:
        print(f"== ERR {url}: {e}"); return ""

def tables(xml, label):
    try:
        root = ET.fromstring(xml)
    except Exception as e:
        print("xml parse err", e); return
    for tw in root.iter("table-wrap"):
        cap = " ".join("".join(c.itertext()) for c in tw.iter("caption"))
        print(f"\n--- {label} TABLE {tw.get('id')}: {cap[:300]}")
        for tr in tw.iter("tr"):
            print(" | ".join(" ".join("".join(td.itertext()).split()) for td in tr if td.tag in ("td", "th")))
    for sm in root.iter("supplementary-material"):
        for m in sm.iter("media"):
            print("SUPP:", m.get("{http://www.w3.org/1999/xlink}href"))

for pmc in ["PMC5930133", "PMC4098712"]:
    x = get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmc}/fullTextXML")
    if not x:
        x = get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmc[3:]}")
    tables(x, pmc)

print("\n##### socrata all-domain search")
for q in ["cardiac rehabilitation", "rehabilitation medicare heart"]:
    t = get("https://api.us.socrata.com/api/catalog/v1?limit=30&q=" + urllib.parse.quote(q))
    try:
        for res in json.loads(t)["results"]:
            x = res["resource"]; print(f"  {res['metadata']['domain']} {x['id']} | {x['name']}")
    except Exception as e:
        print("  parse err", e)
