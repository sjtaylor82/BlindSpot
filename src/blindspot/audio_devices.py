"""Route BlindSpot's own audio to a chosen Windows sound card.

Spotify's Web Playback SDK plays inside a cross-origin frame, so the page
cannot pick an output device.  Windows can, per application: the same
per-app setting the Volume mixer exposes.  It is keyed by executable path,
so it also applies to other apps that share the WebView2 runtime.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import uuid
from ctypes import POINTER, byref, c_uint, c_ulong, c_ushort, c_void_p, c_wchar_p
from dataclasses import dataclass


logger = logging.getLogger(__name__)

AVAILABLE = sys.platform == "win32"

E_RENDER = 0
ROLES = (0, 1)  # eConsole, eMultimedia
DEVICE_STATE_ACTIVE = 1
STGM_READ = 0
CLSCTX_ALL = 23
COINIT_APARTMENTTHREADED = 2
RPC_E_CHANGED_MODE = -2147417850
TH32CS_SNAPPROCESS = 2
AUDIO_RENDER_INTERFACE = "{e6327cad-dcec-4949-ae8a-991e976a79d2}"
AUDIO_POLICY_CLASS = "Windows.Media.Internal.AudioPolicyConfig"
# IAudioPolicyConfigFactory methods follow IInspectable and 19 unused slots.
SET_PERSISTED_ENDPOINT = 25


class AudioDeviceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioOutput:
    id: str
    name: str
    is_default: bool = False


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, value: str) -> "_GUID":
        guid = cls()
        ctypes.memmove(guid.data, uuid.UUID(value).bytes_le, 16)
        return guid


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", c_ulong)]


class _PropVariant(ctypes.Structure):
    _fields_ = [
        ("vt", c_ushort),
        ("reserved1", c_ushort),
        ("reserved2", c_ushort),
        ("reserved3", c_ushort),
        ("value", c_wchar_p),
        ("padding", c_void_p),
    ]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


CLSID_MM_DEVICE_ENUMERATOR = "bcde0395-e52f-467c-8e3d-c4579291692e"
IID_MM_DEVICE_ENUMERATOR = "a95664d2-9614-4f35-a746-de8db63617e6"
PKEY_DEVICE_FRIENDLY_NAME = ("a45c254e-df1c-4efd-8020-67d146a850e0", 14)


def _call(pointer: c_void_p, index: int, *args, argtypes=()) -> None:
    """Call a COM method by vtable slot and raise on a failed HRESULT."""
    vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtable[index])
    method(pointer, *args)


def _release(pointer: c_void_p) -> None:
    if pointer:
        vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtable[2])(pointer)


class _ComApartment:
    def __enter__(self) -> "_ComApartment":
        result = ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        # S_OK and S_FALSE need balancing; an existing apartment of another
        # kind (wx initialises OLE on the main thread) is fine to reuse.
        self.balance = result in (0, 1)
        if not self.balance and result != RPC_E_CHANGED_MODE:
            raise AudioDeviceError(f"COM initialisation failed: {result:#x}")
        return self

    def __exit__(self, *exc) -> None:
        if self.balance:
            ctypes.windll.ole32.CoUninitialize()


def output_devices() -> list[AudioOutput]:
    """Return the active Windows playback devices, default first."""
    if not AVAILABLE:
        return []
    ole32 = ctypes.windll.ole32
    with _ComApartment():
        enumerator = c_void_p()
        ole32.CoCreateInstance(
            byref(_GUID.of(CLSID_MM_DEVICE_ENUMERATOR)),
            None,
            CLSCTX_ALL,
            byref(_GUID.of(IID_MM_DEVICE_ENUMERATOR)),
            byref(enumerator),
        )
        if not enumerator:
            raise AudioDeviceError("Windows audio devices are unavailable.")
        collection = c_void_p()
        default = c_void_p()
        try:
            default_id = ""
            try:
                _call(enumerator, 4, E_RENDER, 1, byref(default),
                      argtypes=(c_uint, c_uint, POINTER(c_void_p)))
                default_id = _device_id(default)
            except OSError:
                pass  # No default device: nothing is plugged in.
            _call(enumerator, 3, E_RENDER, DEVICE_STATE_ACTIVE, byref(collection),
                  argtypes=(c_uint, c_uint, POINTER(c_void_p)))
            count = c_uint()
            _call(collection, 3, byref(count), argtypes=(POINTER(c_uint),))
            devices = []
            for index in range(count.value):
                device = c_void_p()
                _call(collection, 4, index, byref(device),
                      argtypes=(c_uint, POINTER(c_void_p)))
                try:
                    device_id = _device_id(device)
                    devices.append(AudioOutput(
                        device_id,
                        _friendly_name(device) or device_id,
                        device_id == default_id,
                    ))
                finally:
                    _release(device)
        finally:
            _release(default)
            _release(collection)
            _release(enumerator)
    return sorted(devices, key=lambda device: (not device.is_default, device.name.casefold()))


def _device_id(device: c_void_p) -> str:
    value = c_void_p()
    _call(device, 5, byref(value), argtypes=(POINTER(c_void_p),))
    try:
        return ctypes.wstring_at(value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(value)


def _friendly_name(device: c_void_p) -> str:
    store = c_void_p()
    _call(device, 4, STGM_READ, byref(store), argtypes=(c_uint, POINTER(c_void_p)))
    try:
        key = _PropertyKey(_GUID.of(PKEY_DEVICE_FRIENDLY_NAME[0]), PKEY_DEVICE_FRIENDLY_NAME[1])
        value = _PropVariant()
        _call(store, 5, byref(key), byref(value),
              argtypes=(POINTER(_PropertyKey), POINTER(_PropVariant)))
        try:
            return value.value or ""
        finally:
            ctypes.windll.ole32.PropVariantClear(byref(value))
    finally:
        _release(store)


def _process_tree(root: int) -> list[int]:
    """Return root and every descendant, such as WebView2's audio process."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = c_void_p
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == c_void_p(-1).value:
        return [root]
    children: dict[int, list[int]] = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(c_void_p(snapshot), byref(entry))
        while more:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            more = kernel32.Process32NextW(c_void_p(snapshot), byref(entry))
    finally:
        kernel32.CloseHandle(c_void_p(snapshot))
    found, pending = [], [root]
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.append(pid)
        pending.extend(children.get(pid, ()))
    return found


