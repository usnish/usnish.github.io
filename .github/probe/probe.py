import json, re, sys, urllib.request, urllib.parse
UA = {"User-Agent": "Mozilla/5.0 (data probe; usnish.github.io)"}
def get(url, n=None):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
        b = r.read()
        print(f"== {r.status} {len(b)}B {url}")
        return b.decode("utf-8", "replace")
    except Exception as e:
        print(f"== ERR {url}: {e}")
        return ""

print("##### data.cdc.gov catalog search")
for q in ["cardiac rehabilitation", "cardiac rehab", "million hearts"]:
    t = get("https://api.us.socrata.com/api/catalog/v1?domains=data.cdc.gov&limit=50&q=" + urllib.parse.quote(q))
    try:
        for res in json.loads(t)["results"]:
            x = res["resource"]
            print(f"  {x['id']} | {x['name']} | updated {x.get('data_updated_at','')[:10]}")
            print(f"      cols: {', '.join(x.get('columns_name', [])[:25])}")
    except Exception as e:
        print("  parse err", e)

print("##### Beatty 2018 PMC tables")
t = get("https://pmc.ncbi.nlm.nih.gov/articles/PMC5930133/")
for m in re.finditer(r"<table.*?</table>", t, re.S):
    txt = re.sub(r"<[^>]+>", "|", m.group(0))
    txt = re.sub(r"\|+\s*\|*", "|", txt)
    print("TABLE:", txt[:6000])
for m in re.finditer(r'href="([^"]+\.(?:pdf|docx?|xlsx?|csv))"', t):
    print("LINK:", m.group(1))
