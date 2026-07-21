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
