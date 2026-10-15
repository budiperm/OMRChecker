"""Scanning from a scanner (scanner.py, scan_dialog.py) without hardware:
page numbering, DIB decoding, TWAIN struct layout, the WIA ADF loop on fake
COM objects, and the dialog driven with a fake backend (needs a display;
headless Linux: xvfb-run)."""

import ctypes as ct
import sys
import time
import types
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

import scanner  # noqa: E402


def page(value=200, shape=(330, 215)):
    img = np.full(shape, value, np.uint8)
    cv2.rectangle(img, (10, 10), (40, 40), 0, -1)
    return img


class FakeBackend:
    name = "FAKE"

    def __init__(self, pages=3, fail_after=None, delay=0.0):
        self.pages, self.fail_after, self.delay = pages, fail_after, delay
        self.opts = None

    def devices(self):
        return [scanner.Device(self.name, "dev1", "Scanner Uji")]

    def scan(self, device, opts, on_image, cancelled):
        self.opts = opts
        for i in range(self.pages):
            if cancelled():
                break
            if self.fail_after is not None and i == self.fail_after:
                raise scanner.ScanError("Kertas macet di scanner.")
            time.sleep(self.delay)
            on_image(page(100 + i))
        return ["ukuran kertas F4 tidak bisa diatur"] if opts.paper == "F4" else []


class Broken:
    name = "TWAIN"

    def devices(self):
        raise scanner.ScanError("TWAINDSM.dll tidak ditemukan.")


# ---------------------------------------------------------------------------
# saving pages
# ---------------------------------------------------------------------------


def test_numbering_continues_and_never_overwrites(tmp_path):
    (tmp_path / "scan_0007.jpg").write_bytes(b"old")
    (tmp_path / "SCAN_0002.PNG").write_bytes(b"old")
    (tmp_path / "lain.jpg").write_bytes(b"x")
    assert scanner.next_index(tmp_path) == 8
    w = scanner.PageWriter(tmp_path)
    (tmp_path / "scan_0008.jpg").write_bytes(b"appeared meanwhile")
    p1, p2 = w.save(page()), w.save(cv2.cvtColor(page(), cv2.COLOR_GRAY2BGRA))
    assert [p1.name, p2.name] == ["scan_0009.jpg", "scan_0010.jpg"]
    assert (tmp_path / "scan_0007.jpg").read_bytes() == b"old"
    assert cv2.imread(str(p2)).shape == (330, 215, 3)


def test_writer_creates_folder_and_rejects_empty(tmp_path):
    w = scanner.PageWriter(tmp_path / "baru" / "scan")
    assert w.folder.is_dir()
    with pytest.raises(scanner.ScanError):
        w.save(np.zeros((0, 0), np.uint8))


@pytest.mark.parametrize("img", [page(), cv2.cvtColor(page(), cv2.COLOR_GRAY2BGR),
                                 (page() > 128).astype(np.uint8) * 255])  # fmt: skip
def test_dib_from_twain_decodes(img):
    bmp = cv2.imencode(".bmp", img)[1].tobytes()
    dib = bmp[14:]  # TWAIN native transfer: the BMP without its file header
    rebuilt = scanner.dib_to_bmp(dib)
    assert rebuilt == bmp
    out = scanner.decode_image(rebuilt)
    assert out.shape[:2] == img.shape[:2]


def test_dib_with_bitfields_and_short_data():
    w, h = 4, 2
    header = np.array([40, w, h], "<i4").tobytes() + np.array([1, 32], "<u2").tobytes()
    header += np.array([3, w * h * 4, 2835, 2835, 0, 0], "<u4").tobytes()
    masks = np.array([0xFF0000, 0xFF00, 0xFF], "<u4").tobytes()
    pixels = np.full((h, w, 4), 90, np.uint8).tobytes()
    bmp = scanner.dib_to_bmp(header + masks + pixels)
    assert int.from_bytes(bmp[10:14], "little") == 14 + 40 + 12
    with pytest.raises(scanner.ScanError):
        scanner.dib_to_bmp(b"\0" * 10)


def test_decode_rejects_garbage():
    with pytest.raises(scanner.ScanError):
        scanner.decode_image(b"bukan gambar")


# ---------------------------------------------------------------------------
# TWAIN layout (must match twain.h, 2-byte packing)
# ---------------------------------------------------------------------------


