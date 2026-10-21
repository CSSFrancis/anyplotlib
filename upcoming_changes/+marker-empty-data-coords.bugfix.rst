Fixed empty marker groups (``offsets=np.zeros((0, 2))``) raising
``ValueError: offsets must be shape (N, 2)`` when created or updated with
``coords="data"``; an empty ``offsets=[]`` is now accepted in either frame.
