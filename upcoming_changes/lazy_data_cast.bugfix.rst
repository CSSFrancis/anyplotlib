``Plot2D.set_data`` no longer makes a float64 copy of every incoming frame.
The float64 cast now happens lazily in the ``.data`` property (the only reader),
so a frame stream — e.g. scrubbing an in-situ movie — keeps the source dtype and
skips a ~12 ms float64 copy of a 4k frame per tick. ``.data`` still returns a
read-only float64 copy, unchanged for callers.
