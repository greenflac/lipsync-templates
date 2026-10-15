"""Fetch from the web through the policy, and never around it.

WHAT THIS IS FOR

72% of the knowledge base was blog tier on 2026-08-27 — second-hand writing
about vendors rather than vendors. The reflex diagnosis was "the proxy blocks
everything". Measuring it said otherwise: of 28 hosts probed, 10 answered.
What was missing was not access, it was a client that USED the access.

    open    raw.githubusercontent.com  api.github.com  github.com
            pypi.org  files.pythonhosted.org  huggingface.co
            cloud.google.com  storage.googleapis.com
            api.klingai.com  api.fal.ai
    closed  docs.bfl.ai  arxiv.org  kling.ai  help.runwayml.com
            elevenlabs.io  platform.openai.com  ai.google.dev
            api.openai.com  api.replicate.com  unpkg.com  ... (18 total)

The shape of that is worth reading: the API hosts of the two vendors this
project holds keys for are open, and the documentation hosts are shut. So the
vendor is reachable — as a running system, not as prose.

A HOST IS NOT THE UNIT. MEASURED 2026-08-27, twice each way:

    https://docs.qingque.cn/                     tunnel 403, refused
    https://docs.qingque.cn/d/home/eZQD6Ovt...    200, 16 KB

Same host, same minute, reproducible. The proxy terminates TLS, so it can and
does match on the PATH. Everything in this module and in the allowlist request
is keyed by host, because that is the unit a human grants — but "the host is
open" must not be concluded from one URL answering, and "the host is refused"
must not be concluded from one URL failing. Probe the URL you actually need.

The state machine already survives this: the doc path answering wrote an `open`
row that retired the apex's refusal, so the ask did not end up asking for
access we have. That is the latest-row rule doing its job, not luck.

WHAT THIS WILL NOT DO, AND WHY IT IS NOT A LIMITATION TO ENGINEER AROUND

A blocked host stays blocked. No mirror, no read-through proxy, no cache, no
archive copy, no second attempt at a refusal. The proxy README says it plainly
— do not retry or route around organisation policy denials, report them — and
the house rule says the same: the decision belongs to whoever owns the policy,
and going around it silently takes that decision away from them.

So the refusals are not swallowed. Every one is recorded with the URL that
wanted it and why, and `wanted()` renders the accumulated list. That list is
the allowlist request, assembled out of real attempts rather than guesses.

THREE THINGS THAT MUST NEVER PRINT THE SAME

    could not measure   the policy refused the host (CONNECT 403/407)
    could not measure   the network failed, timed out, or DNS died
    fail                the host answered and said no: 404, 500, bad URL

The first is somebody else's decision, the second is worth retrying, the third
is our own mistake. Collapsing them is how "we cannot reach the vendor" turns
into "the vendor has no such page", and that error is exactly what put 33 blog
claims into this base.
"""

from __future__ import annotations

import html.parser
import http.client
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "fetch",
    "имя_существует",
    "reachability",
    "wanted",
    "note_denial",
    "причина_для_записи",
    "последние_состояния",
    "закрыт_политикой",
    "DENIED_PATH",
    "DENIED_PATH_ENV",
    "NO_JOURNAL_ENV",
    "denied_path",
    "MEASURED_ON",
]

#: When the map in this docstring was measured. A reachability claim with no
#: date is the same rot the fact base guards against.
MEASURED_ON = "2026-08-27"

#: CHOSEN: long enough for a slow documentation host, short enough that a
#: chat waiting on it does not feel hung.
TIMEOUT_SECONDS = 25

#: Where refusals accumulate, so the allowlist request writes itself.
DENIED_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "denied_hosts.jsonl"
#: The value `DENIED_PATH` had at import. A test that patches `DENIED_PATH`
#: has named a file on purpose, and that intent beats the environment below.
_DEFAULT_DENIED_PATH = DENIED_PATH

#: ЖУРНАЛ ОТКАЗОВ — ДРУГОЙ ФАЙЛ ИЛИ НИКАКОГО. НАЙДЕНО валидатором 2026-10-14
#: (G13): `search_web` и `fetch_url` — инструменты ЧТЕНИЯ, а дописывали в
#: отслеживаемый git-ом `denied_hosts.jsonl` даже при `STUDIO_NO_JOURNAL=1`,
#: которым остальной пакет (`misses.journal_path`) уже выключал свои журналы.
#: Одно и то же слово среды значило «не пишите» для одного журнала и ничего —
#: для другого. Теперь:
#:   STUDIO_DENIED_PATH=<файл>  — писать и читать отказы там;
#:   STUDIO_NO_JOURNAL=1        — побочные записи (`note_denial`, `note_open`)
#:                                не делаются вовсе; чтение идёт как обычно.
#: Без обеих переменных — прежнее поведение, сессии владельца не меняются.
DENIED_PATH_ENV = "STUDIO_DENIED_PATH"
NO_JOURNAL_ENV = "STUDIO_NO_JOURNAL"


def denied_path(*, writing: bool = False, environ: Any = None) -> Path | None:
    """Где лежит журнал отказов. None — только для записи, когда она выключена.

    Развилка вынесена в одно место (Е1): все пять читателей и писателей
    журнала в этом модуле спрашивают путь здесь.
    """
    среда = os.environ if environ is None else environ
    if DENIED_PATH is not _DEFAULT_DENIED_PATH:
        return DENIED_PATH
    if writing and str(среда.get(NO_JOURNAL_ENV, "") or "").strip() not in ("", "0"):
        return None
    другой = str(среда.get(DENIED_PATH_ENV, "") or "").strip()
    return Path(другой).expanduser() if другой else DENIED_PATH


#: The proxy's signature for an organisation policy denial, as observed:
#: `URLError(<urlopen error Tunnel connection failed: 403 Forbidden>)`.
_DENIAL = re.compile(r"tunnel connection failed:\s*(403|407)", re.I)

_UA = "lipsync-studio-knowledge/1.0 (+https://github.com/greenflac/lipsync-templates)"


#: ПОТОЛОК ДЛИНЫ ПРИЧИНЫ. ВЫБРАНО: самая длинная НАСТОЯЩАЯ формулировка в живом
#: файле — 289 символов (ИЗМЕРЕНО 2026-09-05 на 605 строках, 26 длиннее 200), и
#: 400 оставляет запас, не превращая строку в текстовое поле.
ПОТОЛОК_ПРИЧИНЫ = 400

#: Что вырезается из причины перед записью в отслеживаемый git-ом файл.
#: Почта, телефон и длинная цепочка цифр — то, чем текст заказчика отличается от
#: нашей формулировки. Список закрытый и намеренно грубый: он не «определяет
#: персональные данные», он снимает самые узнаваемые их формы.
_ЛИЧНОЕ = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<почта>"),
    (re.compile(r"(?<!\d)(?:\+\d[\d ()-]{8,}\d)(?!\d)"), "<телефон>"),
    (re.compile(r"(?<!\d)\d{9,}(?!\d)"), "<длинное число>"),
)