def test_twain_struct_sizes():
    ptr = ct.sizeof(ct.c_void_p)
    assert ct.sizeof(scanner.TW_IDENTITY) == 156
    assert ct.sizeof(scanner.TW_CAPABILITY) == 4 + ptr
    assert ct.sizeof(scanner.TW_ONEVALUE) == 6
    assert ct.sizeof(scanner.TW_USERINTERFACE) == 4 + ptr
    assert ct.sizeof(scanner.TW_EVENT) == ptr + 2
    assert ct.sizeof(scanner.TW_PENDINGXFERS) == 6
    assert ct.sizeof(scanner.TW_IMAGELAYOUT) == 28
    assert scanner.TW_IDENTITY.ProductName.offset == 122


def test_fix32():
    assert scanner._fix32(300) == 300
    assert scanner._fix32(8.5) == (0x8000 << 16) | 8
    f = scanner._fix(12.99)
    assert f.Whole == 12 and abs(f.Frac / 65536 - 0.99) < 1e-4


class FakeWin:
    """Win32 stand-ins: Global* over ctypes buffers, an endless message queue."""

    class w:
        class MSG(ct.Structure):
            _fields_ = [("hwnd", ct.c_void_p), ("message", ct.c_uint)]

    def __init__(self):
        self.blocks = {}

    def GlobalAlloc(self, flags, size):
        buf = ct.create_string_buffer(size)
        self.blocks[ct.addressof(buf)] = buf
        return ct.addressof(buf)

    def GlobalLock(self, h):
        return getattr(h, "value", h)

    def GlobalUnlock(self, h):
        return 1

    def GlobalFree(self, h):
        self.blocks.pop(getattr(h, "value", h))

    def GlobalSize(self, h):
        return len(self.blocks[getattr(h, "value", h)])

    CreateWindowExW = staticmethod(lambda *a: 4242)
    DestroyWindow = staticmethod(lambda h: 1)
    PeekMessageW = staticmethod(lambda *a: 1)
    TranslateMessage = DispatchMessageW = staticmethod(lambda m: 0)
    MsgWaitForMultipleObjects = staticmethod(lambda *a: 0)


