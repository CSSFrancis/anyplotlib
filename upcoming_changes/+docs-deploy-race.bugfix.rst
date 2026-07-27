Fixed the docs deployment racing itself on release. A push to ``main`` and its
release tag are different refs, so the ``docs-${{ github.ref }}`` concurrency
group put them in separate groups and both pushed to ``gh-pages`` at once; the
loser was rejected and its versioned directory never appeared, while
``switcher.json`` still advertised the version. The deploy job now uses a
ref-independent group so deployments queue instead.
