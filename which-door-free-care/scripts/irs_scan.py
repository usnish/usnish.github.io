"""Stage 1 of the build: pull every IRS Form 990 Schedule H out of the IRS
e-file bulk releases (TEOS XML downloads, 2024-2026 releases).

For each return that carries a Schedule H, keep the return header (EIN, legal
name, tax year), the Part V Section A list of hospital facilities, and each
Part V Section B policy block (one per facility or facility reporting group),
including line 13's "FPG family income limit for eligibility for free care".

Results are cached per zip file as JSON in _viz/cache/which_door/schedh/, so
the slow scan runs once. Imported by build_data.py; can also be run directly.
"""
import csv
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "_viz" / "cache" / "which_door"
IRS_DIR = ROOT / "_viz" / "cache" / "scout_afford" / "irs"   # shared download cache for the TEOS zips
SCAN_DIR = CACHE / "schedh"
RELEASES = [2024, 2025, 2026]
TEOS_PAGE = "https://www.irs.gov/charities-non-profits/form-990-series-downloads"
INDEX_URL = "https://apps.irs.gov/pub/epostcard/990/xml/{y}/index_{y}.csv"
UA = "usnish.github.io data viz build (contact via github.com/usnish)"

FAC_FIELDS = ["FacilityNum", "FacilityReportingGroupCd", "LicensedHospitalInd", "GeneralMedicalAndSurgicalInd",
              "ChildrensHospitalInd", "TeachingHospitalInd", "CriticalAccessHospitalInd", "ResearchFacilityInd",
              "EmergencyRoom24HrsInd", "EmergencyRoomOtherInd", "OtherDescribedInd", "OtherDescribedTxt", "StateLicenseNum"]
POL_FIELDS = ["FPGFamilyIncmLmtFreeDscntInd", "FPGFamilyIncmLmtFreeCarePct", "FPGFamilyIncmLmtDscntCarePct",
              "IncomeLevelCriteriaInd", "AssetLevelCriteriaInd", "MedicalIndigencyCriteriaInd", "InsuranceStatusCriteriaInd",
              "UnderinsuranceStatCriteriaInd", "ResidencyCriteriaInd", "OtherCriteriaInd", "MadePresumptiveEligDetermInd",
              "EligCriteriaExplainedInd"]
PART1_FIELDS = ["FPGReferenceFreeCareInd", "Percent100Ind", "Percent150Ind", "Percent200Ind", "FreeCareOtherPct"]


def curl(url, dest):
    dest = Path(dest)
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".part")
        subprocess.run(["curl", "-sSfL", "-A", UA, "-C", "-", "-o", str(tmp), url], check=True)
        tmp.rename(dest)
    return dest


def release_zips(year):
    """Zip URLs listed on the IRS TEOS download page for one release year."""
    page = CACHE / "teos_page.html"
    if not page.exists():
        curl(TEOS_PAGE, page)
    urls = sorted(set(re.findall(rf"https://apps\.irs\.gov/pub/epostcard/990/xml/{year}/[^\"']+\.zip", page.read_text("utf-8", "replace"))))
    return urls


def full_990_ids(year):
    """OBJECT_IDs of full Form 990 returns (Schedule H is only filed with a full 990), by batch zip."""
    path = curl(INDEX_URL.format(y=year), CACHE / f"index_{year}.csv")
    by_batch = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if r["RETURN_TYPE"].strip() == "990":
                by_batch.setdefault(r.get("XML_BATCH_ID", "").strip(), set()).add(r["OBJECT_ID"].strip())
    return by_batch


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _txt(el, path):
    x = el.find(path)
    return x.text.strip() if x is not None and x.text else None


def _name(el, tag):
    n = el.find(tag)
    if n is None:
        return None
    parts = [_txt(n, "BusinessNameLine1Txt"), _txt(n, "BusinessNameLine2Txt")]
    return " ".join(p for p in parts if p) or None


def parse_return(blob, oid):
    root = _strip_ns(ET.fromstring(blob))
    hdr = root.find("ReturnHeader")
    sh = root.find(".//IRS990ScheduleH")
    if hdr is None or sh is None:
        return None
    f990 = root.find(".//IRS990")
    out = {
        "oid": oid,
        "ein": _txt(hdr, "Filer/EIN"),
        "filer": _name(hdr.find("Filer"), "BusinessName") if hdr.find("Filer") is not None else None,
        "filer_state": _txt(hdr, "Filer/USAddress/StateAbbreviationCd"),
        "taxyr": _txt(hdr, "TaxYr"),
        "period_begin": _txt(hdr, "TaxPeriodBeginDt"),
        "period_end": _txt(hdr, "TaxPeriodEndDt"),
        "amended": _txt(f990, "AmendedReturnInd") if f990 is not None else None,
        "part1": {k: _txt(sh, k) for k in PART1_FIELDS},
        "fac": [], "pol": [],
    }
    for g in sh.findall("HospitalFacilitiesGrp"):
        d = {k: _txt(g, k) for k in FAC_FIELDS}
        d["name"] = _name(g, "BusinessName")
        d["addr"] = _txt(g, "USAddress/AddressLine1Txt")
        d["city"] = _txt(g, "USAddress/CityNm")
        d["state"] = _txt(g, "USAddress/StateAbbreviationCd")
        d["zip"] = _txt(g, "USAddress/ZIPCd")
        out["fac"].append(d)
    for g in sh.findall("HospitalFcltyPoliciesPrctcGrp"):
        d = {k: _txt(g, k) for k in POL_FIELDS}
        d["name"] = _name(g, "HospitalFacilityName")
        d["nums"] = [x.text.strip() for x in g.findall("FacilityNum") if x.text]
        d["refnums"] = [x.text.strip() for x in g.iter("FacilityRefNum") if x.text]
        out["pol"].append(d)
    return out


