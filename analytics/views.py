from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect, render
from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate
from datetime import timedelta

from .models import PageView

# 保持日数の選択肢
RETENTION_CHOICES = [30, 60, 90, 180]


def is_staff(user):
    return user.is_staff


@login_required
@user_passes_test(is_staff)
def cleanup(request):
    """古いアクセスログを削除"""
    if request.method == "POST":
        try:
            days = int(request.POST.get("days", 90))
        except (ValueError, TypeError):
            days = 90

        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = PageView.objects.filter(timestamp__lt=cutoff).delete()
        messages.success(request, f"{days}日より前のデータ {deleted} 件を削除しました。")
    return redirect("analytics:dashboard")


@login_required
@user_passes_test(is_staff)
def dashboard(request):
    """アクセス解析ダッシュボード"""
    now = timezone.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    thirty_days_ago = today - timedelta(days=30)

    # 本日のアクセス数
    today_count = PageView.objects.filter(
        timestamp__date=today
    ).count()

    # 昨日のアクセス数（前日比用）
    yesterday_count = PageView.objects.filter(
        timestamp__date=yesterday
    ).count()

    # 前日比
    diff = today_count - yesterday_count

    # 直近30日間の日別アクセス数
    daily_data = (
        PageView.objects.filter(timestamp__date__gte=thirty_days_ago)
        .annotate(date=TruncDate("timestamp"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # グラフ用データ（全日付を埋める）
    date_counts = {row["date"]: row["count"] for row in daily_data}
    chart_labels = []
    chart_values = []
    for i in range(30, -1, -1):
        d = today - timedelta(days=i)
        chart_labels.append(f"{d.month}/{d.day}")
        chart_values.append(date_counts.get(d, 0))

    # ユーザー別アクセス数ランキング（直近30日、上位10件）
    user_data = (
        PageView.objects.filter(timestamp__date__gte=thirty_days_ago)
        .values("user__username", "ip_address")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    # 総データ件数
    total_count = PageView.objects.count()

    context = {
        "today_count": today_count,
        "diff": diff,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "user_data": user_data,
        "total_count": total_count,
        "retention_choices": RETENTION_CHOICES,
    }
    return render(request, "analytics/dashboard.html", context)