def _policy_factory() -> c_void_p:
    combase = ctypes.windll.combase
    name = c_void_p()
    combase.WindowsCreateString(
        c_wchar_p(AUDIO_POLICY_CLASS), len(AUDIO_POLICY_CLASS), byref(name)
    )
    # Windows changed the interface identifier in build 21390.
    iid = (
        "ab3d4648-e242-459f-b02f-541c70306324"
        if sys.getwindowsversion().build >= 21390
        else "2a59116d-6c4f-45e0-a74f-707e3fef9258"
    )
    factory = c_void_p()
    try:
        result = combase.RoGetActivationFactory(name, byref(_GUID.of(iid)), byref(factory))
    finally:
        combase.WindowsDeleteString(name)
    if result or not factory:
        raise AudioDeviceError(
            f"This version of Windows cannot choose a sound card per app ({result & 0xFFFFFFFF:#x})."
        )
    return factory


def route_process_tree(device_id: str, root: int | None = None) -> int:
    """Send BlindSpot's audio to device_id, or back to the default when empty.

    Returns the number of processes updated.
    """
    if not AVAILABLE:
        raise AudioDeviceError("Choosing a sound card is only available on Windows.")
    combase = ctypes.windll.combase
    with _ComApartment():
        factory = _policy_factory()
        endpoint = c_void_p()
        try:
            if device_id:
                path = f"\\\\?\\SWD#MMDEVAPI#{device_id}#{AUDIO_RENDER_INTERFACE}"
                combase.WindowsCreateString(c_wchar_p(path), len(path), byref(endpoint))
            updated = 0
            for pid in _process_tree(os.getpid() if root is None else root):
                try:
                    for role in ROLES:
                        _call(factory, SET_PERSISTED_ENDPOINT, pid, E_RENDER, role, endpoint,
                              argtypes=(c_uint, c_uint, c_uint, c_void_p))
                    updated += 1
                except OSError as error:
                    # Short-lived helper processes may exit mid-walk.
                    logger.debug("Sound card routing skipped pid=%s: %s", pid, error)
        finally:
            if endpoint:
                combase.WindowsDeleteString(endpoint)
            _release(factory)
    logger.info(
        "Sound card routing applied device=%s processes=%d",
        "default" if not device_id else "chosen", updated,
    )
    return updated