def причина_для_записи(текст: str) -> str:
    """Причина в том виде, в каком её можно положить в репозиторий.

    ЗАЧЕМ. `denied_hosts.jsonl` лежит в git и уезжает в публичный репозиторий, а
    поле `why_wanted` до 2026-09-05 писалось ДОСЛОВНО — в том числе из
    `search.py`, где оно строилось как «web search for: {текст запроса}», и из
    параметра инструмента MCP, который заполняет клиент. То есть текст, который
    печатал заказчик, мог уехать в коммит.

    ИЗМЕРЕНО 2026-09-05: в живом файле 605 строк, из них с текстом поискового
    запроса — НОЛЬ. То есть сегодня это ничего не стоило — и ровно поэтому
    прошло бы дальше. Дыра закрывается В ОДНОМ МЕСТЕ (Е1): здесь, а не в каждом
    зовущем, иначе следующий зовущий про неё не узнает.

    Отрезание помечается вслух: молча укоротить чужую формулировку значит
    отдать обрезок за целое.
    """
    было = " ".join(str(текст or "").split())
    стало = было
    for образец, замена in _ЛИЧНОЕ:
        стало = образец.sub(замена, стало)
    вырезано = стало != было
    if len(стало) > ПОТОЛОК_ПРИЧИНЫ:
        стало = стало[:ПОТОЛОК_ПРИЧИНЫ] + f" …(обрезано с {len(было)} символов)"
    if вырезано:
        стало += " [узнаваемо личное вырезано перед записью в репозиторий]"
    return стало


#: Одна метка имени хоста по RFC 1123: буквы, цифры, дефис не по краям.
_МЕТКА = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def имя_хоста_годно(host: str) -> bool:
    """Похоже ли это на имя хоста, которое можно записать в журнал отказов.

    ЗАЧЕМ. НАЙДЕНО живым прогоном 2026-10-14: `reachable_hosts('https://x.y/z')`
    строил адрес `https://https://x.y/z/`, старый разбор регулярным выражением
    брал из него хост `https` — и ЭТО слово уезжало в `denied_hosts.jsonl`, то
    есть в заявку, которую читает владелец окружения. Мусор в заявке хуже, чем
    пропуск: он учит читателя не верить остальным строкам.

    Требуется хотя бы одна точка (имя без точки — это `https`, `localhost` или
    опечатка, но не хост в интернете) либо IP-литерал. IDN проверяется в своей
    ASCII-форме.
    """
    имя = str(host or "").strip().lower().rstrip(".")
    if not имя or len(имя) > 253:
        return False
    try:
        ipaddress.ip_address(имя)
        return True
    except ValueError:
        pass
    try:
        ascii_имя = имя.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return False
    метки = ascii_имя.split(".")
    if len(метки) < 2:
        return False
    # ЦИФРОВАЯ ВЕРХНЯЯ МЕТКА — ЭТО НЕ ИМЯ, А НЕГОДНЫЙ IP. НАЙДЕНО валидатором
    # 2026-10-14 (G13): `reachable_hosts('999.999.999.999')` проходил как имя
    # хоста (каждая метка — цифры, а цифры метке разрешены) и уезжал в журнал
    # отказов. Верхняя метка из одних цифр не бывает доменом (RFC 3696 §2), а
    # годный IP-литерал уже принят выше — значит, это IP с ошибкой.
    if метки[-1].isdigit():
        return False
    return all(_МЕТКА.match(м) for м in метки)


def негодный_ip(host: str) -> bool:
    """Похоже на IP-литерал, но адресом не является (`999.999.999.999`, `1.2.3`)."""
    имя = str(host or "").strip().lower().strip("[]").rstrip(".")
    if not имя:
        return False
    try:
        ipaddress.ip_address(имя)
        return False
    except ValueError:
        pass
    if ":" in имя:
        return bool(re.fullmatch(r"[0-9a-f:.%]+", имя))
    return bool(re.fullmatch(r"[0-9.]+", имя)) and "." in имя


def _host(url: str) -> str:
    """Хост из адреса, или "" если адрес не http(s) или хост не годен.

    Разбирается `urlsplit`, а не регулярным выражением. Прежнее
    `https?://([^/:]+)` отдавало `evil.com@127.0.0.1` за хост (часть с
    `user@` — это не хост) и `https` за хост в `https://https://x.y/`.
    """
    text = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    host = host.lower().rstrip(".")
    return host if имя_хоста_годно(host) else ""


def нормализовать_хост(text: str) -> tuple[str, str]:
    """(хост, "") из того, что человек вписал как хост; ("", почему) — если это не хост.

    Принимает `x.y`, `X.Y.`, `x.y:443`, `https://x.y/z` — всё это один хост
    `x.y`. Отказ называет причину: строка, которую нельзя разобрать, не
    пробуется и НЕ ПИШЕТСЯ в журнал отказов.
    """
    raw = str(text or "").strip()
    if not raw:
        return "", "пустая строка"
    кандидат = raw if "://" in raw else f"https://{raw}"
    try:
        parts = urllib.parse.urlsplit(кандидат)
    except ValueError as error:
        return "", f"{raw!r} не разбирается как адрес: {error}"
    if parts.scheme.lower() not in ("http", "https"):
        return "", f"{raw!r}: схема {parts.scheme!r}, а пробуются только http и https"
    host = _host(кандидат)
    if not host:
        if негодный_ip(parts.hostname or ""):
            return "", f"{raw!r} похоже на IP-адрес, но адресом не является (invalid IP literal)"
        return "", f"{raw!r} не похоже на имя хоста"
    return host, ""


# ---------------------------------------------------------------------------
# SSRF. ЗАЧЕМ: сервер готовится к публичному хостингу, и `fetch_url`,
# `reachable_hosts`, `probe_model_limit` берут адрес ИЗ ВЫЗОВА. Без этой
# защиты любой клиент MCP читает через нас 169.254.169.254 (метаданные
# облака с ключами), 127.0.0.1:<порт админки> и локальную сеть хоста.
#
# КАК УСТРОЕНО, И ПОЧЕМУ ТАК:
#   1. ДО запроса: только http/https; имя годно; IP-литерал (в том числе
#      старые формы `2130706433`, `0x7f.1`, которые резолвер честно
#      превращает в 127.0.0.1) и служебные имена (`localhost`, `*.internal`,
#      `metadata.google.internal`) отказываются сразу.
#   2. ПРИ СОЕДИНЕНИИ: имя разрешается и КАЖДЫЙ адрес проверяется, после чего
#      соединение открывается С ПРОВЕРЕННЫМ адресом — не «проверили одно,
#      соединились с другим» (DNS rebinding). Это делает `_GuardedHTTP*`.
#   3. НА ПЕРЕАДРЕСАЦИИ: новый адрес проходит пункт 1, а соединение — пункт 2;
#      схема, отличная от http/https, отказывается.
#
# ГРАНИЦА, СКАЗАННАЯ ВСЛУХ. Когда запрос идёт через ПРОКСИ (как в этой
# песочнице), имя разрешает прокси, а не мы, и пункт 2 проверить нечего:
# остаются пункты 1 и 3 и собственная политика прокси. Разрешать имя у себя
# «на всякий случай» нельзя: адрес, который увидим мы, не обязан совпасть с
# тем, к которому подключится прокси, — это была бы защита на вид.
# ---------------------------------------------------------------------------

#: Сети, в которые запрос из вызова не уходит. Помимо того, что `ipaddress`
#: и так считает частным/служебным, — CGNAT 100.64/10: в 3.11 он не
#: `is_private`, а за ним в облаках бывают внутренние сервисы.
_ЗАКРЫТЫЕ_СЕТИ = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "::/128",
        "fc00::/7",
        "fe80::/10",
    )
)

#: Имена, которые по смыслу внутренние, — отказ без всякого DNS.
_ЗАКРЫТЫЕ_ИМЕНА = ("localhost", "metadata.google.internal", "metadata")
_ЗАКРЫТЫЕ_СУФФИКСЫ = (".localhost", ".internal", ".local", ".home.arpa", ".lan")


