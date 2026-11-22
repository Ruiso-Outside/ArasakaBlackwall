"""Linha de comando do QEMU (sem rodar o QEMU): aceleracao, firmware, disco, rede, QMP e tela, no Linux e no Windows.
python tests/test_command.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

T = Path(tempfile.mkdtemp())
os.environ["ARASAKA_BLACKWALL_HOME"] = str(T)
os.environ.pop("ARASAKA_BLACKWALL_DEMO", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from arasaka_blackwall import core as C  # noqa: E402

assert not C.DEMO, "o modo demonstracao so liga pela variavel de ambiente"
cfg = C.Config()
vm = C.VM(T / "vms" / "win")
vm.meta.update({"name": "Win 11", "profile": "win11", "cpus": 4, "ram": 8192, "uefi": True, "secureboot": True, "ports": "3389"})
vm.path.mkdir(parents=True)
fw = ("C:/qemu/share/edk2-x86_64-secure-code.fd", "C:/qemu/share/edk2-i386-vars.fd")

# Windows com a Plataforma do Hipervisor: -accel whpx (sem accel= no -machine), CPU max, QMP por TCP, janela GTK
with mock.patch.object(C, "WIN", True), mock.patch.object(C, "whpx_ok", lambda: True), \
        mock.patch.object(C, "find_ovmf", lambda secure: fw), mock.patch.object(C, "audio_driver", lambda cfg: "dsound"):
    vm.meta["display"] = "spice"
    cmd = C.build_command(cfg, vm)
    j = " ".join(cmd)
    assert cmd[cmd.index("-machine") + 1] == "q35,smm=on" and cmd[cmd.index("-accel") + 1] == "whpx,kernel-irqchip=off"
    assert cmd[cmd.index("-cpu") + 1] == "max", "WHPX nao aceita -cpu host"
    q = cmd[cmd.index("-qmp") + 1]
    assert q.startswith("tcp:127.0.0.1:") and vm.qmp_path.name == "qmp.port" and vm.qmp_path.read_text() == q.rsplit(":", 1)[1].split(",")[0]
    assert "spice" not in j and "-display gtk" in j, "SPICE nao existe no QEMU para Windows"
    assert "dsound" in j and "hostfwd=tcp::3389-:3389" in j and "edk2-x86_64-secure-code.fd" in j
    assert "unix:" not in j
with mock.patch.object(C, "WIN", True), mock.patch.object(C, "whpx_ok", lambda: False), \
        mock.patch.object(C, "find_ovmf", lambda secure: fw), mock.patch.object(C, "audio_driver", lambda cfg: ""):
    cmd = C.build_command(cfg, vm)
    assert cmd[cmd.index("-accel") + 1] == "tcg", "sem WHPX: emulacao (lenta, mas abre)"
with mock.patch.object(C, "WIN", True):
    vm.meta["tpm"] = True
    assert "TPM" in C.start_vm(cfg, vm) or "QEMU" in C.start_vm(cfg, vm), "Windows: TPM explicado antes de tentar abrir"
    vm.meta["tpm"] = False

# Linux com KVM: o comando de sempre
with mock.patch.object(C, "WIN", False), mock.patch.object(C, "kvm_ok", lambda: True), \
        mock.patch.object(C, "find_ovmf", lambda secure: ("/usr/share/OVMF/OVMF_CODE_4M.secboot.fd", "/x/VARS.fd")), \
        mock.patch.object(C, "audio_driver", lambda cfg: "pipewire"):
    vm.meta["display"] = "gtk"
    cmd = C.build_command(cfg, vm)
    assert cmd[cmd.index("-machine") + 1] == "q35,accel=kvm,smm=on" and "-accel" not in cmd
    assert cmd[cmd.index("-cpu") + 1].startswith("host,hv_relaxed")
    assert cmd[cmd.index("-qmp") + 1].startswith("unix:")
print("OK: linha de comando do QEMU no Windows (WHPX, TCG, QMP por TCP, sem SPICE, TPM) e no Linux (KVM)")
