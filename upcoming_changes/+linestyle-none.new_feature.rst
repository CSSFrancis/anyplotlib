Added ``linestyle="none"`` (also spelled ``"None"``) for a series drawn as
markers with no connecting line — matplotlib's scatter idiom,
``ax.plot(y, linestyle="none", marker="o")``.  An explicit ``linewidth=0``
now means the same thing; it previously fell back to the 1.5 default in the
renderer.
