Filing Change Log Entries
=========================

anyplotlib uses `towncrier <https://towncrier.readthedocs.io/>`_ to manage its
changelog.  When you open a pull request that should appear in the next release
notes, add a short news **fragment file** to this directory as part of that PR.

Naming convention
-----------------

Each fragment is a plain ``.rst`` file named::

    {PR_number}.{type}.rst

where ``{PR_number}`` is the GitHub pull-request number and ``{type}`` is one
of:

=================  ==============================================================
Type               Use when …
=================  ==============================================================
``new_feature``    A user-visible capability has been added.
``bugfix``         A bug has been fixed.
``deprecation``    Something is deprecated and will be removed in a future release.
``removal``        A previously deprecated API has been removed.
``doc``            Documentation improved without any code change.
``maintenance``    Internal / infrastructure change invisible to end users.
=================  ==============================================================

Content guidelines
------------------

* **One sentence per file**, written in the **past tense**, from a user's
  perspective.
* Cross-reference the relevant class or function with a Sphinx role where
  it adds value.
* Do **not** include the PR number in the sentence body — towncrier appends
  the link automatically.

Examples
--------

``123.new_feature.rst``::

    Added :meth:`~anyplotlib.Axes.scatter` for rendering collections of circles
    with per-point radii and colours.

``124.bugfix.rst``::

    Fixed :meth:`~anyplotlib.Figure.savefig` raising ``ValueError`` when the
    ``dpi`` keyword was not supplied explicitly.

``125.deprecation.rst``::

    Deprecated the ``color`` keyword on :class:`~anyplotlib.Plot2D`; use
    ``facecolor`` instead.  ``color`` will be removed in a future release.

``126.removal.rst``::

    Removed ``Figure.tight_layout()``, which was deprecated since v0.1.0.

``127.doc.rst``::

    Expanded the getting-started guide with a pcolormesh walkthrough and
    performance tips.

``128.maintenance.rst``::

    Migrated the CI pipeline to ``uv`` for faster, reproducible dependency
    installation.

Previewing the changelog locally
---------------------------------

See what the next release notes would look like **without** modifying any
files or consuming any fragments::

    uvx towncrier build --draft --version 0.x.0

To actually build the changelog (done automatically by the
**Prepare Release** workflow — do not run this by hand unless you know what
you are doing)::

    uvx towncrier build --yes --version 0.x.0