class SSRFRefused(urllib.error.URLError):
    """Адрес ведёт во внутреннюю сеть; запрос туда не отправлялся."""


def ssrf_reason(error: BaseException) -> str:
    """Текст отказа SSRF, если ошибка — он (urllib заворачивает его в URLError)."""
    for candidate in (error, getattr(error, "reason", None)):
        if isinstance(candidate, SSRFRefused):
            return str(getattr(candidate, "reason", candidate))
    return ""


def ip_закрыт(ip: str) -> str:
    """Почему по этому IP ходить нельзя; "" — можно."""
    try:
        адрес = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return f"{ip!r} не IP-адрес"
    mapped = getattr(адрес, "ipv4_mapped", None)
    if mapped is not None:
        адрес = mapped
    for сеть in _ЗАКРЫТЫЕ_СЕТИ:
        if адрес.version == сеть.version and адрес in сеть:
            return f"{адрес} лежит во внутренней сети {сеть}"
    if (
        адрес.is_private
        or адрес.is_loopback
        or адрес.is_link_local
        or адрес.is_multicast
        or адрес.is_reserved
        or адрес.is_unspecified
    ):
        return f"{адрес} — не публичный адрес"
    return ""


def _ipv4_литерал(host: str) -> str:
    """Старые формы IPv4 (`2130706433`, `0x7f.1`, `0177.0.0.1`) -> точечная запись.

    Разбирает `inet_aton` — ЛОКАЛЬНО, без DNS: ровно этим разбором их потом
    понял бы резолвер. "" — это не IPv4-литерал.
    """
    if not re.fullmatch(r"[0-9a-fx.]+", host):
        return ""
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        return ""


def адрес_закрыт(url: str) -> str:
    """Почему этот адрес нельзя запрашивать (пункт 1 выше); "" — можно.

    Без DNS: ни тест, ни прокси от этой проверки в сеть не ходят.
    """
    text = str(url or "").strip()
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError as error:
        return f"адрес не разбирается: {error}"
    if parts.scheme.lower() not in ("http", "https"):
        return f"схема {parts.scheme!r}: запрашиваются только http и https"
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return "в адресе нет хоста"
    try:
        ipaddress.ip_address(host)
        литерал = host
    except ValueError:
        литерал = _ipv4_литерал(host)
    if литерал:
        return ip_закрыт(литерал)
    if host in _ЗАКРЫТЫЕ_ИМЕНА or host.endswith(_ЗАКРЫТЫЕ_СУФФИКСЫ):
        return f"{host} — служебное внутреннее имя"
    if not имя_хоста_годно(host):
        return f"{host!r} не похоже на имя хоста"
    return ""


def _proxy_hosts() -> set[str]:
    """Хосты настроенных прокси: соединение С НИМИ не проверяется на SSRF."""
    out: set[str] = set()
    for scheme, value in urllib.request.getproxies().items():
        if scheme == "no":
            continue
        try:
            host = urllib.parse.urlsplit(value if "://" in value else f"http://{value}").hostname
        except ValueError:
            continue
        if host:
            out.add(host.lower())
    return out


def _guarded_create_connection(
    address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **_kw
):  # type: ignore[attr-defined]
    """`socket.create_connection`, который соединяется только с проверенным адресом.

    Разрешает имя САМ, проверяет КАЖДЫЙ полученный адрес и подключается к
    одному из них — так проверенный адрес и есть тот, с которым говорим.
    """
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    for *_rest, sockaddr in infos:
        причина = ip_закрыт(sockaddr[0])
        if причина:
            raise SSRFRefused(f"{host} разрешается во внутренний адрес: {причина}")
    last: OSError | None = None
    for family, kind, proto, _canon, sockaddr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:  # type: ignore[attr-defined]
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as error:
            last = error
            sock.close()
    raise last or OSError(f"{host}: getaddrinfo returned nothing")


