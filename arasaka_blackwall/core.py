"""
ARASAKA BLACKWALL // nucleo.

Maquinas virtuais com QEMU + KVM (o mesmo motor usado pelo GNOME Boxes e
pelo virt-manager), sem daemon: cada VM e uma pasta com vm.json, disco
qcow2, variaveis UEFI e estado do TPM. A VM roda como processo proprio
(continua rodando se o app fechar) e e controlada pelo socket QMP.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

APP_ID = "arasaka-blackwall"
APP_NAME = "ARASAKA BLACKWALL"
VERSION = "1.1.0"

DEMO = os.environ.get("ARASAKA_BLACKWALL_DEMO") == "1"

_home = os.environ.get("ARASAKA_BLACKWALL_HOME")
HOME = Path(_home) if _home else Path.home()


def _config_home() -> Path:
    """Configuracoes: %APPDATA% no Windows, ~/.config (XDG) no Linux. Com a pasta pessoal trocada (testes), fica nela."""
    if sys.platform == "win32" and HOME == Path.home():
        return Path(os.environ.get("APPDATA") or HOME)
    return Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))


def _data_home() -> Path:
    """Dados: %LOCALAPPDATA% no Windows, ~/.local/share (XDG) no Linux."""
    if sys.platform == "win32" and HOME == Path.home():
        return Path(os.environ.get("LOCALAPPDATA") or HOME)
    return Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))


if _home:
    DATA = HOME / ".local/share" / APP_ID
    CONFIG_DIR = HOME / ".config" / APP_ID
else:
    DATA = _data_home() / APP_ID
    CONFIG_DIR = _config_home() / APP_ID
ASSETS = Path(__file__).resolve().parent / "assets"


def _migrate_old_name():
    """O app se chamava Arasaka Mikoshi: move as VMs e a configuracao da pasta antiga, uma vez."""
    for new in (DATA, CONFIG_DIR):
        old = new.with_name("arasaka-mikoshi")
        if old.is_dir() and not new.exists():
            try:
                old.rename(new)
            except OSError:
                pass
    cfg = CONFIG_DIR / "config.json"
    try:
        text = cfg.read_text(encoding="utf-8")
        if "/arasaka-mikoshi/" in text:
            cfg.write_text(text.replace("/arasaka-mikoshi/", "/arasaka-blackwall/"), encoding="utf-8")
    except OSError:
        pass


if not DEMO:
    _migrate_old_name()


# ================================================================ Windows (QEMU para Windows + WHPX)
WIN = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def qemu_dirs() -> list[Path]:
    """Onde o QEMU para Windows costuma ficar (instalador oficial e winget)."""
    if not WIN:
        return []
    out = []
    for env in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            out += [Path(base) / "qemu", Path(base) / "Programs" / "qemu"]
    return [d for d in dict.fromkeys(out) if d.is_dir()]


def _resolve(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for d in qemu_dirs():
        exe = d / (Path(name).name + ("" if name.lower().endswith(".exe") else ".exe"))
        if exe.is_file():
            return str(exe)
    return name


def qemu_exe(cfg) -> str:
    return _resolve(cfg.data.get("qemu") or DEFAULTS["qemu"])


def qemu_img_exe(cfg) -> str:
    return _resolve(cfg.data.get("qemu_img") or DEFAULTS["qemu_img"])


def whpx_ok() -> bool:
    """Plataforma do Hipervisor do Windows ligada (o WinHvPlatform.dll so existe com o recurso ativo)."""
    return WIN and (Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "WinHvPlatform.dll").is_file()


def _win_image(pid: int) -> str:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
    finally:
        k32.CloseHandle(h)


def _win_proc_stats(pid: int):
    """(tempo de CPU em s, memoria em MB, segundos desde o inicio) de um processo do Windows."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)  # + PROCESS_VM_READ
    if not h:
        return None

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                   [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                   "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                                   "PagefileUsage", "PeakPagefileUsage")]
    try:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        ft = lambda f: (f.dwHighDateTime << 32 | f.dwLowDateTime)  # noqa: E731
        cpu = (ft(k) + ft(u)) / 1e7
        start = ft(c) / 1e7 - 11644473600                  # FILETIME (1601) -> epoch
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        ctypes.WinDLL("psapi").GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        return cpu, pmc.WorkingSetSize // (1024 * 1024), time.time() - start
    finally:
        k32.CloseHandle(h)


def _free_port() -> int:
    with socket.socket() as t:
        t.bind(("127.0.0.1", 0))
        return t.getsockname()[1]


def win_ovmf(secure: bool) -> tuple[str, str] | None:
    """O firmware UEFI (edk2) que vem dentro do QEMU para Windows."""
    for d in qemu_dirs():
        share = d / "share"
        code = share / ("edk2-x86_64-secure-code.fd" if secure else "edk2-x86_64-code.fd")
        var = share / "edk2-i386-vars.fd"
        if code.is_file() and var.is_file():
            return str(code), str(var)
    return None


# ================================================================ config
DEFAULTS = {
    "vm_dir": str(DATA / "machines"),
    "qemu": "qemu-system-x86_64",
    "qemu_img": "qemu-img",
    "display": "gtk",          # gtk | spice
    "preview": True,           # miniatura ao vivo da tela
}


class Config:
    def __init__(self):
        self.path = CONFIG_DIR / "config.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data.get(k, DEFAULTS.get(k))

    def __setitem__(self, k, v):
        self.data[k] = v
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def vm_dir(self) -> Path:
        return Path(self["vm_dir"]).expanduser()


# ================================================================ perfis de sistema
@dataclass
class Profile:
    key: str
    title: str
    family: str          # windows | linux | other
    cpus: int
    ram: int             # MB
    disk: int            # GB
    uefi: bool
    tpm: bool
    secureboot: bool
    note: str


PROFILES = {
    "win11": Profile("win11", "WINDOWS 11", "windows", 4, 8192, 80, True, True, True,
                     "TPM 2.0 + Secure Boot ativados. Disco NVMe e rede Intel funcionam sem drivers extras."),
    "win10": Profile("win10", "WINDOWS 10", "windows", 4, 6144, 64, True, False, False,
                     "UEFI, disco NVMe e rede Intel: o instalador reconhece tudo sozinho."),
    "linux": Profile("linux", "LINUX", "linux", 4, 4096, 40, True, False, False,
                     "Ubuntu, Zorin, Fedora, Mint, Debian, Arch... Dispositivos VirtIO (mais rapidos)."),
    "other": Profile("other", "OUTRO", "other", 2, 2048, 32, False, False, False,
                     "BIOS legado e hardware generico: para sistemas antigos ou incomuns."),
}

ISO_LINKS = [
    ("Windows 11", "https://www.microsoft.com/software-download/windows11"),
    ("Windows 10", "https://www.microsoft.com/software-download/windows10ISO"),
    ("Zorin OS", "https://zorin.com/os/download/"),
    ("Ubuntu", "https://ubuntu.com/download/desktop"),
    ("Linux Mint", "https://linuxmint.com/download.php"),
    ("Fedora", "https://fedoraproject.org/workstation/download"),
    ("Drivers VirtIO (Windows)", "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/"),
]


# ================================================================ maquina virtual
def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or f"vm-{int(time.time())}"


class VM:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.meta = {
            "name": self.path.name, "profile": "linux", "cpus": 2, "ram": 4096, "disk": "disk.qcow2",
            "uefi": True, "tpm": False, "secureboot": False, "iso": "", "iso2": "", "accel3d": False,
            "display": "", "share": "", "ports": "", "created": time.strftime("%Y-%m-%d %H:%M"),
            "last_run": "",
        }
        try:
            self.meta.update(json.loads((self.path / "vm.json").read_text(encoding="utf-8")))
        except Exception:
            pass

    # -------------------------------------------------- dados
    @property
    def slug(self):
        return self.path.name

    @property
    def name(self):
        return self.meta.get("name") or self.slug

    @property
    def profile(self) -> Profile:
        return PROFILES.get(self.meta.get("profile"), PROFILES["other"])

    @property
    def family(self):
        return self.profile.family

    @property
    def disk(self) -> Path:
        d = Path(self.meta.get("disk") or "disk.qcow2")
        return d if d.is_absolute() else self.path / d

    qmp_path = property(lambda self: self.path / ("qmp.port" if WIN else "qmp.sock"))   # Windows: QMP por TCP local
    pid_path = property(lambda self: self.path / "qemu.pid")
    log_path = property(lambda self: self.path / "qemu.log")
    vars_path = property(lambda self: self.path / "OVMF_VARS.fd")
    tpm_dir = property(lambda self: self.path / "tpm")
    tpm_sock = property(lambda self: self.path / "tpm.sock")
    shot_path = property(lambda self: self.path / "screen.ppm")

    def save(self):
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "vm.json").write_text(json.dumps(self.meta, indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> str:
        m = self.meta
        fw = "UEFI" if m["uefi"] else "BIOS"
        extra = " + TPM" if m["tpm"] else ""
        return f"{m['cpus']} CPU  ·  {m['ram'] // 1024 if m['ram'] >= 1024 else m['ram']}" \
               f"{' GB' if m['ram'] >= 1024 else ' MB'} RAM  ·  {fw}{extra}"

    # -------------------------------------------------- estado
    def pid(self) -> int | None:
        if DEMO:
            return _DEMO_STATE.get(self.slug, {}).get("pid")
        try:
            pid = int(self.pid_path.read_text().strip())
        except (OSError, ValueError):
            return None
        if WIN:
            return pid if "qemu" in _win_image(pid).lower() else None
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return None
        return pid if b"qemu" in cmd else None

    def running(self) -> bool:
        return self.pid() is not None

    def state(self) -> str:
        """stopped | running | paused"""
        if DEMO:
            return _DEMO_STATE.get(self.slug, {}).get("state", "stopped")
        if not self.running():
            return "stopped"
        r = qmp(self, "query-status")
        if r and r.get("status") == "paused":
            return "paused"
        return "running"


def list_vms(cfg: Config) -> list[VM]:
    d = cfg.vm_dir
    d.mkdir(parents=True, exist_ok=True)
    vms = [VM(p) for p in d.iterdir() if (p / "vm.json").exists()]
    return sorted(vms, key=lambda v: v.name.lower())


def get_vm(cfg: Config, slug: str) -> VM | None:
    p = cfg.vm_dir / slug
    return VM(p) if (p / "vm.json").exists() else None


# ================================================================ firmware e ferramentas
OVMF_CANDIDATES = {
    # (code, vars) com e sem secure boot
    "secure": [
        ("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd", "/usr/share/OVMF/OVMF_VARS_4M.ms.fd"),
        ("/usr/share/OVMF/OVMF_CODE.secboot.fd", "/usr/share/OVMF/OVMF_VARS.ms.fd"),
        ("/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd", "/usr/share/edk2/ovmf/OVMF_VARS.secboot.fd"),
        ("/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd", "/usr/share/edk2/x64/OVMF_VARS.4m.fd"),
    ],
    "plain": [
        ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
        ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
        ("/usr/share/edk2/ovmf/OVMF_CODE.fd", "/usr/share/edk2/ovmf/OVMF_VARS.fd"),
        ("/usr/share/edk2/x64/OVMF_CODE.4m.fd", "/usr/share/edk2/x64/OVMF_VARS.4m.fd"),
    ],
}


def find_ovmf(secure: bool) -> tuple[str, str] | None:
    if WIN and not DEMO:
        return win_ovmf(secure)
    if DEMO:
        return ("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd" if secure else "/usr/share/OVMF/OVMF_CODE_4M.fd",
                "/usr/share/OVMF/OVMF_VARS_4M.ms.fd" if secure else "/usr/share/OVMF/OVMF_VARS_4M.fd")
    for code, var in OVMF_CANDIDATES["secure" if secure else "plain"]:
        if Path(code).exists() and Path(var).exists():
            return code, var
    return None


def kvm_ok() -> bool:
    """Aceleracao por hardware: KVM no Linux, WHPX (Plataforma do Hipervisor) no Windows."""
    if WIN and not DEMO:
        return whpx_ok()
    return DEMO or os.access("/dev/kvm", os.R_OK | os.W_OK)


def host_cpus() -> int:
    return os.cpu_count() or 4


def host_ram_mb() -> int:
    if DEMO:
        return 32768
    if WIN:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                       [(n, ctypes.c_ulonglong) for n in ("tp", "ap", "tf", "af", "tv", "av", "ae")]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.tp // (1024 * 1024)
        return 8192
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 8192


def free_disk_gb(path: Path) -> int:
    try:
        p = Path(path)
        while not p.exists():
            p = p.parent
        return shutil.disk_usage(p).free // (1024 ** 3)
    except OSError:
        return 0


# ================================================================ criacao
def create_vm(cfg: Config, name: str, profile: str, cpus: int, ram: int, disk_gb: int, iso: str,
              uefi: bool, tpm: bool, secureboot: bool, accel3d: bool = False, existing_disk: str = "",
              share: str = "", ports: str = "") -> VM:
    slug = slugify(name)
    base, i = slug, 2
    while (cfg.vm_dir / slug).exists():
        slug = f"{base}-{i}"
        i += 1
    vm = VM(cfg.vm_dir / slug)
    vm.meta.update({"name": name.strip() or slug, "profile": profile, "cpus": cpus, "ram": ram, "iso": iso,
                    "uefi": uefi, "tpm": tpm, "secureboot": secureboot and uefi, "accel3d": accel3d,
                    "share": share, "ports": ports})
    vm.path.mkdir(parents=True, exist_ok=True)
    if existing_disk:
        vm.meta["disk"] = existing_disk
    if uefi:
        fw = find_ovmf(secureboot)
        if fw is None:
            raise RuntimeError("Firmware UEFI (OVMF) nao encontrado. Instale o pacote 'ovmf' na aba SISTEMA.")
        if not DEMO:
            shutil.copyfile(fw[1], vm.vars_path)
    if tpm:
        vm.tpm_dir.mkdir(exist_ok=True)
    vm.save()
    if not existing_disk:
        if DEMO:
            vm.disk.write_bytes(b"")
        else:
            r = subprocess.run([qemu_img_exe(cfg), "create", "-q", "-f", "qcow2", "-o", "lazy_refcounts=on",
                                str(vm.disk), f"{disk_gb}G"], capture_output=True, text=True)
            if r.returncode != 0:
                shutil.rmtree(vm.path, ignore_errors=True)
                raise RuntimeError(r.stderr.strip() or "qemu-img falhou")
    return vm


def disk_info(cfg: Config, path: Path) -> dict:
    if DEMO:
        return {"format": "qcow2", "virtual-size": 80 * 1024 ** 3, "actual-size": 23 * 1024 ** 3}
    try:
        r = subprocess.run([qemu_img_exe(cfg), "info", "--output=json", "-U", str(path)],
                           capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except Exception:
        return {}


def resize_disk(cfg: Config, vm: VM, new_gb: int) -> str:
    if DEMO:
        return ""
    r = subprocess.run([qemu_img_exe(cfg), "resize", str(vm.disk), f"{new_gb}G"], capture_output=True, text=True)
    return r.stderr.strip() if r.returncode else ""


def delete_vm(vm: VM):
    stop_vm(vm, force=True)
    shutil.rmtree(vm.path, ignore_errors=True)
    _DEMO_STATE.pop(vm.slug, None)


# ================================================================ linha de comando do QEMU
def _e(path) -> str:
    """Escapa virgulas em caminhos para as opcoes do QEMU."""
    return str(path).replace(",", ",,")


def build_command(cfg: Config, vm: VM) -> list[str]:
    m = vm.meta
    fam = vm.family
    kvm = kvm_ok()
    secure = bool(m.get("secureboot")) and bool(m.get("uefi"))
    # no Windows a aceleracao vai no -accel (o "-machine accel=" e o -accel nao podem ir juntos)
    machine = "q35" if WIN else ("q35,accel=kvm" if kvm else "q35,accel=tcg")
    if secure:
        machine += ",smm=on"
    safe_name = vm.name.replace(",", " ")
    cmd = [qemu_exe(cfg), "-name", f"{safe_name},process=blackwall-{vm.slug}", "-machine", machine]

    if WIN:
        cpu = "max"     # WHPX nao aceita "-cpu host" nem os enlightenments hv_* do KVM
    elif fam == "windows":
        cpu = "host,hv_relaxed,hv_vapic,hv_spinlocks=0x1fff,hv_time,hv_vpindex,hv_synic,hv_stimer," \
              "hv_frequencies,hv_reset,hv_runtime" if kvm else "max"
    else:
        cpu = "host" if kvm else "max"
    cmd += ["-cpu", cpu, "-smp", str(m["cpus"]), "-m", str(m["ram"])]
    if WIN:
        cmd += ["-accel", "whpx,kernel-irqchip=off" if kvm else "tcg"]

    # firmware
    if m.get("uefi"):
        fw = find_ovmf(secure)
        if fw:
            if secure:
                cmd += ["-global", "driver=cfi.pflash01,property=secure,value=on",
                        "-global", "ICH9-LPC.disable_s3=1"]
            cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={_e(fw[0])}",
                    "-drive", f"if=pflash,format=raw,file={_e(vm.vars_path)}"]

    # disco
    fmt = m.get("disk_format") or ("qcow2" if str(vm.disk).endswith(".qcow2") else "")
    fmt_opt = f",format={fmt}" if fmt else ""
    cmd += ["-drive", f"file={_e(vm.disk)},if=none,id=disk0{fmt_opt},discard=unmap,cache=writeback"]
    if fam == "windows":
        # serial do nome antigo (Mikoshi): trocar faria o Windows da VM ver um disco novo
        cmd += ["-device", "nvme,drive=disk0,serial=MIKOSHI0451,bootindex=1"]
    elif fam == "linux":
        cmd += ["-device", "virtio-blk-pci,drive=disk0,bootindex=1"]
    else:
        cmd += ["-device", "ide-hd,drive=disk0,bus=ide.0,bootindex=1"]

    # CD/DVD (sempre presente para poder trocar a ISO com a VM ligada)
    iso = m.get("iso") or ""
    if iso:
        cmd += ["-drive", f"file={_e(iso)},if=none,id=cd0,media=cdrom,readonly=on"]
    else:
        cmd += ["-drive", "if=none,id=cd0,media=cdrom,readonly=on"]
    cmd += ["-device", f"ide-cd,drive=cd0,id=cdrom0,bus=ide.2,bootindex={0 if iso else 2}"]
    if m.get("iso2"):
        cmd += ["-drive", f"file={_e(m['iso2'])},if=none,id=cd1,media=cdrom,readonly=on",
                "-device", "ide-cd,drive=cd1,id=cdrom1,bus=ide.3"]

    # TPM 2.0 (swtpm iniciado antes, ver start_vm)
    if m.get("tpm"):
        cmd += ["-chardev", f"socket,id=chrtpm,path={_e(vm.tpm_sock)}",
                "-tpmdev", "emulator,id=tpm0,chardev=chrtpm", "-device", "tpm-tis,tpmdev=tpm0"]

    # rede (NAT do QEMU) + redirecionamento de portas + pasta compartilhada (Samba)
    nic_model = {"windows": "e1000e", "linux": "virtio-net-pci"}.get(fam, "e1000")
    nic = f"user,model={nic_model}"
    for fwd in parse_ports(m.get("ports", "")):
        nic += f",hostfwd={fwd}"
    if m.get("share") and Path(m["share"]).is_dir() and shutil.which("smbd"):
        nic += f",smb={_e(m['share'])}"
    cmd += ["-nic", nic]

    # USB, tablet (mouse sem "prender"), audio
    cmd += ["-device", "qemu-xhci,id=xhci", "-device", "usb-tablet"]
    audio = audio_driver(cfg)
    if audio:
        cmd += ["-audiodev", f"{audio},id=snd0", "-device", "intel-hda", "-device", "hda-duplex,audiodev=snd0"]
    if fam == "windows":
        cmd += ["-rtc", "base=localtime,clock=host"]
    if fam == "linux":
        cmd += ["-device", "virtio-balloon-pci", "-device", "virtio-rng-pci"]

    # video e janela
    display = m.get("display") or cfg["display"]
    gl = bool(m.get("accel3d")) and fam == "linux" and not WIN
    if WIN:
        display = "gtk"     # o QEMU para Windows nao tem o SPICE (spice-app); a janela GTK funciona
    if display == "spice":
        if fam == "linux":
            cmd += ["-vga", "none", "-device", "virtio-vga-gl" if gl else "virtio-vga"]
        else:
            cmd += ["-vga", "qxl"]
        cmd += ["-device", "virtio-serial-pci",
                "-chardev", "spicevmc,id=vdagent,name=vdagent",
                "-device", "virtserialport,chardev=vdagent,name=com.redhat.spice.0",
                "-chardev", "spicevmc,name=usbredir,id=usbredir1", "-device", "usb-redir,chardev=usbredir1",
                "-chardev", "spicevmc,name=usbredir,id=usbredir2", "-device", "usb-redir,chardev=usbredir2",
                "-spice", f"unix=on,addr={_e(vm.path / 'spice.sock')},disable-ticketing=on"
                          + (",gl=on" if gl else ""),
                "-display", "spice-app" + (",gl=on" if gl else "")]
    else:
        if fam == "linux":
            cmd += ["-vga", "none", "-device", "virtio-vga-gl" if gl else "virtio-vga"]
        else:
            cmd += ["-vga", "std"]
        cmd += ["-display", "gtk,zoom-to-fit=on" + (",gl=on" if gl else "")]

    if WIN:
        port = _free_port()
        vm.qmp_path.write_text(str(port))
        cmd += ["-qmp", f"tcp:127.0.0.1:{port},server=on,wait=off"]
    else:
        cmd += ["-qmp", f"unix:{_e(vm.qmp_path)},server=on,wait=off"]
    cmd += ["-pidfile", str(vm.pid_path), "-monitor", "none"]
    return cmd


_AUDIO_CACHE: dict = {}


def audio_driver(cfg: Config) -> str:
    """Escolhe o backend de audio que o QEMU instalado suporta."""
    if DEMO:
        return "pa"
    if "drv" not in _AUDIO_CACHE:
        rc, out = _run([qemu_exe(cfg), "-audiodev", "help"])
        names = out.split()
        _AUDIO_CACHE["drv"] = next((d for d in ("pipewire", "pa", "alsa", "dsound") if d in names), "")
    return _AUDIO_CACHE["drv"]


def parse_ports(text: str) -> list[str]:
    """'2222:22, 3389' -> ['tcp::2222-:22', 'tcp::3389-:3389']"""
    out = []
    for part in re.split(r"[,\s]+", text or ""):
        part = part.strip()
        if not part:
            continue
        proto = "tcp"
        if part.startswith("udp:"):
            proto, part = "udp", part[4:]
        a, _, b = part.partition(":")
        if a.isdigit() and (not b or b.isdigit()):
            out.append(f"{proto}::{a}-:{b or a}")
    return out


def command_text(cmd: list[str]) -> str:
    out = []
    for a in cmd:
        out.append(f"'{a}'" if re.search(r"[\s,;&|]", a) and not a.startswith("-") else a)
    return " \\\n  ".join(" ".join(out[i:i + 2]) for i in range(0, len(out), 2))


# ================================================================ execucao
_DEMO_STATE: dict = {}


def start_vm(cfg: Config, vm: VM) -> str:
    """Inicia a VM. Retorna '' ou uma mensagem de erro."""
    if vm.running():
        return ""
    if DEMO:
        _DEMO_STATE[vm.slug] = {"pid": 4000 + len(_DEMO_STATE), "state": "running", "t0": time.time()}
        vm.meta["last_run"] = time.strftime("%Y-%m-%d %H:%M")
        vm.save()
        return ""
    if not shutil.which(qemu_exe(cfg)):
        return f"QEMU nao encontrado ({cfg['qemu']}). Instale pela aba SISTEMA."
    if not vm.disk.exists():
        return f"Disco nao encontrado: {vm.disk}"
    for f in (vm.qmp_path, vm.pid_path, vm.tpm_sock):
        f.unlink(missing_ok=True)
    if vm.meta.get("tpm"):
        if WIN:
            return ("Esta VM usa TPM 2.0, que o QEMU para Windows nao emula (nao ha swtpm). Desligue o TPM nas "
                    "configuracoes da VM; para instalar o Windows 11 sem TPM, use a chave BypassTPMCheck no instalador.")
        if not shutil.which("swtpm"):
            return "Esta VM usa TPM 2.0 mas o 'swtpm' nao esta instalado (aba SISTEMA)."
        vm.tpm_dir.mkdir(exist_ok=True)
        subprocess.Popen(["swtpm", "socket", "--tpm2", "--tpmstate", f"dir={vm.tpm_dir}",
                          "--ctrl", f"type=unixio,path={_e(vm.tpm_sock)}", "--terminate",
                          "--log", f"file={vm.path / 'swtpm.log'}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(40):
            if vm.tpm_sock.exists():
                break
            time.sleep(0.05)
    cmd = build_command(cfg, vm)
    log = open(vm.log_path, "w", encoding="utf-8")
    log.write("# " + " ".join(cmd) + "\n\n")
    log.flush()
    subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True, cwd=str(vm.path), creationflags=NO_WINDOW)
    # espera o QEMU subir (ou falhar)
    for _ in range(60):
        time.sleep(0.1)
        if vm.running():
            vm.meta["last_run"] = time.strftime("%Y-%m-%d %H:%M")
            vm.save()
            return ""
        if _log_has_error(vm):
            break
    return "A VM nao iniciou. Ultimas linhas do log:\n" + tail(vm.log_path, 8)


def _log_has_error(vm: VM) -> bool:
    t = tail(vm.log_path, 5).lower()
    return "error" in t or "could not" in t or "failed" in t


def tail(path: Path, n: int = 20) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def stop_vm(vm: VM, force: bool = False):
    if DEMO:
        if vm.slug in _DEMO_STATE:
            _DEMO_STATE[vm.slug] = {"state": "stopped"}
        return
    if not vm.running():
        return
    if not force:
        qmp(vm, "system_powerdown")
        return
    if qmp(vm, "quit") is None:
        pid = vm.pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def pause_vm(vm: VM, pause: bool):
    if DEMO:
        st = _DEMO_STATE.setdefault(vm.slug, {})
        st["state"] = "paused" if pause else "running"
        return
    qmp(vm, "stop" if pause else "cont")


def reset_vm(vm: VM):
    if not DEMO:
        qmp(vm, "system_reset")


def change_iso(vm: VM, iso: str):
    """Troca/ejeta a ISO (com a VM ligada usa QMP; desligada so salva)."""
    vm.meta["iso"] = iso
    vm.save()
    if DEMO or not vm.running():
        return
    if iso:
        qmp(vm, "blockdev-change-medium", {"id": "cdrom0", "filename": iso, "format": "raw",
                                            "read-only-mode": "read-only"})
    else:
        qmp(vm, "eject", {"id": "cdrom0", "force": True})


def screendump(vm: VM) -> Path | None:
    if DEMO:
        return None
    if qmp(vm, "screendump", {"filename": str(vm.shot_path)}) is None:
        return None
    return vm.shot_path


def open_viewer(vm: VM) -> str:
    """Reabre a tela de uma VM SPICE (a janela GTK nao pode ser reaberta)."""
    sock = vm.path / "spice.sock"
    if WIN:
        return "No Windows a janela da VM e a do QEMU (GTK): ela fica aberta enquanto a VM estiver ligada."
    if not sock.exists():
        return "A janela desta VM e do tipo GTK: ela fica aberta enquanto a VM estiver ligada."
    if not shutil.which("remote-viewer"):
        return "remote-viewer (virt-viewer) nao instalado."
    subprocess.Popen(["remote-viewer", f"spice+unix://{sock}", "--title", vm.name],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return ""


# ================================================================ QMP
def qmp(vm: VM, command: str, args: dict | None = None, timeout: float = 2.0):
    """Envia um comando QMP. Retorna o 'return' (dict/list) ou None em erro."""
    if DEMO or not vm.qmp_path.exists():
        return None
    if WIN:
        try:
            addr = ("127.0.0.1", int(vm.qmp_path.read_text().strip()))
        except (OSError, ValueError):
            return None
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    else:
        addr = str(vm.qmp_path)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(addr)
        f = s.makefile("rwb")
        f.readline()  # saudacao
        for msg in ({"execute": "qmp_capabilities"}, {"execute": command, **({"arguments": args} if args else {})}):
            f.write((json.dumps(msg) + "\n").encode())
            f.flush()
            while True:
                line = f.readline()
                if not line:
                    return None
                resp = json.loads(line)
                if "event" in resp:
                    continue
                break
            if "error" in resp:
                return None
        return resp.get("return", {})
    except (OSError, ValueError):
        return None
    finally:
        s.close()


# ================================================================ desempenho
class Stats:
    """CPU (%) e memoria do processo QEMU, lidas de /proc."""

    def __init__(self):
        self.prev: dict[int, tuple[float, float]] = {}

    def read(self, vm: VM) -> dict | None:
        pid = vm.pid()
        if not pid:
            return None
        if DEMO:
            import math
            t = time.time()
            st = _DEMO_STATE.get(vm.slug, {})
            return {"cpu": 18 + 14 * math.sin(t / 3) if st.get("state") == "running" else 0.0,
                    "ram_mb": vm.meta["ram"] * 0.62, "uptime": t - st.get("t0", t)}
        if WIN:
            st = _win_proc_stats(pid)
            if not st:
                return None
            cpu_s, rss, uptime = st
            now = time.time()
            cpu = 0.0
            if pid in self.prev:
                t0, c0 = self.prev[pid]
                if now - t0 > 0:
                    cpu = (cpu_s - c0) / (now - t0) * 100 / max(1, vm.meta["cpus"])
            self.prev[pid] = (now, cpu_s)
            return {"cpu": max(0.0, min(100.0, cpu)), "ram_mb": rss, "uptime": uptime}
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            ticks = int(fields[11]) + int(fields[12])
            start = int(fields[19])
            hz = os.sysconf("SC_CLK_TCK")
            up = float(Path("/proc/uptime").read_text().split()[0])
            rss = 0
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            return None
        now = time.time()
        cpu = 0.0
        if pid in self.prev:
            t0, k0 = self.prev[pid]
            dt = now - t0
            if dt > 0:
                cpu = (ticks - k0) / hz / dt * 100 / max(1, vm.meta["cpus"])
        self.prev[pid] = (now, ticks)
        return {"cpu": max(0.0, min(100.0, cpu)), "ram_mb": rss, "uptime": up - start / hz}


# ================================================================ snapshots (VM desligada)
def snapshots(cfg: Config, vm: VM) -> list[dict]:
    if DEMO:
        return _DEMO_STATE.setdefault(vm.slug + ":snaps", [
            {"name": "instalacao-limpa", "date": "2026-11-18 05:40", "size": "0 B"}])
    if not str(vm.disk).endswith(".qcow2") or not vm.disk.exists():
        return []
    r = subprocess.run([qemu_img_exe(cfg), "snapshot", "-l", "-U", str(vm.disk)], capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 5:
            # ID TAG VM_SIZE DATE TIME VM_CLOCK [ICOUNT]
            m = re.match(r"\s*\S+\s+(.+?)\s+(\S+\s?\S*)\s+(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
            if m:
                out.append({"name": m.group(1).strip(), "size": m.group(2), "date": m.group(3)[:16]})
    return out


def snapshot_cmd(cfg: Config, vm: VM, action: str, name: str) -> str:
    """action: create | apply | delete. Retorna '' ou erro."""
    if vm.running():
        return "Desligue a VM antes de mexer nos snapshots."
    if DEMO:
        lst = _DEMO_STATE.setdefault(vm.slug + ":snaps", [])
        if action == "create":
            lst.append({"name": name, "date": time.strftime("%Y-%m-%d %H:%M"), "size": "0 B"})
        elif action == "delete":
            lst[:] = [s for s in lst if s["name"] != name]
        return ""
    if not str(vm.disk).endswith(".qcow2"):
        return "Snapshots so funcionam com disco qcow2."
    flag = {"create": "-c", "apply": "-a", "delete": "-d"}[action]
    r = subprocess.run([qemu_img_exe(cfg), "snapshot", flag, name, str(vm.disk)], capture_output=True, text=True)
    return r.stderr.strip() if r.returncode else ""


# ================================================================ sistema
@dataclass
class Check:
    key: str
    title: str
    ok: bool
    detail: str
    action: str | None = None
    optional: bool = False


def _run(argv, timeout=5):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 127, str(e)


def cpu_virt() -> str:
    if WIN:
        import ctypes
        import platform
        on = bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(21)) or whpx_ok()   # PF_VIRT_FIRMWARE_ENABLED
        return ("AMD-V" if "AMD" in platform.processor().upper() else "Intel VT-x") if on else ""
    try:
        flags = Path("/proc/cpuinfo").read_text()
    except OSError:
        return ""
    return "Intel VT-x" if " vmx" in flags else ("AMD-V" if " svm" in flags else "")


def system_checks(cfg: Config) -> list[Check]:
    if DEMO:
        return [
            Check("virt", "VIRTUALIZACAO DA CPU", True, "AMD-V · 16 nucleos · 32 GB RAM"),
            Check("kvm", "KVM", True, "/dev/kvm acessivel (aceleracao por hardware)"),
            Check("qemu", "QEMU", True, "QEMU emulator version 8.2.2"),
            Check("ovmf", "FIRMWARE UEFI + SECURE BOOT", True, "OVMF 4M (Microsoft keys)"),
            Check("swtpm", "TPM 2.0 (WINDOWS 11)", True, "swtpm 0.7.3"),
            Check("spice", "VISUALIZADOR SPICE", True, "remote-viewer 11.0", optional=True),
            Check("smb", "PASTA COMPARTILHADA (SAMBA)", False, "opcional: compartilhar pastas com a VM", "smb",
                  optional=True),
        ]
    if WIN:
        return windows_checks(cfg)
    checks = []
    v = cpu_virt()
    checks.append(Check("virt", "VIRTUALIZACAO DA CPU", bool(v),
                        f"{v} · {host_cpus()} nucleos · {host_ram_mb() // 1024} GB RAM" if v else
                        "VT-x/AMD-V desligado: ative na BIOS/UEFI do PC (SVM ou Intel Virtualization)"))
    if Path("/dev/kvm").exists():
        acc = os.access("/dev/kvm", os.R_OK | os.W_OK)
        checks.append(Check("kvm", "KVM", acc, "/dev/kvm acessivel (aceleracao por hardware)" if acc else
                            "sem permissao: adicione seu usuario ao grupo kvm e entre de novo", None if acc else "kvm"))
    else:
        checks.append(Check("kvm", "KVM", False, "modulo KVM ausente (sem virtualizacao a VM fica muito lenta)",
                            "qemu"))
    q = shutil.which(qemu_exe(cfg))
    qv = _run([qemu_exe(cfg), "--version"])[1].splitlines()[0] if q else ""
    checks.append(Check("qemu", "QEMU", bool(q) and bool(shutil.which(qemu_img_exe(cfg))), qv or "nao instalado",
                        None if q else "qemu"))
    fw = find_ovmf(True) or find_ovmf(False)
    checks.append(Check("ovmf", "FIRMWARE UEFI + SECURE BOOT", bool(find_ovmf(True)),
                        Path(fw[0]).name if fw else "OVMF nao instalado", None if find_ovmf(True) else "qemu"))
    sw = shutil.which("swtpm")
    checks.append(Check("swtpm", "TPM 2.0 (WINDOWS 11)", bool(sw),
                        _run(["swtpm", "--version"])[1].splitlines()[0][:60] if sw else "swtpm nao instalado",
                        None if sw else "qemu"))
    rv = shutil.which("remote-viewer")
    checks.append(Check("spice", "VISUALIZADOR SPICE", bool(rv),
                        "remote-viewer (copiar/colar e USB)" if rv else "opcional: area de transferencia e USB",
                        None if rv else "spice", optional=True))
    sm = shutil.which("smbd") or Path("/usr/sbin/smbd").exists()
    checks.append(Check("smb", "PASTA COMPARTILHADA (SAMBA)", bool(sm),
                        "smbd instalado" if sm else "opcional: compartilhar pastas com a VM",
                        None if sm else "smb", optional=True))
    return checks


def windows_checks(cfg: Config) -> list[Check]:
    v = cpu_virt()
    q = Path(qemu_exe(cfg)).is_file()
    qv = _run([qemu_exe(cfg), "--version"])[1].splitlines()[0] if q else ""
    return [
        Check("virt", "VIRTUALIZACAO DA CPU", bool(v), f"{v} · {host_cpus()} nucleos · {host_ram_mb() // 1024} GB RAM" if v else
              "VT-x/AMD-V desligado: ative na BIOS/UEFI do PC (SVM ou Intel Virtualization)"),
        Check("kvm", "PLATAFORMA DO HIPERVISOR (WHPX)", whpx_ok(),
              "aceleracao por hardware ligada" if whpx_ok() else "desligada: sem ela a VM fica muito lenta (pede reiniciar o PC)",
              None if whpx_ok() else "whpx"),
        Check("qemu", "QEMU", q and Path(qemu_img_exe(cfg)).is_file(), qv or "nao instalado", None if q else "qemu"),
        Check("ovmf", "FIRMWARE UEFI + SECURE BOOT", bool(find_ovmf(True)),
              Path(find_ovmf(True)[0]).name if find_ovmf(True) else "vem junto com o QEMU", None if find_ovmf(True) else "qemu"),
        Check("swtpm", "TPM 2.0 (WINDOWS 11)", False, "o QEMU para Windows nao emula TPM: use o BypassTPMCheck", optional=True),
    ]


def dep_script(key: str) -> list[str] | None:
    """Comando (com pkexec) que instala o que falta."""
    if WIN and not DEMO:
        if key == "qemu":
            return ["winget", "install", "-e", "--id", "SoftwareFreedomConservancy.QEMU", "--accept-package-agreements",
                    "--accept-source-agreements"]
        if key == "whpx":   # recurso do Windows: pede administrador (UAC) e reiniciar o PC
            return ["powershell", "-NoProfile", "-Command",
                    "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-Command',"
                    "'Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All -NoRestart'; "
                    "Write-Output 'Plataforma do Hipervisor ligada: reinicie o PC'"]
        return None
    user = os.environ.get("USER", "")
    if key == "qemu":
        s = ("set -e; apt-get update; export DEBIAN_FRONTEND=noninteractive; apt-get install -y "
             "qemu-system-x86 qemu-utils qemu-system-gui ovmf swtpm swtpm-tools; "
             "apt-get install -y qemu-system-modules-spice qemu-system-modules-opengl 2>/dev/null || true; "
             f"usermod -aG kvm {user} || true")
    elif key == "kvm":
        s = f"usermod -aG kvm {user}"
    elif key == "spice":
        s = "DEBIAN_FRONTEND=noninteractive apt-get install -y virt-viewer"
    elif key == "smb":
        s = "DEBIAN_FRONTEND=noninteractive apt-get install -y samba"
    else:
        return None
    if DEMO:
        return [sys.executable, "-c", "import time;print('instalando...');time.sleep(2);print('ok')"]
    return ["pkexec", "sh", "-c", s]


def fmt_uptime(sec: float) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
