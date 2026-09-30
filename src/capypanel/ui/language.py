"""Switching the app's language live: our gettext catalog plus Qt's own translations
(standard buttons, context menus). Open windows update on Qt's LanguageChange event."""

import logging

from PySide6.QtCore import QCoreApplication, QEvent, QLibraryInfo, QTranslator

from capypanel.core import i18n

log = logging.getLogger(__name__)
_qt_translator: QTranslator | None = None


def apply(code: str) -> str:
    """Switch the language and tell every window. Returns the code in use."""
    global _qt_translator
    code = i18n.set_language(code)
    app = QCoreApplication.instance()
    if app is None:
        return code
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if code != i18n.DEFAULT_LANGUAGE:
        translator = QTranslator(app)
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{code}", folder):
            app.installTranslator(translator)
            _qt_translator = translator
        else:
            log.warning("Qt's own translations for %s not found in %s", code, folder)
    # Our texts don't come from a Qt translator, so announce the change ourselves: Qt passes
    # it on to every open window, whose changeEvent then retranslates.
    QCoreApplication.postEvent(app, QEvent(QEvent.Type.LanguageChange))
    return code