class FakeDsm:
    """A TWAIN Data Source Manager with sources, following the TWAIN state
    machine closely enough to catch protocol mistakes."""

    def __init__(self, win, sources=("EPSON DS-410", "PS283"), pages=3, loaded=True, reject=(), fail_at=None):
        self.win, self.sources, self.pages, self.loaded = win, list(sources), pages, loaded
        self.reject, self.fail_at = set(reject), fail_at
        self.caps, self.calls, self.state, self.cursor, self.condition = {}, [], 2, 0, 0
        self.layout = None
        self.pending = 0
        self.ready = False

    def __call__(self, app, dest, dg, dat, msg, data):
        s = scanner
        obj = data._obj if data is not None else None
        self.calls.append((dat, msg))
        assert app._obj.ProductName == b"OMRChecker"
        if dat == s.DAT_PARENT:
            assert obj.value == 4242
            self.state = 3 if msg == s.MSG_OPENDSM else 2
            return s.TWRC_SUCCESS
        if dat == s.DAT_IDENTITY and msg in (s.MSG_GETFIRST, s.MSG_GETNEXT):
            self.cursor = 0 if msg == s.MSG_GETFIRST else self.cursor + 1
            if self.cursor >= len(self.sources):
                return s.TWRC_ENDOFLIST
            obj.ProductName = self.sources[self.cursor].encode()
            obj.Id = self.cursor + 1
            return s.TWRC_SUCCESS
        if dat == s.DAT_IDENTITY and msg == s.MSG_OPENDS:
            assert self.state == 3
            self.state = 4
            self.opened = obj.ProductName.decode()
            return s.TWRC_SUCCESS
        if dat == s.DAT_IDENTITY and msg == s.MSG_CLOSEDS:
            assert self.state == 4, "close the source only after disabling it"
            self.state = 3
            return s.TWRC_SUCCESS
        assert dest is not None and dest._obj.Id, "source calls need the opened identity"
        if dat == s.DAT_STATUS:
            obj.ConditionCode = self.condition
            return s.TWRC_SUCCESS
        if dat == s.DAT_CAPABILITY and msg == s.MSG_SET:
            assert self.state == 4, "capabilities are negotiated before enabling"
            one = s.TW_ONEVALUE.from_address(self.win.GlobalLock(obj.hContainer))
            if obj.Cap in self.reject:
                return s.TWRC_FAILURE
            self.caps[obj.Cap] = (one.ItemType, one.Item)
            return s.TWRC_SUCCESS
        if dat == s.DAT_CAPABILITY and msg == s.MSG_GETCURRENT:
            if obj.Cap != s.CAP_FEEDERLOADED:
                return s.TWRC_FAILURE
            h = self.win.GlobalAlloc(0, ct.sizeof(s.TW_ONEVALUE))
            one = s.TW_ONEVALUE.from_address(h)
            one.ItemType, one.Item = s.TWTY_BOOL, int(self.loaded)
            obj.ConType, obj.hContainer = s.TWON_ONEVALUE, h
            return s.TWRC_SUCCESS
        if dat == s.DAT_IMAGELAYOUT:
            f = obj.Frame
            self.layout = (f.Right.Whole + f.Right.Frac / 65536, f.Bottom.Whole + f.Bottom.Frac / 65536)
            return s.TWRC_SUCCESS
        if dat == s.DAT_USERINTERFACE and msg == s.MSG_ENABLEDS:
            assert self.state == 4 and obj.hParent == 4242
            self.show_ui = obj.ShowUI
            self.state, self.ready, self.pending = 5, True, self.pages
            return s.TWRC_SUCCESS
        if dat == s.DAT_USERINTERFACE and msg == s.MSG_DISABLEDS:
            assert self.state == 5, "disable only from state 5"
            self.state = 4
            return s.TWRC_SUCCESS
        if dat == s.DAT_EVENT:
            assert self.state >= 5
            if self.ready:
                self.ready, self.state = False, 6
                obj.TWMessage = s.MSG_XFERREADY
                return s.TWRC_DSEVENT
            obj.TWMessage = s.MSG_NULL
            return 5  # TWRC_NOTDSEVENT
        if dat == s.DAT_IMAGENATIVEXFER:
            assert self.state == 6
            if self.fail_at is not None and self.pages - self.pending == self.fail_at:
                self.condition = 20  # paper jam
                return s.TWRC_FAILURE
            bmp = cv2.imencode(".bmp", page(60 + self.pending))[1].tobytes()[14:]
            h = self.win.GlobalAlloc(0, len(bmp))
            ct.memmove(h, bmp, len(bmp))
            obj.value = h
            self.state = 7
            return s.TWRC_XFERDONE
        if dat == s.DAT_PENDINGXFERS:
            assert self.state in (6, 7)
            self.pending = 0 if msg == s.MSG_RESET else self.pending - 1
            obj.Count = self.pending
            self.state = 6 if self.pending else 5
            return s.TWRC_SUCCESS
        raise AssertionError(f"unexpected call DAT {dat:#x} MSG {msg:#x}")


@pytest.fixture
def twain():
    def make(**kw):
        win = FakeWin()
        dsm = FakeDsm(win, **kw)
        return scanner.Twain(session=lambda: scanner.TwainSession(entry=dsm, win=win)), dsm, win

    return make


def test_twain_lists_sources(twain):
    t, dsm, _ = twain()
    assert [d.name for d in t.devices()] == ["EPSON DS-410", "PS283"]
    assert dsm.state == 2


def test_twain_adf_scan(twain, tmp_path):
    t, dsm, win = twain(pages=3)
    dev = scanner.Device("TWAIN", "PS283", "PS283")
    opts = scanner.Options(feeder=True, duplex=False, dpi=300, color=False, paper="F4")
    saved, warnings = scanner.scan(dev, opts, tmp_path, backends=[t])
    assert [p.name for p in saved] == ["scan_0001.jpg", "scan_0002.jpg", "scan_0003.jpg"]
    assert warnings == []
    assert dsm.opened == "PS283" and dsm.state == 2 and dsm.show_ui == 0
    assert dsm.caps[scanner.ICAP_PIXELTYPE] == (scanner.TWTY_UINT16, scanner.TWPT_GRAY)
    assert dsm.caps[scanner.ICAP_XRESOLUTION] == (scanner.TWTY_FIX32, 300)
    assert dsm.caps[scanner.CAP_FEEDERENABLED] == (scanner.TWTY_BOOL, 1)
    assert dsm.caps[scanner.CAP_XFERCOUNT] == (scanner.TWTY_INT16, 0xFFFFFFFF)
    assert dsm.caps[scanner.CAP_DUPLEXENABLED] == (scanner.TWTY_BOOL, 0)
    assert dsm.layout == pytest.approx((8.46, 12.99), abs=1e-3)
    assert win.blocks == {}  # every handle freed
    assert cv2.imread(str(saved[0]), cv2.IMREAD_GRAYSCALE).shape == (330, 215)


