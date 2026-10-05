"""Фоновая работа на Windows (аналог autostart.sh): без прав администратора.

- «Планировщик заданий»: LeadParser\\Auto каждые 30 мин (биржи, ответы, рассылка)
  и LeadParser\\Daily в 08:00 (карты, сайты, Excel, сводка). Работают и от батареи,
  пропущенный запуск выполняется, когда компьютер снова включён.
- Папка «Автозагрузка»: слежение за Telegram-каналами при входе в Windows.
Всё запускается через pythonw.exe — без чёрных окон. Журнал: data/leads.log
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

BASE = Path(__file__).resolve().parent
LEADS = BASE / "leads.py"
LOG = BASE / "data" / "leads.log"
TASKS = {
    r"LeadParser\Auto": ("auto", "Парсер клиентов: биржи, ответы и рассылка каждые 30 минут", "PT30M"),
    r"LeadParser\Daily": ("daily", "Парсер клиентов: карты, анализ сайтов, сводка в 08:00", None),
}
NO_WINDOW = 0x08000000


def pythonw():
    p = Path(sys.executable).with_name("pythonw.exe")
    return p if p.exists() else Path(sys.executable)


def startup_file():
    return Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup" / "LeadParser-watch.vbs"


def _run(args):
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    out = (r.stdout or b"") + (r.stderr or b"")
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return r.returncode, out.decode(enc)
        except UnicodeDecodeError:
            pass
    return r.returncode, out.decode("utf-8", "replace")


def _task_xml(arg, descr, repeat):
    repetition = f"<Repetition><Interval>{repeat}</Interval><Duration>P1D</Duration></Repetition>" if repeat else ""
    start = "2026-01-01T00:00:00" if repeat else "2026-01-01T08:00:00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(descr)}</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      {repetition}
      <StartBoundary>{start}</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(pythonw()))}</Command>
      <Arguments>{escape(f'"{LEADS}" {arg}')}</Arguments>
      <WorkingDirectory>{escape(str(BASE))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _watch_cmd():
    return [str(pythonw()), str(LEADS), "telegram", "--watch"]


def _stop_watch():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*leads.py*telegram*--watch*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    _run(["powershell", "-NoProfile", "-Command", ps])


def _watch_running():
    ps = ("@(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' or Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*leads.py*telegram*--watch*' }).Count")
    code, out = _run(["powershell", "-NoProfile", "-Command", ps])
    return out.strip().isdigit() and int(out.strip()) > 0


def install():
    ok = True
    for name, (arg, descr, repeat) in TASKS.items():
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
            f.write(_task_xml(arg, descr, repeat))
        code, out = _run(["schtasks", "/Create", "/TN", name, "/XML", f.name, "/F"])
        os.unlink(f.name)
        print(f"{'✔' if code == 0 else '✖'} {name}: {out.strip()}")
        ok &= code == 0
    # слежение за Telegram: при входе в Windows + запустить прямо сейчас
    pyw, leads, *args = _watch_cmd()
    cmd = f'""{pyw}"" ""{leads}"" ' + " ".join(args)
    startup_file().write_text(f'CreateObject("WScript.Shell").Run "{cmd}", 0, False\r\n', encoding="utf-16")
    _stop_watch()
    subprocess.Popen(_watch_cmd(), cwd=BASE, creationflags=NO_WINDOW | 0x00000008)  # DETACHED_PROCESS
    print("✔ Слежение за Telegram: запущено и будет стартовать при входе в Windows")
    if ok:
        print("\nАвтозапуск включён. Работает, пока компьютер включён и вы вошли в Windows.")


def remove():
    for name in TASKS:
        code, out = _run(["schtasks", "/Delete", "/TN", name, "/F"])
        print(f"{name}: {'удалено' if code == 0 else 'не найдено'}")
    startup_file().unlink(missing_ok=True)
    _stop_watch()
    print("Автозапуск выключен.")


def status():
    for name in TASKS:
        code, out = _run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"])
        if code != 0:
            print(f"{name}: не установлено")
            continue
        keep = [l.strip() for l in out.splitlines()
                if any(k in l for k in ("Next Run", "Следующий запуск", "Status", "Состояние", "Last Run", "Прошлый запуск"))]
        print(f"{name}: " + "; ".join(keep))
    print("Слежение за Telegram: " + ("работает" if _watch_running() else "не запущено"))


def logs(n=60):
    if not LOG.exists():
        print("Журнал пока пуст")
        return
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-n:]))


if __name__ == "__main__":
    {"install": install, "remove": remove, "status": status, "logs": logs}.get(
        (sys.argv[1:] or ["status"])[0], status)()
