---
layout: default
title: Projects | Usnish (Ush) Majumdar
description: "Projects by Usnish (Ush) Majumdar: interactive maps and charts built from public data about access to health care."
permalink: /projects/
---

# Projects

<p class="projects-intro">Interactive maps and charts built from public data about access to health care. Each page explains how its numbers were estimated and links to the data and build scripts behind it.</p>

{% for project in site.data.projects %}{% if project.items %}
<section class="project-group">
  <h2 class="project-group-title">{{ project.title }}</h2>
  {% for item in project.items %}{% include project-card.html project=item level=3 %}{% endfor %}
</section>
{% endif %}{% endfor %}

{% assign other_count = 0 %}{% for project in site.data.projects %}{% unless project.items %}{% assign other_count = other_count | plus: 1 %}{% endunless %}{% endfor %}
{% if other_count > 0 %}
<section class="project-group">
  <h2 class="project-group-title">Other</h2>
  {% for project in site.data.projects %}{% unless project.items %}{% include project-card.html project=project level=3 %}{% endunless %}{% endfor %}
</section>
{% endif %}
