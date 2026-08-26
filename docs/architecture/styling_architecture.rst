Styling architecture
====================

The theming package owns ``ColorScheme``, palette resolution, and stylesheet
generation. Form and shared-widget services apply those values to generic Qt
surfaces.

Scope styling is derived from an application-supplied scope token and color
strategy. Enabled/disabled field styling is derived from the current form state.
Widgets consume the resulting presentation values; they do not decide domain
inheritance or persist colors as configuration semantics.

Applications may provide their own palette and scope-color adapter. Keep Qt
stylesheet construction and contrast rules in pyqt-reactive, while domain labels
and semantic status colors remain in the host.

``AccentChromeColorPolicy`` is the single contrast owner for dynamic
scope-accent buttons, help controls, and tree selections. Bright accents such
as the root scope's white identity project to neutral interactive chrome, so
selection text remains readable without changing the scope's border identity.

Application theming leaves ``QApplication`` on Qt's native style and derives
shared colors through its palette and stylesheet. Reapplying a scheme compares
the generated stylesheet with ``QApplication.styleSheet()`` before asking Qt to
repolish the widget tree. ``ThemedCheckBox`` owns the one platform-sensitive
indicator override at the leaf widget, while splitter visibility is declared by
the shared stylesheet. No Python ``QStyle`` replacement competes with Qt's
stylesheet style owner.
