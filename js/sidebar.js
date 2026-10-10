---
---
// Injects the site sidebar (_includes/sidebar.html) into pages hosted outside
// this repo, such as /biochemical-pathways-poster/, so their projects menu stays
// in sync with _data/projects.yml. Jekyll renders this file at build time.
//
// Usage: <header class="sidebar" data-site-sidebar>…fallback…</header>
//        <script src="/js/sidebar.js"></script>
{% capture sidebar %}{% include sidebar.html %}{% endcapture %}
(function () {
  var el = document.querySelector('[data-site-sidebar]');
  if (el) el.innerHTML = {{ sidebar | strip | jsonify }};
})();
