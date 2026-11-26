---
title: Code and documentation conventions
status: current
updated: 2026-11-26
---

# Code and documentation conventions

> How docstrings and these pages are written, and how to turn them into a documentation site with MkDocs.

## Docstrings

Every module, class and function, private helpers and nested functions included, has a docstring in **Google style**, the style [mkdocstrings](https://mkdocstrings.github.io/python/) reads by default.

```python
def resumable_run(con, source: str, window_days: float):
    """An unfinished harvest of `source` young enough to resume.

    Args:
        con: An open store connection.
        source: The harvest source.
        window_days: The oldest a run may be, by its start time, to be resumed.

    Returns:
        The `runs` row of the latest harvest when it is still `running`
        (interrupted) or `partial` and started within `window_days`, else None.
    """
```

- **First line:** what it is or what it does, in one sentence. Say *why* in the paragraph after it when the reason isn't obvious, particularly where v3 did something else.
- **Sections:** `Args:` for every parameter (except `self`), `Returns:` or `Yields:`, and `Raises:` for exceptions the caller should expect. `Attributes:` on dataclasses. `Example:` with a fenced code block where it helps.
- **Markup:** Markdown, not reStructuredText. Code and names in backticks (`` `runs` ``, `` `citations.http.HttpClient` ``). No Sphinx roles such as `:func:`; mkdocstrings prints them literally.
- **Tests** have a one-line docstring saying what they check, written as a statement: "A harvest that loses most of its links is rejected ...". Test helpers and fakes are documented like other code.
- **Plain English**, British spelling, short sentences, as in the rest of the repository.

Two checks, neither of them part of CI yet:

```
pip install ruff griffe

# every module, class and function has a well-formed Google-style docstring
ruff check --isolated --select D --config "lint.pydocstyle.convention='google'" citations tests

# every parameter named under Args: exists (catches a stale docstring after a rename)
python - <<'PY'
import logging, griffe
logging.basicConfig()
package = griffe.load("citations", docstring_parser="google",
                      docstring_options={"warn_unknown_params": True, "warn_missing_types": False})
def visit(obj):
    if not obj.is_alias:
        if obj.docstring:
            obj.docstring.parsed      # logs a warning for each parameter that isn't in the signature
        for member in obj.members.values():
            visit(member)
visit(package)
PY
```

Both pass on the current code.

## These pages

- Each page starts with front matter: `title`, `status` (`current`, `draft` or `planned`) and `updated` (the date of the last real change).
- One subject per page, in the numbered section it belongs to (see the [index](../README.md)).
- The README stays short and links here. The specification pages (`2-specification/`) are what consumers rely on: change them in the same pull request as the code.
- Diagrams are Mermaid, which GitHub and MkDocs both render.
- Link to code by path (`citations/merge.py`), and to pull requests and issues by full URL.

[AGENTS.md](../../AGENTS.md) lists which page to update for which change.

## Publishing a site with MkDocs

Nothing in the repository depends on MkDocs; these pages read well on GitHub as they are. To build a site from them with an API reference generated from the docstrings, add a `docs` extra to `pyproject.toml`:

```toml
docs = ["mkdocs-material", "mkdocstrings[python]"]
```

then `mkdocs.yml` at the repository root:

```yaml
site_name: NERC EDS dataset citations
docs_dir: docs
theme:
  name: material
plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [.]
          options:
            docstring_style: google
            docstring_options:
              warn_missing_types: false   # not every function has type hints
            show_source: false
            members_order: source
            filters: ["!^_"]              # leave private helpers out of the site
markdown_extensions:
  - tables
  - admonition
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
```

and one page per module under `docs/reference/`, for example `docs/reference/harvest.md`:

```markdown
# citations.harvest

::: citations.harvest
```

```
pip install -e ".[docs]"
mkdocs serve        # http://127.0.0.1:8000
mkdocs build        # the site, in site/ (add it to .gitignore)
```

`docs/README.md` becomes the home page. Links from these pages to files outside `docs/` (the root README, AGENTS.md) work on GitHub but MkDocs warns about them; that is expected. This configuration was tried with MkDocs 1.6, mkdocs-material 9.8 and mkdocstrings-python 2.0, and builds every page and module with no other warnings. To publish it on GitHub Pages, add a workflow that runs `mkdocs gh-deploy`.
