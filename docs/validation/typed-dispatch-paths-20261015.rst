Typed dispatch and structural owner paths
=========================================

Owner: core-route-counts. Source baseline: ``19917ea`` on PyQt PR #33.
This is a source/library checkpoint, not installed application acceptance.

Cause and ownership
-------------------

Nested managers already carry absolute field IDs. The former dispatch factory
prepended each ancestor ID again. Real managers with either an empty root ID
or root ID ``config`` produced mutation address ``config.child.value`` but
notification address ``config.config.child.value``.

``FieldDispatchContext`` now stores one ``DottedFieldPath`` in ``field_path``.
Its existing source/root manager references remain distinct responsibilities.
``from_event`` binds through the source manager and obtains the root from the
existing form-tree index. State mutation, logging and both root signals consume
that same path. The factory, its two path fields, ancestor reconstruction and
separate root walk are deleted, without compatibility aliases.

``DottedFieldPath.child`` owns qualification. The existing manager binding now
returns that type. Declaration/type lookup, inline context, labels/help,
placeholders, resets, enabled actions and hierarchy/preview readers use the
owning operation instead of root/child string branches. Generic chrome and
validation readers use the path type directly, without requiring a private
manager method. The competing chrome/bridge path helpers and widget-creation
root walk are deleted. Display aliases, ScopeKey and structural paths remain
separate contracts.

``resolve_inline_dataclass_structural_target`` accepts a typed inline owner.
All three production callers retain it: manager flash routing and both scrolling
helpers. Exact-owner matching uses its value/field name; decoded structural
owners select children through ``direct_child_name``. The original
``StructuralFieldPath.relative_path`` reaches the cell resolver unchanged.
The existing whole-child visual fallback remains. The redundant caller-supplied
child hint, owner tuples, slices and rejoining are deleted.

Source evidence
---------------

The retained pre-edit evidence used NRA's syntax/family owners across the whole
PyQt production package and the paired dependency roots. A fresh pass over the
same 1,145 source modules reports 5,759 original declarations / 5,733 nominal
projections, compared with 5,760 / 5,734 before. The removed class is the dispatch
factory. All 26 unprojected classes remain explicitly OPEN; parse omissions: zero.
Dynamic aliases, external Qt bases, C3 and invocation effects are not established
by this census.

Searches over source/tests/docs find no old dispatch factory, source/root path
fields, structural child-hint keyword or deleted path/root helpers. Searches in
OpenHCS production source and the paired Toad/FormBridge/ObjectState source find
no external consumers of the changed private binding or resolver/context APIs.
This is a named-source search, not proof about dynamic aliases.

Verification and limits
-----------------------

* 85 focused PyQt checks passed in 3.32 seconds, serially under CPU affinity and
  reduced priority, using existing dependencies and an isolated Python 3.12
  verifier. Private identity/runtime pins were cleared for the final run.
* Real QApplication, ObjectState and ParameterFormManager instances cover empty
  and nonempty root IDs, normal/reset dispatch, actual reset_parameter, callback
  execution, reentrant dispatch suppression, and both root signals. Mutation and
  signals use exactly ``config.child.value``; no doubled state key is introduced.
* Real form-backed sectioned editors cover root/nested/deep typed owners,
  unrelated paths and indexed cell routing (row 0, column 1). Existing chrome,
  tree, navigation, viewport, reset/flash, projection and enabled-title checks
  are included. Reset lifecycle policy is otherwise unchanged.
* Whitespace checks pass. No build, dependency installation, global pin change,
  application installation or Settings/Sort acceptance occurred in this turn.
* Diagnostic ``0eea3abba9c24303c603e4b675117d06`` was inspected read-only: failed
  input 9481 remains failed after WebSocket close 1012. It was not replayed.
  The separate uncertain candidate/build attempt remains undisposed. The blocked
  persistent goal was not changed; Codex retains integration/installation.

Retained scratch belongs to core-route-counts under
``/home/ts/.cache/agent-scratch/core-native-formbridge``: ``dispatch-before-*``
records the original source/reproducer; ``remaining-source-9501-*-check.log`` and
``remaining-source-9501-{index.json,source-summary.txt,index-family-sites.json}``
record this checkpoint. These are unfinished-review evidence, not installed
application receipts. The disposable ``dispatch-check-env`` is retired after
checking for active borrowers; source and results remain.
