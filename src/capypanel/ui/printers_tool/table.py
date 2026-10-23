"""The printer table: name, address, brand, model and tags; serial number and asset tag can be
shown from the column titles' right-click menu."""

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.printers.printer import info_of
from capypanel.ui.list_workspace.panels import ItemTable


class PrinterTable(ItemTable):
    ADDRESS, BRAND, MODEL, SERIAL, ASSET_TAG, TAGS = 1, 2, 3, 4, 5, 6
    COLUMNS = ("name", "address", "brand", "model", "serial", "asset_tag", "tags")
    HIDDEN = ("serial", "asset_tag")  # until the user shows them
    # Every column is searched while it shows; notes are searched too, but have no column.
    SEARCHED = frozenset(range(len(COLUMNS)))

    def retranslate(self) -> None:
        self.setHeaderLabels(
            [
                _("Name"),
                _("Address"),
                _("Brand"),
                _("Model"),
                _("Serial number"),
                _("Asset tag"),
                _("Tags"),
            ]
        )

    def row_texts(self, item: Host) -> list[str]:
        info = info_of(item)
        return [
            item.name,
            item.address,
            info.brand,
            info.model,
            info.serial,
            info.asset_tag,
            ", ".join(item.tags),
        ]

    def set_hidden_columns(self, keys: object) -> None:
        super().set_hidden_columns(keys if isinstance(keys, list) else list(self.HIDDEN))
