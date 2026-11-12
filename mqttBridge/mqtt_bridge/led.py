"""Controllo facoltativo del ring RGB I2C del gateway DSGW-210."""

from __future__ import annotations

import fcntl
import logging
import os
import threading

_LOGGER = logging.getLogger(__name__)

I2C_SLAVE_FORCE = 0x0706
RING_ADDRESS = 0x23
ENABLE_REGISTER = 0x01
FRAME_REGISTER = 0x02
BREATH = (2, 4, 7, 11, 16, 22, 29, 37, 46, 56, 66, 76, 85, 92, 97, 100, 97, 92, 85, 76, 66, 56, 46, 37, 29, 22, 16, 11, 7, 4)
SPIN = ((100, 0, 0, 4, 12, 35), (35, 100, 0, 0, 4, 12), (12, 35, 100, 0, 0, 4),
        (4, 12, 35, 100, 0, 0), (0, 4, 12, 35, 100, 0), (0, 0, 4, 12, 35, 100))


class RingLED:
    """Il device non è obbligatorio: su host senza I2C il bridge resta operativo."""

    _COLORS = {
        "starting": (0, 40, 120),     # blu
        "pending": (180, 65, 0),     # ambra
        "connecting": (0, 100, 120), # ciano
        "online": (0, 120, 0),       # verde
        "reconnecting": (180, 65, 0),
        "error": (180, 0, 0),        # rosso
        "off": (0, 0, 0),
    }

    def __init__(self, enabled: bool = True, device: str = "/dev/i2c-0") -> None:
        self._enabled = enabled
        self._device = device
        self._fd: int | None = None
        self._state = "off"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._enabled:
            return
        try:
            fd = os.open(self._device, os.O_RDWR | os.O_CLOEXEC)
            fcntl.ioctl(fd, I2C_SLAVE_FORCE, RING_ADDRESS)
            self._fd = fd
            self._write(bytes((ENABLE_REGISTER, 0x3F)))
        except OSError as err:
            if "fd" in locals():
                os.close(fd)
            _LOGGER.info("Ring LED non disponibile (%s): continuo senza controllo LED", err)
            self._fd = None
            return
        self._thread = threading.Thread(target=self._animate, name="ring-led", daemon=True)
        self._thread.start()
        self.set_state("starting")

    def set_state(self, state: str) -> None:
        if state not in self._COLORS:
            raise ValueError(f"stato LED sconosciuto: {state}")
        if self._fd is None:
            return
        with self._lock:
            if state == self._state:
                return
            self._state = state
        if state in ("online", "error", "off"):
            self._solid(self._COLORS[state])
        _LOGGER.debug("Stato ring LED: %s", state)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _write(self, data: bytes) -> None:
        if self._fd is None:
            return
        try:
            os.write(self._fd, data)
        except OSError:
            _LOGGER.exception("Scrittura sul ring LED fallita; disabilito il driver")
            os.close(self._fd)
            self._fd = None

    def _frame(self, color: tuple[int, int, int], levels: tuple[int, ...]) -> None:
        red, green, blue = color
        values = bytearray((FRAME_REGISTER,))
        for index, level in enumerate(levels):
            r, g, b = red * level // 100, green * level // 100, blue * level // 100
            # Il cablaggio del ring DSGW scambia rosso e verde sui LED 4, 5 e 6.
            values.extend((r, b, g) if index >= 3 else (g, b, r))
        self._write(bytes(values))

    def _solid(self, color: tuple[int, int, int]) -> None:
        self._frame(color, (100, 100, 100, 100, 100, 100))

    def _animate(self) -> None:
        state = ""
        step = 0
        while not self._stop.wait(0.05):
            with self._lock:
                current = self._state
            if current != state:
                state, step = current, 0
            if state in ("starting", "pending"):
                color = self._COLORS[state]
                self._frame(color, (BREATH[step % len(BREATH)],) * 6)
                step += 1
                if step % len(BREATH) == 0:
                    self._stop.wait(0.2)
            elif state in ("connecting", "reconnecting"):
                self._frame(self._COLORS[state], SPIN[step % len(SPIN)])
                step += 1
                self._stop.wait(0.04)
            elif state == "error":
                self._solid(self._COLORS[state])
            elif state in ("online", "off"):
                continue

