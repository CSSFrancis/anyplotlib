# anyplotlib 0.1.0 — Release Plan

Status as of 2026-06-12: `pyproject.toml` already says `0.1.0`, `CHANGELOG.rst`
already contains a `v0.1.0 (2026-04-12)` section, but **no git tag exists and
nothing is on PyPI** (the name `anyplotlib` is still available). The release
automation (`prepare_release.yml` → tag → `release.yml` OIDC publish) is built
and ready; what remains is mostly housekeeping.

## Phase 1 — Clean the working tree (blockers)

- [ ] **Decide on the uncommitted `anywidget_bridge.js` work** (+611 lines: a
      HyperSpy/Enthought-traits shim for Pyodide). It is experimental and
      unrelated to core plotting — either finish it on a feature branch or
      stash it. Don't let it ride into the release commit unreviewed.
- [ ] **Commit or drop `Examples/Interactive/plot_segment_by_contrast_advanced.py`**
      (untracked). If kept, it runs in docs CI — verify it executes.
- [ ] **Commit `uv.lock`** (currently untracked). CI uses `uv sync`; a
      committed lockfile makes CI and contributor environments reproducible.
- [ ] Commit the audit fixes from this session: `LICENSE`, packaging excludes,
      classifier/keywords, colormap-fallback fix, `Plot3D` geometry refactor,
      `vw` → `apl` alias standardization, README/AGENTS.md/FIGURE_ESM.md
      updates.

## Phase 2 — Reconcile the changelog and version

The Prepare Release workflow can only bump *up* from 0.1.0, so for this first
release do the changelog manually:

- [ ] Fold the three pending `upcoming_changes/` fragments (6, 9, 11) into the
      existing `v0.1.0` section of `CHANGELOG.rst` (or run
      `uvx towncrier build --version 0.1.0` after deleting the stale section),
      update the date, and delete the consumed fragments.
- [ ] Verify `docs/conf.py` `release` string matches `0.1.0`.
- [ ] Verify `docs/_root/switcher.json` has (or will get) a `v0.1.0` entry.

## Phase 3 — One-time PyPI setup

- [ ] On pypi.org, add a **pending trusted publisher**:
      Owner `CSSFrancis`, repo `anyplotlib`, workflow `release.yml`,
      environment `pypi` (matches the `environment:` block in release.yml).
- [ ] Create the `pypi` environment in the GitHub repo settings (release.yml
      references it; publishing fails without it).

## Phase 4 — Pre-tag verification

- [ ] CI green on `main` (tests.yml matrix: 3.10–3.13 × linux/mac/win, plus
      lowest-direct resolution job).
- [ ] `uv build`, then sanity-check the artifacts:
      `uvx twine check dist/*` and install the wheel in a fresh venv,
      `python -c "import anyplotlib"`. (After this session's packaging fix the
      wheel no longer ships `anyplotlib/tests/` and PNG baselines — confirm
      it is ~250 KB, not ~890 KB.)
- [ ] Build docs locally (`make html`) and click through the interactive
      gallery — the Pyodide bridge loads the wheel built from the release
      commit.
- [ ] Smoke-test in a real JupyterLab session: `subplots`, `imshow` + widget
      drag, `plot` + vline widget, `bar`, `plot_surface`, inset.

## Phase 5 — Ship

```bash
git fetch origin
git tag v0.1.0 origin/main
git push origin v0.1.0
```

This triggers `release.yml` (build → PyPI publish → GitHub Release with
changelog notes) and the docs deploy. Afterwards:

- [ ] Verify `pip install anyplotlib` works from a clean environment.
- [ ] Verify the GitHub Release notes rendered correctly.
- [ ] Check the versioned docs URL and the root redirect.

## Post-0.1.0 backlog (quality items from the audit, none blocking)

1. **Duplicate CI**: `ci.yml` and `tests.yml` both run pytest on every
   push/PR (ubuntu + 3.12 overlaps). Move the Codecov upload into the
   tests.yml ubuntu/3.12 job and delete `ci.yml`.
2. **Colormap fidelity**: with colorcet installed (a hard dependency),
   `"viridis"` silently renders as colorcet `bmy` and `"inferno"` as `kb`
   (black→blue) — visually very different from the matplotlib maps users
   expect. Consider embedding real 256-entry LUTs for the half-dozen most
   common matplotlib names (a few KB) instead of aliasing.
3. **Add a linter/formatter**: no ruff/flake8 config exists. Add `ruff`
   (lint + format) to the dev group and CI; the codebase is clean enough
   that adoption should be cheap.
4. **Coverage in `addopts`**: `--cov` on every local `pytest` run slows quick
   iterations and overwrites `coverage.xml`. Consider moving coverage flags
   into the CI invocation only.
5. **Typing**: annotations are partial (`_fig: object`, untyped dicts).
   If type-checking is a goal, add `py.typed` + mypy/pyright gradually.
6. **`Axes.imshow` silently drops RGB channels** (`data[:, :, 0]`). Either
   render RGB properly or raise with a clear message; silent channel
   dropping will surprise matplotlib users.
7. **`figure_esm.js` size** (~4,400 lines, one closure): consider an
   esbuild-based bundling step so the JS can live in modules while anywidget
   still receives a single `_esm` string. Until then, keep
   `FIGURE_ESM.md` regenerated (instructions are in its header).
8. **`Event` dataclass breadth**: plot-type-specific fields (`bar_index`,
   `ray`, `line_id`) live on the universal event. Fine at this scale; if
   event types grow, consider per-kind payload dataclasses.
9. **Large-scale 3-D rendering (WebGPU)**: scoped in `WEBGPU_PLAN.md` —
   phased, demand-gated, canvas fallback contract. Phase 0 (canvas cheats +
   `voxels_from_volume` resampling API) is worth shipping independently.
