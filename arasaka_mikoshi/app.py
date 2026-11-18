"""
ARASAKA MIKOSHI // interface (PySide6 / Qt 6).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QProcess, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from . import core
from .core import APP_NAME, VERSION, VM, Config
from .kit import (BG2, FG, FONTS, LINE, MUTED, RED, RED_HI, BaseDialog, CutFrame, HudHeader, Indicator, Page,
                  SidebarBrand, StatusCard, button, label, load_fonts, logo_pixmap, spaced, stylesheet)

EXTRA_QSS = """
QSpinBox { background: #050506; border: 1px solid #2a2a31; padding: 7px 8px; selection-background-color: #e3121f; }
QSpinBox:focus { border-color: #e3121f; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; background: #141418; border: none; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e3121f; }
QSpinBox::up-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent;
  border-bottom: 5px solid #ececf0; width: 0; height: 0; }
QSpinBox::down-arrow { border-left: 4px solid transparent; border-right: 4px solid transparent;
  border-top: 5px solid #ececf0; width: 0; height: 0; }
QPlainTextEdit#log { background: #030304; border: 1px solid #1d1d22; color: #c9c9cf; }
QPushButton::menu-indicator { image: none; width: 0; }
"""

STATE_TXT = {"running": "ONLINE", "paused": "PAUSADA", "stopped": "OFFLINE"}
GLYPH = {"win11": "WIN 11", "win10": "WIN 10", "linux": "LINUX", "other": "SYS"}


class Task(QThread):
    """Roda uma funcao bloqueante fora da interface."""
    done = Signal(object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        except Exception as e:  # noqa: BLE001
            self.done.emit(f"erro: {e}")


# ================================================================ widgets
class ScreenView(QWidget):
    """Monitor HUD: mostra a tela da VM (screendump) ou o estado offline."""

    def __init__(self):
        super().__init__()
        self.img: QImage | None = None
        self.state = "stopped"
        self.glyph = ""
        self.title = ""
        self.setMinimumHeight(300)
        self.t = 0
        tm = QTimer(self)
        tm.timeout.connect(self._tick)
        tm.start(60)

    def _tick(self):
        self.t += 1
        self.update()

    def set_vm(self, vm: VM | None, state: str):
        self.state = state
        self.glyph = GLYPH.get(vm.meta["profile"], "SYS") if vm else ""
        self.title = vm.name.upper() if vm else ""
        if state == "stopped":
            self.img = None

    def set_image(self, img: QImage | None):
        if img is not None and not img.isNull():
            self.img = img

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        # area 16:10 centralizada
        h = H - 4
        w = min(W - 4, h * 16 / 10)
        h = w * 10 / 16
        x0, y0 = (W - w) / 2, (H - h) / 2
        r = QRectF(x0, y0, w, h)
        p.fillRect(r, QColor(4, 4, 5))
        if self.img is not None and self.state != "stopped":
            sc = self.img.scaled(int(w), int(h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawImage(QPointF(x0 + (w - sc.width()) / 2, y0 + (h - sc.height()) / 2), sc)
            if self.state == "paused":
                p.fillRect(r, QColor(0, 0, 0, 150))
        else:
            p.setPen(QPen(QColor(227, 18, 31, 22), 1))
            step = 26
            gx = x0
            while gx < x0 + w:
                p.drawLine(QPointF(gx, y0), QPointF(gx, y0 + h))
                gx += step
            gy = y0
            while gy < y0 + h:
                p.drawLine(QPointF(x0, gy), QPointF(x0 + w, gy))
                gy += step
            lg = logo_pixmap(int(h * 0.34))
            p.setOpacity(0.18 if self.state == "stopped" else 0.9)
            p.drawPixmap(int(x0 + w / 2 - lg.width() / lg.devicePixelRatio() / 2), int(y0 + h * 0.18), lg)
            p.setOpacity(1)
            f = QFont(FONTS["ui"])
            f.setPixelSize(int(h * 0.075))
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 8)
            p.setFont(f)
            p.setPen(FG if self.state != "stopped" else MUTED)
            p.drawText(QRectF(x0, y0 + h * 0.58, w, h * 0.12), Qt.AlignCenter, self.glyph)
            f.setPixelSize(int(h * 0.045))
            f.setLetterSpacing(QFont.AbsoluteSpacing, 5)
            p.setFont(f)
            msg = {"stopped": "CONSTRUCT OFFLINE", "paused": "EXECUCAO SUSPENSA",
                   "running": "SINAL DE VIDEO NA JANELA DA VM"}[self.state]
            p.setPen(RED if self.state == "stopped" else MUTED)
            p.drawText(QRectF(x0, y0 + h * 0.72, w, h * 0.08), Qt.AlignCenter, msg)
        # scanlines + feixe
        p.setPen(QPen(QColor(0, 0, 0, 55), 1))
        yy = y0
        while yy < y0 + h:
            p.drawLine(QPointF(x0, yy), QPointF(x0 + w, yy))
            yy += 3
        if self.state == "running":
            by = y0 + ((self.t * 4) % int(h + 60)) - 30
            g = QLinearGradient(0, by - 30, 0, by + 30)
            g.setColorAt(0, QColor(227, 18, 31, 0))
            g.setColorAt(0.5, QColor(227, 18, 31, 28))
            g.setColorAt(1, QColor(227, 18, 31, 0))
            p.fillRect(QRectF(x0, max(y0, by - 30), w, min(60, y0 + h - max(y0, by - 30))), g)
        # moldura
        p.setPen(QPen(QColor(227, 18, 31, 170) if self.state != "stopped" else LINE, 1))
        p.drawRect(r)
        p.setPen(QPen(RED, 3))
        L = 26
        for cx, cy, sx, sy in [(x0, y0, 1, 1), (x0 + w, y0, -1, 1), (x0, y0 + h, 1, -1), (x0 + w, y0 + h, -1, -1)]:
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * L, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * L))
        # etiqueta
        f = QFont(FONTS["mono"])
        f.setPixelSize(11)
        p.setFont(f)
        tag = f" {self.title}  //  {STATE_TXT.get(self.state, '')} "
        tw = p.fontMetrics().horizontalAdvance(tag) + 8
        p.fillRect(QRectF(x0 + 34, y0 - 1, tw, 18), QColor(5, 5, 6))
        p.setPen(RED_HI if self.state != "stopped" else MUTED)
        p.drawText(QRectF(x0 + 38, y0 - 1, tw, 18), Qt.AlignVCenter, tag)


class Meter(QWidget):
    """Barra segmentada estilo HUD (CPU / RAM)."""

    def __init__(self, title: str):
        super().__init__()
        self.title, self.value, self.text = title, 0.0, "--"
        self.setMinimumHeight(54)

    def set(self, value: float, text: str):
        self.value, self.text = max(0.0, min(1.0, value)), text
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        W = self.width()
        f = QFont(FONTS["ui"])
        f.setPixelSize(12)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(f)
        p.setPen(MUTED)
        p.drawText(QRectF(0, 0, W, 18), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        fm = QFont(FONTS["mono"])
        fm.setPixelSize(12)
        p.setFont(fm)
        p.setPen(FG)
        p.drawText(QRectF(0, 0, W, 18), Qt.AlignRight | Qt.AlignVCenter, self.text)
        n = 32
        gap = 3
        sw = (W - gap * (n - 1)) / n
        lit = round(self.value * n)
        for i in range(n):
            c = (RED_HI if i > n * 0.8 else RED) if i < lit else QColor(30, 30, 36)
            p.fillRect(QRectF(i * (sw + gap), 26, sw, 14), c)


class ProfileCard(CutFrame):
    clicked = Signal(str)

    def __init__(self, prof: core.Profile):
        super().__init__(cut=12)
        self.key = prof.key
        self.prof = prof
        self.selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(118)

    def set_selected(self, s: bool):
        self.selected = s
        self.set_border(RED if s else LINE)
        self.fill = QColor(26, 6, 9) if s else BG2

    def mousePressEvent(self, _e):
        self.clicked.emit(self.key)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        f = QFont(FONTS["ui"])
        f.setPixelSize(30)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(f)
        p.setPen(RED if self.selected else QColor(80, 80, 90))
        p.drawText(QRectF(0, 14, W, 40), Qt.AlignCenter, GLYPH[self.key])
        f.setPixelSize(13)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(f)
        p.setPen(FG)
        p.drawText(QRectF(0, 60, W, 20), Qt.AlignCenter, self.prof.title)
        fm = QFont(FONTS["mono"])
        fm.setPixelSize(11)
        p.setFont(fm)
        p.setPen(MUTED)
        pr = self.prof
        p.drawText(QRectF(0, 84, W, 18), Qt.AlignCenter,
                   f"{pr.cpus} CPU · {pr.ram // 1024} GB · {pr.disk} GB{' · TPM' if pr.tpm else ''}")


def path_row(edit: QLineEdit, title: str, filt: str = "", folder=False, extra: QPushButton | None = None):
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(edit, 1)

    def pick():
        start = edit.text() or str(Path.home() / "Downloads")
        if folder:
            pth = QFileDialog.getExistingDirectory(edit, title, start)
        else:
            pth, _ = QFileDialog.getOpenFileName(edit, title, start, filt)
        if pth:
            edit.setText(pth)
    row.addWidget(button("PROCURAR", None, pick))
    if extra:
        row.addWidget(extra)
    return row


def iso_menu_button(parent) -> QPushButton:
    b = button("BAIXAR ISO ▾")
    m = QMenu(b)
    for name, url in core.ISO_LINKS:
        m.addAction(name, lambda u=url: QDesktopServices.openUrl(QUrl(u)))
    b.setMenu(m)
    return b


# ================================================================ pagina: maquinas
class MachinesPage(Page):
    def __init__(self, win):
        super().__init__(win, "CONSTRUCTS", "Suas maquinas virtuais", "MIKOSHI://VAULT")
        self.stats = core.Stats()
        self.tasks = []
        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(label("MAQUINAS", "section", 3))
        self.list = QListWidget()
        self.list.setFixedWidth(260)
        self.list.setIconSize(QSize(22, 22))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.currentItemChanged.connect(lambda *_: self.show_vm())
        left.addWidget(self.list, 1)
        left.addWidget(button("+  NOVA MAQUINA", "primary", lambda: win.go("new")))
        body.addLayout(left)

        self.right = QStackedWidget()
        empty = CutFrame(cut=16)
        el = QVBoxLayout(empty)
        el.setContentsMargins(40, 40, 40, 40)
        el.addStretch()
        lg = QLabel()
        lg.setPixmap(logo_pixmap(96))
        lg.setAlignment(Qt.AlignCenter)
        el.addWidget(lg)
        t = label("NENHUMA MAQUINA NO COFRE", None, 4, 20, True)
        t.setAlignment(Qt.AlignCenter)
        el.addWidget(t)
        d = label("Crie uma maquina com Windows ou Linux a partir de uma ISO.", "muted", 0.5)
        d.setAlignment(Qt.AlignCenter)
        el.addWidget(d)
        el.addWidget(button("CRIAR PRIMEIRA MAQUINA", "primary", lambda: win.go("new")), 0, Qt.AlignCenter)
        el.addStretch()
        self.right.addWidget(empty)

        det = QWidget()
        dl = QVBoxLayout(det)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(12)
        head = QHBoxLayout()
        self.v_title = label("", None, 3, 22, True)
        head.addWidget(self.v_title)
        head.addStretch()
        self.v_ind = Indicator(False)
        head.addWidget(self.v_ind)
        self.v_state = label("", "red", 3, 13, True)
        head.addWidget(self.v_state)
        dl.addLayout(head)
        self.v_meta = label("", "muted", 0.5)
        dl.addWidget(self.v_meta)
        self.screen = ScreenView()
        dl.addWidget(self.screen, 1)

        meters = QHBoxLayout()
        meters.setSpacing(18)
        self.m_cpu = Meter("CPU")
        self.m_ram = Meter("MEMORIA")
        self.m_up = label("UPTIME  --:--:--", "muted", 2, 12, True)
        meters.addWidget(self.m_cpu, 2)
        meters.addWidget(self.m_ram, 2)
        meters.addWidget(self.m_up, 1)
        dl.addLayout(meters)

        act = QHBoxLayout()
        act.setSpacing(8)
        self.b_start = button("▶  INICIAR", "primary", self.start)
        self.b_start.setMinimumWidth(150)
        self.b_stop = button("DESLIGAR", None, lambda: self.power(False), "Desliga como o botao de energia (ACPI)")
        self.b_pause = button("PAUSAR", None, self.toggle_pause)
        self.b_reset = button("REINICIAR", None, lambda: self.run_vm(core.reset_vm))
        self.b_kill = button("FORCAR", "danger", lambda: self.power(True), "Corta a energia na hora")
        self.b_view = button("ABRIR TELA", None, self.view, "Reabre a janela SPICE")
        for b in (self.b_start, self.b_stop, self.b_pause, self.b_reset, self.b_kill, self.b_view):
            act.addWidget(b)
        act.addStretch()
        dl.addLayout(act)

        cols = QHBoxLayout()
        cols.setSpacing(14)
        media = CutFrame(cut=10)
        ml = QVBoxLayout(media)
        ml.setContentsMargins(16, 12, 16, 12)
        ml.addWidget(label("MIDIA (CD/DVD)", "section", 3))
        self.v_iso = label("", "muted", 0.3)
        self.v_iso.setWordWrap(True)
        ml.addWidget(self.v_iso)
        mr = QHBoxLayout()
        mr.addWidget(button("TROCAR ISO", None, self.pick_iso))
        mr.addWidget(button("EJETAR", None, lambda: self.set_iso("")))
        mr.addStretch()
        ml.addLayout(mr)
        cols.addWidget(media, 1)

        snap = CutFrame(cut=10)
        sl = QVBoxLayout(snap)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.addWidget(label("SNAPSHOTS", "section", 3))
        self.snaps = QListWidget()
        self.snaps.setMaximumHeight(96)
        sl.addWidget(self.snaps)
        sr = QHBoxLayout()
        sr.addWidget(button("SALVAR", None, self.snap_create, "Salva o estado do disco (VM desligada)"))
        sr.addWidget(button("RESTAURAR", None, lambda: self.snap_do("apply")))
        sr.addWidget(button("APAGAR", "ghost", lambda: self.snap_do("delete")))
        sr.addStretch()
        sl.addLayout(sr)
        cols.addWidget(snap, 1)
        dl.addLayout(cols)

        cfg_row = QHBoxLayout()
        cfg_row.setSpacing(8)
        cfg_row.addWidget(button("EDITAR", None, self.edit))
        cfg_row.addWidget(button("COMANDO QEMU", "ghost", self.show_cmd))
        cfg_row.addWidget(button("LOG", "ghost", self.show_log))
        cfg_row.addWidget(button("PASTA", "ghost", lambda: self.cur() and QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.cur().path)))))
        cfg_row.addStretch()
        cfg_row.addWidget(button("EXCLUIR MAQUINA", "danger", self.delete))
        dl.addLayout(cfg_row)
        self.right.addWidget(det)
        body.addWidget(self.right, 1)
        self.lay.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1500)
        self.shot_n = 0

    # ------------------------------------------------ dados
    def cur(self) -> VM | None:
        it = self.list.currentItem()
        return core.get_vm(self.win.cfg, it.data(Qt.UserRole)) if it else None

    def refresh(self, select: str | None = None):
        keep = select or (self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None)
        self.list.blockSignals(True)
        self.list.clear()
        for vm in core.list_vms(self.win.cfg):
            st = vm.state()
            it = QListWidgetItem(f"{vm.name.upper()}\n{GLYPH.get(vm.meta['profile'])}  ·  {STATE_TXT[st]}")
            it.setData(Qt.UserRole, vm.slug)
            it.setIcon(QIcon(logo_pixmap(22)))
            if st != "stopped":
                it.setForeground(QColor(255, 59, 71))
            f = it.font()
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
            it.setFont(f)
            self.list.addItem(it)
            if vm.slug == keep:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.show_vm()

    def show_vm(self):
        vm = self.cur()
        if not vm:
            self.right.setCurrentIndex(0)
            return
        self.right.setCurrentIndex(1)
        self.v_title.setText(vm.name.upper())
        info = core.disk_info(self.win.cfg, vm.disk)
        size = info.get("virtual-size", 0) / 1024 ** 3
        used = info.get("actual-size", 0) / 1024 ** 3
        extra = []
        if vm.meta.get("ports"):
            extra.append("PORTAS " + vm.meta["ports"])
        if vm.meta.get("share"):
            extra.append("PASTA COMPARTILHADA")
        self.v_meta.setText(f"{vm.profile.title}  ·  {vm.summary()}  ·  DISCO {used:.1f}/{size:.0f} GB"
                            + ("  ·  " + "  ·  ".join(extra) if extra else ""))
        iso = vm.meta.get("iso") or ""
        self.v_iso.setText(Path(iso).name if iso else "Nenhuma ISO inserida (a VM inicia pelo disco).")
        self.v_iso.setToolTip(iso)
        self.snaps.clear()
        for s in core.snapshots(self.win.cfg, vm):
            self.snaps.addItem(f"{s['name']}   ·   {s['date']}")
        self.update_state(vm)

    def update_state(self, vm: VM):
        st = vm.state()
        on = st != "stopped"
        self.v_state.setText(STATE_TXT[st])
        self.v_state.setObjectName("red" if on else "muted")
        self.v_state.style().unpolish(self.v_state)
        self.v_state.style().polish(self.v_state)
        self.v_ind.set_ok(not on)
        self.screen.set_vm(vm, st)
        self.b_start.setVisible(not on)
        for b in (self.b_stop, self.b_pause, self.b_reset, self.b_kill):
            b.setVisible(on)
        self.b_view.setVisible(on and (vm.meta.get("display") or self.win.cfg["display"]) == "spice")
        self.b_pause.setText("RETOMAR" if st == "paused" else "PAUSAR")
        s = self.stats.read(vm) if on else None
        if s:
            self.m_cpu.set(s["cpu"] / 100, f"{s['cpu']:.0f}%")
            self.m_ram.set(s["ram_mb"] / max(1, vm.meta["ram"]),
                           f"{s['ram_mb'] / 1024:.1f} / {vm.meta['ram'] / 1024:.0f} GB")
            self.m_up.setText(f"UPTIME  {core.fmt_uptime(s['uptime'])}")
        else:
            self.m_cpu.set(0, "--")
            self.m_ram.set(0, "--")
            self.m_up.setText("UPTIME  --:--:--")
        return st

    def tick(self):
        if not self.isVisible():
            return
        vm = self.cur()
        if not vm:
            return
        old = self.screen.state
        st = self.update_state(vm)
        if st != old:
            self.refresh(vm.slug)
        if st == "running" and self.win.cfg["preview"]:
            self.shot_n += 1
            if self.shot_n % 2 == 0:
                if core.DEMO:
                    self.screen.set_image(demo_screen(vm))
                else:
                    t = Task(core.screendump, vm)
                    t.done.connect(lambda p: isinstance(p, Path) and self.screen.set_image(QImage(str(p))))
                    self.keep(t)

    def keep(self, t: Task):
        self.tasks = [x for x in self.tasks if x.isRunning()]
        self.tasks.append(t)
        t.start()

    # ------------------------------------------------ acoes
    def start(self):
        vm = self.cur()
        if not vm:
            return
        self.b_start.setEnabled(False)
        self.b_start.setText("INICIANDO...")
        t = Task(core.start_vm, self.win.cfg, vm)

        def done(err):
            self.b_start.setEnabled(True)
            self.b_start.setText("▶  INICIAR")
            if err:
                self.win.alert("FALHA AO INICIAR", str(err))
            else:
                self.win.toast(f"{vm.name} online")
            self.refresh(vm.slug)
        t.done.connect(done)
        self.keep(t)

    def power(self, force: bool):
        vm = self.cur()
        if not vm:
            return
        if force and not self.win.confirm("FORCAR DESLIGAMENTO",
                                          "Cortar a energia da VM agora? Trabalho nao salvo dentro dela sera perdido."):
            return
        core.stop_vm(vm, force)
        self.win.toast("Sinal de desligamento enviado" if not force else "VM desligada")
        QTimer.singleShot(800, lambda: self.refresh(vm.slug))

    def toggle_pause(self):
        vm = self.cur()
        if vm:
            core.pause_vm(vm, vm.state() != "paused")
            self.update_state(vm)

    def run_vm(self, fn):
        vm = self.cur()
        if vm:
            fn(vm)

    def view(self):
        vm = self.cur()
        if vm:
            err = core.open_viewer(vm)
            if err:
                self.win.toast(err)

    def pick_iso(self):
        vm = self.cur()
        if not vm:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Escolha a ISO", str(Path.home() / "Downloads"),
                                           "Imagens de disco (*.iso *.img);;Todos (*)")
        if p:
            self.set_iso(p)

    def set_iso(self, iso: str):
        vm = self.cur()
        if vm:
            core.change_iso(vm, iso)
            self.show_vm()
            self.win.toast("ISO inserida" if iso else "ISO ejetada")

    def snap_create(self):
        vm = self.cur()
        if not vm:
            return
        name, ok = QInputDialog.getText(self, "SNAPSHOT", "Nome do snapshot:",
                                        text=time.strftime("snap-%Y%m%d-%H%M"))
        if ok and name.strip():
            err = core.snapshot_cmd(self.win.cfg, vm, "create", name.strip().replace(" ", "-"))
            self.win.toast(err or "Snapshot salvo")
            self.show_vm()

    def snap_do(self, action: str):
        vm = self.cur()
        it = self.snaps.currentItem()
        if not vm or not it:
            self.win.toast("Selecione um snapshot")
            return
        name = it.text().split("   ·   ")[0]
        verb = "Restaurar o disco para" if action == "apply" else "Apagar o snapshot"
        if self.win.confirm("SNAPSHOT", f"{verb} '{name}'?"):
            err = core.snapshot_cmd(self.win.cfg, vm, action, name)
            self.win.toast(err or "Feito")
            self.show_vm()

    def edit(self):
        vm = self.cur()
        if not vm:
            return
        d = EditDialog(self, self.win.cfg, vm)
        if d.exec() == QDialog.Accepted:
            err = d.apply()
            if err:
                self.win.alert("EDITAR", err)
            self.refresh(vm.slug)

    def show_cmd(self):
        vm = self.cur()
        if vm:
            TextDialog(self, "COMANDO QEMU", core.command_text(core.build_command(self.win.cfg, vm))).exec()

    def show_log(self):
        vm = self.cur()
        if vm:
            TextDialog(self, "LOG DA VM", core.tail(vm.log_path, 200) or "(vazio)").exec()

    def delete(self):
        vm = self.cur()
        if vm and self.win.confirm("EXCLUIR MAQUINA", f"Excluir '{vm.name}' e o disco virtual dela?\n{vm.path}\n\n"
                                                      "Isso nao pode ser desfeito."):
            core.delete_vm(vm)
            self.refresh()


def demo_screen(vm: VM) -> QImage:
    img = QImage(1280, 800, QImage.Format_RGB32)
    p = QPainter(img)
    win = vm.family == "windows"
    g = QLinearGradient(0, 0, 1280, 800)
    g.setColorAt(0, QColor(0, 60, 140) if win else QColor(40, 10, 60))
    g.setColorAt(1, QColor(0, 120, 215) if win else QColor(200, 70, 20))
    p.fillRect(0, 0, 1280, 800, g)
    p.fillRect(0, 752, 1280, 48, QColor(20, 20, 24, 230))
    f = QFont(FONTS["ui"])
    f.setPixelSize(56)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255))
    p.drawText(QRectF(0, 300, 1280, 100), Qt.AlignCenter, "Windows Setup" if win else "Install Ubuntu")
    f.setPixelSize(24)
    p.setFont(f)
    p.drawText(QRectF(0, 400, 1280, 50), Qt.AlignCenter, time.strftime("%H:%M:%S"))
    p.end()
    return img


# ================================================================ dialogos
class TextDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent, title, "")
        self.setMinimumSize(760, 480)
        t = QPlainTextEdit(text)
        t.setObjectName("log")
        t.setReadOnly(True)
        f = QFont(FONTS["mono"])
        f.setPixelSize(12)
        t.setFont(f)
        self.lay.addWidget(t, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("COPIAR", None, lambda: QApplication.clipboard().setText(text)))
        row.addWidget(button("FECHAR", "primary", self.accept))
        self.lay.addLayout(row)


class EditDialog(BaseDialog):
    def __init__(self, parent, cfg: Config, vm: VM):
        super().__init__(parent, "EDITAR MAQUINA", vm.name)
        self.cfg, self.vm = cfg, vm
        on = vm.running()
        form = QFormLayout()
        form.setSpacing(10)
        m = vm.meta
        self.name = QLineEdit(vm.name)
        form.addRow(label("NOME", "muted", 2, bold=True), self.name)
        self.cpus = QSpinBox()
        self.cpus.setRange(1, core.host_cpus())
        self.cpus.setValue(m["cpus"])
        form.addRow(label("CPUS", "muted", 2, bold=True), self.cpus)
        self.ram = QSpinBox()
        self.ram.setRange(1, max(2, core.host_ram_mb() // 1024))
        self.ram.setSuffix(" GB")
        self.ram.setValue(max(1, m["ram"] // 1024))
        form.addRow(label("MEMORIA", "muted", 2, bold=True), self.ram)
        info = core.disk_info(cfg, vm.disk)
        self.cur_disk = int(round(info.get("virtual-size", 0) / 1024 ** 3)) or 1
        self.disk = QSpinBox()
        self.disk.setRange(self.cur_disk, 4096)
        self.disk.setSuffix(" GB")
        self.disk.setValue(self.cur_disk)
        self.disk.setToolTip("So e possivel aumentar. Depois, aumente a particao dentro do sistema.")
        form.addRow(label("DISCO", "muted", 2, bold=True), self.disk)
        self.display = QComboBox()
        self.display.addItem("Janela QEMU (GTK)", "gtk")
        self.display.addItem("SPICE: copiar/colar e USB", "spice")
        self.display.setCurrentIndex(1 if (m.get("display") or cfg["display"]) == "spice" else 0)
        form.addRow(label("TELA", "muted", 2, bold=True), self.display)
        self.share = QLineEdit(m.get("share", ""))
        self.share.setPlaceholderText("pasta do Linux visivel na VM (precisa do Samba)")
        form.addRow(label("COMPARTILHAR", "muted", 2, bold=True), path_row(self.share, "Pasta", folder=True))
        self.ports = QLineEdit(m.get("ports", ""))
        self.ports.setPlaceholderText("ex.: 2222:22, 3389")
        form.addRow(label("PORTAS", "muted", 2, bold=True), self.ports)
        self.lay.addLayout(form)
        self.tpm = QCheckBox("TPM 2.0")
        self.tpm.setChecked(bool(m.get("tpm")))
        self.lay.addWidget(self.tpm)
        self.gl = QCheckBox("Aceleracao 3D (virgl, so Linux)")
        self.gl.setChecked(bool(m.get("accel3d")))
        self.gl.setEnabled(vm.family == "linux")
        self.lay.addWidget(self.gl)
        if on:
            self.lay.addWidget(label("A VM esta ligada: as mudancas valem na proxima vez que ela iniciar "
                                     "(o disco so pode ser aumentado com ela desligada).", "red", 0.3, wrap=True))
            self.disk.setEnabled(False)
        self.add_buttons("SALVAR")

    def apply(self) -> str:
        m = self.vm.meta
        m.update({"name": self.name.text().strip() or m["name"], "cpus": self.cpus.value(),
                  "ram": self.ram.value() * 1024, "display": self.display.currentData(),
                  "share": self.share.text().strip(), "ports": self.ports.text().strip(),
                  "tpm": self.tpm.isChecked(), "accel3d": self.gl.isChecked()})
        self.vm.save()
        if self.disk.isEnabled() and self.disk.value() > self.cur_disk:
            return core.resize_disk(self.cfg, self.vm, self.disk.value())
        return ""


# ================================================================ pagina: nova maquina
class NewPage(Page):
    def __init__(self, win):
        super().__init__(win, "NOVO CONSTRUCT", "Crie uma maquina virtual com Windows ou Linux", "MIKOSHI://FORGE")
        self.lay.addWidget(label("01  //  SISTEMA", "section", 3))
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.cards = {}
        for key, prof in core.PROFILES.items():
            c = ProfileCard(prof)
            c.clicked.connect(self.select)
            cards.addWidget(c)
            self.cards[key] = c
        self.lay.addLayout(cards)
        self.note = label("", "muted", 0.3, wrap=True)
        self.lay.addWidget(self.note)

        self.lay.addWidget(label("02  //  INSTALADOR", "section", 3))
        box = CutFrame(cut=12)
        f = QFormLayout(box)
        f.setContentsMargins(20, 16, 20, 16)
        f.setSpacing(12)
        self.iso = QLineEdit()
        self.iso.setPlaceholderText("arquivo .iso do Windows ou da distribuicao Linux")
        self.iso.textChanged.connect(self.iso_changed)
        f.addRow(label("ISO", "muted", 2, bold=True),
                 path_row(self.iso, "Escolha a ISO", "Imagens de disco (*.iso *.img);;Todos (*)",
                          extra=iso_menu_button(self)))
        self.name = QLineEdit()
        self.name.setPlaceholderText("ex.: Windows Trabalho")
        f.addRow(label("NOME", "muted", 2, bold=True), self.name)
        self.use_disk = QCheckBox("Usar um disco virtual existente (qcow2, vdi, vmdk, vhdx, img) em vez de criar")
        f.addRow("", self.use_disk)
        self.disk_path = QLineEdit()
        self.disk_path.setEnabled(False)
        self.use_disk.toggled.connect(self.disk_path.setEnabled)
        f.addRow(label("DISCO", "muted", 2, bold=True),
                 path_row(self.disk_path, "Disco existente", "Discos (*.qcow2 *.vdi *.vmdk *.vhdx *.img *.raw)"))
        self.lay.addWidget(box)

        self.lay.addWidget(label("03  //  HARDWARE", "section", 3))
        hw = CutFrame(cut=12)
        g = QGridLayout(hw)
        g.setContentsMargins(20, 16, 20, 16)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(10)
        self.cpus = QSpinBox()
        self.cpus.setRange(1, core.host_cpus())
        self.ram = QSpinBox()
        self.ram.setRange(1, max(2, core.host_ram_mb() // 1024 - 1))
        self.ram.setSuffix(" GB")
        self.disk = QSpinBox()
        self.disk.setRange(8, 4096)
        self.disk.setSuffix(" GB")
        for i, (t, w, hint) in enumerate([
                ("CPUS", self.cpus, f"de {core.host_cpus()} no PC"),
                ("MEMORIA", self.ram, f"de {core.host_ram_mb() // 1024} GB no PC"),
                ("DISCO", self.disk, f"{core.free_disk_gb(win.cfg.vm_dir)} GB livres · cresce conforme o uso")]):
            g.addWidget(label(t, "muted", 2, bold=True), 0, i)
            g.addWidget(w, 1, i)
            g.addWidget(label(hint, "dim", 0.3), 2, i)
        self.lay.addWidget(hw)

        self.lay.addWidget(label("04  //  OPCOES", "section", 3))
        op = CutFrame(cut=12)
        ol = QGridLayout(op)
        ol.setContentsMargins(20, 16, 20, 16)
        ol.setVerticalSpacing(10)
        self.uefi = QCheckBox("Firmware UEFI")
        self.secure = QCheckBox("Secure Boot")
        self.tpm = QCheckBox("TPM 2.0")
        self.gl = QCheckBox("Aceleracao 3D (Linux)")
        self.uefi.toggled.connect(lambda v: (self.secure.setEnabled(v), v or self.secure.setChecked(False)))
        for i, w in enumerate([self.uefi, self.secure, self.tpm, self.gl]):
            ol.addWidget(w, 0, i)
        self.display = QComboBox()
        self.display.addItem("Janela QEMU (GTK): simples", "gtk")
        self.display.addItem("SPICE: copiar/colar, USB e tela redimensionavel", "spice")
        self.display.setCurrentIndex(1 if win.cfg["display"] == "spice" else 0)
        ol.addWidget(label("TELA", "muted", 2, bold=True), 1, 0)
        ol.addWidget(self.display, 1, 1, 1, 3)
        self.share = QLineEdit()
        self.share.setPlaceholderText("opcional: pasta do Linux visivel dentro da VM (via Samba)")
        ol.addWidget(label("COMPARTILHAR", "muted", 2, bold=True), 2, 0)
        ol.addLayout(path_row(self.share, "Pasta compartilhada", folder=True), 2, 1, 1, 3)
        self.ports = QLineEdit()
        self.ports.setPlaceholderText("opcional: portas do PC -> VM, ex.: 2222:22 (SSH), 3389 (RDP)")
        ol.addWidget(label("PORTAS", "muted", 2, bold=True), 3, 0)
        ol.addWidget(self.ports, 3, 1, 1, 3)
        self.lay.addWidget(op)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("CRIAR", None, lambda: self.create(False)))
        b = button("CRIAR E INICIAR  ▶", "primary", lambda: self.create(True))
        b.setMinimumWidth(220)
        row.addWidget(b)
        self.lay.addLayout(row)
        self.lay.addStretch()
        self.profile = ""
        self.select("win11")

    def select(self, key: str):
        self.profile = key
        p = core.PROFILES[key]
        for k, c in self.cards.items():
            c.set_selected(k == key)
            c.update()
        self.note.setText("■  " + p.note)
        self.cpus.setValue(min(p.cpus, core.host_cpus()))
        self.ram.setValue(min(p.ram // 1024, self.ram.maximum()))
        self.disk.setValue(p.disk)
        self.uefi.setChecked(p.uefi)
        self.secure.setChecked(p.secureboot)
        self.secure.setEnabled(p.uefi)
        self.tpm.setChecked(p.tpm)
        self.gl.setChecked(False)
        self.gl.setEnabled(p.family == "linux")
        if not self.name.text() or self.name.property("auto"):
            self.name.setText(p.title.title())
            self.name.setProperty("auto", True)

    def iso_changed(self, text: str):
        n = Path(text).name.lower()
        if not n:
            return
        if "win11" in n or "win 11" in n or "windows11" in n or "windows 11" in n:
            self.select("win11")
        elif "win10" in n or "windows10" in n or "windows 10" in n:
            self.select("win10")
        elif any(k in n for k in ("ubuntu", "zorin", "fedora", "mint", "debian", "arch", "manjaro", "pop", "kali",
                                  "elementary", "opensuse", "endeavour", "linux")):
            self.select("linux")
        if self.name.property("auto") or not self.name.text():
            stem = Path(text).stem.replace("_", " ").replace("-", " ")
            self.name.setText(" ".join(stem.split()[:3]).title())
            self.name.setProperty("auto", True)

    def create(self, start: bool):
        iso = self.iso.text().strip()
        existing = self.disk_path.text().strip() if self.use_disk.isChecked() else ""
        if not iso and not existing:
            if not self.win.confirm("SEM ISO", "Nenhuma ISO escolhida: a maquina vai iniciar sem sistema.\n"
                                               "Criar mesmo assim? (voce pode inserir a ISO depois)"):
                return
        if iso and not Path(iso).exists() and not core.DEMO:
            self.win.alert("ISO", f"Arquivo nao encontrado:\n{iso}")
            return
        try:
            vm = core.create_vm(self.win.cfg, self.name.text().strip() or "Maquina", self.profile,
                                self.cpus.value(), self.ram.value() * 1024, self.disk.value(), iso,
                                self.uefi.isChecked(), self.tpm.isChecked(), self.secure.isChecked(),
                                self.gl.isChecked(), existing, self.share.text().strip(), self.ports.text().strip())
        except RuntimeError as e:
            self.win.alert("ERRO", str(e))
            return
        vm.meta["display"] = self.display.currentData()
        if existing and not existing.endswith(".qcow2"):
            fmt = core.disk_info(self.win.cfg, Path(existing)).get("format", "")
            if fmt:
                vm.meta["disk_format"] = fmt
        vm.save()
        self.name.setProperty("auto", True)
        self.iso.clear()
        self.win.go("vms")
        page = self.win.pages["vms"]
        page.refresh(vm.slug)
        self.win.toast(f"{vm.name} criada")
        if start:
            page.start()


# ================================================================ pagina: sistema
class SystemPage(Page):
    def __init__(self, win):
        super().__init__(win, "SYSTEM STATUS", "Virtualizacao do computador hospedeiro", "MIKOSHI://HOST")
        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        self.lay.addLayout(self.grid)
        row = QHBoxLayout()
        row.addWidget(button("INSTALAR TUDO", "primary", lambda: self.install("qemu"),
                             "QEMU, UEFI (OVMF), TPM (swtpm) e permissao KVM"))
        row.addWidget(button("REVERIFICAR", "ghost", self.refresh))
        row.addStretch()
        row.addWidget(iso_menu_button(self))
        self.lay.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.setPlaceholderText("saida das instalacoes aparece aqui")
        self.lay.addWidget(self.log)
        info = CutFrame(cut=12, fill=QColor(10, 4, 6))
        il = QVBoxLayout(info)
        il.setContentsMargins(20, 14, 20, 14)
        il.addWidget(label("COMO FUNCIONA", "section", 3))
        il.addWidget(label(
            "O Mikoshi usa o QEMU com KVM, a mesma tecnologia do GNOME Boxes e do virt-manager: a VM roda "
            "direto no processador, com desempenho perto do nativo. Depois de instalar, encerre a sessao e "
            "entre de novo para a permissao do KVM valer.", "muted", 0.3, wrap=True))
        self.lay.addWidget(info)
        self.lay.addStretch()
        self.proc: QProcess | None = None

    def refresh(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        checks = core.system_checks(self.win.cfg)
        for i, ch in enumerate(checks):
            self.grid.addWidget(StatusCard(ch, self.install), i // 2, i % 2)
        self.win.set_link(all(c.ok or c.optional for c in checks))

    def install(self, key: str):
        cmd = core.dep_script(key)
        if not cmd or self.proc:
            return
        self.log.appendPlainText(f">> instalando ({key})... digite sua senha na janela que abrir")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
                                             .rstrip()))

        def fin(code, _s):
            self.log.appendPlainText("■ concluido" if code == 0 else f"!! falhou (codigo {code})")
            self.proc = None
            self.refresh()
            if code == 0 and key in ("qemu", "kvm"):
                self.win.alert("KVM", "Instalado. Encerre a sessao e entre de novo para a permissao do KVM valer.")
        self.proc.finished.connect(fin)
        self.proc.start(cmd[0], cmd[1:])


# ================================================================ pagina: configuracoes
class SettingsPage(Page):
    def __init__(self, win):
        super().__init__(win, "CONFIGURACOES", "Preferencias do Mikoshi", f"BUILD://{VERSION}")
        cfg = win.cfg
        box = CutFrame(cut=12)
        form = QFormLayout(box)
        form.setContentsMargins(22, 20, 22, 20)
        form.setSpacing(14)
        self.dir = QLineEdit(str(cfg.vm_dir))
        self.dir.editingFinished.connect(lambda: self._set("vm_dir", self.dir.text().strip()))
        form.addRow(label("PASTA DAS VMS", "muted", 2, bold=True), path_row(self.dir, "Pasta das VMs", folder=True))
        self.qemu = QLineEdit(cfg["qemu"])
        self.qemu.editingFinished.connect(lambda: self._set("qemu", self.qemu.text().strip() or "qemu-system-x86_64"))
        form.addRow(label("QEMU", "muted", 2, bold=True), self.qemu)
        self.disp = QComboBox()
        self.disp.addItem("Janela QEMU (GTK)", "gtk")
        self.disp.addItem("SPICE (remote-viewer)", "spice")
        self.disp.setCurrentIndex(1 if cfg["display"] == "spice" else 0)
        self.disp.currentIndexChanged.connect(lambda _: self._set("display", self.disp.currentData()))
        form.addRow(label("TELA PADRAO", "muted", 2, bold=True), self.disp)
        pv = QCheckBox("Miniatura ao vivo da tela da VM")
        pv.setChecked(bool(cfg["preview"]))
        pv.toggled.connect(lambda v: self._set("preview", v))
        form.addRow("", pv)
        self.lay.addWidget(box)
        about = CutFrame(cut=12, fill=QColor(10, 4, 6))
        al = QVBoxLayout(about)
        al.setContentsMargins(22, 18, 22, 18)
        al.addWidget(label(f"{APP_NAME}  v{VERSION}", None, 3, 16, True))
        al.addWidget(label("Gerenciador de maquinas virtuais para Linux (QEMU/KVM, OVMF, swtpm, SPICE). "
                           "Arasaka e Mikoshi sao da CD PROJEKT RED; projeto pessoal de fa.", "muted", 0.3,
                           wrap=True))
        self.lay.addWidget(about)
        self.lay.addStretch()

    def _set(self, k, v):
        self.win.cfg[k] = v
        if k == "vm_dir":
            self.win.pages["vms"].refresh()


# ================================================================ janela
class MainWindow(QMainWindow):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(core.ASSETS / "arasaka-mikoshi.svg")))
        self.resize(1320, 900)
        self.setMinimumSize(1080, 720)
        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 14)
        sl.setSpacing(2)
        sl.addWidget(SidebarBrand("MIKOSHI"))
        sl.addSpacing(10)
        self.nav = QButtonGroup(self)
        self.stack = QStackedWidget()
        self.pages = {"vms": MachinesPage(self), "new": NewPage(self), "sys": SystemPage(self),
                      "settings": SettingsPage(self)}
        for i, (key, text) in enumerate([("vms", "MAQUINAS"), ("new", "NOVA MAQUINA"), ("sys", "SISTEMA"),
                                         ("settings", "CONFIGURACOES")]):
            b = QPushButton(f"{i + 1:02d}   {text}")
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            spaced(b, 2.5)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav.addButton(b, i)
            sl.addWidget(b)
            self.stack.addWidget(self.pages[key])
        sl.addStretch()
        host = label(f"HOST  {core.host_cpus()} CPU · {core.host_ram_mb() // 1024} GB", "dim", 1.5, 11, True)
        host.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(host)
        self.link = label("■  KVM", "muted", 1.5, 11, True)
        self.link.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(self.link)
        ver = label(f"MIKOSHI v{VERSION}{'  ·  DEMO' if core.DEMO else ''}", "dim", 2, 11)
        ver.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(ver)
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.toast_lbl = QLabel(self)
        self.toast_lbl.setStyleSheet("background:#000; border:1px solid #e3121f; padding:10px 18px; color:#ececf0;")
        self.toast_lbl.hide()
        self.set_link(core.kvm_ok())
        self.go("vms" if core.list_vms(cfg) else "sys")

    def go(self, key: str):
        self.nav.button(list(self.pages).index(key)).setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        self.pages[key].refresh()

    def set_link(self, ok: bool):
        self.link.setObjectName("muted" if ok else "red")
        self.link.setText("■  KVM · ONLINE" if ok else "■  KVM INDISPONIVEL")
        self.link.style().unpolish(self.link)
        self.link.style().polish(self.link)

    def toast(self, text: str):
        self.toast_lbl.setText(text)
        spaced(self.toast_lbl, 1)
        self.toast_lbl.adjustSize()
        self.toast_lbl.move(self.width() - self.toast_lbl.width() - 24, 20)
        self.toast_lbl.raise_()
        self.toast_lbl.show()
        QTimer.singleShot(3200, self.toast_lbl.hide)

    def confirm(self, title: str, text: str) -> bool:
        mb = QMessageBox(self)
        mb.setWindowTitle(title)
        mb.setText(text)
        mb.setIcon(QMessageBox.Warning)
        yes = mb.addButton("CONFIRMAR", QMessageBox.AcceptRole)
        yes.setProperty("kind", "danger")
        mb.addButton("CANCELAR", QMessageBox.RejectRole)
        mb.exec()
        return mb.clickedButton() is yes

    def alert(self, title: str, text: str):
        mb = QMessageBox(self)
        mb.setWindowTitle(title)
        mb.setText(text)
        mb.addButton("OK", QMessageBox.AcceptRole).setProperty("kind", "primary")
        mb.exec()


def main(argv: list[str] | None = None):
    argv = list(sys.argv if argv is None else argv)
    QApplication.setApplicationName(core.APP_ID)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setDesktopFileName(core.APP_ID)
    app = QApplication(argv)
    load_fonts()
    app.setStyleSheet(stylesheet() + EXTRA_QSS)
    app.setWindowIcon(QIcon(str(core.ASSETS / "arasaka-mikoshi.svg")))
    win = MainWindow(Config())
    win.show()
    shot = next((a.split("=", 1)[1] for a in argv if a.startswith("--screenshot=")), None)
    if shot:
        path, _, page = shot.partition(",")
        if page:
            QTimer.singleShot(200, lambda: win.go(page))
        QTimer.singleShot(2600, lambda: (win.grab().save(path), app.quit()))
    return app.exec()
