import threading
import time
import websocket
import json
from urllib.parse import urlencode
from resotolib.logger import log
from resotolib.event import EventType, remove_event_listener, add_event_listener, Event
from resotolib.args import ArgumentParser
from resotolib.jwt import encode_jwt_to_headers
from resotolib.core.ca import TLSData
from typing import Callable, Dict, Optional, Set

from resotolib.types import Json


class CoreEvents(threading.Thread):
    def __init__(
        self,
        resotocore_ws_uri: str,
        events: Optional[Set[str]] = None,
        message_processor: Optional[Callable[[Json], None]] = None,
        tls_data: Optional[TLSData] = None,
    ) -> None:
        super().__init__()
        self.ws_uri = f"{resotocore_ws_uri}/events"
        if events:
            query_string = urlencode({"show": ",".join(events)})
            self.ws_uri += f"?{query_string}"
        self.message_processor = message_processor
        self.tls_data = tls_data
        self.ws: Optional[websocket.WebSocketApp] = None
        self.shutdown_event = threading.Event()
        self.__connected = False

    def connected(self) -> bool:
        return self.__connected

    def __del__(self) -> None:
        remove_event_listener(EventType.SHUTDOWN, self.shutdown)

    def run(self) -> None:
        self.name = "eventbus-listener"
        add_event_listener(EventType.SHUTDOWN, self.shutdown)
        while not self.shutdown_event.is_set():
            log.debug("Connecting to resotocore event bus")
            try:
                self.connect()
            except Exception as e:
                log.error(e)
            time.sleep(1)

    def connect(self) -> None:
        log.debug(f"Connecting to {self.ws_uri}")
        headers: Dict[str, str] = {}
        if getattr(ArgumentParser.args, "psk", None):
            encode_jwt_to_headers(headers, {}, ArgumentParser.args.psk)
        self.ws = websocket.WebSocketApp(
            self.ws_uri,
            header=headers,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_ping=self.on_ping,
            on_pong=self.on_pong,
        )
        sslopt = None
        if self.tls_data:
            sslopt = {"ca_certs": self.tls_data.ca_cert_path}
        self.ws.run_forever(sslopt=sslopt, ping_interval=20, ping_timeout=10, ping_payload="ping")

    def shutdown(self, event: Optional[Event] = None) -> None:
        log.debug("Received shutdown event - shutting down resotocore event bus listener")
        self.shutdown_event.set()
        if self.ws:
            self.ws.close()

    def on_message(self, _: websocket.WebSocketApp, message: str) -> None:
        try:
            json_message: Json = json.loads(message)
        except json.JSONDecodeError:
            log.exception(f"Unable to decode received message {message}")
            return
        log.debug(f"Received event: {json_message}")
        if self.message_processor is not None and callable(self.message_processor):
            try:
                self.message_processor(json_message)
            except Exception:
                log.exception(f"Something went wrong while processing {message}")

    def on_error(self, _: websocket.WebSocketApp, e: Exception) -> None:
        log.debug(f"Event bus error: {e!r}")

    def on_close(self, _: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        self.__connected = False
        log.debug("Disconnected from resotocore event bus")

    def on_open(self, _: websocket.WebSocketApp) -> None:
        self.__connected = True
        log.debug("Connected to resotocore event bus")

    def on_ping(self, _: websocket.WebSocketApp, message: str) -> None:
        log.debug("Ping from resotocore event bus")

    def on_pong(self, _: websocket.WebSocketApp, message: str) -> None:
        log.debug("Pong from resotocore event bus")
