"""Activity screen: Kimi's recent actions, API usage, and approvals."""

from __future__ import annotations

import json

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .widgets import Card, button, esc, label, run_async

STATUS_ROLE = {"completed": "success", "started": "info", "rejected": "danger", "failed": "danger",
               "interrupted": "warning"}
SOURCE_LABEL = {"mind": "Haiku", "instinct": "instinct", "fallback": "habit", "user": "you"}


class ActivityPage(QWidget):
    def __init__(self, runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(label("Activity and approvals", heading=True, role="h1"))

        top = QHBoxLayout()
        self.usage_card = Card("AI usage today")
        self.usage_text = label("")
        self.usage_card.add(self.usage_text)
        top.addWidget(self.usage_card, 1)
        self.approvals_card = Card("Waiting for your approval")
        self.approvals_box = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.approvals_box)
        self.approvals_box.setContentsMargins(0, 0, 0, 0)
        self.approvals_card.add(holder)
        self.approvals_card.add(label("Kimi can only prepare things to share. Nothing is sent or published "
                                      "unless you approve it here.", role="caption", muted=True))
        top.addWidget(self.approvals_card, 2)
        lay.addLayout(top)

        log_card = Card("Kimi's recent actions")
        self.log = QTreeWidget()
        self.log.setHeaderLabels(["When", "Action", "Chosen by", "Status", "Result / reason"])
        self.log.setRootIsDecorated(False)
        self.log.setAlternatingRowColors(True)
        self.log.setAccessibleName("Recent actions")
        hdr = self.log.header()
        for i in range(4):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        log_card.add(self.log, 1)
        log_card.add(label("'Haiku' means Claude Haiku 5.5 suggested it and Python validated it; 'instinct' and "
                           "'habit' are local behaviours that cost nothing. Rejected ideas were blocked by the "
                           "safety checks.", role="caption", muted=True))
        lay.addWidget(log_card, 1)
        self._log_sig = None
        self._approval_sig = None

    def refresh(self) -> None:
        rt = self.rt
        t = theme.tokens()
        today = rt.ledger.today_stats()
        s = rt.settings.get()
        cost = today.get("cost", 0.0) or 0.0
        self.usage_text.setText(
            f"<p><b>${cost:.4f}</b> of your ${s.daily_budget_usd:.2f} daily limit (estimated)</p>"
            f"<p>{today.get('requests', 0)} requests · {today.get('input', 0):,} input tokens "
            f"({today.get('cache_read', 0):,} from cache) · {today.get('output', 0):,} output tokens</p>"
            f"<p style='color:{t.ink_muted}'>AI status: {esc(rt.client.status.replace('_', ' '))}"
            f"{' - ' + esc(rt.client.status_detail) if rt.client.status_detail else ''}</p>"
        )
        rows = rt.db.query("SELECT * FROM action_log ORDER BY id DESC LIMIT 150")
        sig = (len(rows), rows[0]["id"] if rows else None, rows[0]["status"] if rows else None)
        if sig != self._log_sig:
            self._log_sig = sig
            self.log.clear()
            for r in rows:
                day = int(r["sim_minute"] // 1440) + 1
                m = int(r["sim_minute"] % 1440)
                try:
                    params = json.loads(r["params"] or "{}")
                except ValueError:
                    params = {}
                detail = r["reason"] or r["result"] or ""
                action = r["action"]
                extra = params.get("destination") or params.get("topic") or params.get("food") or params.get("title")
                if extra:
                    action = f"{action} ({str(extra)[:30]})"
                item = QTreeWidgetItem([f"Day {day} {m // 60:02d}:{m % 60:02d}", action,
                                        SOURCE_LABEL.get(r["source"], r["source"]), r["status"], detail])
                item.setForeground(3, QColor(getattr(t, STATUS_ROLE.get(r["status"], "ink"))))
                item.setToolTip(4, detail)
                self.log.addTopLevelItem(item)
        pending = rt.outbox.pending()
        asig = tuple(p["id"] for p in pending)
        if asig != self._approval_sig:
            self._approval_sig = asig
            while self.approvals_box.count():
                w = self.approvals_box.takeAt(0).widget()
                if w:
                    w.deleteLater()
            if not pending:
                self.approvals_box.addWidget(label("Nothing is waiting for approval.", muted=True))
            for item in pending:
                self.approvals_box.addWidget(self._approval_row(item))

    def _approval_row(self, item: dict) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(label(f"<b>{esc(item['title'])}</b>"))
        preview = item["body"][:300] + ("…" if len(item["body"]) > 300 else "")
        lay.addWidget(label(esc(preview), role="caption", muted=True))
        btns = QHBoxLayout()
        email = button("Open as email draft", tooltip="Opens a draft in your own mail program; you send it yourself",
                       slot=lambda: self._approve(item["id"], "email"))
        github = button("Publish to GitHub", tooltip="Commits the creation to Kimi's local repository and pushes it",
                        slot=lambda: self._approve(item["id"], "github"))
        github.setEnabled(bool(self.rt.settings.get().github_remote_url))
        decline = button("Decline", slot=lambda: self._decline(item["id"]))
        for b in (email, github, decline):
            btns.addWidget(b)
        btns.addStretch(1)
        holder = QWidget()
        holder.setLayout(btns)
        btns.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(holder)
        return w

    def _approve(self, item_id: int, method: str) -> None:
        item = self.rt.outbox.get(item_id)
        verb = "open an email draft for" if method == "email" else "publish to GitHub"
        if QMessageBox.question(self, "Approve sharing",
                                f"Do you want to {verb} this?\n\n{item['title']}\n\n{item['body'][:600]}",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        def done(result, error) -> None:
            if error is not None:
                QMessageBox.warning(self, "Kimi", f"That didn't work: {error}")
                return
            ok, message, url = result
            if url:
                QDesktopServices.openUrl(QUrl(url))
            (QMessageBox.information if ok else QMessageBox.warning)(self, "Kimi", message)
            self._approval_sig = None
            self.refresh()

        run_async(lambda: self.rt.approve_share(item_id, method), done)

    def _decline(self, item_id: int) -> None:
        self.rt.reject_share(item_id)
        self._approval_sig = None
        self.refresh()