def _охранять(connection: Any) -> Any:
    """Подменить соединению способ подключения на проверяющий (пункт 2)."""
    original = connection._create_connection

    def create(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        # Через туннель или к самому прокси — это соединение С ПРОКСИ, имя
        # цели разрешает он; см. «границу» выше.
        if getattr(connection, "_tunnel_host", None) or str(address[0]).lower() in _proxy_hosts():
            return original(address, *args, **kwargs)
        return _guarded_create_connection(address, *args, **kwargs)

    connection._create_connection = create
    return connection


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _охранять(self)


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _охранять(self)


class _GuardedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # type: ignore[no-untyped-def]
        return self.do_open(_GuardedHTTPConnection, req)


class _GuardedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # type: ignore[no-untyped-def]
        kwargs: dict[str, Any] = {"context": getattr(self, "_context", None)}
        if hasattr(self, "_check_hostname"):
            kwargs["check_hostname"] = self._check_hostname
        return self.do_open(_GuardedHTTPSConnection, req, **kwargs)


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Переадресация проходит ту же проверку, что и первый адрес (пункт 3)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        причина = адрес_закрыт(newurl)
        if причина:
            raise SSRFRefused(f"переадресация на {newurl} отказана: {причина}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_STOCK_URLOPEN = urllib.request.urlopen
_GUARDED_OPENER: Any = None


def _open(request: urllib.request.Request, *, timeout: float) -> Any:
    """Единственная дверь наружу для адресов из вызова: с охраной SSRF.

    Если `urllib.request.urlopen` ПОДМЕНЁН (тестовый дублёр транспорта),
    зовётся он: тест, заменивший транспорт, заменил его целиком, и сети нет.
    Иначе — свой opener с охраняемыми соединениями и переадресацией. Он НЕ
    ставится глобально (`install_opener`), чтобы не менять поведение чужих
    модулей этого процесса.
    """
    global _GUARDED_OPENER
    if urllib.request.urlopen is not _STOCK_URLOPEN:
        return urllib.request.urlopen(request, timeout=timeout)
    if _GUARDED_OPENER is None:
        _GUARDED_OPENER = urllib.request.build_opener(
            _GuardedHTTPHandler, _GuardedHTTPSHandler, _GuardedRedirect
        )
    return _GUARDED_OPENER.open(request, timeout=timeout)


def имя_существует(host: str) -> bool | None:
    """Резолвится ли это имя. Три исхода: да, нет, резолвер не ответил (Р1).

    ЗАЧЕМ. ВОСПРОИЗВЕДЕНО 2026-09-07: прокси отвечает `Tunnel connection
    failed: 403` ОДИНАКОВО и на настоящий хост, и на выдуманный
    (`docs-nesuschestvuet-2026.example-nope-xyz.com` дал ровно тот же отказ,
    что и `example.com`). Значит журнал отказов — а через него и заявка,
    которую читает ВЛАДЕЛЕЦ ОКРУЖЕНИЯ, — не отличает «хост закрыт политикой»
    от «хоста не существует», и владельца можно попросить открыть домен,
    которого нет.

    ЭТО НЕ ОБХОД Ц3. С закрытого хоста здесь ничего не скачивается и никакое
    соединение с ним не устанавливается: спрашивается только, есть ли такое
    имя, — ровно чтобы не занимать чужое время просьбой про несуществующее.
    Ц10 требует того же от имён, попадающих в код.

    ГДЕ ЭТО РЕШАЕТСЯ, И ПОЧЕМУ НЕ В ЖУРНАЛЕ ОТКАЗОВ. Первая версия спрашивала
    DNS прямо в `note_denial` — в функции, которую зовут десятки тестов, — и
    тем самым завела сеть в тесты, чего Т4 не допускает: три фикстуры на
    зарезервированном `example.test` покраснели в ту же минуту и показали это.
    Поэтому имя проверяется В ОДНОМ месте (Е1) — в
    `scripts/allowlist_request.py`, который и так ходит в сеть и собирает
    документ для человека.

    ИЗМЕРЕНО 2026-09-07: разрешение имени стоит 0.01–0.03 с и различает обе
    стороны — `example.com`, `docs.bfl.ai`, `kling.ai` резолвятся;
    `qwertyuiop-nope-12345.dev` и выдуманный домен выше — нет.
    """
    имя = str(host or "").strip().lower()
    if not имя:
        return None
    try:
        socket.getaddrinfo(имя, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as ошибка:
        # `gaierror` — ЭТО ОБА ИСХОДА, И РАЗЛИЧАЕТ ИХ КОД. Найдено приёмкой
        # 2026-09-07: первая редакция ловила `gaierror` целиком и объявляла
        # «имени нет», а ветка `except OSError` под ней была для DNS
        # недостижима. Цена измерена тем же прогоном: при недоступном
        # резолвере из просьбы вылетали ВСЕ 49 хостов, и документ печатал
        # человеку «CLOSED, нечего просить» — то есть прибор врал ровно тем
        # способом, который правка объявила недопустимым.
        #
        #   EAI_NONAME  такого имени нет            -> False, это ответ
        #   всё прочее  резолвер не смог ответить   -> None, третий исход
        #
        # EAI_AGAIN («сервер имён занят, попробуйте позже») — обычное дело
        # там, где имена резолвит прокси, а локального DNS нет.
        return False if ошибка.errno == socket.EAI_NONAME else None
    except OSError:
        # Не резолвер, а окружение: нет сети вовсе, сокеты отобраны раннером.
        return None
    return True


def note_denial(url: str, reason: str, why_wanted: str = "", *, incidental: bool = False) -> dict:
    """Record that the policy refused a host, so the request for it writes itself.

    :param why_wanted: what the caller was trying to learn. An allowlist request
        that says "we need arxiv.org" is weaker than one that says which claim
        is stuck on blog tier without it.
    :param incidental: True when nobody asked for this host — it was swept up by
        a bulk probe, such as tagging search hits with whether they open.

        OBSERVED 2026-08-27, on the first live Gemini search: one query added
        five hosts nobody had ever wanted (atlascloud.ai, magnific.com, kie.ai,
        evolink.ai, wavespeed.ai) to a file holding six hosts that a real
        question was stuck behind. `wanted()` presents that file to a human who
        then goes and asks for the hosts in it, and its own note claimed each
        one "was needed for a real question". A few more searches and the ask
        the owner has to justify is mostly noise. Refusals are still all
        recorded — routing around them is what is forbidden, not counting them —
        but an incidental one is reported apart from the ask.
    """
    host = _host(url)
    if not host:
        return {"recorded": False, "host": ""}
    row = {
        "host": host,
        "url": str(url),
        "reason": reason,
        "why_wanted": причина_для_записи(why_wanted),
        "incidental": bool(incidental),
        "state": STATE_REFUSED,
        "first_seen": date.today().isoformat(),
    }
    журнал = denied_path(writing=True)
    if журнал is None:
        # Запись выключена (`STUDIO_NO_JOURNAL`): отказ НЕ теряется для
        # вызывающего — он в ответе, — но в файл не идёт.
        return {"recorded": False, "host": host, "journal": "off"}
    журнал.parent.mkdir(parents=True, exist_ok=True)
    # This file is append-only history, and three things make a new row worth
    # appending:
    #
    #  fresh     nobody has recorded this host at all
    #  promoted  it was met by a bulk probe and is now actually needed, so it
    #            can move into the ask. Without this, the order two calls
    #            happened in would decide whether a host the owner needs is
    #            ever asked for.
    #  restated  it is already in the ask, but for a DIFFERENT reason. The
    #            reason is the whole request — OBSERVED 2026-08-27, docs.bfl.ai
    #            was still asked for because "every recorded claim about it is
    #            blog tier", which the re-tiering had made false that morning.
    #            Keeping only the first reason freezes the request at whatever
    #            the base looked like the day the host was first refused.
    rows = _read_denied()
    known = {
        r.get("host"): bool(r.get("incidental", False))
        for r in rows
        if str(r.get("state", STATE_REFUSED)) == STATE_REFUSED
    }
    # A host whose latest row is NOT a refusal, refused again, is a fresh
    # refusal rather than a restatement: the grant went away, or the plan came
    # back. Written against "not refused" and not against the list of other
    # states, because this rule was first written when there were two states
    # and it silently stopped covering the third the day `unwanted` was added
    # — OBSERVED 2026-08-27, by a test that expected a withdrawn host to
    # return to the ask when it was refused again, and it did not.
    latest_state = _latest_states(rows)
    for row_host, state in latest_state.items():
        if state != STATE_REFUSED:
            known.pop(row_host, None)
    # The last reason we gave for ASKING. An `open` row carries no reason, so
    # letting it reset this made the restatement rule fire on a re-refusal and
    # quietly do the reopening rule's job — which left that rule dead code that
    # no test could distinguish from a working one (OBSERVED 2026-08-27).
    latest_reason = ""
    for previous in rows:
        if (
            previous.get("host") == host
            and not previous.get("incidental", False)
            and str(previous.get("state", STATE_REFUSED)) == STATE_REFUSED
        ):
            latest_reason = str(previous.get("why_wanted", ""))
    fresh = host not in known
    promoted = not fresh and known[host] and not incidental
    restated = not fresh and not incidental and why_wanted.strip() != latest_reason.strip()
    if fresh or promoted or restated:
        with журнал.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": fresh or promoted or restated, "host": host}


#: A row's state. Absent means `refused`: every row written before 2026-08-27
#: was a refusal, because that was the only thing this file recorded.
STATE_REFUSED = "refused"
STATE_OPEN = "open"
#: Still refused, and no longer wanted. A third state because dropping a plan
#: is not the same event as being granted access, and recording it as `open`
#: would put a lie in the file — the host never answered.
#:
#: OBSERVED 2026-08-27: Reddit was dropped, and the two hosts carrying its
#: terms stayed in the ask with the reason "decides whether a collector may be
#: written at all". Nobody was going to write one. A request that asks for
#: access nobody needs any more is the same defect as one that asks for access
#: already granted, and this file had already been fixed once for the second.
STATE_UNWANTED = "unwanted"


def _latest_states(rows: list[dict]) -> dict[str, str]:
    """The last state recorded for each host. Absent `state` means refused."""
    latest: dict[str, str] = {}
    for row in rows:
        host = row.get("host", "")
        if host:
            latest[host] = str(row.get("state", STATE_REFUSED))
    return latest


def последние_состояния(denied: Path | None = None) -> dict[str, str]:
    """Хост -> его ПОСЛЕДНЕЕ записанное состояние. Одно место на весь проект.

    Журнал отказов дописывается, а не переписывается: строка `open` снимает
    прежний отказ. Разбор «по любому упоминанию» на живой базе завышает вдвое
    (274 хоста против 210 закрытых, ИЗМЕРЕНО 2026-09-06), и однажды это уже
    стоило независимой проверке ошибки в 983 раза.
    """
    путь = (denied_path() or DENIED_PATH) if denied is None else denied
    try:
        текст = путь.read_text(encoding="utf-8")
    except OSError:
        return {}
    состояния: dict[str, str] = {}
    for строка in текст.splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("//"):
            continue
        try:
            row = json.loads(строка)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("host"):
            состояния[str(row["host"]).lower()] = str(row.get("state", STATE_REFUSED))
    return состояния


def закрыт_политикой(url: str, denied: Path | None = None) -> bool:
    """Записан ли хост этого адреса ПОСЛЕДНИМ состоянием как отказавший.

    Журнал отказов — журнал СОСТОЯНИЙ: строка `open` снимает прежний отказ, и
    считать по любому упоминанию значит завышать. Независимая проверка
    2026-09-05 наступила на это и записала число: «закрыт» без учёта поздних
    проб дал 983 строки против 1 настоящей — завышение в 983 раза.
    """
    host = _host(url)
    if not host:
        return False
    return последние_состояния(denied).get(host, "") == STATE_REFUSED


def note_open(url: str) -> dict:
    """Record that a previously-refused host now answers, retiring it from the ask.

    OBSERVED 2026-08-27: the allowlist request is assembled from refusals that
    happened, and a refusal never expires. When the owner granted 21 hosts, the
    generated request went on asking for all 21 — it had no way to learn it had
    been answered. A request that asks for access you already granted is worse
    than no request: it is the reason the next one is not read.

    So this file is a log of STATE CHANGES, not of refusals. One row is written
    the first time a refused host answers, and `wanted()` reads the latest row
    per host. The history of "asked on this date, granted by that one" survives
    in the file, which is the part worth keeping.

    Called from `fetch()` on any successful response, so the ask retires itself
    through ordinary use rather than only when somebody remembers to re-run the
    request generator.
    """
    host = _host(url)
    if not host:
        return {"recorded": False, "host": ""}
    latest = _latest_states(_read_denied()).get(host, "")
    # Only a transition is written. Without this, every fetch of an open host
    # appends a row forever.
    #
    # The test is "not already open", not "is refused": written the second way,
    # a host withdrawn from the ask that LATER answered was never recorded as
    # open, so the file lost the fact that access had arrived — OBSERVED
    # 2026-08-27, the day `unwanted` was added, by the test that expected it.
    if latest == "" or latest == STATE_OPEN:
        return {"recorded": False, "host": host}
    журнал = denied_path(writing=True)
    if журнал is None:
        return {"recorded": False, "host": host, "journal": "off"}
    журнал.parent.mkdir(parents=True, exist_ok=True)
    with журнал.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "host": host,
                    "url": str(url),
                    "state": STATE_OPEN,
                    "first_seen": date.today().isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return {"recorded": True, "host": host}


def note_unwanted(host: str, reason: str) -> dict:
    """Withdraw a host from the ask without claiming it opened. Three outcomes.

    For a plan that was abandoned. The host stays refused — that is the truth —
    and stops being asked for, and the reason travels with it so the next
    reader can see the ask shrank by a decision rather than by a grant.

    A host nobody ever asked for is `could not measure`, not a success: a typo
    would otherwise report that it had been withdrawn.
    """
    name = str(host or "").strip().lower()
    why = str(reason or "").strip()
    if not name or not why:
        missing = [n for n, v in (("host", name), ("reason", why)) if not v]
        return {
            "outcome": FAIL,
            "checked": 2,
            "violations": len(missing),
            "unmeasured": 0,
            "note": ", ".join(missing)
            + " is required; a withdrawal without a reason is a deletion",
            "host": name,
        }
    latest = ""
    for row in _read_denied():
        if row.get("host") == name:
            latest = str(row.get("state", STATE_REFUSED))
    if latest == "":
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{name} has never been recorded as refused, so there was nothing to withdraw",
            "host": name,
        }
    if latest == STATE_UNWANTED:
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": f"{name} was already withdrawn from the ask",
            "host": name,
        }
    # Явное действие оператора, а не побочный эффект чтения: пишется и при
    # `STUDIO_NO_JOURNAL`, но в тот файл, который назван средой.
    журнал = denied_path() or DENIED_PATH
    журнал.parent.mkdir(parents=True, exist_ok=True)
    with журнал.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "host": name,
                    "state": STATE_UNWANTED,
                    "reason": why,
                    "first_seen": date.today().isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": f"{name} withdrawn from the ask: {why}",
        "host": name,
    }


