; Nora Studio per-user Windows installer wizard (Inno Setup 6).
; Database/configuration live in %LOCALAPPDATA%\NoraStudio, outside {app}.
#define AppName "Nora Studio"
#define AppVersion "0.3.3"
#define AppExe "NoraStudio.exe"

[Setup]
AppId={{B2F4D622-8AC7-4D97-9B41-651209ABC219}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Nora Studio
DefaultDirName={localappdata}\Programs\Nora Studio
DefaultGroupName=Nora Studio
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=NoraStudio-Setup-{#AppVersion}
SetupIconFile=..\assets\NoraStudio.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableDirPage=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\NoraStudio.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Nora Studio"; Filename: "{app}\NoraStudio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Nora Studio"; Filename: "{app}\NoraStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\NoraStudio.exe"; Description: "{cm:LaunchProgram,Nora Studio}"; Flags: nowait postinstall skipifsilent

; Intentionally omit [UninstallDelete]. Never erase %LOCALAPPDATA%\NoraStudio
; because it stores the owner's SQLite database and authentication settings.
