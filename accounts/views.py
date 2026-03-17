from django.shortcuts import render, redirect
from . import forms
from .models import UserActivateToken
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required


def regist(request):
    regist_form = forms.RegistForm(request.POST or None)
    if regist_form.is_valid():
        regist_form.save(commit=True)
        messages.success(request, "登録メールを送信しました。メールのURLをクリックして本登録を完了してください。")
        return redirect("accounts:login")
    return render(
        request,
        "accounts/regist.html",
        context={"regist_form": regist_form},
    )


def activate_user(request, token):
    try:
        UserActivateToken.objects.activate_user_by_token(token)
        messages.success(request, "ユーザーを有効化しました")
    except ValueError:
        messages.error(request, "無効または期限切れのトークンです")

    return render(request, "accounts/activate_user.html")


def user_login(request):
    login_form = forms.LoginForm(request.POST or None)
    if login_form.is_valid():
        email = login_form.cleaned_data["email"]
        password = login_form.cleaned_data["password"]
        user = authenticate(email=email, password=password)
        if user:
            login(request, user)
            return redirect("accounts:login")  # TODO: ログイン後のホーム画面に変更
        else:
            messages.warning(request, "ログインに失敗しました")
    return render(
        request,
        "accounts/user_login.html",
        context={"login_form": login_form},
    )


@login_required
def user_logout(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def user_info(request):
    return render(
        request,
        "accounts/user_info.html",
        context={"user": request.user},
    )


@login_required
def user_edit(request):
    user_edit_form = forms.UserEditForm(
        request.POST or None, request.FILES or None, instance=request.user
    )
    if user_edit_form.is_valid():
        user_edit_form.save(commit=True)
        messages.success(request, "更新完了しました")
    return render(
        request,
        "accounts/user_edit.html",
        context={"user_edit_form": user_edit_form},
    )


@login_required
def change_password(request):
    password_change_form = forms.PasswordChangeForm(
        request.POST or None, instance=request.user
    )
    if password_change_form.is_valid():
        password_change_form.save(commit=True)
        messages.success(request, "パスワード更新しました")
        update_session_auth_hash(request, request.user)
    return render(
        request,
        "accounts/change_password.html",
        context={"password_change_form": password_change_form},
    )
