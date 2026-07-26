``save_html`` / ``to_html`` / ``figure_state`` now capture overlay widgets at
their current positions; widget moves reach JS as targeted events that never
rewrite the panel traits, so a snapshot used to show every widget where it was
created.