def test_twain_rejected_settings_become_warnings(twain, tmp_path):
    t, dsm, _ = twain(pages=1, reject={scanner.ICAP_XRESOLUTION, scanner.CAP_DUPLEXENABLED})
    opts = scanner.Options(duplex=True, dpi=200, color=True, paper="A4")
    _, warnings = scanner.scan(scanner.Device("TWAIN", "PS283", "PS283"), opts, tmp_path, backends=[t])
    assert warnings == ["resolusi 200 dpi tidak diterima scanner", "scan dua sisi tidak didukung"]
    assert dsm.caps[scanner.ICAP_SUPPORTEDSIZES] == (scanner.TWTY_UINT16, scanner.TWSS_A4)
    assert dsm.caps[scanner.ICAP_PIXELTYPE][1] == scanner.TWPT_RGB


def test_twain_empty_feeder(twain, tmp_path):
    t, dsm, _ = twain(loaded=False)
    with pytest.raises(scanner.ScanError, match="Tidak ada kertas"):
        scanner.scan(scanner.Device("TWAIN", "PS283", "PS283"), scanner.Options(), tmp_path, backends=[t])
    assert dsm.state == 2


def test_twain_paper_jam_keeps_pages(twain, tmp_path):
    t, dsm, _ = twain(pages=4, fail_at=2)
    with pytest.raises(scanner.ScanError, match="macet") as e:
        scanner.scan(scanner.Device("TWAIN", "PS283", "PS283"), scanner.Options(), tmp_path, backends=[t])
    assert len(e.value.saved) == 2 and dsm.state == 2


def test_twain_cancel_resets(twain, tmp_path):
    t, dsm, _ = twain(pages=5)
    seen = []
    saved, _ = scanner.scan(scanner.Device("TWAIN", "PS283", "PS283"), scanner.Options(), tmp_path,
                            on_page=lambda p, n: seen.append(n), cancelled=lambda: len(seen) >= 2,
                            backends=[t])  # fmt: skip
    assert len(saved) == 2
    assert (scanner.DAT_PENDINGXFERS, scanner.MSG_RESET) in dsm.calls and dsm.state == 2


def test_twain_flatbed_and_unknown_source(twain, tmp_path):
    t, dsm, _ = twain(pages=1)
    saved, _ = scanner.scan(scanner.Device("TWAIN", "EPSON DS-410", "x"), scanner.Options(feeder=False), tmp_path,
                            backends=[t])  # fmt: skip
    assert len(saved) == 1
    assert dsm.caps[scanner.CAP_FEEDERENABLED] == (scanner.TWTY_BOOL, 0)
    assert dsm.caps[scanner.CAP_XFERCOUNT] == (scanner.TWTY_INT16, 1)
    with pytest.raises(scanner.ScanError, match="tidak ditemukan"):
        scanner.scan(scanner.Device("TWAIN", "Canon", "Canon"), scanner.Options(), tmp_path, backends=[t])


# ---------------------------------------------------------------------------
# scan() and list_devices()
# ---------------------------------------------------------------------------


def test_scan_saves_every_page(tmp_path):
    fake = FakeBackend(pages=3)
    dev = fake.devices()[0]
    seen = []
    saved, warnings = scanner.scan(dev, scanner.Options(paper="F4"), tmp_path,
                                   on_page=lambda p, n: seen.append((p.name, n)), backends=[fake])  # fmt: skip
    assert [p.name for p in saved] == ["scan_0001.jpg", "scan_0002.jpg", "scan_0003.jpg"]
    assert seen[-1] == ("scan_0003.jpg", 3)
    assert warnings == ["ukuran kertas F4 tidak bisa diatur"]


def test_scan_error_keeps_pages(tmp_path):
    fake = FakeBackend(pages=5, fail_after=2)
    with pytest.raises(scanner.ScanError) as e:
        scanner.scan(fake.devices()[0], scanner.Options(), tmp_path, backends=[fake])
    assert "macet" in str(e.value)
    assert [p.name for p in e.value.saved] == ["scan_0001.jpg", "scan_0002.jpg"]


