#define MyAppName "百度资质自动提交工具"
#define MyAppVersion "0.30.6"
#define MyAppPublisher "Baidu Partner Flice"
#define MyAppExeName "BaiduPartnerFlice.exe"

#ifndef MyArchitecturesAllowed
  #error MyArchitecturesAllowed must be defined by an architecture entry script
#endif

[Setup]
AppId={{E76089DF-32B1-43F0-8921-D6FE9B6125B9}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BaiduPartnerFlice
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed={#MyArchitecturesAllowed}
ArchitecturesInstallIn64BitMode={#MyArchitecturesAllowed}
OutputDir=..\installer-output
OutputBaseFilename=BaiduPartnerFlice-{#MyAppVersion}-Windows-Setup
SetupIconFile=..\assets\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DefaultDialogFontName=Microsoft YaHei UI
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "..\dist\BaiduPartnerFlice\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
