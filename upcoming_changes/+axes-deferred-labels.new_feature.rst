Added :meth:`Axes.set_xlabel <anyplotlib.Axes.set_xlabel>`,
:meth:`~anyplotlib.Axes.set_ylabel` and :meth:`~anyplotlib.Axes.set_title`,
which work before a plot is attached: the axes keeps the labels and applies
them to the plot that is attached first and to any plot that later replaces
it (a second ``imshow``/``plot``/… call on the same axes).
