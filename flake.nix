{
  description = "Calibre-Web Automated — automated eBook management built on Calibre-Web";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      overlay = final: _prev: {
        calibre-web-automated = final.callPackage ./nix/package.nix { };
      };
    in

    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ overlay ];
        };
      in
      {
        # ── Packages ────────────────────────────────────────────────────────
        packages = {
          default = pkgs.calibre-web-automated;
          calibre-web-automated = pkgs.calibre-web-automated;
        };

        # ── App shortcut ────────────────────────────────────────────────────
        # Wrapper that mirrors the NixOS module's preStart so `nix run .#`
        # works out of the box without any manual library initialisation.
        apps.default =
          let
            script = pkgs.writeShellScript "cps-run" ''
              : "''${CWA_LIBRARY_DIR:=$HOME/calibre-library}"
              export CWA_LIBRARY_DIR

              if [ ! -f "$CWA_LIBRARY_DIR/metadata.db" ]; then
                echo "Initialising empty Calibre library at $CWA_LIBRARY_DIR ..." >&2
                mkdir -p "$CWA_LIBRARY_DIR"
                ${pkgs.calibre}/bin/calibredb \
                  --with-library "$CWA_LIBRARY_DIR" list 2>/dev/null || true
              fi

              exec ${pkgs.calibre-web-automated}/bin/cps "$@"
            '';
          in
          {
            type = "app";
            program = "${script}";
          };

        # ── Development shell ────────────────────────────────────────────────
        devShells.default = import ./shell.nix { inherit pkgs; };

        # ── Formatter ───────────────────────────────────────────────────────
        formatter = pkgs.nixfmt-rfc-style;
      }
    ) // {
      # ── Overlay (for use in downstream flakes) ───────────────────────────
      overlays.default = overlay;

      # ── NixOS module ────────────────────────────────────────────────────
      nixosModules = {
        default = import ./nix/module.nix;
        calibre-web-automated = import ./nix/module.nix;
      };
    };
}
