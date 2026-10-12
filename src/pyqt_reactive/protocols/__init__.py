"""
Widget contract definitions and adapters.

ABC-based widget contracts that eliminate duck typing in favor of
explicit, fail-loud inheritance-based architecture.
"""

from .widget_adapters import (
    CheckBoxAdapter,
    ComboBoxAdapter,
    DoubleSpinBoxAdapter,
    KeySequenceEditAdapter,
    LineEditAdapter,
    PlaceholderStateMixin,
    PyQtWidgetMeta,
    SpinBoxAdapter,
)
from .widget_protocols import (
    ChangeSignalEmitter,
    ChildFieldChromeRefreshable,
    ChildFieldIdentityProvider,
    ChildFieldNavigationTargetProvider,
    ChildFieldSemanticChromeRefreshable,
    ChildSubfieldNavigationTargetProvider,
    CurrentValueValidatable,
    DirtyMarkerSettable,
    EnumSelectable,
    InlineDataclassGroupBoxChromeProvider,
    InlineDataclassRootResettable,
    PlaceholderCapable,
    PlaceholderStateTrackable,
    RangeConfigurable,
    RawResolvedValueSettable,
    ResolvedValuePreviewSettable,
    ValueGettable,
    ValueSettable,
    WidgetCapability,
    WidgetCapabilityTagged,
    widget_capability_tags,
    widget_supports_capability,
)

__all__ = [
    "ValueGettable",
    "ValueSettable",
    "CurrentValueValidatable",
    "DirtyMarkerSettable",
    "ResolvedValuePreviewSettable",
    "RawResolvedValueSettable",
    "ChildFieldChromeRefreshable",
    "ChildFieldSemanticChromeRefreshable",
    "ChildFieldIdentityProvider",
    "ChildFieldNavigationTargetProvider",
    "ChildSubfieldNavigationTargetProvider",
    "InlineDataclassGroupBoxChromeProvider",
    "InlineDataclassRootResettable",
    "PlaceholderCapable",
    "PlaceholderStateTrackable",
    "WidgetCapability",
    "WidgetCapabilityTagged",
    "widget_capability_tags",
    "widget_supports_capability",
    "RangeConfigurable",
    "EnumSelectable",
    "ChangeSignalEmitter",
    "LineEditAdapter",
    "KeySequenceEditAdapter",
    "SpinBoxAdapter",
    "DoubleSpinBoxAdapter",
    "ComboBoxAdapter",
    "CheckBoxAdapter",
    "PlaceholderStateMixin",
    "PyQtWidgetMeta",
]
