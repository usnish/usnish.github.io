// Small shared helpers for the data visualization pages (needs d3 + topojson-client)
window.VK = (function () {
  const RAMP = ["#f1eef6", "#d8d2e8", "#bcb2d8", "#9c90c2", "#7b6fa6", "#5b5478", "#3b3550"];
  const projection = d3.geoAlbersUsa().scale(1300).translate([487.5, 305]); // matches us-atlas *-albers-10m
  const int = d3.format(",");
  const money = v => v == null || isNaN(v) ? "–" : (Math.abs(v) >= 1e9 ? "$" + (v / 1e9).toFixed(1) + "B"
    : Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(1) + "M" : Math.abs(v) >= 1e3 ? "$" + (v / 1e3).toFixed(0) + "K" : "$" + Math.round(v));

  function stats(el, items) {
    el.innerHTML = items.map(([k, v, s]) =>
      `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`).join("");
  }

  // County choropleth with state borders, hover tooltip and a legend.
  function countyMap({ svg, us, tooltip, wrap, html }) {
    const path = d3.geoPath();
    const counties = topojson.feature(us, us.objects.counties).features;
    const g = svg.append("g");
    const shapes = g.selectAll("path").data(counties).join("path").attr("class", "county").attr("d", path)
      .attr("fill", "var(--nodata)");
    svg.append("path").datum(topojson.mesh(us, us.objects.states, (a, b) => a !== b))
      .attr("fill", "none").attr("stroke", "var(--stroke)").attr("stroke-width", 1).attr("d", path).attr("pointer-events", "none");
    const overlay = svg.append("g");
    const legend = svg.append("g").attr("class", "legend").attr("transform", "translate(560,18)");
    const tip = d3.select(tooltip);
    const stateNames = new Map(topojson.feature(us, us.objects.states).features.map(f => [f.id, f.properties.name]));
    function show(e, f) {
      const [x, y] = d3.pointer(e, wrap);
      tip.html(html(f.id, `${f.properties.name}, ${stateNames.get(f.id.slice(0, 2)) || ""}`)).style("opacity", 1)
        .style("left", Math.min(x + 14, wrap.clientWidth - 270) + "px").style("top", Math.min(y + 14, wrap.clientHeight - 140) + "px");
      shapes.classed("active", d => d === f);
    }
    shapes.on("mousemove", show).on("mouseleave", () => { tip.style("opacity", 0); shapes.classed("active", false); });
    return {
      shapes, overlay, legend, stateNames, counties,
      fill(valueOf, color) { shapes.attr("fill", f => { const v = valueOf(f.id); return v == null || isNaN(v) ? "var(--nodata)" : color(v); }); },
      highlight(fips) { shapes.classed("active", f => f.id === fips); },
    };
  }

  // Quantile legend (equal-count bins); fmt formats the break values
  function legend(g, color, fmt, title, extra) {
    g.selectAll("*").remove();
    const w = 52;
    color.range().forEach((c, i) => g.append("rect").attr("x", i * w).attr("width", w).attr("height", 10).attr("fill", c));
    (color.quantiles ? color.quantiles() : color.thresholds ? color.thresholds() : color.domain()).forEach((t, i) =>
      g.append("text").attr("x", (i + 1) * w).attr("y", 24).attr("text-anchor", "middle").text(fmt(t)));
    g.append("text").attr("x", 0).attr("y", -6).text(title);
    if (extra) extra(g.append("g").attr("transform", "translate(0,40)"));
  }

  // Horizontal bars: rows = [{group?, label, value, note?}]
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

  return { RAMP, projection, int, money, stats, countyMap, legend, bars, pressButtons };
})();