def test_scan_cancel(tmp_path):
    fake = FakeBackend(pages=5)
    calls = iter([False, False, True])
    saved, _ = scanner.scan(fake.devices()[0], scanner.Options(), tmp_path, cancelled=lambda: next(calls),
                            backends=[fake])  # fmt: skip
    assert len(saved) == 2


def test_unexpected_exception_becomes_scan_error(tmp_path):
    class Crash(FakeBackend):
        def scan(self, *a):
            raise RuntimeError("driver crash")

    with pytest.raises(scanner.ScanError, match="driver crash"):
        scanner.scan(Crash().devices()[0], scanner.Options(), tmp_path, backends=[Crash()])


def test_list_devices_reports_problems():
    devices, problems = scanner.list_devices([Broken(), FakeBackend()])
    assert [d.label for d in devices] == ["Scanner Uji  (FAKE)"]
    assert problems == ["TWAIN: TWAINDSM.dll tidak ditemukan."]


def test_options_roundtrip(tmp_path):
    path = tmp_path / "scanner.json"
    scanner.Options(device="WIA:x", feeder=False, dpi=200, paper="F4").save(path)
    o = scanner.Options.load(path)
    assert (o.device, o.feeder, o.dpi, o.paper) == ("WIA:x", False, 200, "F4")
    path.write_text('{"dpi": 300, "lama": 1}')
    assert scanner.Options.load(path).dpi == 300
    assert scanner.Options.load(tmp_path / "tidak_ada.json") == scanner.Options()


# ---------------------------------------------------------------------------
# WIA on fake COM objects
# ---------------------------------------------------------------------------


class ComError(Exception):
    def __init__(self, code):
        super().__init__(f"com error {code:#x}")
        self.hresult = -2147352567  # DISP_E_EXCEPTION
        self.excepinfo = (0, "WIA", "", None, 0, code - (1 << 32))


class Prop:
    def __init__(self, pid, value, accept=True, maximum=None):
        self.PropertyID, self._value, self.accept, self.SubTypeMax = pid, value, accept, maximum

    @property
    def Value(self):
        return self._value

    @Value.setter
    def Value(self, v):
        if not self.accept:
            raise ComError(0x80070057)
        self._value = v


class SimplexProp(Prop):
    Value = property(Prop.Value.fget)

    @Value.setter
    def Value(self, v):
        if v & scanner.DUPLEX:
            raise ComError(0x80070057)
        self._value = v


class FakeItem:
    def __init__(self, pages, end_code=scanner.WIA_PAPER_EMPTY):
        self.pages, self.end_code = list(pages), end_code
        self.Properties = [Prop(pid, 0) for pid in (scanner.WIA_IPS_CUR_INTENT, scanner.WIA_IPS_XRES,
                                                    scanner.WIA_IPS_YRES, scanner.WIA_IPS_XPOS, scanner.WIA_IPS_YPOS)]
        self.Properties += [Prop(scanner.WIA_IPS_XEXTENT, 0, maximum=2550), Prop(scanner.WIA_IPS_YEXTENT, 0, maximum=3500)]

    def Transfer(self, fmt):
        assert fmt == scanner.WIA_FORMAT_BMP
        if not self.pages:
            raise ComError(self.end_code)
        data = cv2.imencode(".bmp", self.pages.pop(0))[1].tobytes()
        return types.SimpleNamespace(FileData=types.SimpleNamespace(BinaryData=memoryview(data)))


class FakeWiaDevice:
    def __init__(self, item, feed_ready=True, duplex_ok=True):
        self.Items = [item]
        self.Properties = [Prop(scanner.WIA_DPS_DOCUMENT_HANDLING_STATUS, 1 if feed_ready else 0),
                           Prop(scanner.WIA_DPS_PAGES, 0), Prop(scanner.WIA_DPS_PAGE_SIZE, 0),
                           Prop(scanner.WIA_DPS_PAGE_WIDTH, 0), Prop(scanner.WIA_DPS_PAGE_HEIGHT, 0)]  # fmt: skip
        self.Properties.append((Prop if duplex_ok else SimplexProp)(scanner.WIA_DPS_DOCUMENT_HANDLING_SELECT,
                                                                    scanner.FLATBED))  # fmt: skip

    def prop(self, pid):
        return scanner._prop(self.Properties, pid).Value


