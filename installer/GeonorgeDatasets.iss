; Inno Setup installer for GeonorgeDatasets.exe
; Prereqs:
; - Build the exe first (dist\GeonorgeDatasets.exe)
; - Install Inno Setup and ensure ISCC.exe is on PATH

#define AppName "Geonorge Datasets"
#define AppExeName "GeonorgeDatasets.exe"
#define AppPublisher "GeonorgeDatasets"
#define AppURL "https://github.com/"
#define AppVersion "1.2.0"

[Setup]
AppId={{8C7B1C4A-7D4A-4E9C-9D0A-9F3C6A58E2C1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=GeonorgeDatasetsSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Inno Setup 7+: "x64" is deprecated. Use "x64compatible" so the installer runs on
; x64 Windows and Windows on ARM (x64 emulation) and still installs into Program Files.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

