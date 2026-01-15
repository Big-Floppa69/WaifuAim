; WaifuAim Installer Script
; Created for Inno Setup

#define MyAppName "WaifuAim"
#define MyAppVersion "1.0"
#define MyAppVersionInfo "1.0.0.0"
#define MyAppPublisher "FDC Team (Open Source)"
#define MyAppURL "https://github.com/Big-Floppa69/WaifuAim"
#define MyAppExeName "main.py"

; Prefer the latest PyInstaller output from WaifuAim.spec.
; Fallback kept for older builds that produced a differently named exe.
#if FileExists("dist\\WaifuAim.exe")
  #define MyBuiltExe "dist\\WaifuAim.exe"
#else
  #define MyBuiltExe "dist\\Zenless Zone Zero Crosshair.exe"
#endif

[Setup]
; Basic setup information
AppId={{B8C9F3A2-4D5E-4F7A-8B9C-1D2E3F4A5B6C7}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\WaifuAim
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE.txt
InfoBeforeFile=INSTALLER_INFO.txt
OutputDir=Output
OutputBaseFilename=WaifuAim_Setup_v{#MyAppVersion}
SetupIconFile=astra_yao_tray.ico
VersionInfoVersion={#MyAppVersionInfo}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1
Name: "startup"; Description: "Run WaifuAim on system startup"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Compiled application (PyInstaller)
; We install it as WaifuAim.exe so the installed folder has the expected name.
Source: "{#MyBuiltExe}"; DestDir: "{app}"; DestName: "WaifuAim.exe"; Flags: ignoreversion

; Optional dependency installer (uses system Python)
Source: "install_dependencies.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion

; Runtime configuration files (user-editable defaults)
Source: "app_settings.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "hotkey_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "standard_crosshair_settings.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "art_transforms.json"; DestDir: "{app}"; Flags: ignoreversion

; Icons and images
Source: "astra_yao_tray.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "astra_yao_tray.png"; DestDir: "{app}"; Flags: ignoreversion

; Display images directory
Source: "display_images\*"; DestDir: "{app}\display_images"; Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation


; Installer helper scripts
; (Not installed) Python helper scripts are not needed for the compiled build.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\WaifuAim.exe"; WorkingDir: "{app}"; IconFilename: "{app}\astra_yao_tray.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\WaifuAim.exe"; WorkingDir: "{app}"; IconFilename: "{app}\astra_yao_tray.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\WaifuAim.exe"; WorkingDir: "{app}"; IconFilename: "{app}\astra_yao_tray.ico"; Tasks: quicklaunchicon


[Registry]
; Add registry entries for the application
Root: HKCU; Subkey: "Software\WaifuAim"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"
Root: HKCU; Subkey: "Software\WaifuAim"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WaifuAim"; ValueData: """{app}\WaifuAim.exe"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\install_dependencies.bat"; Flags: runascurrentuser postinstall waituntilterminated skipifsilent; StatusMsg: "Installing Python dependencies..."; Description: "Install Python dependencies"
Filename: "{app}\WaifuAim.exe"; Flags: runascurrentuser postinstall skipifsilent; StatusMsg: "Launching {#MyAppName}..."; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c ""taskkill /f /im WaifuAim.exe 2>nul"""; Flags: runascurrentuser
Filename: "{cmd}"; Parameters: "/c ""reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""WaifuAim"" /f 2>nul"""; Flags: runascurrentuser

[UninstallDelete]
Type: filesandordirs; Name: "{app}\display_images"

[Code]
function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString);
  result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  result := (GetUninstallString() <> '');
end;

function InitializeSetup(): Boolean;
var
  sExistingInstallPath: String;
  sDefaultInstallPath: String;
begin
  Result := True;
  
  // Python installation check will be handled in the [Run] section
  
    // Check if this is an upgrade
    if RegQueryStringValue(HKCU, 'Software\WaifuAim', 'InstallPath', sExistingInstallPath) or
      RegQueryStringValue(HKCU, 'Software\Zenless Zone Zero Crosshair', 'InstallPath', sExistingInstallPath) then
  begin
    sExistingInstallPath := RemoveBackslashUnlessRoot(sExistingInstallPath);
    // {app} isn't initialized yet during InitializeSetup, so compare against the
    // default install directory instead.
    sDefaultInstallPath := RemoveBackslashUnlessRoot(ExpandConstant('{autopf}\\WaifuAim'));

    if sExistingInstallPath = sDefaultInstallPath then
    begin
      if IsUpgrade() then
      begin
        Result := MsgBox('This will upgrade the existing installation. Do you want to continue?', mbConfirmation, MB_YESNO) = IDYES;
      end
      else
      begin
        Result := MsgBox('An existing installation was detected. This will overwrite the existing installation. Do you want to continue?', mbConfirmation, MB_YESNO) = IDYES;
      end;
    end
    else
    begin
      Result := MsgBox(
        Format('An existing installation was detected in a different directory (%s). This will install to %s. Continue?', [sExistingInstallPath, sDefaultInstallPath]),
        mbConfirmation,
        MB_YESNO
      ) = IDYES;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Post-installation tasks
  end;
end;

procedure CurInstallDirChanged(Param: String);
begin
  // Installation directory changed
end;