@pytest.fixture
def wia(monkeypatch):
    def install(device):
        info = types.SimpleNamespace(Type=1, DeviceID="{wia-1}", Properties=[Prop(7, "EPSON DS-410")],
                                     Connect=lambda: device)  # fmt: skip
        other = types.SimpleNamespace(Type=2, DeviceID="{cam}", Properties=[], Connect=None)
        manager = types.SimpleNamespace(DeviceInfos=[other, info])
        monkeypatch.setattr(scanner.Wia, "_manager", staticmethod(lambda: manager))
        monkeypatch.setattr(scanner.Wia, "_com", lambda self, fn: fn())
        monkeypatch.setitem(sys.modules, "pywintypes", types.SimpleNamespace(com_error=ComError))
        return scanner.Wia()

    return install


def test_wia_lists_only_scanners(wia):
    w = wia(FakeWiaDevice(FakeItem([])))
    assert w.devices() == [scanner.Device("WIA", "{wia-1}", "EPSON DS-410")]


def test_wia_adf_scans_until_paper_empty(wia, tmp_path):
    item = FakeItem([page(), page(120), page(140)])
    dev = FakeWiaDevice(item)
    w = wia(dev)
    opts = scanner.Options(feeder=True, duplex=True, dpi=300, color=False, paper="F4")
    saved, warnings = scanner.scan(w.devices()[0], opts, tmp_path, backends=[w])
    assert len(saved) == 3 and warnings == []
    assert dev.prop(scanner.WIA_DPS_DOCUMENT_HANDLING_SELECT) == scanner.FEEDER | scanner.DUPLEX
    assert dev.prop(scanner.WIA_DPS_PAGES) == 1
    assert dev.prop(scanner.WIA_DPS_PAGE_HEIGHT) == 12990
    props = {p.PropertyID: p.Value for p in item.Properties}
    assert props[scanner.WIA_IPS_CUR_INTENT] == scanner.INTENT_GRAY
    assert props[scanner.WIA_IPS_XRES] == 300
    assert props[scanner.WIA_IPS_XEXTENT] == 2538
    assert props[scanner.WIA_IPS_YEXTENT] == 3500  # clipped to what the scanner allows


def test_wia_duplex_unsupported_falls_back(wia, tmp_path):
    dev = FakeWiaDevice(FakeItem([page()]), duplex_ok=False)
    w = wia(dev)
    _, warnings = scanner.scan(w.devices()[0], scanner.Options(duplex=True), tmp_path, backends=[w])
    assert dev.prop(scanner.WIA_DPS_DOCUMENT_HANDLING_SELECT) == scanner.FEEDER
    assert warnings == ["scan dua sisi tidak didukung"]


def test_wia_empty_feeder(wia, tmp_path):
    w = wia(FakeWiaDevice(FakeItem([page()]), feed_ready=False))
    with pytest.raises(scanner.ScanError, match="Tidak ada kertas"):
        scanner.scan(w.devices()[0], scanner.Options(feeder=True), tmp_path, backends=[w])


def test_wia_paper_jam_keeps_pages(wia, tmp_path):
    w = wia(FakeWiaDevice(FakeItem([page(), page()], end_code=0x80210002)))
    with pytest.raises(scanner.ScanError, match="macet") as e:
        scanner.scan(w.devices()[0], scanner.Options(), tmp_path, backends=[w])
    assert len(e.value.saved) == 2


def test_wia_flatbed_one_page(wia, tmp_path):
    dev = FakeWiaDevice(FakeItem([page(), page()]))
    w = wia(dev)
    saved, _ = scanner.scan(w.devices()[0], scanner.Options(feeder=False, color=True), tmp_path, backends=[w])
    assert len(saved) == 1
    assert dev.prop(scanner.WIA_DPS_DOCUMENT_HANDLING_SELECT) == scanner.FLATBED


def test_hresult_from_com_error():
    assert scanner._hresult(ComError(0x80210003)) == 0x80210003
    plain = types.SimpleNamespace(hresult=-2147024809, excepinfo=None)
    assert scanner._hresult(plain) == 0x80070057


def test_twain_needs_windows():
    if sys.platform == "win32":
        pytest.skip("Windows: real TWAIN")
    with pytest.raises(scanner.ScanError, match="Windows"):
        scanner.Twain().devices()


# ---------------------------------------------------------------------------
# dialog
# ---------------------------------------------------------------------------


