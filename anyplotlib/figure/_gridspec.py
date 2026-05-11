"""
figure/_gridspec.py
===================
Grid layout descriptors: GridSpec and SubplotSpec.
"""

from __future__ import annotations


class SubplotSpec:
    """Describes which grid cells a subplot occupies."""

    def __init__(self, gs: "GridSpec", row_start: int, row_stop: int,
                 col_start: int, col_stop: int):
        self._gs = gs
        self.row_start = row_start
        self.row_stop  = row_stop
        self.col_start = col_start
        self.col_stop  = col_stop

    def __repr__(self) -> str:
        return (f"SubplotSpec(rows={self.row_start}:{self.row_stop}, "
                f"cols={self.col_start}:{self.col_stop})")


class GridSpec:
    """Define a grid of subplot cells.

    Parameters
    ----------
    nrows, ncols : int
        Grid dimensions.
    width_ratios : list of float, optional
        Relative column widths (length ncols).  Defaults to equal widths.
    height_ratios : list of float, optional
        Relative row heights (length nrows).  Defaults to equal heights.

    Examples
    --------
    >>> gs = GridSpec(2, 3, width_ratios=[2, 1, 1])
    >>> spec = gs[0, :]          # top row spanning all columns
    >>> spec = gs[1, 1:3]        # bottom-right 2 columns
    """

    def __init__(self, nrows: int, ncols: int, *,
                 width_ratios: list | None = None,
                 height_ratios: list | None = None):
        self.nrows = nrows
        self.ncols = ncols
        self.width_ratios  = list(width_ratios)  if width_ratios  else [1] * ncols
        self.height_ratios = list(height_ratios) if height_ratios else [1] * nrows
        if len(self.width_ratios)  != ncols:
            raise ValueError("len(width_ratios) must equal ncols")
        if len(self.height_ratios) != nrows:
            raise ValueError("len(height_ratios) must equal nrows")

    def __getitem__(self, key) -> SubplotSpec:
        """Return a SubplotSpec for the given (row, col) index or slice pair.

        Matches matplotlib's GridSpec indexing exactly:
        - Integer index ``i`` selects a single row or column (negative indices
          count from the end, just like Python lists).
        - Slice ``start:stop`` selects rows/columns ``start`` up to (but not
          including) ``stop``.  The full-span slice ``:`` selects all rows or
          columns.
        - Step values other than 1 (or None) raise ``ValueError``.
        - Out-of-range or empty slices raise ``IndexError``.
        """
        if not isinstance(key, tuple) or len(key) != 2:
            raise IndexError("GridSpec requires a (row, col) index or slice pair")
        row_idx, col_idx = key

        def _resolve(idx, n, axis_name):
            if isinstance(idx, int):
                i = idx if idx >= 0 else n + idx
                if not (0 <= i < n):
                    raise IndexError(
                        f"{axis_name} index {idx} is out of bounds for size {n}"
                    )
                return i, i + 1
            if isinstance(idx, slice):
                start, stop, step = idx.indices(n)
                if step != 1:
                    raise ValueError(
                        f"GridSpec slices must have step 1 (got {step})"
                    )
                if start >= stop:
                    raise IndexError(
                        f"GridSpec slice {idx} produces an empty span on axis of size {n}"
                    )
                return start, stop
            raise IndexError(f"Invalid GridSpec index: {idx!r}")

        r0, r1 = _resolve(row_idx, self.nrows, "row")
        c0, c1 = _resolve(col_idx, self.ncols, "col")
        return SubplotSpec(self, r0, r1, c0, c1)

    def __repr__(self) -> str:
        return f"GridSpec({self.nrows}, {self.ncols})"
