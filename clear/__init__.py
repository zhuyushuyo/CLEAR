"""CLEAR — Cashflow, Loans, Expenses, Assets & Repayment.

The packages are split so that everything except the ``ui``-related modules
(theme, widgets, chart, dialogs, pages, store, main_window, app) is plain
Python and can be tested without Qt.
"""

from .info import APP_NAME, APP_VERSION

__all__ = ["APP_NAME", "APP_VERSION"]
