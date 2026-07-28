from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class EmailSender(Protocol):
    @property
    def is_enabled(self) -> bool: ...

    async def send(self, *, to: str, subject: str, body: str, html: Optional[str] = None) -> None:
        """Send a message. `body` is the plain-text part and is always required.

        When `html` is given the message goes out as multipart/alternative, so a client
        that cannot (or will not) render HTML still shows the text — which for a login
        code is the part that actually matters.
        """
        ...
