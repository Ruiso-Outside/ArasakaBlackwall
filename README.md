# ARASAKA MIKOSHI

Gerenciador de **máquinas virtuais** para Linux com o visual da Arasaka. Roda **Windows 10, Windows 11
e distribuições Linux** dentro de janelas no seu Zorin OS.

O Mikoshi não é um hipervisor novo. Ele usa o **QEMU + KVM**, o mesmo motor do GNOME Boxes e do
virt-manager: a VM roda direto no processador, com desempenho perto do nativo.

| Peça | Função |
|---|---|
| **QEMU + KVM** | Executa a máquina virtual |
| **OVMF** | Firmware UEFI, com Secure Boot |
| **swtpm** | TPM 2.0 virtual, exigido pelo Windows 11 |
| **SPICE / virt-viewer** (opcional) | Copiar e colar entre o PC e a VM, pendrive USB na VM, tela que se ajusta ao tamanho da janela |
| **Samba** (opcional) | Pasta do Linux visível dentro da VM |

## Abas do app

| Aba | O que tem |
|---|---|
| **01 Máquinas** | Monitor com a tela ao vivo da VM, uso de CPU e memória, tempo ligada. Botões para iniciar, desligar, pausar, reiniciar e forçar o desligamento. Trocar ou ejetar a ISO com a VM ligada. Snapshots. Editar, ver o comando QEMU, ver o log e excluir |
| **02 Nova máquina** | Perfis prontos (Windows 11, Windows 10, Linux, Outro), ISO, CPU, memória, disco, UEFI, Secure Boot, TPM, aceleração 3D, tipo de tela, pasta compartilhada e portas |
| **03 Sistema** | Verifica VT-x/AMD-V, KVM, QEMU, OVMF, swtpm, SPICE e Samba. Instala o que faltar e tem links para baixar ISOs |
| **04 Configurações** | Pasta das VMs, tela padrão, miniatura ao vivo |

### Perfis

| Perfil | Hardware virtual |
|---|---|
| **Windows 11** | 4 CPUs, 8 GB, 80 GB, UEFI + Secure Boot + TPM 2.0, disco **NVMe** e rede **Intel e1000e**. O instalador do Windows reconhece tudo sem drivers extras |
| **Windows 10** | Igual ao Windows 11, sem TPM |
| **Linux** | 4 CPUs, 4 GB, 40 GB, UEFI, dispositivos **VirtIO** (os mais rápidos). Aceleração 3D (virgl) opcional |
| **Outro** | BIOS legado e hardware genérico, para sistemas antigos |

Ao escolher a ISO, o perfil é detectado pelo nome do arquivo (por exemplo `Win11_...iso`,
`ubuntu-...iso` ou `Zorin-OS-...iso`).

## Instalar

```bash
tar xzf ArasakaMikoshi.tar.gz && cd ArasakaMikoshi
```

```bash
./install.sh
```

Rode **sem sudo**. Depois, **encerre a sessão e entre de novo**, para seu usuário ganhar a permissão
do KVM.

| Opção | Efeito |
|---|---|
| `--sem-spice` | Não instala o virt-viewer |
| `--com-samba` | Instala o Samba, para pastas compartilhadas |

Se a aba Sistema disser que a virtualização está desligada, entre na BIOS/UEFI do PC e ative
**SVM Mode** (AMD) ou **Intel Virtualization Technology**.

## Criar uma VM

1. Vá em **02 Nova máquina** e escolha a ISO. Use **BAIXAR ISO** se ainda não tiver o arquivo.
2. Confira CPU, memória e disco. O disco é um arquivo qcow2 que só ocupa o espaço realmente usado.
3. Clique em **CRIAR E INICIAR**. A janela da VM abre e o instalador do sistema começa.
4. Depois de instalar, clique em **EJETAR** na aba Máquinas, para a VM passar a iniciar pelo disco.
   No Windows, se aparecer "Press any key to boot from CD", aperte uma tecla só na primeira vez.

### Dicas

- **Tela GTK × SPICE:** a GTK é a janela do próprio QEMU, a mais simples. A SPICE abre o
  virt-viewer, que tem copiar e colar, USB e ajuste automático de resolução. No Windows, instale o
  [spice-guest-tools](https://www.spice-space.org/download.html) dentro da VM. Em Linux, o
  `spice-vdagent` geralmente já vem instalado.
- Fechar a janela GTK desliga a VM na hora. Prefira o botão **DESLIGAR**.
- **Snapshots** salvam o estado do disco e só funcionam com a VM desligada. Faça um logo depois de
  instalar o sistema, para poder voltar a uma instalação limpa.
- **Portas:** `2222:22` permite `ssh -p 2222 usuario@localhost` e `3389` permite acessar a VM por
  Área de Trabalho Remota.
- **Pasta compartilhada:** dentro da VM, acesse `\\10.0.2.4\qemu` (Windows) ou
  `smb://10.0.2.4/qemu` (Linux). Precisa do Samba no PC.
- **Disco existente:** a opção "Usar um disco virtual existente" aceita discos do VirtualBox (.vdi),
  do VMware (.vmdk) e do Hyper-V (.vhdx).
- As VMs continuam ligadas mesmo se você fechar o Mikoshi. Reabra o app para controlá-las.

## Linha de comando

```bash
arasaka-mikoshi                # interface
arasaka-mikoshi --start SLUG   # liga uma VM direto (SLUG = nome da pasta da VM)
```

Cada VM fica em `~/.local/share/arasaka-mikoshi/machines/<nome>/`, com estes arquivos:

| Arquivo | Conteúdo |
|---|---|
| `vm.json` | Configuração |
| `disk.qcow2` | Disco |
| `OVMF_VARS.fd` | Variáveis UEFI |
| `tpm/` | Estado do TPM |
| `qemu.log` | Log da última execução |

## Desinstalar

```bash
./uninstall.sh
```

O comando acima mantém as VMs. Para apagar também as VMs, use `./uninstall.sh --tudo`.

---

Arasaka e Mikoshi são marcas da CD PROJEKT RED, e a fonte cedge1 usa a licença FontStruct
Non-Commercial. Este é um projeto pessoal de fã, sem fins comerciais.
