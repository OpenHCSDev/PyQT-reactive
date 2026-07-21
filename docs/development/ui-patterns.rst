UI extension patterns
=====================

State first
-----------

Forms render an ``ObjectState``. A reusable widget or service should consume
state, typed form contracts, or a host protocol rather than importing a host
application's domain classes.

Nominal widget selection
------------------------

Add field/widget behavior through the strategy declarations in
``pyqt_reactive.forms.widget_strategies`` and the protocol types in
``pyqt_reactive.protocols``. Do not create a second type-to-widget dictionary.

Service boundary
----------------

Services coordinate generic mechanics such as signals, navigation, field
changes, search, process status, or widget-tree projection. Host adapters own
domain semantics and translate them into the generic protocols.

Lifecycle
---------

- create or retrieve the authoritative ObjectState;
- construct the form or manager with explicit configuration;
- register cross-window signals for the manager lifetime;
- disconnect callbacks and release windows deterministically;
- keep long-running work outside the GUI thread.

Testing
-------

Use ``pytest-qt`` with an explicit ObjectState and color scheme. Test strategy
selection, state updates, cross-window propagation, and teardown separately.
