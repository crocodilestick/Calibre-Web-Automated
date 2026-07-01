{ config
, lib
, pkgs
, ...
}:

let
  cfg = config.services.calibre-web-automated;
  inherit (lib)
    escapeShellArgs
    mkEnableOption
    mkIf
    mkOption
    mkPackageOption
    types
    ;

  defaultUser = "calibre-web";
  defaultGroup = "calibre-web";
in
{
  options.services.calibre-web-automated = {
    enable = mkEnableOption "Calibre-Web Automated";

    package = mkPackageOption pkgs "calibre-web-automated" { };

    user = mkOption {
      type = types.str;
      default = defaultUser;
      description = "User account under which the service runs.";
    };

    group = mkOption {
      type = types.str;
      default = defaultGroup;
      description = "Group under which the service runs.";
    };

    port = mkOption {
      type = types.port;
      default = 8083;
      description = "TCP port the web interface listens on.";
    };

    configDir = mkOption {
      type = types.path;
      default = "/var/lib/calibre-web-automated";
      description = ''
        Directory that holds <filename>app.db</filename> (settings, users,
        OAuth tokens) and other runtime state.
      '';
    };

    libraryDir = mkOption {
      type = types.path;
      default = "/var/lib/calibre-web-automated/library";
      description = ''
        Calibre library root directory.  Must contain (or will receive)
        a <filename>metadata.db</filename> created by Calibre.
      '';
    };

    ingestDir = mkOption {
      type = types.path;
      default = "/var/lib/calibre-web-automated/ingest";
      description = ''
        Drop-folder watched for new eBooks.  Files placed here are
        automatically imported and optionally converted.
      '';
    };

    openFirewall = mkOption {
      type = types.bool;
      default = false;
      description = "Open <option>port</option> in the firewall.";
    };

    extraArgs = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ "-r" "-l" ];
      description = ''
        Extra flags appended to the <command>cps</command> invocation.
        See <command>cps --help</command> for available options.
      '';
    };

    environment = mkOption {
      type = types.attrsOf types.str;
      default = { };
      example = {
        TRUSTED_PROXY_COUNT = "1";
        CWA_WATCH_MODE = "inotify";
        HARDCOVER_TOKEN = "your-token-here";
      };
      description = "Additional environment variables injected into the service.";
    };
  };

  config = mkIf cfg.enable {
    systemd.services.calibre-web-automated = {
      description = "Calibre-Web Automated";
      documentation = [ "https://github.com/crocodilestick/Calibre-Web-Automated/wiki" ];
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      environment = {
        CWA_PORT_OVERRIDE = toString cfg.port;
        HOME = cfg.configDir;
        CWA_LIBRARY_DIR = cfg.libraryDir;
      } // cfg.environment;

      preStart = ''
        # Create all runtime directories the app and background workers expect.
        mkdir -p \
          ${escapeShellArgs [ cfg.configDir cfg.libraryDir cfg.ingestDir ]} \
          ${lib.escapeShellArg cfg.configDir}/processed_books/failed \
          ${lib.escapeShellArg cfg.configDir}/processed_books/fixed_originals \
          ${lib.escapeShellArg cfg.configDir}/log_archive \
          ${lib.escapeShellArg cfg.configDir}/metadata_change_logs \
          ${lib.escapeShellArg cfg.configDir}/metadata_temp \
          ${lib.escapeShellArg cfg.configDir}/tmp

        # Initialise an empty Calibre library on first run so the app auto-
        # detects it via CWA_LIBRARY_DIR without requiring web-UI setup.
        if [ ! -f ${lib.escapeShellArg cfg.libraryDir}/metadata.db ]; then
          ${pkgs.calibre}/bin/calibredb \
            --with-library ${lib.escapeShellArg cfg.libraryDir} \
            list 2>/dev/null || true
        fi

        # Write dirs.json so background workers (ingest, convert, cover) know
        # where to find the library, ingest folder, and temp dir.
        printf '{"ingest_folder":"%s","library_dir":"%s","tmp_conversion_dir":"%s"}\n' \
          ${lib.escapeShellArg cfg.ingestDir} \
          ${lib.escapeShellArg cfg.libraryDir} \
          ${lib.escapeShellArg cfg.configDir}/tmp \
          > ${lib.escapeShellArg cfg.configDir}/dirs.json
      '';

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.configDir;
        ExecStart = "${cfg.package}/bin/cps -p ${cfg.configDir}/app.db ${escapeShellArgs cfg.extraArgs}";

        Restart = "on-failure";
        RestartSec = "10s";

        # Hardening
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        RestrictNamespaces = true;
        LockPersonality = true;
        # Python itself does not use executable memory; set false only if
        # certain extensions require it.
        MemoryDenyWriteExecute = false;
        RestrictRealtime = true;
        ReadWritePaths = [ cfg.configDir cfg.libraryDir cfg.ingestDir ];
      };
    };

    users.users = mkIf (cfg.user == defaultUser) {
      ${defaultUser} = {
        isSystemUser = true;
        group = cfg.group;
        home = cfg.configDir;
        description = "Calibre-Web Automated service account";
      };
    };

    users.groups = mkIf (cfg.group == defaultGroup) {
      ${defaultGroup} = { };
    };

    networking.firewall.allowedTCPPorts = mkIf cfg.openFirewall [ cfg.port ];
  };
}
