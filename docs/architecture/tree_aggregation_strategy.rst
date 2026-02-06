Tree Aggregation Strategy
=========================

Module
------

``pyqt_reactive.strategies.tree_aggregation``

Purpose
-------

Provide explicit, pluggable percent aggregation policies for recursive tree
structures.

Core Contracts
--------------

- ``TreeAggregationPolicyABC``
- ``TreeAggregationPolicyRegistry``

Built-in Policies
-----------------

- ``MeanTreeAggregationPolicy``: aggregate as arithmetic mean of children
- ``ExplicitPercentTreeAggregationPolicy``: preserve node-local percent

Why This Matters
----------------

Tree UIs often mix nodes that should be averaged (parent rollups) and nodes
that should remain explicit (leaf/detail progress). A typed policy registry
prevents hidden ad-hoc math and fails loudly on unknown policy IDs.

Usage
-----

1. Register policies in ``TreeAggregationPolicyRegistry``.
2. Assign policy ID per node type in domain builder code.
3. Aggregate recursively using ``registry.aggregate(...)``.

See Also
--------

- :doc:`tree_state_sync_system`
- :doc:`zmq_server_browser_widget`
