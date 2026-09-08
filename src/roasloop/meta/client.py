"""Meta Graph API 얇은 래퍼.

facebook-business SDK 대신 requests 를 쓴다. 의존성이 가볍고, 버전이 올라가도
엔드포인트 문자열 하나만 바꾸면 되기 때문이다.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator

import requests

log = logging.getLogger("roasloop.meta")

API_VERSION = os.environ.get("META_API_VERSION", "v23.0")
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

#: 재시도해야 하는 Meta 에러 코드.
#:   1, 2      일시적 API 오류
#:   4, 17, 80004  요청량 제한
#:   613       호출 한도 초과
RETRYABLE_CODES = {1, 2, 4, 17, 341, 613, 80000, 80004}

#: 재시도하면 안 되는 코드. 요청 자체가 잘못된 것이라 몇 번을 보내도 결과가 같다.
#: Meta 는 이런 오류에도 HTTP 500 을 주는 경우가 있어서, 상태코드만 보면 헛되이 4번을 더 보낸다.
CLIENT_ERROR_CODES = {100, 102, 190, 200, 2500, 3018}


class MetaAPIError(RuntimeError):
    def __init__(self, payload: dict, status: int):
        err = payload.get("error", {})
        self.code = err.get("code")
        self.subcode = err.get("error_subcode")
        self.message = err.get("message", str(payload))
        self.user_message = err.get("error_user_msg", "")
        self.status = status
        detail = f"[{status}/{self.code}] {self.message}"
        if self.user_message:
            detail += f"\n  → {self.user_message}"
        super().__init__(detail)

    @property
    def retryable(self) -> bool:
        if self.code in CLIENT_ERROR_CODES:
            return False
        return self.code in RETRYABLE_CODES or self.status >= 500


class MetaClient:
    def __init__(self, access_token: str, ad_account_id: str, max_retries: int = 4):
        self.access_token = access_token
        self.ad_account_id = ad_account_id
        self.max_retries = max_retries
        self.session = requests.Session()

    # ------------------------------------------------------------------ 저수준
    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = path if path.startswith("http") else f"{BASE_URL}/{path.lstrip('/')}"
        params = kwargs.pop("params", {}) or {}
        params.setdefault("access_token", self.access_token)

        delay = 2.0
        last: MetaAPIError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, params=params, timeout=120, **kwargs)
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise RuntimeError(f"Meta API 연결 실패: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            if resp.ok:
                return resp.json() if resp.content else {}

            try:
                payload = resp.json()
            except ValueError:
                payload = {"error": {"message": resp.text}}
            last = MetaAPIError(payload, resp.status_code)
            if not last.retryable or attempt == self.max_retries:
                raise last
            log.warning("Meta API 재시도 %d/%d — %s", attempt + 1, self.max_retries, last.message)
            time.sleep(delay)
            delay *= 2
        assert last is not None
        raise last

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, data=data)

    def paged(self, path: str, params: dict | None = None) -> Iterator[dict]:
        """커서 페이징을 끝까지 따라간다."""
        page = self.get(path, params)
        while True:
            yield from page.get("data", [])
            nxt = page.get("paging", {}).get("next")
            if not nxt:
                return
            page = self._request("GET", nxt)

    # ------------------------------------------------------------------ 편의
    def account_path(self, edge: str) -> str:
        return f"{self.ad_account_id}/{edge}"

    def update_status(self, object_id: str, status: str) -> dict:
        """캠페인/광고셋/광고의 상태 변경. status 는 ACTIVE 또는 PAUSED."""
        if status not in {"ACTIVE", "PAUSED"}:
            raise ValueError(f"status 는 ACTIVE 또는 PAUSED 여야 합니다: {status!r}")
        return self.post(object_id, {"status": status})

    def update_budget(self, adset_id: str, daily_budget: int) -> dict:
        """일 예산 변경. 계정 통화의 최소 단위(KRW=원, USD=센트) 정수."""
        return self.post(adset_id, {"daily_budget": int(daily_budget)})
