"""Password-protect a data visualization page for GitHub Pages.

GitHub Pages can't check passwords, so the page is encrypted instead: the plaintext
page in <page>/_src/index.html, plus every file under <page>/_src/data/, is bundled,
encrypted with AES-256-GCM under a key derived from the password (PBKDF2-SHA256), and
written to <page>/index.html as a small password form. The browser decrypts it with
the Web Crypto API and swaps in the real page; requests for data/... are answered
from the decrypted bundle, so the data never sits on the site in the clear.

Keep <page>/_src/ out of git (see .gitignore): the repository is public.
The password is read from the PAGE_PASSWORD environment variable, or prompted for.

Usage: python3 _viz/encrypt_page.py ma-cardiac-rehab   (needs: pip install cryptography)
"""
import base64
import getpass
import hashlib
import html
import json
import os
import re
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SITE = Path(__file__).resolve().parents[1]
ITERATIONS = 600_000

# Answers fetch("data/...") from the decrypted bundle; inserted at the top of the page's <head>
SHIM = """<script>(function () {
  var files = %s, real = window.fetch.bind(window);
  window.fetch = function (u, o) {
    var p = new URL(typeof u === "string" ? u : u.url, location.href).pathname;
    for (var k in files) if (p.slice(-k.length - 1) === "/" + k)
      return Promise.resolve(new Response(files[k], { headers: { "Content-Type": /\\.json$/.test(k) ? "application/json" : "text/csv" } }));
    return real(u, o);
  };
})();</script>"""

GATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="../assets/viz/viz.css">
<style>
  .gate {{ max-width: 420px; margin: 12vh auto 0; }}
  .gate h1 {{ font-size: 24px; margin: 0 0 6px; letter-spacing: -0.01em; }}
  .gate p {{ color: var(--muted); margin: 0 0 16px; }}
  .gate form {{ display: flex; gap: 8px; }}
  .gate input {{ flex: 1; font: inherit; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }}
  .gate button {{ font: inherit; padding: 8px 14px; border: 1px solid var(--accent); border-radius: 6px; background: var(--accent); color: var(--bg); cursor: pointer; }}
  .gate .err {{ color: var(--warn); font-size: 13px; min-height: 1.4em; margin-top: 8px; }}
</style>
</head>
<body>
<main>
  <a class="back" href="/">&larr; usnish.github.io</a>
  <div class="gate">
    <h1>{title}</h1>
    <p>This page is password-protected.</p>
    <form id="f">
      <input id="pw" type="password" autocomplete="current-password" aria-label="Password" placeholder="Password" autofocus>
      <button type="submit">Open</button>
    </form>
    <div class="err" id="err" role="alert"></div>
  </div>
</main>
<script type="application/octet-stream" id="payload">{payload}</script>
<script>
(function () {{
  var ITER = {iterations};
  function bytes(b64) {{ var s = atob(b64), a = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }}
  async function open(pw) {{
    var raw = bytes(document.getElementById("payload").textContent.trim());
    var base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
    var key = await crypto.subtle.deriveKey({{ name: "PBKDF2", salt: raw.slice(0, 16), iterations: ITER, hash: "SHA-256" }},
      base, {{ name: "AES-GCM", length: 256 }}, false, ["decrypt"]);
    var plain = await crypto.subtle.decrypt({{ name: "AES-GCM", iv: raw.slice(16, 28) }}, key, raw.slice(28));
    return new TextDecoder().decode(plain);
  }}
  document.getElementById("f").addEventListener("submit", async function (e) {{
    e.preventDefault();
    var err = document.getElementById("err"), btn = this.querySelector("button");
    if (!window.crypto || !crypto.subtle) {{ err.textContent = "This browser can't open protected pages (it needs HTTPS and Web Crypto)."; return; }}
    btn.disabled = true; err.textContent = "Opening…";
    try {{
      var page = await open(document.getElementById("pw").value);
      document.open(); document.write(page); document.close();
    }} catch (x) {{
      err.textContent = "That password didn't work."; btn.disabled = false;
    }}
  }});
}})();
</script>
</body>
</html>
"""


def main():
    page = SITE / sys.argv[1]
    src = page / "_src"
    doc = (src / "index.html").read_text(encoding="utf-8")
    files = {f.relative_to(src).as_posix(): f.read_text(encoding="utf-8")
             for f in sorted((src / "data").rglob("*")) if f.is_file()}
    shim = SHIM % json.dumps(files, separators=(",", ":")).replace("</", "<\\/")
    doc = re.sub(r"<head>", lambda m: m.group(0) + "\n" + shim, doc, count=1)
    title = re.search(r"<title>(.*?)</title>", doc, re.S).group(1).strip()

    pw = os.environ.get("PAGE_PASSWORD") or getpass.getpass("Page password: ")
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITERATIONS, dklen=32)
    blob = salt + iv + AESGCM(key).encrypt(iv, doc.encode("utf-8"), None)
    out = GATE.format(title=html.escape(title), payload=base64.b64encode(blob).decode(), iterations=ITERATIONS)
    (page / "index.html").write_text(out, encoding="utf-8")
    print(f"wrote {page / 'index.html'} ({len(out) / 1e3:.0f} KB; {len(files)} data files bundled)")


if __name__ == "__main__":
    main()