@pytest.fixture
def display(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter", exc_type=ImportError)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    try:
        tk.Tk().destroy()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    return tk


@pytest.fixture
def root(display):
    r = display.Tk()
    yield r
    r.destroy()


def wait(w, cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        w.update()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timeout")


def test_dialog_scans_into_folder(root, tmp_path, monkeypatch):
    import scan_dialog

    monkeypatch.setattr(scan_dialog.messagebox, "showerror", lambda *a, **k: None)
    fake = FakeBackend(pages=2)
    folder = tmp_path / "ljk"
    seen = []
    d = scan_dialog.ScanDialog(root, folder, on_page=seen.append, backends=[Broken(), fake])
    wait(d, lambda: d.device.get() == "Scanner Uji  (FAKE)")
    assert str(d.show_ui_cb["state"]) == "disabled"  # driver window is TWAIN only
    d.feeder.set(False)
    d.on_source()
    assert str(d.duplex_cb["state"]) == "disabled"
    d.feeder.set(True)
    d.duplex.set(True)
    d.dpi.set("200")
    d.paper.set("F4 / Folio")
    d.start()
    wait(d, lambda: "Selesai" in d.status.get())
    assert [p.name for p in seen] == ["scan_0001.jpg", "scan_0002.jpg"]
    assert "F4 tidak bisa diatur" in d.status.get()
    o = fake.opts
    assert (o.feeder, o.duplex, o.dpi, o.paper, o.show_ui) == (True, True, 200, "F4", False)
    assert scanner.Options.load().device == "FAKE:dev1"

    fake.fail_after, fake.pages = 1, 3  # second batch: jam after one sheet
    d.start()
    wait(d, lambda: d.status.get().startswith("Gagal"))
    assert "1 lembar sebelumnya" in d.status.get()
    assert sorted(p.name for p in folder.iterdir()) == ["scan_0001.jpg", "scan_0002.jpg", "scan_0003.jpg"]
    d.close()
    assert not d.winfo_exists()


def test_dialog_without_scanner(root, tmp_path):
    import scan_dialog

    d = scan_dialog.ScanDialog(root, tmp_path, backends=[Broken()])
    wait(d, lambda: "Tidak ada scanner" in d.device_info.get())
    assert "TWAINDSM.dll" in d.device_info.get()
    assert str(d.start_btn["state"]) == "normal"
    d.destroy()


def test_dialog_close_while_scanning_stops(root, tmp_path, monkeypatch):
    import scan_dialog

    monkeypatch.setattr(scan_dialog.messagebox, "askyesno", lambda *a, **k: True)
    fake = FakeBackend(pages=50, delay=0.05)
    seen = []
    d = scan_dialog.ScanDialog(root, tmp_path, on_page=seen.append, backends=[fake])
    wait(d, lambda: bool(d.device.get()))
    d.start()
    wait(d, lambda: len(seen) >= 2)
    d.close()
    wait(root, lambda: not d.winfo_exists())
    assert 2 <= len(list(tmp_path.glob("scan_*.jpg"))) < 50
    assert len(seen) == len(list(tmp_path.glob("scan_*.jpg")))
    assert not d.worker.is_alive()


def test_wizard_step3_scan_button(display, tmp_path, monkeypatch):
    import scan_dialog
    import wizard

    fake = FakeBackend(pages=2)
    real = scan_dialog.ScanDialog
    state = {"started": False}

    def dialog(master, folder, on_page=None):
        d = real(master, folder, on_page=on_page, backends=[fake])

        def drive():
            if not state["started"] and d.device.get():
                state["started"] = True
                d.start()
            elif state["started"] and "Selesai" in d.status.get():
                d.close()
                return
            d.after(50, drive)

        d.after(50, drive)
        return d

    monkeypatch.setattr(scan_dialog, "ScanDialog", dialog)
    w = wizard.Wizard(library=tmp_path / "lib", settings=tmp_path / "ujian.json")
    try:
        w.go(2)
        step = w.steps[2]
        folder = tmp_path / "LJK kelas 9A"
        monkeypatch.setattr(wizard.filedialog, "askdirectory", lambda **k: str(folder))
        button = next(b for b in iter_widgets(step) if isinstance(b, wizard.ttk.Button)
                      and b["text"] == "Scan dari scanner...")  # fmt: skip
        button.invoke()
        assert step.folder.get() == str(folder)
        assert step.files.get(0, "end") == ("scan_0001.jpg", "scan_0002.jpg")
        assert step.count.get().startswith("2 file")
    finally:
        w.destroy()


def iter_widgets(w):
    for c in w.winfo_children():
        yield c
        yield from iter_widgets(c)