def _read_denied() -> list[dict]:
    журнал = denied_path() or DENIED_PATH
    if not журнал.is_file():
        return []
    rows: list[dict] = []
    for line in журнал.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def read_capped(reader: Any, max_bytes: int) -> tuple[bytes, bool]:
    """Read at most `max_bytes`, and say whether there was more.

    Kept out of `fetch` on purpose (rule T5): the fork that decides whether a
    body is whole has to be reachable from a test, and a fork inside a function
    that opens a socket is not.

    THE DEFECT THIS EXISTS FOR, reproduced 2026-08-31 before the fix: a Civitai
    listing at limit=100 is ~1.8 MB, a plain `read(max_bytes)` cut it
    mid-object, and the caller reported "the listing answered with something
    that is not JSON". True, and blaming the wrong thing — the evidence for
    truncation was in the length and nobody looked (rule E2). A whole collection
    run died on a message that sent the reader after the format.
    """
    body = reader.read(max_bytes + 1)
    if len(body) > max_bytes:
        return body[:max_bytes], True
    return body, False


def fetch(
    url: str,
    *,
    why_wanted: str = "",
    max_bytes: int = 400_000,
    incidental: bool = False,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> dict:
    """Open one URL through the configured proxy. Three outcomes, no fallbacks.

    :param why_wanted: what this fetch was for. Carried into the denial record
        when the policy refuses, so the allowlist request explains itself.
    :param incidental: True when this host is being swept by a bulk probe
        rather than actually wanted; see `note_denial`. A refusal is recorded
        either way — this only keeps it out of the ask.
    :param headers: extra request headers, merged over the User-Agent. For an
        API that authenticates per request — an OAuth bearer token, an API key
        header. The User-Agent stays unless a caller replaces it deliberately.
    :param data: a request body. Its presence is what makes this a POST, which
        is how an OAuth token endpoint is asked for a token.
    :returns: the house judging dict plus `host`, `status`, `text` and
        `denied` — True only when the refusal came from the egress policy.

    A denial is never retried and never re-routed. That is the whole contract.

    `headers` and `data` exist so an authenticated API is reached THROUGH this
    function rather than beside it. A second HTTP path would be a second place
    where a policy refusal could be swallowed, retried or routed around, and a
    second place where a refusal fails to reach the allowlist request — the
    bookkeeping only works because there is one door.
    """
    target = str(url or "").strip()
    if not target.startswith(("http://", "https://")):
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{target!r} is not an http(s) URL, so nothing was attempted",
            "host": "",
            "status": None,
            "text": "",
            "denied": False,
        }

    host = _host(target)
    # SSRF, ПУНКТ 1: до того как существует запрос. Отказ — `fail`: это адрес
    # вызывающего, а не решение политики, и в журнал отказов он НЕ пишется —
    # заявка на открытие внутренней сети была бы хуже мусора.
    закрыт = адрес_закрыт(target)
    if закрыт:
        return _ssrf_refusal(target, закрыт)
    sent = {"User-Agent": _UA}
    sent.update({str(k): str(v) for k, v in (headers or {}).items()})
    request = urllib.request.Request(target, headers=sent, data=data)
    try:
        with _open(request, timeout=TIMEOUT_SECONDS) as response:
            body, truncated = read_capped(response, max_bytes)
            text = body.decode("utf-8", "replace")
            content_type = ""
            try:
                content_type = str(response.headers.get("Content-Type", "") or "")
            except Exception:  # noqa: BLE001 - a double without headers is not a failure
                content_type = ""
            # The host answered, so if it was in the ask it no longer belongs
            # there. Retiring it here rather than in the request generator
            # means ordinary use keeps the ask honest.
            note_open(target)
            return {
                "outcome": PASS,
                "checked": 1,
                "violations": 0,
                "unmeasured": 0,
                "truncated": truncated,
                "max_bytes": max_bytes,
                "note": (
                    f"{host} answered {response.status}, {len(body)} bytes read"
                    + (
                        f" И ОБРЕЗАНО на потолке {max_bytes}: тело длиннее, "
                        "остаток не прочитан — если это JSON, он неполный"
                        if truncated
                        else ""
                    )
                ),
                "host": host,
                "status": response.status,
                "content_type": content_type,
                "text": text,
                "denied": False,
            }
    except urllib.error.HTTPError as error:
        # The host answered and said no. That is OUR bad URL, not the policy's
        # doing, and the two must not print the same. It is also proof the host
        # is reachable, which is what retires it from the ask — a 404 on a bare
        # root is a very common way for a granted host to greet us.
        note_open(target)
        # The error BODY is kept. An API that refuses you usually says why in
        # it, and throwing it away turns a diagnosable refusal into a bare
        # number — MEASURED 2026-08-27, when oauth.reddit.com answered 403 and
        # only the body distinguished "you are blocked" from "your token is
        # wrong", which is the difference between a credential being worth
        # obtaining and not.
        try:
            error_text = error.read(max_bytes).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a body we cannot read is not a new failure
            error_text = ""
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{host} answered {error.code} {error.reason}",
            "host": host,
            "status": error.code,
            "text": error_text,
            "denied": False,
        }
    except urllib.error.URLError as error:
        отказ_ssrf = ssrf_reason(error)
        if отказ_ssrf:
            return _ssrf_refusal(target, отказ_ssrf)
        reason = str(getattr(error, "reason", error))
        if _DENIAL.search(reason):
            записано = note_denial(target, reason, why_wanted, incidental=incidental)
            # Нота не обещает записи, которой не было: при `STUDIO_NO_JOURNAL`
            # журнал выключен, и «Recorded» было бы неправдой.
            if записано.get("journal") == "off":
                хвост = (
                    f"NOT recorded: the denial journal is off in this process ({NO_JOURNAL_ENV})."
                )
            else:
                хвост = "Recorded — run `wanted()` for the list to ask them for."
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    f"{host} is refused by this organisation's egress policy "
                    f"({reason}). Not retried and not routed around: that is the "
                    f"policy owner's decision. {хвост}"
                ),
                "host": host,
                "status": None,
                "text": "",
                "denied": True,
            }
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{host} could not be reached: {reason}. Worth retrying.",
            "host": host,
            "status": None,
            "text": "",
            "denied": False,
        }
    except Exception as error:  # noqa: BLE001 - a fetch must not take the chat down
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{host} failed unexpectedly: {type(error).__name__}: {error}",
            "host": host,
            "status": None,
            "text": "",
            "denied": False,
        }