def _repack(src, infos, dest):
    """Write a plain (non-ZIP64) zip holding the given members' compressed bytes unchanged."""
    import struct
    central, off = [], 0
    with open(dest, "wb") as out:
        for info in infos:
            src.seek(info.header_offset)
            h = src.read(30)
            nlen, xlen = struct.unpack("<HH", h[26:30])
            src.seek(info.header_offset + 30 + nlen + xlen)
            data = src.read(info.compress_size)
            name = info.filename.rsplit("/", 1)[-1].encode()
            dt = h[10:14]
            local = (b"PK\x03\x04" + struct.pack("<HHH", 21, 0, info.compress_type) + dt +
                     struct.pack("<IIIHH", info.CRC, info.compress_size, info.file_size, len(name), 0) + name)
            out.write(local)
            out.write(data)
            central.append(b"PK\x01\x02" + struct.pack("<HHHH", 21, 21, 0, info.compress_type) + dt +
                           struct.pack("<IIIHHHHHII", info.CRC, info.compress_size, info.file_size, len(name), 0, 0, 0, 0, 0, off) + name)
            off += len(local) + len(data)
        cd = b"".join(central)
        out.write(cd)
        out.write(b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, len(infos), len(infos), len(cd), off, 0))


def scan_zip(args):
    url, keep = args
    name = url.rsplit("/", 1)[1]
    cache = SCAN_DIR / (name.replace(".zip", ".json"))
    if cache.exists():
        return name, len(json.loads(cache.read_text()))
    path = curl(url, IRS_DIR / name)
    rows, bad, deflate64 = [], 0, []

    def take(blob, oid):
        nonlocal bad
        if b"IRS990ScheduleH" not in blob:
            return
        try:
            r = parse_return(blob, oid)
        except ET.ParseError:
            bad += 1
            return
        if r:
            r["release"] = name[:4]
            r["batch"] = name[:-4]
            rows.append(r)

    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if not base.endswith(".xml"):
                continue
            oid = base.split("_")[0]
            if keep is not None and oid not in keep:
                continue
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                deflate64.append(info)  # the largest IRS zips use Deflate64, which Python can't decompress
                continue
            take(z.read(info), oid)
    if deflate64:
        # Info-ZIP's unzip can inflate Deflate64 but trips over these archives' ZIP64 directory, so copy
        # the raw compressed members into small, plain zip files and let unzip extract those.
        tmp = CACHE / ("tmp_" + name[:-4])
        tmp.mkdir(exist_ok=True)
        with open(path, "rb") as src:
            for i in range(0, len(deflate64), 1500):
                chunk = deflate64[i:i + 1500]
                mini = tmp / "mini.zip"
                _repack(src, chunk, mini)
                out = tmp / "x"
                subprocess.run(["unzip", "-qq", "-o", str(mini), "-d", str(out)], check=True)
                for info in chunk:
                    base = info.filename.rsplit("/", 1)[-1]
                    f = out / base
                    take(f.read_bytes(), base.split("_")[0])
                subprocess.run(["rm", "-rf", str(out), str(mini)], check=True)
        subprocess.run(["rm", "-rf", str(tmp)], check=True)
    cache.write_text(json.dumps(rows))
    if bad:
        print(f"  {name}: {bad} returns could not be parsed", file=sys.stderr)
    return name, len(rows)


def scan_all(procs=6):
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    IRS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for y in RELEASES:
        ids = full_990_ids(y)
        for u in release_zips(y):
            batch = u.rsplit("/", 1)[1][:-4]
            jobs.append((u, ids.get(batch)))  # None = no index entry for this batch: scan every file
    with Pool(procs) as p:
        for name, n in p.imap_unordered(scan_zip, jobs):
            print(f"  {name}: {n} Schedule H returns", flush=True)
    rows = []
    for u, _ in jobs:
        rows += json.loads((SCAN_DIR / u.rsplit("/", 1)[1].replace(".zip", ".json")).read_text())
    return rows


if __name__ == "__main__":
    rows = scan_all()
    print(len(rows), "Schedule H returns in", RELEASES)
