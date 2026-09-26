# Two stages: build the static site once with mkdocs-material (needs Python + pip
# installs), then serve just the resulting HTML/CSS/JS with plain nginx -- the running
# container never needs Python, pip, or the source markdown at all.
FROM python:3.12-slim AS build
WORKDIR /site
# mkdocs-rss-plugin pulls in GitPython, which refuses to even import without a real `git`
# binary on PATH (unrelated to whether the plugin's git-based dates are actually used here).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY mkdocs.yml hooks.py render_plots.py ./
COPY overrides ./overrides
COPY docs ./docs
# Must run before `mkdocs build` -- it rewrites ```matplotlib code blocks into plain HTML
# (a button + hidden image) and writes the rendered PNGs to docs/assets/plots/ so they
# already exist on disk before MkDocs decides which files to copy into the built site.
RUN python3 render_plots.py
RUN mkdocs build --strict

FROM nginx:alpine
COPY --from=build /site/site /usr/share/nginx/html