# ---------------------------------------------------------------------------
# ЧТЕНИЕ СТРАНИЦЫ ЧЕЛОВЕКОМ-АГЕНТОМ. ИЗМЕРЕНО 2026-10-14 живым прогоном
# `fetch_url`: ai.google.dev отдал 264 тыс. символов, platform.minimax.io —
# 424 тыс., и почти всё это разметка, скрипты и меню. Агент, которому вернули
# такое, либо не дочитывает до сути, либо съедает на чтение весь контекст.
# Поэтому инструмент по умолчанию отдаёт ТЕКСТ страницы, кусками, и говорит,
# сколько осталось. `fetch()` для программ остаётся как был: ему нужен сырой
# JSON и сырой HTML.
# ---------------------------------------------------------------------------

#: Сколько символов текста отдаётся за один вызов, если не попросили иначе.
#: ВЫБРАНО: ~5 тыс. токенов — страница документации целиком или её большая
#: часть, и при этом пять таких чтений не съедают контекст агента.
PAGE_CHARS = 20_000

#: Потолок `max_chars`, сколько бы ни попросили. ВЫБРАНО вчетверо выше
#: умолчания: больше за один раз агенту читать незачем, для того и `offset`.
PAGE_CHARS_MAX = 80_000

#: Сколько байт тела скачивать для чтения кусками. 424 тыс. символов
#: minimax — самый длинный ответ, что мы видели; 2 МБ покрывают его с запасом.
PAGE_BYTES = 2_000_000

#: Теги, содержимое которых — не текст страницы.
_НЕ_ТЕКСТ = frozenset(
    {"script", "style", "nav", "noscript", "svg", "template", "iframe", "head", "canvas"}
)
#: Теги, после которых в тексте начинается новая строка.
_БЛОЧНЫЕ = frozenset(
    {
        "p", "div", "section", "article", "main", "header", "footer", "aside",
        "br", "hr", "li", "ul", "ol", "dl", "dt", "dd", "tr", "table", "thead",
        "tbody", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
        "figure", "figcaption", "form", "details", "summary",
    }
)  # fmt: skip


