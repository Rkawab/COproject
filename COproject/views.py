from django.shortcuts import redirect


def home(request):
    """ルートURLへのアクセス: ログイン済みなら献立一覧、未ログインならログイン画面へ"""
    if request.user.is_authenticated:
        return redirect("recipes:list")
    return redirect("accounts:login")
