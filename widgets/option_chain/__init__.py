"""Option Chain widget — self-registers with WidgetRegistry on import."""

from app.widget_registry import WidgetDefinition, WidgetRegistry
from widgets.option_chain.option_chain_widget import OptionChainWidget

WidgetRegistry.register(
    WidgetDefinition(
        widget_id=OptionChainWidget.widget_id,
        display_name="Option Chain",
        category="Market Data",
        factory=OptionChainWidget,
        description="Live strike ladder with OI, Greeks, and IV",
    )
)
