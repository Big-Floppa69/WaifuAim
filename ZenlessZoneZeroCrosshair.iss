; Zenless Zone Zero Crosshair Installer Script
; Created for Inno Setup

#define MyAppName "Zenless Zone Zero Crosshair"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "FDDC Team (Open Source)"
#define MyAppURL "https://github.com/Big-Floppa69/ZenlessZoneZeroCrosshair.git"
#define MyAppExeName "main.py"

[Setup]
; Basic setup information
AppId={{B8C9F3A2-4D5E-4F7A-8B9C-1D2E3F4A5B6C7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE.txt
InfoBeforeFile=README.md
OutputDir=Output
OutputBaseFilename=ZenlessZoneZeroCrosshair_Setup_v{#MyAppVersion}
SetupIconFile=astra_yao_tray.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1
Name: "startup"; Description: "Run Zenless Zone Zero Crosshair on system startup"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "pythoncheck"; Description: "Check for Python installation and dependencies"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main application files
Source: "main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "control_panel.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "tray_icon.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "hotkey_manager.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "hotkeys.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "image_editor.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "image_manager.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "utils.py"; DestDir: "{app}"; Flags: ignoreversion

; Configuration files
Source: "hotkey_config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

; Icons and images
Source: "astra_yao_tray.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "astra_yao_tray.png"; DestDir: "{app}"; Flags: ignoreversion

; Display images directory
Source: "display_images\*"; DestDir: "{app}\display_images"; Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation
Source: "readme.media\*"; DestDir: "{app}\readme.media"; Flags: ignoreversion recursesubdirs createallsubdirs

; Installer helper scripts
Source: "install_dependencies.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "run_app.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "python_check.py"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\astra_yao_tray.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\astra_yao_tray.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\astra_yao_tray.ico"; Tasks: quicklaunchicon


[Registry]
; Add registry entries for the application
Root: HKCU; Subkey: "Software\Zenless Zone Zero Crosshair"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"
Root: HKCU; Subkey: "Software\Zenless Zone Zero Crosshair"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ZenlessZoneZeroCrosshair"; ValueData: "cmd /c ""cd /d ""{app}"" && python main.py"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python --version"""; Flags: runascurrentuser; StatusMsg: "Checking Python installation..."; Tasks: pythoncheck
Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python -m pip install --upgrade pip"""; Flags: runascurrentuser; StatusMsg: "Upgrading pip..."; Tasks: pythoncheck
Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python -m pip install -r requirements.txt"""; Flags: runascurrentuser; StatusMsg: "Installing Python dependencies..."; Tasks: pythoncheck

Filename: "{app}\install_dependencies.bat"; Flags: runascurrentuser; StatusMsg: "Installing application dependencies..."
Filename: "{cmd}"; Parameters: "/c ""cd /d ""{app}"" && python main.py"""; Flags: runascurrentuser; StatusMsg: "Launching {#MyAppName}..."; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c ""taskkill /f /im python.exe 2>nul"""; Flags: runascurrentuser
Filename: "{cmd}"; Parameters: "/c ""reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""ZenlessZoneZeroCrosshair"" /f 2>nul"""; Flags: runascurrentuser

[UninstallDelete]
Type: filesandordirs; Name: "{app}\display_images"
Type: filesandordirs; Name: "{app}\readme.media"

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
  iResultCode: Integer;
  sUnInstallString: String;
begin
  Result := True;
  
  // Python installation check will be handled in the [Run] section
  
  // Check if this is an upgrade
  if RegQueryStringValue(HKCU, 'Software\Zenless Zone Zero Crosshair', 'InstallPath', sUnInstallString) then
  begin
    sUnInstallString := RemoveBackslashUnlessRoot(sUnInstallString);
    if sUnInstallString = ExpandConstant('{app}') then
    begin
      if IsUpgrade() then
      begin
        Result := MsgBox(ExpandConstant('This will upgrade the existing installation. Do you want to continue?'), mbConfirmation, MB_YESNO) = IDYES;
      end
      else
      begin
        Result := MsgBox(ExpandConstant('An existing installation was detected. This will overwrite the existing installation. Do you want to continue?'), mbConfirmation, MB_YESNO) = IDYES;
      end;
    end
    else
    begin
      Result := MsgBox(ExpandConstant('An existing installation was detected in a different directory. This will install to {app}. Continue?'), mbConfirmation, MB_YESNO) = IDYES;
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