UI services
===========

pyqt-reactive services are small reusable operations around forms, windows,
polling, styling, signals, process tracking, and tree projections. They expose
explicit constructor dependencies and protocols so a host can assemble only
the capabilities it needs.

Representative groups include:

- parameter help, reset, value collection, and widget operations;
- field dispatch, signals, flags, and interval snapshot polling;
- scope color/token, window navigation, and code-document services;
- process tracking, server scanning, metrics, and presentation strategies;
- tree projection, aggregation, search, and rebuild coordination.

Services do not own host models. Domain validation, configuration topology,
function catalogs, execution policy, and persistence adapters belong to the
application. See :doc:`service_registry` and
:doc:`widget_protocol_system`.
