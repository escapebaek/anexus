# board/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Board, Comment
from .forms import BoardForm, CommentForm
from django.core.paginator import Paginator # Paginator를 import 합니다.

def board_index(request):
    # 모든 게시글을 ID의 역순(최신순)으로 가져옵니다.
    all_boards = Board.objects.all().order_by('-id')
    
    # Paginator 객체를 생성합니다. (페이지당 10개의 게시글을 보여주기)
    paginator = Paginator(all_boards, 10) 
    
    # URL에서 'page' 파라미터를 가져옵니다. 없으면 1로 간주합니다.
    page_number = request.GET.get('page')
    
    # 해당 페이지의 게시글 목록 객체(page_obj)를 생성합니다.
    # page_obj는 현재 페이지의 게시물, 페이지 번호 등 모든 정보를 담고 있습니다.
    page_obj = paginator.get_page(page_number)
    
    # 이제 'boards' 대신 'page_obj'를 템플릿으로 전달합니다.
    context = {'page_obj': page_obj}
    return render(request, 'board/board_index.html', context)

@login_required
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
            # 기존 board_detail 로직을 유지
            pass
    else:
        comment_form = CommentForm()

    context = {
        'board': board,
        'comments': comments,
        'comment_form': comment_form,
        'can_edit': request.user == board.author  # 현재 사용자가 작성자인지 확인
    }
    return render(request, 'board/board_detail.html', context)

@login_required
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
def comment_delete(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    if request.user == comment.author or request.user.is_superuser:
        comment.delete()
    return redirect('board_detail', pk=comment.board.pk)

@login_required
def board_edit(request, pk):
    board = get_object_or_404(Board, pk=pk)
    if request.user != board.author:
        return redirect('board_detail', pk=pk)

    if request.method == 'POST':
        form = BoardForm(request.POST, instance=board)
        if form.is_valid():
            form.save()
            return redirect('board_detail', pk=pk)
    else:
        form = BoardForm(instance=board)
    
    return render(request, 'board/board_form.html', {'form': form})

@login_required
def board_delete(request, pk):
    board = get_object_or_404(Board, pk=pk)
    if request.user != board.author:
        return redirect('board_detail', pk=pk)

    if request.method == 'POST':
        board.delete()
        return redirect('board_index')

    return render(request, 'board/board_confirm_delete.html', {'board': board})

def board_create(request):
    if request.method == "POST":
        form = BoardForm(request.POST)
        if form.is_valid():
            board = form.save(commit=False)
            board.author = request.user
            board.save()
            return redirect('board_index')
    else:
        form = BoardForm()
    return render(request, 'board/board_form.html', {'form': form})