class _Текст(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.куски: list[str] = []
        self.заголовок: list[str] = []
        self._глубина_скрытого = 0
        self._в_title = False
        self._в_pre = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        tag = tag.lower()
        if tag == "title":
            self._в_title = True
        if tag in _НЕ_ТЕКСТ:
            self._глубина_скрытого += 1
        if tag == "pre":
            self._в_pre += 1
        if tag in _БЛОЧНЫЕ:
            self.куски.append("\n")
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and not self._глубина_скрытого:
            self.куски.append("#" * int(tag[1]) + " ")
        if tag == "li" and not self._глубина_скрытого:
            self.куски.append("- ")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if tag.lower() in ("br", "hr"):
            self.куски.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._в_title = False
        if tag in _НЕ_ТЕКСТ and self._глубина_скрытого:
            self._глубина_скрытого -= 1
        if tag == "pre" and self._в_pre:
            self._в_pre -= 1
        if tag in _БЛОЧНЫЕ:
            self.куски.append("\n")

    def handle_data(self, data: str) -> None:
        if self._в_title:
            self.заголовок.append(data)
            return
        if self._глубина_скрытого:
            return
        self.куски.append(data if self._в_pre else re.sub(r"\s+", " ", data))


def похоже_на_html(text: str, content_type: str = "") -> bool:
    """HTML ли это: по заголовку ответа, а без него — по началу тела."""
    if "html" in str(content_type or "").lower():
        return True
    if str(content_type or "").strip() and "text/plain" not in content_type.lower():
        return False
    начало = str(text or "")[:2048].lstrip().lower()
    return начало.startswith(("<!doctype html", "<html")) or "<body" in начало


def текст_страницы(markup: str) -> tuple[str, str]:
    """(заголовок, текст) из HTML. Без скриптов, стилей и навигации."""
    parser = _Текст()
    try:
        parser.feed(str(markup or ""))
        parser.close()
    except Exception:  # noqa: BLE001 - кривая разметка даёт то, что успели прочесть
        pass
    текст = "".join(parser.куски)
    строки = [" ".join(s.split()) for s in текст.split("\n")]
    # Пустые строки выбрасываются: на живых страницах их больше, чем текста, а
    # агенту они стоят токенов и ничего не несут.
    сжатый = [строка for строка in строки if строка]
    return " ".join("".join(parser.заголовок).split()), "\n".join(сжатый).strip()


def page(
    url: str,
    *,
    why_wanted: str = "",
    max_chars: int = PAGE_CHARS,
    offset: int = 0,
    raw: bool = False,
) -> dict:
    """Страница для чтения: текст вместо разметки, кусками, с остатком.

    Обёртка над `fetch` для инструмента `fetch_url`. Все три исхода и запись
    отказа — от `fetch`; здесь меняется только ТО, ЧТО отдаётся в `text`.

    :param max_chars: сколько символов отдать (1 .. `PAGE_CHARS_MAX`).
    :param offset: с какого символа ИЗВЛЕЧЁННОГО текста начать; следующий
        кусок — `next_offset` из ответа.
    :param raw: отдать тело как пришло (HTML-разметку, JSON) — тоже кусками.
    """
    try:
        лимит = int(max_chars)
    except (TypeError, ValueError):
        лимит = PAGE_CHARS
    лимит = max(1, min(лимит, PAGE_CHARS_MAX))
    try:
        начало = max(0, int(offset))
    except (TypeError, ValueError):
        начало = 0
    out = fetch(url, why_wanted=why_wanted, max_bytes=PAGE_BYTES)
    тело = str(out.get("text") or "")
    вид = "raw"
    заголовок = ""
    if not raw and тело and похоже_на_html(тело, str(out.get("content_type") or "")):
        заголовок, тело = текст_страницы(тело)
        вид = "text extracted from HTML (script, style, nav dropped)"
    всего = len(тело)
    кусок = тело[начало : начало + лимит]
    дальше = начало + len(кусок)
    осталось = max(0, всего - дальше)
    result = {
        **out,
        "text": кусок,
        "title": заголовок,
        "form": вид,
        "offset": начало,
        "max_chars": лимит,
        "total_chars": всего,
        "returned_chars": len(кусок),
        "remaining_chars": осталось,
        "next_offset": дальше if осталось else None,
        "truncated": bool(осталось) or bool(out.get("truncated")),
    }
    if тело or начало:
        хвост = (
            f"; {всего} chars of {вид}, returned {начало}..{дальше}"
            + (
                f", {осталось} more — call again with offset={дальше}"
                if осталось
                else ", nothing more"
            )
            + (
                f". THE DOWNLOAD ITSELF WAS CUT at {PAGE_BYTES} bytes, so the page is longer "
                "than anything offset can reach"
                if out.get("truncated")
                else ""
            )
        )
        result["note"] = str(out.get("note", "")) + хвост
    return result


def _ssrf_refusal(target: str, why: str) -> dict:
    return {
        "outcome": FAIL,
        "checked": 1,
        "violations": 1,
        "unmeasured": 0,
        "note": (
            f"{target!r} is refused before sending: {why}. Requests from a tool call "
            "never go to private, loopback, link-local or metadata addresses. Nothing "
            "was sent and nothing was recorded in the denial journal."
        ),
        "host": _host(target),
        "status": None,
        "text": "",
        "denied": False,
        "ssrf": True,
    }


def reachability(hosts: Any = None, *, why_wanted: str = "") -> dict:
    """Probe hosts now rather than trusting the map in the docstring.

    A reachability map is a measurement with a date on it, and this is how the
    date gets refreshed. Cheap: one HEAD-shaped GET per host.

    :param why_wanted: the question these hosts are being probed FOR. Given, the
        refusals join the allowlist request under that reason. Left empty, this
        is a map refresh — nobody asked for any particular host — and refusals
        are recorded as incidental, out of the ask.

        OBSERVED 2026-08-27, twice: a bulk sweep wrote every refused host into
        the file a human reads to decide what access to grant. Search results
        was the first place, this was the second, and the reason recorded here
        was the literal string "reachability probe", which tells that human
        nothing at all. A host really wanted is promoted into the ask by
        `note_denial` the first time somebody probes it WITH a question, so
        nothing is lost by defaulting to incidental.
    """
    if isinstance(hosts, str):
        hosts = [h for h in hosts.split(",") if h.strip()]
    given = list(hosts) if hosts else list(_DEFAULT_HOSTS)
    asked_for = str(why_wanted or "").strip()
    open_hosts: list[str] = []
    closed: list[str] = []
    other: list[dict] = []
    # ВХОД РАЗБИРАЕТСЯ ДО ПРОБЫ. Найдено живым прогоном 2026-10-14: строка
    # `https://x.y/z` пробовалась как хост, и в журнал отказов уехал хост
    # `https`. Негодная строка не пробуется, не пишется и называется в ответе.
    targets: list[str] = []
    invalid: list[dict] = []
    for raw in given:
        host, why = нормализовать_хост(raw)
        if not host:
            invalid.append({"input": str(raw), "why": why})
        elif host not in targets:
            targets.append(host)
    for host in targets:
        out = fetch(
            f"https://{host}/",
            why_wanted=asked_for or "refreshing the reachability map; nobody asked for this host",
            incidental=not asked_for,
        )
        if out.get("ssrf"):
            invalid.append({"input": host, "why": out["note"]})
        elif out["denied"]:
            closed.append(host)
        elif out["outcome"] in {PASS, FAIL}:
            # FAIL here means the host ANSWERED — 400 or 404 on a bare root is
            # still proof the host is reachable, which is what this measures.
            open_hosts.append(host)
        else:
            other.append({"host": host, "note": out["note"]})

    # THE DEFECT THIS BLOCK EXISTS FOR, found by review 2026-08-31 and reproduced
    # with a stubbed fetch: with egress or DNS down, every host lands in `other`
    # and this returned `pass` with an EMPTY `open` list — "checked 12,
    # violations 0", the exact shape of rule R2 that this repository keeps a
    # separate test against. The module's own docstring, forty lines up, forbids
    # it in so many words: "could not measure — the network failed, timed out,
    # or DNS died". An agent branching on `outcome` could not tell "the policy
    # forbids nothing" from "we reached nobody".
    #
    # The branch below covers "nothing was probed": every input was junk or an
    # internal address (2026-10-14), or no input at all. Junk is the caller's
    # error and comes back as `fail` with `invalid` naming each one.
    if not (open_hosts or closed or other):
        return {
            "outcome": FAIL if invalid else UNMEASURED,
            "checked": len(invalid),
            "violations": len(invalid),
            "unmeasured": 0 if invalid else 1,
            "note": (
                f"none of the {len(invalid)} input(s) is a host that can be probed; "
                "nothing was sent and nothing was recorded"
                if invalid
                else "no hosts were given, so nothing was probed"
            ),
            "open": [],
            "closed": [],
            "unreached": [],
            "invalid": invalid,
        }

    return {
        "outcome": FAIL if closed else (PASS if open_hosts else UNMEASURED),
        "checked": len(targets),
        "violations": len(closed),
        "unmeasured": len(other),
        "note": (
            f"{len(open_hosts)} open, {len(closed)} refused by policy, "
            f"{len(other)} unreached for other reasons, out of {len(targets)} probed"
            + (
                f"; {len(invalid)} input(s) were not probeable hosts and were skipped "
                "(see `invalid`) — nothing was recorded for them"
                if invalid
                else ""
            )
            + (
                " — NOBODY answered, so this is not a map of what is allowed, it is "
                "a map of nothing: treat it as не смогли, not as a clean bill"
                if not open_hosts and not closed
                else ""
            )
        ),
        "open": sorted(open_hosts),
        "closed": sorted(closed),
        "unreached": other,
        "invalid": invalid,
        # Карта — измерение с датой и точкой обзора: открыто ОТСЮДА и СЕЙЧАС.
        "measured_on": date.today().isoformat(),
        "vantage": "this server's process, through its configured egress"
        + (" proxy" if _proxy_hosts() else " (no proxy)"),
    }


#: Сколько символов причины остаётся в КРАТКОЙ форме заявки. ВЫБРАНО: самая
#: длинная настоящая причина — 289 символов (см. `ПОТОЛОК_ПРИЧИНЫ`), а
#: краткой форме достаточно начала фразы, чтобы понять, о чём просили.
КРАТКАЯ_ПРИЧИНА = 160


def wanted(*, full: bool = True) -> dict:
    """The allowlist request, assembled from refusals that actually happened.

    :param full: every row as the journal stored it (the default, for scripts
        that build the request document). False gives the compact form the MCP
        tool returns by default: per asked host only host, reason (cut to
        `КРАТКАЯ_ПРИЧИНА`) and date; the bulk-probe pile and the granted list
        as counts plus host names. MEASURED 2026-10-14: the full form was
        75 733 characters — more than an agent can afford to read to learn
        that sixty hosts are being asked for.
    """
    out = _wanted_full()
    if full:
        return out

    def _кратко(row: dict) -> dict:
        причина = " ".join(str(row.get("why_wanted") or "").split())
        if len(причина) > КРАТКАЯ_ПРИЧИНА:
            причина = причина[:КРАТКАЯ_ПРИЧИНА] + "…"
        item = {
            "host": row.get("host", ""),
            "why_wanted": причина,
            "first_seen": row.get("first_seen", ""),
        }
        if row.get("also_answered"):
            item["also_answered"] = row["also_answered"]
        return item

    return {
        **{k: out[k] for k in ("outcome", "checked", "violations", "unmeasured", "note")},
        "form": "compact — pass full=True for every row as recorded",
        "counts": {
            "asked": len(out["hosts"]),
            "also_refused": len(out["also_refused"]),
            "granted": len(out["granted"]),
            "withdrawn": len(out["withdrawn"]),
        },
        "hosts": [_кратко(r) for r in out["hosts"]],
        "also_refused": sorted(str(r.get("host", "")) for r in out["also_refused"]),
        "granted": out["granted"],
        "withdrawn": out["withdrawn"],
    }


def _wanted_full() -> dict:
    """The full allowlist request; see `wanted`."""
    rows = _read_denied()
    if not rows:
        return {
            "outcome": PASS,
            "checked": 0,
            "violations": 0,
            "unmeasured": 0,
            "note": "no host has been refused yet, so there is nothing to ask for",
            "hosts": [],
            "also_refused": [],
            "granted": [],
            "withdrawn": [],
        }
    # The latest row per host decides. A host recorded open has been granted
    # and is no longer asked for; the rows stay in the file so the history of
    # "asked on this date, granted on that one" can be read back.
    state: dict[str, str] = {}
    for row in rows:
        host = row.get("host", "")
        if host:
            state[host] = str(row.get("state", STATE_REFUSED))
    opened = sorted(h for h, s in state.items() if s == STATE_OPEN)
    withdrawn = sorted(h for h, s in state.items() if s == STATE_UNWANTED)

    by_host: dict[str, dict] = {}
    # Адреса этого хоста, которые ОТВЕЧАЛИ. Хост — не единица доступа (см.
    # докстроку модуля: `docs.qingque.cn/` закрыт, а страница на нём открыта).
    answered: dict[str, list[str]] = {}
    for row in rows:
        if str(row.get("state", STATE_REFUSED)) == STATE_OPEN and row.get("host"):
            url = str(row.get("url") or "")
            if url and url not in answered.setdefault(row["host"], []):
                answered[row["host"]].append(url)
    for row in rows:
        host = row.get("host", "")
        if not host or state.get(host) in (STATE_OPEN, STATE_UNWANTED):
            continue
        # ТОЛЬКО СТРОКИ-ОТКАЗЫ ВЫБИРАЮТСЯ В ЗАЯВКУ. НАЙДЕНО 2026-10-14: у строки
        # `open` нет поля `incidental`, она читалась как «не мазок» и
        # вытесняла настоящую причину — в `hosts` уезжал `docs.qingque.cn` с
        # `state: open` и без всякого `why_wanted`, а `unwanted`-строки
        # Reddit — с причиной ОТКАЗА от хоста вместо причины просьбы.
        if str(row.get("state", STATE_REFUSED)) != STATE_REFUSED:
            continue
        kept = by_host.get(host)
        # Two rules, in this order. A host wanted for a real question outranks
        # the same host met by a bulk probe, whichever was written first. And
        # among real questions the LATEST wins, because the file is append-only
        # history and the newest reason is the one written against today's
        # fact base — an old reason can have gone stale under it.
        if kept is None or not row.get("incidental", False):
            by_host[host] = row

    for host, urls in answered.items():
        if host in by_host:
            by_host[host] = {**by_host[host], "also_answered": urls}
    asked = [by_host[h] for h in sorted(by_host) if not by_host[h].get("incidental", False)]
    swept = [by_host[h] for h in sorted(by_host) if by_host[h].get("incidental", False)]

    if not asked:
        # Three ways to have nothing to ask for, and they are not the same
        # thing. Printing one message for all three is how "they granted
        # everything" becomes indistinguishable from "nobody ever asked".
        if opened and not swept:
            note = (
                f"nothing to ask for: all {len(opened)} host(s) that were asked for "
                "have since been granted and now answer. The request is closed."
            )
        elif opened:
            note = (
                f"nothing to ask for: {len(opened)} host(s) asked for have since "
                f"been granted, and the remaining {len(swept)} refused host(s) were "
                "swept up by bulk probes rather than needed for a question."
            )
        else:
            note = (
                f"nothing to ask for: every one of the {len(swept)} refused host(s) "
                "was swept up by a bulk probe, not needed for a question. Listed "
                "under `also_refused` so the refusals are not lost."
            )
        return {
            "outcome": PASS if opened and not swept else UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": len(swept),
            "note": note,
            "hosts": [],
            "also_refused": swept,
            "granted": opened,
            "withdrawn": withdrawn,
        }
    return {
        "outcome": FAIL,
        "checked": len(rows),
        "violations": len(asked),
        "unmeasured": len(swept),
        "note": (
            f"{len(asked)} host(s) refused by egress policy while answering a real "
            "question; ask the policy owner rather than routing around them."
            + (
                f" A further {len(swept)} host(s) were refused during bulk probes "
                "and are under `also_refused` — they are NOT part of the ask."
                if swept
                else ""
            )
        ),
        "hosts": asked,
        "also_refused": swept,
        "granted": opened,
        "withdrawn": withdrawn,
    }


#: MEASURED 2026-08-27 on this machine. Kept as the default probe list so a
#: caller can ask "is this still true" in one call.
_DEFAULT_HOSTS: tuple[str, ...] = (
    "raw.githubusercontent.com",
    "api.github.com",
    "pypi.org",
    "huggingface.co",
    "cloud.google.com",
    "api.klingai.com",
    "api.fal.ai",
    "docs.bfl.ai",
    "arxiv.org",
    "kling.ai",
    "help.runwayml.com",
    "elevenlabs.io",
)
