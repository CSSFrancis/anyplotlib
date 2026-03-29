{{ fullname | escape | underline}}

.. currentmodule:: {{ module }}

.. autoclass:: {{ objname }}
   :show-inheritance:

{% block methods %}
{% if methods %}
.. rubric:: Methods

.. autosummary::
   :nosignatures:

{% for item in methods %}
   ~{{ fullname }}.{{ item }}
{%- endfor %}

{% endif %}
{% endblock %}

{% block attributes %}
{% if attributes %}
.. rubric:: Attributes

.. autosummary::
   :nosignatures:

{% for item in attributes %}
   ~{{ fullname }}.{{ item }}
{%- endfor %}

{% endif %}
{% endblock %}
