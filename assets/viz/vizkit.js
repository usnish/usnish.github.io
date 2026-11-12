// Small shared helpers for the data visualization pages (needs d3 + topojson-client)
window.VK = (function () {
  const RAMP = ["#eff3ff", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#084594"];
  const projection = d3.geoAlbersUsa().scale(1300).translate([487.5, 305]); // matches us-atlas *-albers-10m
  const int = d3.format(",");
  const money = v => v == null || isNaN(v) ? "–" : (Math.abs(v) >= 1e9 ? "$" + (v / 1e9).toFixed(1) + "B"
    : Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : Math.abs(v) >= 1e3 ? "$" + (v / 1e3).toFixed(0) + "K" : "$" + Math.round(v));

  // Phones (and any screen this narrow) get tap-to-open cards instead of hover tooltips
  const SMALL = "(max-width: 600px)";
  const small = () => window.matchMedia(SMALL).matches;
  const CLOSE = `<button type="button" class="close" aria-label="Close">×</button>`;

  function stats(el, items) {
    el.innerHTML = items.map(([k, v, s]) =>
      `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`).join("");
  }

  // Scroll el into view only if part of it is off screen
  function reveal(el) {
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > window.innerHeight) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // County choropleth with state borders, an HTML legend above it, hover tooltips with a mouse,
  // and a detail card below the map when a county is tapped or picked from a list.
  // names: optional Map of fips -> county name for counties the map has no shape for (still selectable from a list)
  function countyMap({ svg, us, tooltip, wrap, html, names }) {
    const path = d3.geoPath();
    const counties = topojson.feature(us, us.objects.counties).features;
    const byId = new Map(counties.map(f => [f.id, f]));
    const g = svg.append("g");
    const shapes = g.selectAll("path").data(counties).join("path").attr("class", "county").attr("d", path)
      .attr("fill", "var(--nodata)");
    svg.append("path").datum(topojson.mesh(us, us.objects.states, (a, b) => a !== b))
      .attr("fill", "none").attr("stroke", "var(--stroke)").attr("stroke-width", 1).attr("d", path).attr("pointer-events", "none");
    const overlay = svg.append("g");
    // Kept for older callers; VK.legend draws into the HTML box instead, which stays readable on a phone
    const legend = svg.append("g").attr("class", "legend").attr("transform", "translate(560,18)");
    const legendBox = document.createElement("div");
    legendBox.className = "vk-legend";
    wrap.insertBefore(legendBox, svg.node());
    legend.node()._vkHtml = legendBox;
    const card = document.createElement("div");
    card.className = "vk-card";
    card.hidden = true;
    card.setAttribute("aria-live", "polite");
    wrap.appendChild(card);

    const tip = d3.select(tooltip);
    const stateNames = new Map(topojson.feature(us, us.objects.states).features.map(f => [f.id, f.properties.name]));
    const label = f => `${f.properties.name}, ${stateNames.get(f.id.slice(0, 2)) || ""}`;
    const nameOf = fips => byId.has(fips) ? label(byId.get(fips))
      : names && names.has(fips) ? `${names.get(fips)}, ${stateNames.get(fips.slice(0, 2)) || ""}` : null;
    let hovered = null, selected = null, pinned = false, touch = false, rows = null, rowFips = d => d.fips;

    function paint() {
      shapes.classed("active", f => f.id === hovered || f.id === selected);
      shapes.filter(f => f.id === hovered || f.id === selected).raise();
      if (rows) rows.classed("active", d => rowFips(d) === selected);
    }
    function place(x, y) {
      tip.style("left", Math.max(0, Math.min(x + 14, wrap.clientWidth - 270)) + "px")
        .style("top", Math.max(0, Math.min(y + 14, wrap.clientHeight - 140)) + "px");
    }
    function hideTip() { tip.style("opacity", 0).classed("pinned", false); pinned = false; }

    // Mouse hover (desktop). Touch taps go to the card instead, so no tooltip gets stuck over the map.
    shapes.on("pointermove", (e, f) => {
      if (e.pointerType !== "mouse" || small()) return;
      touch = false;
      const [x, y] = d3.pointer(e, wrap);
      tip.html(html(f.id, label(f))).classed("pinned", false).style("opacity", 1);
      pinned = false;
      place(x, y);
      hovered = f.id; paint();
    }).on("pointerleave", e => {
      if (e.pointerType !== "mouse") return;
      hovered = null; paint();
      if (!pinned) tip.style("opacity", 0);
    }).on("pointerdown", e => { touch = e.pointerType !== "mouse"; })
      .on("click", (e, f) => {
        if (!(touch || small())) return;
        select(f.id);
        // A card that opens below the fold after a map tap is scrolled just far enough to show it
        if (!card.hidden && card.getBoundingClientRect().bottom > window.innerHeight) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });

    function useCard() { return touch || small(); }
    function render() {
      const name = nameOf(selected), f = byId.get(selected);
      if (!name) return;
      if (useCard() || !f) { // no shape to pin a tooltip to: show the card below the map
        hideTip();
        card.innerHTML = CLOSE + html(selected, name);
        card.hidden = false;
        card.querySelector(".close").onclick = clear;
      } else {
        // Mouse users picking from a list: pin the tooltip at the county
        card.hidden = true;
        const c = path.centroid(f), sr = svg.node().getBoundingClientRect(), wr = wrap.getBoundingClientRect();
        const k = sr.width / (svg.node().viewBox.baseVal.width || 975);
        tip.html(CLOSE + html(selected, name)).classed("pinned", true).style("opacity", 1);
        pinned = true;
        place(sr.left - wr.left + c[0] * k, sr.top - wr.top + c[1] * k);
        tip.select(".close").on("click", clear);
      }
    }
    function select(fips, { scroll = false } = {}) {
      if (!nameOf(fips)) return;
      selected = fips; hovered = null;
      paint(); render();
      if (scroll) reveal(useCard() ? svg.node() : wrap);
    }
    function clear() {
      selected = null; card.hidden = true; hideTip(); paint();
    }
    // A tap or click anywhere else (not on a control, a county, the card or a list row) closes the detail
    document.addEventListener("click", e => {
      if (!selected) return;
      if (e.target.closest(".county, .vk-card, .tooltip, [data-vk-row], button, select, input, label, a")) return;
      clear();
    });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && selected) clear(); });

    return {
      shapes, overlay, legend, stateNames, counties,
      fill(valueOf, color) {
        shapes.attr("fill", f => { const v = valueOf(f.id); return v == null || isNaN(v) ? "var(--nodata)" : color(v); });
        if (selected) render(); // keep an open card in step with the measure shown
      },
      highlight(fips) { hovered = fips; paint(); },
      select, clear,
      // Make ranked-list rows hover-highlight, and tap/click/Enter to select, their county
      bindRows(sel, fipsOf = d => d.fips) {
        rows = sel; rowFips = fipsOf;
        sel.attr("tabindex", 0).attr("role", "button").attr("data-vk-row", "")
          .on("mouseenter", (e, d) => { hovered = fipsOf(d); paint(); })
          .on("mouseleave", () => { hovered = null; paint(); })
          .on("pointerdown", e => { touch = e.pointerType !== "mouse"; })
          .on("click", (e, d) => select(fipsOf(d), { scroll: true }))
          .on("keydown", (e, d) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(fipsOf(d), { scroll: true }); } });
        paint();
        return sel;
      },
    };
  }

  // Legend for a binned colour scale; fmt formats the break values. Drawn as HTML above the map
  // when countyMap made a box for it (normal text size at any screen width), else inside the SVG.
  function legend(g, color, fmt, title, extra) {
    g.selectAll("*").remove();
    const breaks = color.quantiles ? color.quantiles() : color.thresholds ? color.thresholds() : color.domain();
    const box = g.node()._vkHtml;
    if (box) {
      const n = color.range().length;
      box.innerHTML = `<div class="vk-legend-title">${title}</div>` +
        `<div class="vk-legend-scale">${color.range().map(c => `<span style="background:${c}"></span>`).join("")}</div>` +
        `<div class="vk-legend-ticks">${breaks.map((t, i) => `<span style="left:${(100 * (i + 1) / n).toFixed(3)}%">${fmt(t)}</span>`).join("")}</div>`;
      if (!extra) return;
    }
    const w = 52;
    color.range().forEach((c, i) => g.append("rect").attr("x", i * w).attr("width", w).attr("height", 10).attr("fill", c));
    breaks.forEach((t, i) =>
      g.append("text").attr("x", (i + 1) * w).attr("y", 24).attr("text-anchor", "middle").text(fmt(t)));
    g.append("text").attr("x", 0).attr("y", -6).text(title);
    if (extra) extra(g.append("g").attr("transform", "translate(0,40)"));
  }

  // Horizontal bars: rows = [{group?, label, value, note?}]. Below 600px the CSS puts each label on its own line.
  function bars(el, rows, { fmt = v => v.toFixed(1) + "%", max } = {}) {
    const m = max || d3.max(rows, r => r.value) || 1;
    let html = "", last;
    for (const r of rows) {
      if (r.group && r.group !== last) { html += `<div class="grp">${r.group}</div>`; last = r.group; }
      html += `<div class="lbl">${r.label}</div><div class="track"><div class="fill" style="width:${(100 * r.value / m).toFixed(1)}%;${r.color ? `background:${r.color}` : ""}"></div></div><div class="num">${fmt(r.value)}</div>`;
    }
    el.innerHTML = html;
  }

  function pressButtons(container, items, current, onClick, label = d => d.label, sub = d => d.sub) {
    d3.select(container).selectAll("button").data(items).join("button").attr("type", "button")
      .html(d => `${label(d)}${sub(d) ? `<span class="sub">${sub(d)}</span>` : ""}`)
      .attr("aria-pressed", d => d === current).on("click", (e, d) => onClick(d));
  }

  return { RAMP, projection, int, money, stats, countyMap, legend, bars, pressButtons, small, reveal, CLOSE };
})();
