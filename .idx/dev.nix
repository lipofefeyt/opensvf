{ pkgs, ... }: {
  channel = "stable-24.05";

  packages = [
    pkgs.act
    pkgs.xdg-utils
    pkgs.docker
    pkgs.gh           # Provides Github CLI
    pkgs.cmake
    pkgs.gnumake
    pkgs.gcc          # Provides GCC
    pkgs.python311    
    pkgs.python311Packages.pyyaml
    pkgs.git          # Provides Git
    pkgs.curl         # Provides curl
    pkgs.file         # Provides fileutils
    pkgs.binutils     # Provides strings, objdump, nm
    pkgs.which
    pkgs.jdk21        # Provides JDK for YAMCS

    # aarch64 cross-compiler (lighter — just the compiler, no full sysroot)
    pkgs.gcc-arm-embedded

    # QEMU user-mode only (much lighter than full system QEMU)
    pkgs.qemu
  ];

  idx = {
    extensions = [
      "ms-vscode.cpptools"
    ];

    workspace = {
      onStart = {
        setup = "source scripts/setup-workspace.sh";
      };
    };
  };
}
