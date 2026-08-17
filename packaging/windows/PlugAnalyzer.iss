; Inno Setup 6 definition for the internal Windows x64 pilot installer.
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build_windows_x64.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_windows_x64.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_windows_x64.ps1
#endif
#ifndef SetupIcon
  #error SetupIcon must be supplied by build_windows_x64.ps1
#endif

#define MyAppName "Plug Analyzer"
#define MyAppPublisher "Plug Analyzer Team"
#define MyAppExeName "PlugAnalyzer.exe"

[Setup]
AppId={{8D7E7D65-673C-4FF7-A929-3DB083F49A9D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Plug Analyzer
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=Plug-Analyzer-{#MyAppVersion}-windows-x64-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile={#SetupIcon}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
