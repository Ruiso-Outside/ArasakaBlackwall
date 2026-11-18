"""
ARASAKA MIKOSHI // ponto de entrada.

  arasaka-mikoshi                 abre a interface
  arasaka-mikoshi --start SLUG    liga uma VM direto (atalhos)
"""
import sys

from . import core


def main() -> int:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--start":
        cfg = core.Config()
        vm = core.get_vm(cfg, args[1])
        if not vm:
            print(f"VM '{args[1]}' nao encontrada", file=sys.stderr)
            return 1
        err = core.start_vm(cfg, vm)
        if err:
            print(err, file=sys.stderr)
            return 1
        return 0
    if args[:1] in (["--version"], ["-v"]):
        print(f"{core.APP_NAME} {core.VERSION}")
        return 0
    from .app import main as gui
    return gui(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
