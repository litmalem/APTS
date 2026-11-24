"""One fixed, pinned endpoint per invocation; no proxies, redirects, or target override."""
from __future__ import annotations

import base64
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import re
import queue
import socket
import ssl
from threading import Thread
import time
from urllib.parse import urlsplit

from mission_orchestrator.governance_binding import resource_in_canonical_scope
from .execution_contract import ExecutionSourceRejected
from .runtime_control import stop_socket
from .tls_trust import create_verified_tls_context


@dataclass(frozen=True)
class PinnedTarget:
    host: str
    ip: str
    port: int
    path: str
    tls: bool

    def definition(self):
        return asdict(self)


def parse_endpoint(target, default_port):
    value = target["target_value"]
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise ExecutionSourceRejected("INVALID_TARGET_ENDPOINT")
    if target["target_type"] == "URL":
        try:
            u = urlsplit(value)
            if u.scheme not in {"http", "https"} or not u.hostname or u.username is not None or u.password is not None or u.fragment or u.query:
                raise ValueError("unsupported URL")
            host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
            path = u.path or "/"
            if re.search(r"[^A-Za-z0-9/._~-]", path) or ".." in path.split("/"):
                raise ValueError("unsupported path")
            tls = u.scheme == "https"
        except ValueError as exc:
            raise ExecutionSourceRejected("INVALID_TARGET_URL") from exc
    elif target["target_type"] in {"IP", "HOST", "DOMAIN"}:
        host, port, path, tls = value, default_port, "/", False
    else:
        raise ExecutionSourceRejected("UNSUPPORTED_TARGET_TYPE")
    try:
        address = ipaddress.ip_address(host)
        host = str(address)
    except ValueError:
        if target["target_type"] == "IP":
            raise ExecutionSourceRejected("IP_TARGET_MUST_BE_LITERAL")
        if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host) or any(not x or len(x)>63 or x.startswith("-") or x.endswith("-") for x in host.split(".")):
            raise ExecutionSourceRejected("INVALID_TARGET_HOST")
        host = host.lower()
    if type(port) is not int or not 1 <= port <= 65535:
        raise ExecutionSourceRejected("INVALID_TARGET_PORT")
    return host, port, path, tls


def _ip_allowed(ip, source, target=None):
    address = ipaddress.ip_address(ip)
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        return False
    scope = source["scope"]
    for item in scope.get("excluded_targets", []):
        # URL exclusions are enforced per path, not against the entire host IP.
        if item.get("target_type") == "URL": continue
        if _address_matches(address, item):
            return False
    ranges = scope.get("network_ranges", source.get("constraints", {}).get("network_ranges", []))
    allowed_by_target = any(_address_matches(address, item) for item in scope.get("targets", []))
    if ranges:
        return any(address in ipaddress.ip_network(x, strict=False) for x in ranges)
    if allowed_by_target:
        return True
    # Only the exact reserved localhost name explicitly declared as a LAB URL
    # may resolve to loopback. Arbitrary hostnames and private DNS stay denied.
    if target and target.get('target_type') == 'URL' and address.is_loopback:
        host = urlsplit(target['target_value']).hostname
        if host == 'localhost' and any(
                item.get('target_type') == 'URL' and item.get('environment') == 'LAB'
                and urlsplit(item['target_value']).hostname == 'localhost'
                and resource_in_canonical_scope({'scope': {'targets': [item]}}, target['target_value'])[0]
                for item in scope.get('targets', [])):
            return True
    if target and target.get('target_type') == 'URL' and urlsplit(target['target_value']).hostname == 'localhost':
        return False
    # An explicitly scoped URL authorizes its public DNS destination. Keep
    # numeric network boundaries restrictive, and never let a hostname grant
    # access to private/local or special addresses through DNS rebinding.
    if not target or target.get('target_type') != 'URL' or not address.is_global:
        return False
    numeric_targets = [item for item in scope.get('targets', [])
                       if item.get('target_type') in {'IP','CIDR'}]
    if numeric_targets:
        return False
    host = urlsplit(target['target_value']).hostname
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return any(item.get('target_type') == 'URL'
               and urlsplit(item['target_value']).hostname == host
               and resource_in_canonical_scope({'scope':{'targets':[item]}}, target['target_value'])[0]
               for item in scope.get('targets', []))


def _address_matches(address, item):
    kind, value = item.get("target_type"), item.get("target_value")
    try:
        if kind in {"IP", "HOST"}:
            return address == ipaddress.ip_address(value)
        if kind == "CIDR":
            return address in ipaddress.ip_network(value, strict=False)
        if kind == "URL":
            return address == ipaddress.ip_address(urlsplit(value).hostname)
    except (ValueError, TypeError):
        pass
    return False


