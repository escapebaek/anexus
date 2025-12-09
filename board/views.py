# board/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Board, Comment
from .forms import BoardForm, CommentForm
from django.core.paginator import Paginator
from accounts.decorators import user_is_specially_approved

@login_required
@user_is_specially_approved
def board_index(request):
    # 공지사항과 일반 글을 분리해서 가져오기
    notices = Board.objects.filter(is_notice=True).order_by('-id')
    regular_boards = Board.objects.filter(is_notice=False).order_by('-id')
    
    # 일반 글에만 페이지네이션 적용
    paginator = Paginator(regular_boards, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'notices': notices,  # 공지사항 목록
        'page_obj': page_obj,  # 페이지네이션된 일반 글 목록
    }
    return render(request, 'board/board_index.html', context)

@login_required
@user_is_specially_approved
def board_detail(request, pk):
    board = get_object_or_404(Board, pk=pk)
    comments = board.comments.all()

    if request.method == 'POST':
        if 'content' in request.POST:  # 댓글이 달리는 경우
            comment_form = CommentForm(request.POST)
            if comment_form.is_valid():
                comment = comment_form.save(commit=False)
                comment.board = board
                comment.author = request.user
                comment.save()
                return redirect('board_detail', pk=board.pk)
        else:  # 게시글 수정/삭제의 경우
            pass
    else:
        comment_form = CommentForm()

    context = {
        'board': board,
        'comments': comments,
        'comment_form': comment_form,
        'can_edit': request.user == board.author or request.user.is_staff or request.user.is_superuser
    }
    return render(request, 'board/board_detail.html', context)

@login_required
@user_is_specially_approved
def comment_edit(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    if request.user != comment.author and not request.user.is_superuser:
        return redirect('board_detail', pk=comment.board.pk)

    if request.method == 'POST':
        form = CommentForm(request.POST, instance=comment)
        if form.is_valid():
            form.save()
            return redirect('board_detail', pk=comment.board.pk)
    else:
        form = CommentForm(instance=comment)

    return render(request, 'board/comment_edit.html', {'form': form})

@login_required
@user_is_specially_approved
def comment_delete(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    if request.user == comment.author or request.user.is_superuser:
        comment.delete()
    return redirect('board_detail', pk=comment.board.pk)

@login_required
@user_is_specially_approved
def board_edit(request, pk):
    board = get_object_or_404(Board, pk=pk)
    
    # 작성자이거나 관리자만 수정 가능
    if request.user != board.author and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, '수정 권한이 없습니다.')
        return redirect('board_detail', pk=pk)

    if request.method == 'POST':
        form = BoardForm(request.POST, instance=board, user=request.user)
        if form.is_valid():
            # 일반 사용자가 공지사항으로 설정하려고 하는 경우 방지
            if not (request.user.is_staff or request.user.is_superuser):
                form.instance.is_notice = False
            form.save()
            messages.success(request, '글이 성공적으로 수정되었습니다.')
            return redirect('board_detail', pk=pk)
    else:
        form = BoardForm(instance=board, user=request.user)
    
    return render(request, 'board/board_form.html', {'form': form})

@login_required
@user_is_specially_approved
def board_delete(request, pk):
    board = get_object_or_404(Board, pk=pk)
    
    # 작성자이거나 관리자만 삭제 가능
    if request.user != board.author and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, '삭제 권한이 없습니다.')
        return redirect('board_detail', pk=pk)

    if request.method == 'POST':
        board.delete()
        messages.success(request, '글이 성공적으로 삭제되었습니다.')
        return redirect('board_index')

    return render(request, 'board/board_confirm_delete.html', {'board': board})

@login_required
@user_is_specially_approved
def board_create(request):
    if request.method == "POST":
        form = BoardForm(request.POST, user=request.user)
        if form.is_valid():
            board = form.save(commit=False)
            board.author = request.user
            
            # 일반 사용자가 공지사항으로 설정하려고 하는 경우 방지
            if not (request.user.is_staff or request.user.is_superuser):
                board.is_notice = False
                
            board.save()
            messages.success(request, '글이 성공적으로 등록되었습니다.')
            return redirect('board_index')
    else:
        form = BoardForm(user=request.user)
    return render(request, 'board/board_form.html', {'form': form})