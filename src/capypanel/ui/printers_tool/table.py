"""The printer table: name, brand, model, address and tags; serial number and asset tag can be
shown from the column titles' right-click menu."""

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.printers.printer import info_of
from capypanel.ui.list_workspace.panels import ItemTable


class PrinterTable(ItemTable):
    BRAND, MODEL, ADDRESS, TAGS, SERIAL, ASSET_TAG = 1, 2, 3, 4, 5, 6
    COLUMNS = ("name", "brand", "model", "address", "tags", "serial", "asset_tag")
    HIDDEN = ("serial", "asset_tag")  # until the user shows them
    # Every column is searched while it shows; notes are searched too, but have no column.
    SEARCHED = frozenset(range(len(COLUMNS)))

    def retranslate(self) -> None:
        self.setHeaderLabels(
            [
                _("Name"),
                _("Brand"),
                _("Model"),
                _("Address"),
                _("Tags"),
                _("Serial number"),
                _("Asset tag"),
            ]
        )

    def row_texts(self, item: Host) -> list[str]:
        info = info_of(item)
        return [
            item.name,
            info.brand,
            info.model,
            item.address,
            ", ".join(item.tags),
            info.serial,
            info.asset_tag,
        ]

    def set_hidden_columns(self, keys: object) -> None:
        super().set_hidden_columns(keys if isinstance(keys, list) else list(self.HIDDEN))
