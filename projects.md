---
layout: default
title: Projects | Usnish Majumdar
permalink: /projects/
---

# Projects

{% for project in site.data.projects %}
<div class="project">
  {% if project.image %}<a href="{{ project.url }}"><img src="{{ project.image }}" alt="{{ project.title }}" class="project-thumb"></a>{% endif %}
  <h2><a href="{{ project.url }}">{{ project.title }}</a></h2>
  <p>{{ project.description }}</p>
  {% if project.repo %}<p class="project-meta"><a href="{{ project.repo }}">source on GitHub</a></p>{% endif %}
</div>
{% endfor %}