class TargetBroker:
    def __init__(self, *, resolver=None):
        self.resolver = resolver or socket.getaddrinfo

    def validate_pin(self, request, context, adapter, pinned):
        expected = parse_endpoint(request["target"], adapter.default_port)
        if (pinned.host, pinned.port, pinned.path, pinned.tls) != expected:
            raise ExecutionSourceRejected("PINNED_ENDPOINT_REQUEST_MISMATCH")
        sources = [context["mission_scope"], context["pentest_context"]["boundary"], context["pentest_context"]["task"]]
        if not all(resource_in_canonical_scope(s, request["target"]["target_value"])[0] and _ip_allowed(pinned.ip, s, request['target']) for s in sources):
            raise ExecutionSourceRejected("PINNED_ADDRESS_OUTSIDE_CURRENT_SCOPE")

    def validate_profile_pin(self,request,context,adapter,root_pin,url,child):
        from .web_profile_collection import redirect_destination
        from mission_orchestrator.governance_binding import _target_matches
        self.validate_pin(request,context,adapter,root_pin)
        target=request["target"]["target_value"]
        if redirect_destination(target,target,url)!=url:
            raise ExecutionSourceRejected("PROFILE_OUTSIDE_AUTHORIZED_PREFIX")
        expected=parse_endpoint({"target_type":"URL","target_value":url},adapter.default_port)
        if ((child.host,child.port,child.path,child.tls)!=expected or child.ip!=root_pin.ip
            or child.host!=root_pin.host or child.port!=root_pin.port or child.tls!=root_pin.tls):
            raise ExecutionSourceRejected("PROFILE_PIN_CHANGED")
        sources=[context["mission_scope"],context["pentest_context"]["boundary"],context["pentest_context"]["task"]]
        for source in sources:
            for exclusion in source["scope"].get("excluded_targets",[]):
                blocked=_target_matches(url,exclusion)
                if exclusion.get("target_type")=="URL":
                    blocked=blocked or redirect_destination(exclusion["target_value"],exclusion["target_value"],url)==url
                if blocked:raise ExecutionSourceRejected("PROFILE_PATH_EXPLICITLY_EXCLUDED")

    def pin(self, request, context, adapter, *, deadline=None, runtime=None):
        if runtime:
            runtime.check()
        target = request["target"]
        host, port, path, tls = parse_endpoint(target, adapter.default_port)
        sources = [context["mission_scope"], context["pentest_context"]["boundary"], context["pentest_context"]["task"]]
        if not all(resource_in_canonical_scope(s, target["target_value"])[0] for s in sources):
            raise ExecutionSourceRejected("TARGET_OUTSIDE_CURRENT_SCOPE")
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                if deadline is None:
                    records = self.resolver(host, port, type=socket.SOCK_STREAM)
                else:
                    pending = queue.Queue()
                    def resolve():
                        try:
                            pending.put(self.resolver(host, port, type=socket.SOCK_STREAM))
                        except Exception as exc:
                            pending.put(exc)
                    Thread(target=resolve, daemon=True).start()
                    while True:
                        if runtime:
                            runtime.check()
                        try:
                            records = pending.get(timeout=min(0.05, _remaining(deadline)) if runtime else _remaining(deadline))
                            break
                        except queue.Empty as exc:
                            if not runtime or time.monotonic() >= deadline:
                                raise TimeoutError("bounded DNS resolution timeout") from exc
                    if isinstance(records, Exception):
                        raise records
                addresses = sorted({str(ipaddress.ip_address(x[4][0])) for x in records})
            except TimeoutError:
                raise
            except (ValueError, OSError) as exc:
                raise ExecutionSourceRejected("TARGET_DNS_RESOLUTION_FAILED") from exc
        if not addresses or len(addresses) > 32 or not all(_ip_allowed(ip, s, target) for ip in addresses for s in sources):
            raise ExecutionSourceRejected("RESOLVED_ADDRESS_OUTSIDE_SCOPE")
        return PinnedTarget(host, addresses[0], port, path, tls)

    def observe(self, adapter, pinned, limits, *, deadline, before_io, authorization_header=None, runtime=None):
        """before_io must revalidate GSS, sources, and the durable claim immediately before connect."""
        tls_context = create_verified_tls_context() if pinned.tls else None
        fresh_deadline = before_io()
        if fresh_deadline is not None:
            deadline = min(deadline, fresh_deadline)
        if runtime:
            runtime.tighten_deadline(deadline)
        authorization_header = authorization_header() if callable(authorization_header) else authorization_header
        if authorization_header and not pinned.tls:
            raise ExecutionSourceRejected("CREDENTIALS_REQUIRE_TLS")
        timeout = min(limits["timeout_seconds"], deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError("adapter deadline expired")
        family = socket.AF_INET6 if ":" in pinned.ip else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as raw, ExitStack() as resources:
            tracked = getattr(runtime, "cleanup_sockets", None)
            owned = [raw]
            if tracked is not None:
                tracked.append(raw)
            def close_owned():
                # A profile opens several sequential connections. Keep the
                # cleanup ledger limited to live owned sockets, removing each
                # only after its OS handle is confirmed closed. This also
                # covers TLS handshake failures before response collection.
                for current in reversed(owned):
                    current.close()
                if tracked is not None:
                    for current in owned:
                        if current.fileno() == -1 and current in tracked:
                            tracked.remove(current)
            resources.callback(close_owned)
            if runtime:
                resources.enter_context(runtime.attach(lambda: stop_socket(raw)))
                runtime.check()
            raw.settimeout(timeout)
            raw.connect((pinned.ip, pinned.port))
            if runtime:
                runtime.check()
            connected = True
            peer = str(ipaddress.ip_address(raw.getpeername()[0]))
            if peer != pinned.ip:
                raise ExecutionSourceRejected("TARGET_PEER_PIN_MISMATCH")
            sock = raw
            if tls_context:
                raw.settimeout(_remaining(deadline))
                sock = tls_context.wrap_socket(raw, server_hostname=pinned.host, do_handshake_on_connect=runtime is None)
                owned.append(sock)
                if tracked is not None:
                    tracked.append(sock)
                if runtime:
                    resources.enter_context(runtime.attach(lambda: stop_socket(sock)))
                    runtime.check()
                    sock.do_handshake()
            observation_complete = False
            data = b""
            sent_bytes = 0
            try:
                if adapter.operation == "TCP_CONNECT":
                    data = b""
                else:
                    if adapter.operation in {"HTTP_HEAD", "WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"}:
                        host = "[" + pinned.host + "]" if ":" in pinned.host else pinned.host
                        method = "GET" if adapter.operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"} else "HEAD"
                        # Fingerprinting uses exactly one GET to the authorized target path.
                        # Redirects are returned as metadata and are never followed.
                        header = "" if authorization_header is None else "Authorization: " + authorization_header + "\r\n"
                        message = (f"{method} {pinned.path} HTTP/1.1\r\nHost: {host}:{pinned.port}\r\n"
                                   "User-Agent: APTS-AuthorizedAdapter/6.4\r\nAccept: text/html,application/xhtml+xml,*/*;q=0.1\r\n"
                                   "Accept-Encoding: identity\r\nConnection: close\r\n" + header + "\r\n").encode("ascii")
                        if len(message) > limits["max_network_bytes"]:
                            raise ExecutionSourceRejected("REQUEST_BYTE_QUOTA_EXCEEDED")
                        if runtime:
                            runtime.check()
                        sock.settimeout(_remaining(deadline))
                        sock.sendall(message)
                        sent_bytes = len(message)
                    data = b""
                    receive_quota = limits["max_network_bytes"] - sent_bytes
                    # Hard cap; HEAD does not read response bodies or follow Location.
                    while len(data) < receive_quota:
                        if runtime:
                            runtime.check()
                        sock.settimeout(_remaining(deadline))
                        chunk = sock.recv(min(4096, receive_quota - len(data)))
                        if not chunk:
                            break
                        data += chunk
                        if adapter.operation == "TCP_BANNER" or (adapter.operation in {"HTTP_HEAD", "WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"} and b"\r\n\r\n" in data and adapter.operation == "HTTP_HEAD"):
                            break
                if adapter.operation == "HTTP_HEAD":
                    data = data.split(b"\r\n\r\n", 1)[0] + (b"\r\n\r\n" if b"\r\n\r\n" in data else b"")
                observation_complete = True
                return {"connected": connected, "peer_ip": peer, "response_bytes": len(data),
                        "response_sha256": hashlib.sha256(data).hexdigest(),
                        "response_b64": base64.b64encode(data).decode("ascii"),
                        "byte_limit_reached": len(data) + sent_bytes >= limits["max_network_bytes"]}
            finally:
                try:
                    capture = getattr(runtime, "evidence_capture", None)
                    if capture:
                        # Evidence capture validates the transient bytes, then stores only
                        # status, byte count and digest; raw response bytes are not retained.
                        capture.observe_target({"connected": connected, "peer_ip": peer,
                            "response_bytes": len(data), "response_sha256": hashlib.sha256(data).hexdigest(),
                            "response_b64": base64.b64encode(data).decode("ascii"),
                            "byte_limit_reached": len(data) + sent_bytes >= limits["max_network_bytes"]},
                            complete=observation_complete)
                finally:
                    if sock is not raw:
                        sock.close()


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("adapter wall deadline expired")
    return remaining
