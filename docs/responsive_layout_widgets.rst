Responsive layout widgets
=========================

The responsive layout system keeps related controls on one row while their
declared minimum widths fit, then moves complete control groups to a second row
when horizontal capacity is insufficient. It has no global enable switch and no
pixel threshold API.

Capacity is the authority
-------------------------

The shared width calculation uses each widget's ``minimumSizeHint()`` (falling
back to ``sizeHint()``), its explicit minimum width, layout margins, and spacing.
That makes the widgets' own size policies and content the authority. Callers do
not estimate label text, copy breakpoint constants, or branch on a window name.

Resize events schedule a layout check through a single-shot timer. A nonpositive
width is treated as an initial layout pass and does not force premature
wrapping. The visible second row participates in minimum and preferred height;
an empty second row stays hidden.

``ResponsiveTwoRowWidget``
--------------------------

``ResponsiveTwoRowWidget(parent=None, layout_config=None)`` owns two groups:

* left widgets always remain in row one;
* right widgets stay right-aligned in row one while the complete row fits, then
  move together to row two.

``layout_config`` must be a ``ParameterFormLayoutConfig`` and supplies margins
and spacing. The public composition methods are
``add_left_widget(widget, stretch=0)`` and
``add_right_widget(widget, stretch=0)``.

.. code-block:: python

   from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton, QWidget
   from pyqt_reactive.widgets.shared.responsive_layout_widgets import (
       ResponsiveTwoRowWidget,
   )

   parent = QWidget()
   row = ResponsiveTwoRowWidget(parent=parent)
   row.add_left_widget(QLabel("Search"))
   row.add_right_widget(QLineEdit(), stretch=1)
   row.add_right_widget(QPushButton("Reset"))

``ResponsiveParameterRow``
--------------------------

``ResponsiveParameterRow(parent=None, layout_config=None)`` specializes the
two-row owner for forms. ``set_label()`` applies the preferred size policy and
enables word wrapping for ``QLabel``. ``set_input()`` adds an expanding right
widget; ``set_reset_button()`` and ``set_help_button()`` add fixed right-side
actions.

Regular ``ParameterFormManager`` fields use this container automatically. There
is no setup call to enable responsiveness:

.. code-block:: python

   from dataclasses import dataclass

   from objectstate import ObjectState
   from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager

   @dataclass
   class ProcessingConfig:
       long_description_field_name: str = "default"

   state = ObjectState(ProcessingConfig(), scope_id="processing")
   form = ParameterFormManager(state)

``StagedWrapLayout``
--------------------

``StagedWrapLayout(parent=None, spacing=4)`` moves named widget groups as units.
``set_groups(groups, stay_priority, right_align_names=None)`` receives the visual
group order and the order in which groups should remain on row one while they
fit. The first priority group remains on row one; further groups join it only
when their combined minimum widths and spacing fit. Other groups appear on row
two in visual order.

Names in ``right_align_names`` receive leading stretch in whichever row contains
them. Names are layout identities supplied by the composing widget, not a
package-wide table of button labels.

``FormWindowActionHeader`` uses this owner for title/action composition, so top
actions remain one right-aligned row whenever their real minimum widths fit and
wrap only under actual pressure.

``FormWindowActionHeader``
--------------------------

``FormWindowActionHeader`` gives action groups semantic placement through
``HeaderActionGroupRole``:

* ``TITLE_COMPANION`` keeps controls such as Help beside the title;
* ``COMMIT`` keeps the commit group, such as Cancel and Save, at the top-right;
* ``AUXILIARY`` places actions such as Reset and View Code at the right while
  space permits and moves them together to the second row under pressure.

The roles are the authority for stay priority and right alignment. When any
group uses a role, every group must use one and callers must not also supply
manual ``stay_priority`` or ``right_aligned_group_ids``. The older explicit
placement arguments remain available only for role-free compositions.

.. code-block:: python

   from PyQt6.QtWidgets import QPushButton
   from pyqt_reactive.widgets.shared.form_window_action_header import (
       FormWindowActionHeader,
       HeaderAction,
       HeaderActionGroup,
       HeaderActionGroupRole,
   )

   header = FormWindowActionHeader(
       title_text="Configure RenderSettings",
       action_groups=[
           HeaderActionGroup(
               "help",
               [HeaderAction("help", QPushButton("Help"))],
               role=HeaderActionGroupRole.TITLE_COMPANION,
           ),
           HeaderActionGroup(
               "auxiliary",
               [HeaderAction("reset", QPushButton("Reset"))],
               role=HeaderActionGroupRole.AUXILIARY,
           ),
           HeaderActionGroup(
               "commit",
               [HeaderAction("save", QPushButton("Save"))],
               role=HeaderActionGroupRole.COMMIT,
           ),
       ],
   )

``HeaderAction.id`` provides stable lookup through ``header.action(id)``.
Call ``refresh_layout()`` after changing caller-owned action visibility. The
title label reports height-for-width, so genuine wrapping increases the header
height instead of clipping a second title line.

The header owns geometry only. Code-mode behavior belongs to the window's
:doc:`architecture/window_code_documents` driver, while save/cancel behavior
belongs to the composing form.

``ResponsiveGroupBoxTitle``
---------------------------

``ResponsiveGroupBoxTitle(parent=None)`` composes title, help, inline, and
right-action groups through ``StagedWrapLayout``. The help widget is inserted
with the title. Inline controls follow it, while right controls can move to the
second row and remain right-aligned.

``GroupBoxWithHelp`` creates this title compositor. Its methods preserve the
group semantics:

* ``addTitleInlineWidget()`` keeps a control with the title/help group;
* ``addTitleWidget()`` adds a right-side action that can move to row two; and
* ``addResetAllTitleWidget()`` records and adds the group reset action at that
  same right-side boundary.

.. code-block:: python

   from PyQt6.QtWidgets import QPushButton
   from pyqt_reactive.widgets.shared.clickable_help_components import (
       GroupBoxWithHelp,
   )

   group = GroupBoxWithHelp(
       title="Processing configuration",
       help_target=ProcessingConfig,
   )
   group.addTitleWidget(QPushButton("Reset all"))

Extension rules
---------------

* Express minimum usable width through the widget's size hints and size policy.
* Group controls that must move together before passing them to
  ``StagedWrapLayout``.
* Keep semantic action dispatch outside the layout owner; the layout only owns
  geometry and stable group placement.
* Do not reintroduce global wrapping flags, fixed pixel breakpoint parameters,
  or widget-specific breakpoint tables.
