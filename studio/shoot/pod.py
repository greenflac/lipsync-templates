"""Команда на поде RunPod через его собственный JupyterLab (терминал по websocket).

ЗАЧЕМ ТАК. Из облачной сессии агента закрыты SSH, API и документация RunPod
(записано в `studio/knowledge/denied_hosts.jsonl`), а MCP-коннектор RunPod
управляет подами, но не исполняет в них команды. Открыт только HTTP-прокси
`<pod>-<port>.proxy.runpod.net`, и через порт 8888 отвечает JupyterLab
шаблона ComfyUI — его терминал и есть канал. До 2026-10-07 этот код жил в
`/tmp` агента и пропал бы вместе с сессией.

Пароль — из окружения (`POD_JUPYTER_PW`); в коде и журнале его нет.
Зависимости `requests` и `websocket-client` нужны только здесь и ставятся
отдельно: гейт их не требует.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid


def run(pod_id: str, command: str, timeout_s: int = 120, password: str = "") -> str:
    """Выполнить `command` в терминале пода и вернуть его вывод."""
    import requests
    import websocket

    base = f"https://{pod_id}-8888.proxy.runpod.net"
    s = requests.Session()
    # НАБЛЮДЕНО 2026-10-08: сразу после старта пода прокси минуту-две отвечает
    # то 404, то 502, пока поднимаются JupyterLab и ComfyUI. Это не отказ.
    status = 0
    for _ in range(12):
        s.get(base + "/login", timeout=30)
        r = s.post(
            base + "/login",
            data={"password": password, "_xsrf": s.cookies.get("_xsrf", "")},
            timeout=30,
            allow_redirects=False,
        )
        status = r.status_code
        if status in (200, 302):
            break
        time.sleep(10)
    else:
        raise RuntimeError(f"вход в JupyterLab пода не удался: HTTP {status}")
    hdr = {"X-XSRFToken": s.cookies.get("_xsrf", "")}
    term = s.post(base + "/api/terminals", headers=hdr, timeout=30).json()["name"]
    cookie = "; ".join(f"{k}={v}" for k, v in s.cookies.items())
    ws = websocket.create_connection(
        base.replace("https", "wss") + f"/terminals/websocket/{term}",
        header=[f"Cookie: {cookie}"],
        timeout=30,
    )
    mark = "__DONE_" + uuid.uuid4().hex[:8]
    # Метка разбита кавычками: в эхе набранной команды её нет целиком, и конец
    # ловится только по настоящему выводу. НАБЛЮДЕНО 2026-10-08: длинная строка
    # перерисовывается терминалом, эхо давало метку дважды раньше вывода.
    ws.send(json.dumps(["stdin", f"{command}; echo {mark[:4]}''{mark[4:]}\r"]))
    out, t0 = "", time.time()
    try:
        while time.time() - t0 < timeout_s:
            msg = json.loads(ws.recv())
            if msg[0] == "stdout":
                out += msg[1]
                if mark in out:
                    break
    finally:
        ws.close()
        s.delete(base + f"/api/terminals/{term}", headers=hdr, timeout=30)
    out = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", out)
    head = f"echo {mark[:4]}''{mark[4:]}"
    i = out.rfind(head)
    body = out[i + len(head) :] if i >= 0 else out
    return body.split(mark)[0].strip() if mark in body else out[-4000:]


def script_command(text: str, name: str = "/tmp/studio_shoot_step.sh") -> str:
    """Скрипт целиком — одной командой терминала: записать heredoc и запустить в bash.

    Не «вставить строки в терминал»: `set -e` из скрипта тогда закрыл бы саму
    оболочку терминала на первой ошибке, и вывод пропал бы.
    """
    return f"cat > {name} <<'STUDIO_SHOOT_EOF'\n{text.rstrip()}\nSTUDIO_SHOOT_EOF\nbash {name}"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "python -m studio.shoot.pod POD_ID 'команда' [таймаут_с]\n"
            "python -m studio.shoot.pod POD_ID --file скрипт.sh [таймаут_с]",
            file=sys.stderr,
        )
        sys.exit(2)
    args = sys.argv[2:]
    if args[0] == "--file":
        with open(args[1], encoding="utf-8") as f:
            cmd = script_command(f.read())
        args = args[1:]
    else:
        cmd = args[0]
    print(
        run(
            sys.argv[1],
            cmd,
            int(args[1]) if len(args) > 1 else 120,
            os.environ.get("POD_JUPYTER_PW", ""),
        )
    )
