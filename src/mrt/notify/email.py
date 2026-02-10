from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from ..models import Alert
from .base import Notifier


@dataclass(slots=True)
class EmailNotifier(Notifier):
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    to_list: tuple[str, ...]
    use_tls: bool = True

    def channel(self) -> str:
        return "email"

    def send(self, alert: Alert) -> None:
        if not self.to_list:
            raise ValueError("EmailNotifier.to_list is empty")

        msg = EmailMessage()
        msg["Subject"] = f"[MRT] {alert.event.title}"
        msg["From"] = self.username
        msg["To"] = ", ".join(self.to_list)
        msg.set_content(alert.content)

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as client:
            if self.use_tls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(msg)

