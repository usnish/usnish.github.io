---
layout: default
title: Projects | Usnish (Ush) Majumdar
permalink: /projects/
---

# Projects

{% for project in site.data.projects %}
{% if project.items %}
<section class="project-group">
  <h2 class="project-group-title">{{ project.title }}</h2>
  {% for item in project.items %}{% include project-card.html project=item %}{% endfor %}
</section>
{% else %}
{% include project-card.html project=project %}
{% endif %}
{% endfor %}
