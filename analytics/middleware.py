from .models import PageView

# 記録対象外のURLプレフィックス
EXCLUDE_PREFIXES = (
    "/static/",
    "/admin/",
    "/analytics/",
    "/media/",
    "/favicon.ico",
)


class PageViewMiddleware:
    """全リクエストをPageViewテーブルに記録するミドルウェア"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # 除外対象のパスはスキップ
        path = request.path
        if any(path.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
            return response

        # GETリクエストのみ記録（POST等は除外）
        if request.method != "GET":
            return response

        # 成功レスポンスのみ記録（2xx）
        if not (200 <= response.status_code < 300):
            return response

        # クライアントIPを取得（プロキシ経由対応）
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if not ip:
            ip = request.META.get("REMOTE_ADDR")

        PageView.objects.create(
            path=path,
            ip_address=ip or None,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            referrer=request.META.get("HTTP_REFERER", ""),
        )

        return response
