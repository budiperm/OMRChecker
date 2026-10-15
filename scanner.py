"""

 Scanning LJK straight from a scanner into the scan folder (Windows only).

 Two backends, shown together in one list:
   TWAIN  ctypes over the 64-bit Data Source Manager (TWAINDSM.dll), native
          transfer, own hidden window and message loop in the scan thread
   WIA    the WIA Automation Layer (wiaaut.dll) through pywin32

 Nothing here touches Tk: a scan runs in a worker thread and reports every
 page through a callback. Pages are saved as scan_0001.jpg, scan_0002.jpg, ...
 continuing after the highest number already in the folder.

"""

import ctypes as ct
import json
import os
import re
import struct
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PAPER_INCHES = {"A4": (8.27, 11.69), "F4": (8.46, 12.99)}  # F4 / folio: 215 x 330 mm
PREFIX = "scan_"


class ScanError(Exception):
    """A problem worth showing to the user as is (Indonesian text)."""


@dataclass(frozen=True)
class Device:
    backend: str  # "TWAIN" or "WIA"
    id: str  # TWAIN product name / WIA DeviceID
    name: str

    @property
    def key(self):
        return f"{self.backend}:{self.id}"

    @property
    def label(self):
        return f"{self.name}  ({self.backend})"


@dataclass
class Options:
    device: str = ""  # Device.key of the last scanner used
    feeder: bool = True  # ADF; False = flatbed glass
    duplex: bool = False
    dpi: int = 300
    color: bool = False  # grayscale is enough for LJK and much smaller
    paper: str = ""  # "" = scanner default, or a PAPER_INCHES key
    show_ui: bool = False  # TWAIN: let the driver show its own window

    @staticmethod
    def path():
        import ujian

        return ujian.app_data_dir() / "scanner.json"

    def save(self, path=None):
        path = Path(path or self.path())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path=None):
        try:
            data = json.loads(Path(path or cls.path()).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Saving pages
# ---------------------------------------------------------------------------


def next_index(folder):
    """1 + the highest scan_NNNN number in folder (1 when there is none)."""
    pattern = re.compile(rf"{PREFIX}(\d+)\.(jpe?g|png)$", re.IGNORECASE)
    numbers = [int(m.group(1)) for p in Path(folder).glob(f"{PREFIX}*") if (m := pattern.match(p.name))]
    return max(numbers, default=0) + 1


class PageWriter:
    """Saves decoded pages as JPEG, never overwriting a file."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.index = next_index(self.folder)
        self.saved = []

    def save(self, img):
        import cv2

        if img is None or img.size == 0:
            raise ScanError("Scanner mengirim gambar kosong.")
        if img.ndim == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        while (path := self.folder / f"{PREFIX}{self.index:04d}.jpg").exists():
            self.index += 1
        ok, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise ScanError("Gambar hasil scan tidak bisa disimpan sebagai JPG.")
        data.tofile(str(path))
        self.index += 1
        self.saved.append(path)
        return path


def decode_image(data):
    """Encoded image bytes (BMP/PNG/JPEG/TIFF) -> BGR or gray array."""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(bytes(data), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ScanError("Format gambar dari scanner tidak dikenali.")
    if img.dtype != np.uint8:  # 16-bit gray/colour
        img = (img >> 8).astype(np.uint8)
    return img


def dib_to_bmp(dib):
    """A packed DIB (BITMAPINFOHEADER + colour table + pixels, what TWAIN
    native transfer hands over on Windows) -> the bytes of a .bmp file."""
    dib = bytes(dib)
    if len(dib) < 40:
        raise ScanError("Data gambar dari scanner terpotong.")
    header_size, _w, _h, _planes, bits, compression, _size, _xr, _yr, used = struct.unpack_from("<IiiHHIIiiI", dib)
    colors = used or (1 << bits if bits <= 8 else 0)
    masks = 12 if compression == 3 and header_size == 40 else 0  # BI_BITFIELDS
    offset = 14 + header_size + masks + 4 * colors
    return struct.pack("<2sIHHI", b"BM", 14 + len(dib), 0, 0, offset) + dib


# ---------------------------------------------------------------------------
# TWAIN
# ---------------------------------------------------------------------------

DG_CONTROL, DG_IMAGE = 1, 2
DAT_CAPABILITY, DAT_EVENT, DAT_IDENTITY, DAT_PARENT, DAT_PENDINGXFERS = 1, 2, 3, 4, 5
DAT_STATUS, DAT_USERINTERFACE, DAT_IMAGELAYOUT, DAT_IMAGENATIVEXFER = 8, 9, 0x102, 0x104
MSG_NULL, MSG_GET, MSG_GETCURRENT, MSG_GETFIRST, MSG_GETNEXT, MSG_SET, MSG_RESET = 0, 1, 2, 4, 5, 6, 7
MSG_XFERREADY, MSG_CLOSEDSREQ, MSG_CLOSEDSOK = 0x101, 0x102, 0x103
MSG_OPENDSM, MSG_CLOSEDSM, MSG_OPENDS, MSG_CLOSEDS = 0x301, 0x302, 0x401, 0x402
MSG_DISABLEDS, MSG_ENABLEDS, MSG_PROCESSEVENT, MSG_ENDXFER = 0x501, 0x502, 0x601, 0x701
TWRC_SUCCESS, TWRC_FAILURE, TWRC_CHECKSTATUS, TWRC_CANCEL = 0, 1, 2, 3
TWRC_DSEVENT, TWRC_XFERDONE, TWRC_ENDOFLIST = 4, 6, 7
TWON_ONEVALUE = 5
TWTY_INT16, TWTY_UINT16, TWTY_BOOL, TWTY_FIX32 = 1, 4, 6, 7
CAP_XFERCOUNT, ICAP_PIXELTYPE, ICAP_UNITS = 0x0001, 0x0101, 0x0102
CAP_FEEDERENABLED, CAP_FEEDERLOADED, CAP_AUTOFEED, CAP_DUPLEXENABLED = 0x1002, 0x1003, 0x1007, 0x1013
ICAP_XRESOLUTION, ICAP_YRESOLUTION, ICAP_SUPPORTEDSIZES = 0x1118, 0x1119, 0x1122
TWPT_GRAY, TWPT_RGB, TWUN_INCHES, TWSS_NONE, TWSS_A4 = 1, 2, 0, 0, 1
DF_APP2 = 0x20000000
ENCODING = "mbcs" if sys.platform == "win32" else "latin-1"  # TWAIN 1.x strings: ANSI code page

TWAIN_CONDITIONS = {
    3: "Scanner tidak ditemukan atau sedang dipakai program lain.",
    4: "Scanner sedang dipakai program lain.",
    20: "Kertas macet di scanner.",
    21: "Kertas tertarik dobel.",
    23: "Scanner tidak merespons. Periksa kabel dan pastikan scanner menyala.",
    29: "Tidak ada kertas di ADF.",
}


def _fix32(value):
    whole = int(value)
    frac = int(round((value - whole) * 65536)) & 0xFFFF
    return ((frac << 16) | (whole & 0xFFFF)) & 0xFFFFFFFF


class TW_VERSION(ct.Structure):
    _pack_ = 2
    _fields_ = [("MajorNum", ct.c_uint16), ("MinorNum", ct.c_uint16), ("Language", ct.c_uint16),
                ("Country", ct.c_uint16), ("Info", ct.c_char * 34)]  # fmt: skip


class TW_IDENTITY(ct.Structure):
    _pack_ = 2
    _fields_ = [("Id", ct.c_uint32), ("Version", TW_VERSION), ("ProtocolMajor", ct.c_uint16),
                ("ProtocolMinor", ct.c_uint16), ("SupportedGroups", ct.c_uint32),
                ("Manufacturer", ct.c_char * 34), ("ProductFamily", ct.c_char * 34),
                ("ProductName", ct.c_char * 34)]  # fmt: skip


class TW_CAPABILITY(ct.Structure):
    _pack_ = 2
    _fields_ = [("Cap", ct.c_uint16), ("ConType", ct.c_uint16), ("hContainer", ct.c_void_p)]


class TW_ONEVALUE(ct.Structure):
    _pack_ = 2
    _fields_ = [("ItemType", ct.c_uint16), ("Item", ct.c_uint32)]


class TW_FIX32(ct.Structure):
    _pack_ = 2
    _fields_ = [("Whole", ct.c_int16), ("Frac", ct.c_uint16)]


class TW_FRAME(ct.Structure):
    _pack_ = 2
    _fields_ = [("Left", TW_FIX32), ("Top", TW_FIX32), ("Right", TW_FIX32), ("Bottom", TW_FIX32)]


class TW_IMAGELAYOUT(ct.Structure):
    _pack_ = 2
    _fields_ = [("Frame", TW_FRAME), ("DocumentNumber", ct.c_uint32), ("PageNumber", ct.c_uint32),
                ("FrameNumber", ct.c_uint32)]  # fmt: skip


class TW_USERINTERFACE(ct.Structure):
    _pack_ = 2
    _fields_ = [("ShowUI", ct.c_uint16), ("ModalUI", ct.c_uint16), ("hParent", ct.c_void_p)]


class TW_PENDINGXFERS(ct.Structure):
    _pack_ = 2
    _fields_ = [("Count", ct.c_uint16), ("EOJ", ct.c_uint32)]


class TW_EVENT(ct.Structure):
    _pack_ = 2
    _fields_ = [("pEvent", ct.c_void_p), ("TWMessage", ct.c_uint16)]


class TW_STATUS(ct.Structure):
    _pack_ = 2
    _fields_ = [("ConditionCode", ct.c_uint16), ("Data", ct.c_uint16)]


def _fix(value):
    v = _fix32(value)
    return TW_FIX32(ct.c_int16(v & 0xFFFF).value, v >> 16)


def _twain_dll():
    """The 64-bit TWAIN DSM: a copy next to the program first, then the one
    the scanner driver installed in System32."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidates = [here / "TWAINDSM.dll", Path(sys.executable).parent / "TWAINDSM.dll", "TWAINDSM.dll"]
    for c in candidates:
        if isinstance(c, Path) and not c.exists():
            continue
        try:
            return ct.WinDLL(str(c))
        except OSError:
            continue
    raise ScanError("TWAINDSM.dll (TWAIN 64-bit) tidak ditemukan. Pasang driver TWAIN terbaru dari situs produsen scanner.")


class _Win32:
    """The handful of user32/kernel32 calls TWAIN needs, with 64-bit safe signatures."""

    def __init__(self):
        from ctypes import wintypes as w

        self.w = w
        u, k = ct.WinDLL("user32", use_last_error=True), ct.WinDLL("kernel32", use_last_error=True)
        self.CreateWindowExW = u.CreateWindowExW
        self.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ct.c_int, ct.c_int, ct.c_int,
                                         ct.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]  # fmt: skip
        self.CreateWindowExW.restype = w.HWND
        self.DestroyWindow = u.DestroyWindow
        self.DestroyWindow.argtypes = [w.HWND]
        self.PeekMessageW = u.PeekMessageW
        self.PeekMessageW.argtypes = [ct.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        self.TranslateMessage = u.TranslateMessage
        self.TranslateMessage.argtypes = [ct.POINTER(w.MSG)]
        self.DispatchMessageW = u.DispatchMessageW
        self.DispatchMessageW.argtypes = [ct.POINTER(w.MSG)]
        self.DispatchMessageW.restype = ct.c_ssize_t
        self.MsgWaitForMultipleObjects = u.MsgWaitForMultipleObjects
        self.MsgWaitForMultipleObjects.argtypes = [w.DWORD, ct.c_void_p, w.BOOL, w.DWORD, w.DWORD]
        for name, args, res in (("GlobalAlloc", [w.UINT, ct.c_size_t], ct.c_void_p),
                                ("GlobalLock", [ct.c_void_p], ct.c_void_p),
                                ("GlobalUnlock", [ct.c_void_p], w.BOOL),
                                ("GlobalFree", [ct.c_void_p], ct.c_void_p),
                                ("GlobalSize", [ct.c_void_p], ct.c_size_t)):  # fmt: skip
            f = getattr(k, name)
            f.argtypes, f.restype = args, res
            setattr(self, name, f)


class TwainSession:
    """One DSM connection, opened and closed in the thread that uses it.
    entry/win replace DSM_Entry and the Win32 calls in tests."""

    def __init__(self, entry=None, win=None):
        if entry is None:
            if sys.platform != "win32":
                raise ScanError("TWAIN hanya tersedia di Windows.")
            win = _Win32()
            entry = _twain_dll().DSM_Entry
            entry.restype = ct.c_uint16
            entry.argtypes = [ct.POINTER(TW_IDENTITY), ct.POINTER(TW_IDENTITY), ct.c_uint32, ct.c_uint16,
                              ct.c_uint16, ct.c_void_p]  # fmt: skip
        self.entry, self.win = entry, win
        WS_POPUP = 0x80000000
        self.hwnd = self.win.CreateWindowExW(0, "STATIC", "OMRChecker TWAIN", WS_POPUP, 0, 0, 0, 0, None, None, None, None)
        self.app = TW_IDENTITY(
            Version=TW_VERSION(MajorNum=1, MinorNum=0, Language=13, Country=1, Info=b"OMRChecker"),
            ProtocolMajor=2, ProtocolMinor=4, SupportedGroups=DG_CONTROL | DG_IMAGE | DF_APP2,
            Manufacturer=b"OMRChecker", ProductFamily=b"OMRChecker", ProductName=b"OMRChecker",
        )  # fmt: skip
        self.ds = None
        self.dsm_open = False
        parent = ct.c_void_p(self.hwnd)
        if self.call(None, DG_CONTROL, DAT_PARENT, MSG_OPENDSM, ct.byref(parent)) != TWRC_SUCCESS:
            self.close()
            raise ScanError("TWAIN tidak bisa dibuka (DSM gagal).")
        self.dsm_open = True

    def call(self, dest, dg, dat, msg, data):
        return self.entry(ct.byref(self.app), ct.byref(dest) if dest is not None else None, dg, dat, msg, data)

    def ds_call(self, dg, dat, msg, data):
        return self.call(self.ds, dg, dat, msg, data)

    def condition(self):
        status = TW_STATUS()
        self.call(self.ds, DG_CONTROL, DAT_STATUS, MSG_GET, ct.byref(status))
        return status.ConditionCode

    def sources(self):
        names, ident = [], TW_IDENTITY()
        rc = self.call(None, DG_CONTROL, DAT_IDENTITY, MSG_GETFIRST, ct.byref(ident))
        while rc == TWRC_SUCCESS:
            names.append(ident.ProductName.decode(ENCODING, "replace"))
            ident = TW_IDENTITY()
            rc = self.call(None, DG_CONTROL, DAT_IDENTITY, MSG_GETNEXT, ct.byref(ident))
        return names

    def open(self, name):
        ident = TW_IDENTITY()
        rc = self.call(None, DG_CONTROL, DAT_IDENTITY, MSG_GETFIRST, ct.byref(ident))
        while rc == TWRC_SUCCESS and ident.ProductName.decode(ENCODING, "replace") != name:
            ident = TW_IDENTITY()
            rc = self.call(None, DG_CONTROL, DAT_IDENTITY, MSG_GETNEXT, ct.byref(ident))
        if rc != TWRC_SUCCESS:
            raise ScanError(f"Scanner TWAIN '{name}' tidak ditemukan. Periksa kabel dan pastikan scanner menyala.")
        if self.call(None, DG_CONTROL, DAT_IDENTITY, MSG_OPENDS, ct.byref(ident)) != TWRC_SUCCESS:
            code = self.condition()
            raise ScanError(TWAIN_CONDITIONS.get(code, f"Scanner '{name}' tidak bisa dibuka (kode TWAIN {code})."))
        self.ds = ident

    # capabilities
    def set_cap(self, cap, item_type, value):
        """Best effort: True when the scanner accepted the value."""
        w = self.win
        handle = w.GlobalAlloc(0x0042, ct.sizeof(TW_ONEVALUE))  # GHND
        if not handle:
            return False
        try:
            one = TW_ONEVALUE.from_address(w.GlobalLock(handle))
            one.ItemType, one.Item = item_type, value & 0xFFFFFFFF
            w.GlobalUnlock(handle)
            capability = TW_CAPABILITY(cap, TWON_ONEVALUE, handle)
            return self.ds_call(DG_CONTROL, DAT_CAPABILITY, MSG_SET, ct.byref(capability)) in (TWRC_SUCCESS, TWRC_CHECKSTATUS)
        finally:
            w.GlobalFree(handle)

    def get_cap(self, cap):
        """Current value of a one-value capability, or None."""
        capability = TW_CAPABILITY(cap, TWON_ONEVALUE, None)
        if self.ds_call(DG_CONTROL, DAT_CAPABILITY, MSG_GETCURRENT, ct.byref(capability)) != TWRC_SUCCESS:
            return None
        handle = capability.hContainer
        if not handle:
            return None
        try:
            if capability.ConType != TWON_ONEVALUE:
                return None
            value = TW_ONEVALUE.from_address(self.win.GlobalLock(handle)).Item
            self.win.GlobalUnlock(handle)
            return value
        finally:
            self.win.GlobalFree(handle)

    def set_layout(self, inches):
        layout = TW_IMAGELAYOUT(TW_FRAME(_fix(0), _fix(0), _fix(inches[0]), _fix(inches[1])), 1, 1, 1)
        return self.ds_call(DG_IMAGE, DAT_IMAGELAYOUT, MSG_SET, ct.byref(layout)) in (TWRC_SUCCESS, TWRC_CHECKSTATUS)

    def configure(self, opts):
        warnings = []
        if not self.set_cap(ICAP_PIXELTYPE, TWTY_UINT16, TWPT_RGB if opts.color else TWPT_GRAY):
            warnings.append("mode warna/abu-abu tidak bisa diatur")
        self.set_cap(ICAP_UNITS, TWTY_UINT16, TWUN_INCHES)
        if not (self.set_cap(ICAP_XRESOLUTION, TWTY_FIX32, _fix32(opts.dpi))
                and self.set_cap(ICAP_YRESOLUTION, TWTY_FIX32, _fix32(opts.dpi))):  # fmt: skip
            warnings.append(f"resolusi {opts.dpi} dpi tidak diterima scanner")
        if opts.feeder:
            if not self.set_cap(CAP_FEEDERENABLED, TWTY_BOOL, 1):
                warnings.append("ADF tidak bisa dipilih")
            self.set_cap(CAP_AUTOFEED, TWTY_BOOL, 1)
            if not self.set_cap(CAP_XFERCOUNT, TWTY_INT16, -1):
                warnings.append("jumlah lembar tidak bisa diatur")
            if opts.duplex and not self.set_cap(CAP_DUPLEXENABLED, TWTY_BOOL, 1):
                warnings.append("scan dua sisi tidak didukung")
            elif not opts.duplex:
                self.set_cap(CAP_DUPLEXENABLED, TWTY_BOOL, 0)
        else:
            self.set_cap(CAP_FEEDERENABLED, TWTY_BOOL, 0)
            self.set_cap(CAP_XFERCOUNT, TWTY_INT16, 1)
        if opts.paper in PAPER_INCHES:
            ok = opts.paper == "A4" and self.set_cap(ICAP_SUPPORTEDSIZES, TWTY_UINT16, TWSS_A4)
            if not ok:
                self.set_cap(ICAP_SUPPORTEDSIZES, TWTY_UINT16, TWSS_NONE)
                ok = self.set_layout(PAPER_INCHES[opts.paper])
            if not ok:
                warnings.append(f"ukuran kertas {opts.paper} tidak bisa diatur")
        return warnings

    # acquisition
    def acquire(self, opts, on_image, cancelled, timeout=180):
        """Enable the source and transfer every page it delivers."""
        w = self.win
        if opts.feeder and not opts.show_ui and self.get_cap(CAP_FEEDERLOADED) == 0:
            raise ScanError("Tidak ada kertas di ADF. Masukkan LJK lalu coba lagi.")
        ui = TW_USERINTERFACE(1 if opts.show_ui else 0, 0, self.hwnd)
        rc = self.ds_call(DG_CONTROL, DAT_USERINTERFACE, MSG_ENABLEDS, ct.byref(ui))
        if rc not in (TWRC_SUCCESS, TWRC_CHECKSTATUS):
            code = self.condition()
            raise ScanError(TWAIN_CONDITIONS.get(code, f"Scanner menolak mulai scan (kode TWAIN {code})."))
        pages, started, msg = 0, time.monotonic(), w.w.MSG()
        try:
            while True:
                if cancelled():
                    return pages
                if not opts.show_ui and pages == 0 and time.monotonic() - started > timeout:
                    raise ScanError("Scanner tidak mengirim gambar. Periksa kertas dan scanner, lalu coba lagi.")
                if not w.PeekMessageW(ct.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                    w.MsgWaitForMultipleObjects(0, None, False, 50, 0x04FF)  # QS_ALLINPUT
                    continue
                event = TW_EVENT(ct.cast(ct.pointer(msg), ct.c_void_p), MSG_NULL)
                rc = self.ds_call(DG_CONTROL, DAT_EVENT, MSG_PROCESSEVENT, ct.byref(event))
                if event.TWMessage == MSG_XFERREADY:
                    pages += self.transfer(on_image, cancelled)
                    if not opts.show_ui:
                        return pages
                elif event.TWMessage in (MSG_CLOSEDSREQ, MSG_CLOSEDSOK):
                    return pages
                if rc != TWRC_DSEVENT:
                    w.TranslateMessage(ct.byref(msg))
                    w.DispatchMessageW(ct.byref(msg))
        finally:
            self.ds_call(DG_CONTROL, DAT_USERINTERFACE, MSG_DISABLEDS, ct.byref(ui))

    def transfer(self, on_image, cancelled):
        w, pages = self.win, 0
        pending = TW_PENDINGXFERS()
        while True:
            handle = ct.c_void_p()
            rc = self.ds_call(DG_IMAGE, DAT_IMAGENATIVEXFER, MSG_GET, ct.byref(handle))
            if rc == TWRC_XFERDONE and handle.value:
                try:
                    size = w.GlobalSize(handle)
                    data = ct.string_at(w.GlobalLock(handle), size)
                    w.GlobalUnlock(handle)
                finally:
                    w.GlobalFree(handle)
                on_image(decode_image(dib_to_bmp(data)))
                pages += 1
            elif rc == TWRC_FAILURE:
                code = self.condition()
                self.ds_call(DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, ct.byref(pending))
                if code in TWAIN_CONDITIONS and code != 29:
                    raise ScanError(TWAIN_CONDITIONS[code])
                if pages == 0 and code != 29:
                    raise ScanError(f"Transfer gambar gagal (kode TWAIN {code}).")
                return pages
            self.ds_call(DG_CONTROL, DAT_PENDINGXFERS, MSG_ENDXFER, ct.byref(pending))
            if pending.Count == 0:
                return pages
            if cancelled():
                self.ds_call(DG_CONTROL, DAT_PENDINGXFERS, MSG_RESET, ct.byref(pending))
                return pages

    def close(self):
        if self.ds is not None:
            self.call(None, DG_CONTROL, DAT_IDENTITY, MSG_CLOSEDS, ct.byref(self.ds))
            self.ds = None
        if self.dsm_open:
            self.call(None, DG_CONTROL, DAT_PARENT, MSG_CLOSEDSM, ct.byref(ct.c_void_p(self.hwnd)))
            self.dsm_open = False
        if self.hwnd:
            self.win.DestroyWindow(self.hwnd)
            self.hwnd = None


class Twain:
    name = "TWAIN"

    def __init__(self, session=TwainSession):
        self.session = session

    def devices(self):
        session = self.session()
        try:
            return [Device(self.name, n, n) for n in session.sources()]
        finally:
            session.close()

    def scan(self, device, opts, on_image, cancelled):
        session = self.session()
        try:
            session.open(device.id)
            warnings = session.configure(opts)
            session.acquire(opts, on_image, cancelled)
            return warnings
        finally:
            session.close()


# ---------------------------------------------------------------------------
# WIA
# ---------------------------------------------------------------------------

WIA_FORMAT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
WIA_DPS_DOCUMENT_HANDLING_SELECT, WIA_DPS_DOCUMENT_HANDLING_STATUS = 3088, 3087
WIA_DPS_PAGES, WIA_DPS_PAGE_SIZE, WIA_DPS_PAGE_WIDTH, WIA_DPS_PAGE_HEIGHT = 3096, 3097, 3098, 3099
WIA_IPS_CUR_INTENT, WIA_IPS_XRES, WIA_IPS_YRES = 6146, 6147, 6148
WIA_IPS_XPOS, WIA_IPS_YPOS, WIA_IPS_XEXTENT, WIA_IPS_YEXTENT = 6149, 6150, 6151, 6152
FEEDER, FLATBED, DUPLEX, FEED_READY = 1, 2, 4, 1
INTENT_COLOR, INTENT_GRAY = 1, 2
WIA_PAPER_EMPTY = 0x80210003
WIA_ERRORS = {
    0x80210002: "Kertas macet di scanner.",
    0x80210003: "Tidak ada kertas di ADF. Masukkan LJK lalu coba lagi.",
    0x80210004: "Ada masalah dengan kertas di ADF.",
    0x80210005: "Scanner offline. Periksa kabel dan pastikan scanner menyala.",
    0x80210006: "Scanner sedang sibuk. Tunggu sebentar lalu coba lagi.",
    0x80210007: "Scanner sedang pemanasan. Tunggu sebentar lalu coba lagi.",
    0x80210008: "Scanner butuh perhatian (lihat panel/lampu scanner).",
    0x8021000A: "Komunikasi dengan scanner terputus. Periksa kabel.",
    0x80210015: "Scanner tidak ditemukan. Periksa kabel dan pastikan scanner menyala.",
    0x80210016: "Tutup scanner terbuka.",
    0x80210017: "Lampu scanner mati.",
}


def _hresult(error):
    """The WIA error code inside a pywintypes.com_error."""
    codes = [getattr(error, "hresult", None)]
    info = getattr(error, "excepinfo", None)
    if info and len(info) > 5:
        codes.insert(0, info[5])
    for c in codes:
        if isinstance(c, int) and (c & 0xFFFFFFFF) >> 16 == 0x8021:
            return c & 0xFFFFFFFF
    return (codes[-1] or 0) & 0xFFFFFFFF


def _prop(props, pid, default=None):
    for p in props:
        if p.PropertyID == pid:
            return p
    return default


def _set(props, pid, value):
    """Best effort: True when the driver kept the value."""
    p = _prop(props, pid)
    if p is None:
        return False
    try:
        p.Value = value
        return True
    except Exception:
        return False


class Wia:
    name = "WIA"

    @staticmethod
    def _manager():
        try:
            import win32com.client
        except ImportError as e:
            raise ScanError("Komponen WIA (pywin32) tidak tersedia.") from e
        return win32com.client.Dispatch("WIA.DeviceManager")

    def _com(self, fn):
        import pythoncom

        pythoncom.CoInitialize()
        try:
            return fn()
        finally:
            pythoncom.CoUninitialize()

    def devices(self):
        def run():
            out = []
            for info in self._manager().DeviceInfos:
                if info.Type == 1:  # ScannerDeviceType
                    name = _prop(info.Properties, 7)  # WIA_DIP_DEV_NAME
                    out.append(Device(self.name, info.DeviceID, name.Value if name else info.DeviceID))
            return out

        return self._com(run)

    def scan(self, device, opts, on_image, cancelled):
        return self._com(lambda: self._scan(device, opts, on_image, cancelled))

    def _scan(self, device, opts, on_image, cancelled):
        import pywintypes

        info = next((i for i in self._manager().DeviceInfos if i.DeviceID == device.id), None)
        if info is None:
            raise ScanError(f"Scanner WIA '{device.name}' tidak ditemukan. Periksa kabel dan pastikan scanner menyala.")
        try:
            dev = info.Connect()
        except pywintypes.com_error as e:
            raise ScanError(WIA_ERRORS.get(_hresult(e), f"Scanner '{device.name}' tidak bisa dibuka ({e}).")) from e
        warnings = []
        dprops = dev.Properties
        if opts.feeder:
            if not _set(dprops, WIA_DPS_DOCUMENT_HANDLING_SELECT, FEEDER | (DUPLEX if opts.duplex else 0)):
                if not opts.duplex or not _set(dprops, WIA_DPS_DOCUMENT_HANDLING_SELECT, FEEDER):
                    warnings.append("ADF tidak bisa dipilih")
                else:
                    warnings.append("scan dua sisi tidak didukung")
            _set(dprops, WIA_DPS_PAGES, 1)
            status = _prop(dprops, WIA_DPS_DOCUMENT_HANDLING_STATUS)
            if status is not None and not (status.Value & FEED_READY):
                raise ScanError(WIA_ERRORS[WIA_PAPER_EMPTY])
        else:
            _set(dprops, WIA_DPS_DOCUMENT_HANDLING_SELECT, FLATBED)
        item = next(iter(dev.Items), None)
        if item is None:
            raise ScanError("Scanner tidak menyediakan sumber gambar.")
        props = item.Properties
        if not _set(props, WIA_IPS_CUR_INTENT, INTENT_COLOR if opts.color else INTENT_GRAY):
            warnings.append("mode warna/abu-abu tidak bisa diatur")
        if not (_set(props, WIA_IPS_XRES, opts.dpi) and _set(props, WIA_IPS_YRES, opts.dpi)):
            warnings.append(f"resolusi {opts.dpi} dpi tidak diterima scanner")
        if opts.paper in PAPER_INCHES:
            if not self._paper(dprops, props, opts):
                warnings.append(f"ukuran kertas {opts.paper} tidak bisa diatur")

        pages = 0
        while not cancelled():
            try:
                image = item.Transfer(WIA_FORMAT_BMP)
            except pywintypes.com_error as e:
                code = _hresult(e)
                if code == WIA_PAPER_EMPTY and (pages or not opts.feeder):
                    break
                raise ScanError(WIA_ERRORS.get(code, f"Scan gagal (kode WIA {code:#010x}).")) from e
            on_image(decode_image(image.FileData.BinaryData))
            pages += 1
            if not opts.feeder:
                break
        return warnings

    @staticmethod
    def _paper(dprops, props, opts):
        w_in, h_in = PAPER_INCHES[opts.paper]
        if opts.feeder:
            if opts.paper == "A4":
                _set(dprops, WIA_DPS_PAGE_SIZE, 0)  # WIA_PAGE_A4
            else:
                _set(dprops, WIA_DPS_PAGE_SIZE, 2)  # WIA_PAGE_CUSTOM, thousandths of an inch
                _set(dprops, WIA_DPS_PAGE_WIDTH, int(w_in * 1000))
                _set(dprops, WIA_DPS_PAGE_HEIGHT, int(h_in * 1000))
        ok = True
        for pid, inches in ((WIA_IPS_XEXTENT, w_in), (WIA_IPS_YEXTENT, h_in)):
            p = _prop(props, pid)
            if p is None:
                ok = False
                continue
            pixels = int(round(inches * opts.dpi))
            try:
                pixels = min(pixels, int(p.SubTypeMax))  # flatbed glass may be shorter than F4
            except Exception:
                pass
            ok = _set(props, pid, pixels) and ok
        _set(props, WIA_IPS_XPOS, 0)
        _set(props, WIA_IPS_YPOS, 0)
        return ok


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

BACKENDS = (Twain(), Wia())


def list_devices(backends=BACKENDS):
    """All scanners from every backend -> (devices, problems). Call it from a
    worker thread: TWAIN and WIA can take a few seconds."""
    devices, problems = [], []
    for b in backends:
        try:
            devices += b.devices()
        except ScanError as e:
            problems.append(f"{b.name}: {e}")
        except Exception as e:
            problems.append(f"{b.name}: {type(e).__name__}: {e}")
    return devices, problems


def backend_of(device, backends=BACKENDS):
    return next(b for b in backends if b.name == device.backend)


def scan(device, opts, folder, on_page=None, cancelled=lambda: False, backends=BACKENDS):
    """Scan with device into folder. on_page(path, count) after each saved page.
    Returns (saved paths, warnings); raises ScanError, keeping the pages saved
    so far in error.saved."""
    writer = PageWriter(folder)

    def on_image(img):
        path = writer.save(img)
        if on_page:
            on_page(path, len(writer.saved))

    try:
        warnings = backend_of(device, backends).scan(device, opts, on_image, cancelled) or []
    except ScanError as e:
        e.saved = writer.saved
        raise
    except Exception as e:
        err = ScanError(f"Scan gagal: {type(e).__name__}: {e}")
        err.saved = writer.saved
        raise err from e
    return writer.saved, warnings


def main(argv=None):
    """`OMRChecker-debug.exe --cek-scanner`: list the scanners each backend sees."""
    devices, problems = list_devices()
    for d in devices:
        print(f"[{d.backend}] {d.name}  ({d.id})")
    for p in problems:
        print(f"Masalah {p}")
    if not devices:
        print("Tidak ada scanner yang terdeteksi.")
    return 0 if devices else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
